# Диагностика и анализ трафика DHCP

## Определения

**Анализ трафика DHCP (Dynamic Host Configuration Protocol)** — процесс перехвата и декодирования пакетов протокола для выявления ошибок в конфигурации, сетевых задержек или несанкционированных действий (Rogue DHCP).

**Диагностика (troubleshooting) DHCP** — систематический процесс поиска причин отказа в выдаче IP-адресов, охватывающий уровни от L2 (связность) до L7 (логика сервера).

**APIPA (Automatic Private IP Addressing)** — механизм самоназначения адреса из сети `169.254.0.0/16` (IPv4), когда DHCP-сервер недоступен. В IPv6 аналогичную роль играют **Link-Local** адреса (`fe80::/10`), назначаемые всегда.

**Debug-режим (отладка)** — уровень логирования, при котором DHCP-сервер записывает детальную информацию о каждом этапе обработки запроса (парсинг опций, выбор подсети, проверка классов). Критически важен для отладки сложных сценариев, но создаёт нагрузку на диск.

## Пошаговая методология диагностики

Диагностика DHCP-проблем должна выполняться последовательно от нижних уровней OSI к верхним:

```
Уровень 1: L2 (Канальный)
├─ Есть ли физическая связность? (link light, ethtool)
├─ Правильно ли настроен VLAN на порту? (access/trunk)
├─ DHCP Snooping: не блокирует ли Trusted/Untrusted порт?
└─ MAC-адрес клиента виден на коммутаторе?

Уровень 2: L3 (Сетевой)
├─ Маршрутизация между подсетями работает?
├─ DHCP Relay (giaddr) корректно заполнен?
├─ Маршрут от сервера к подсети клиента существует?
└─ NAT не блокирует DHCP-трафик (UDP 67/68)?

Уровень 3: L4 (Транспортный)
├─ UDP 67/68 (IPv4) или 546/547 (IPv6) не заблокирован?
├─ Firewall на сервере: `iptables -L -n | grep 67`
├─ Сервер слушает на нужном интерфейсе?
└─ Нет конфликта портов (другой DHCP на том же порту)?

Уровень 4: L7 (Прикладной)
├─ Конфигурация сервера корректна? (`dhcpd -t`)
├─ Достаточно ли адресов в пуле? (`grep "no free leases"`)
├─ Опции DHCP совместимы с клиентом?
├─ DDNS работает? (если включён)
└─ Авторитарность сервера настроена? (`authoritative;`)
```

### Быстрый старт: Checklist за 60 секунд

```bash
# 1. Статус сервиса
systemctl status isc-dhcp-server  # или kea-dhcp4

# 2. Синтаксис конфига
dhcpd -t -cf /etc/dhcp/dhcpd.conf  # ISC DHCP
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf  # Kea DHCP

# 3. Последние ошибки
journalctl -u isc-dhcp-server --since "10 min ago" | grep -iE "error|fail|abandon|no free"

# 4. Текущие аренды
wc -l /var/lib/dhcp/dhcpd.leases  # Количество записей

# 5. Живой трафик
sudo tcpdump -i any -n udp port 67 -c 10  # 10 пакетов
```

## Сравнение процессов DORA (v4) и SARR (v6)

Для эффективной диагностики необходимо понимать различия в хендшейках протоколов:

| Этап | DHCPv4 (DORA) | DHCPv6 (SARR) | Транспорт |
| :--- | :--- | :--- | :--- |
| **1. Поиск** | **D**iscover (Broadcast) | **S**olicit (Multicast `ff02::1:2`) | UDP 67/68 (v4), 547/546 (v6) |
| **2. Ответ** | **O**ffer (Unicast/Broadcast) | **A**dvertise (Unicast) | - |
| **3. Запрос** | **R**equest (Broadcast) | **R**equest (Multicast) | - |
| **4. Финал** | **A**cknowledge (Unicast) | **R**eply (Unicast) | - |

**Нюанс IPv6:** DHCPv6 часто не передаёт шлюз по умолчанию. Клиент получает его через **Router Advertisements (RA)**. Если IPv6-адрес получен, но интернета нет — проверяйте флаги RA (M/O) и наличие маршрутов.

### Таймлайн DORA: ожидаемые задержки

Нормальные временные интервалы для каждого этапа DORA:

```
Клиент                          Сервер
  |                               |
  |── DISCOVER ──────────────────>|  t=0ms
  |                               |  (Обработка: парсинг, выбор подсети)
  |<── OFFER ────────────────────|  t=50-200ms (норма)
  |                               |
  |── REQUEST ──────────────────>|  t=200-250ms
  |                               |  (fsync в dhcpd.leases)
  |<── ACK ─────────────────────|  t=250-500ms (норма)
  |                               |
  |  Клиент настраивает IP        |  t=500ms-2s
  |  ( Gratuitous ARP, DAD )      |
  |                               |
  |◄── Время до использования ──►|  t<5s — ОК
  |                               |  t=5-30s — медленно (проверить disk I/O)
  |                               |  t>30s — проблема
```

**Пороговые значения:**
- **DISCOVER → OFFER:** >1с — проблема с сервером (перегрузка, медленный disk I/O)
- **OFFER → ACK:** >2с — сервер не может записать lease (fsync зависает)
- **Клиент收到ACK → IP активен:** >10с — проблема на клиенте (DAD, Gratuitous ARP)

**Причины медленного DORA:**
- Сервер работает на виртуальной машине с медленным диском (fsync в `dhcpd.leases`)
- Конфигурация сервера содержит сложные `class`-выражения (ILINEAR-search)
- Relay-агент добавляет задержку (подсчёт `hops`)
- Множественные серверы в failover-конфигурации (ожидание синхронизации)

**Нюанс IPv6:** DHCPv6 часто не передаёт шлюз по умолчанию. Клиент получает его через **Router Advertisements (RA)**. Если IPv6-адрес получен, но интернета нет — проверяйте флаги RA (M/O) и наличие маршрутов.

## Анализ на стороне клиента

### Принудительное обновление (Force Renew)

| ОС | Команда | Описание |
| :--- | :--- | :--- |
| **Windows** | `ipconfig /release && ipconfig /renew` | Полный DORA-цикл |
| **Linux (dhclient)** | `sudo dhclient -r eth0 && sudo dhclient -v eth0` | Release + VERBOSE-режим |
| **Linux (NetworkManager)** | `nmcli con up <con_name>` | Через NM |
| **macOS** | `sudo ipconfig set en0 DHCP` | Полный сброс |

### Просмотр текущей аренды

```bash
# Linux (dhclient)
cat /var/lib/dhcp/dhclient.leases
# → dhcp-lease-time, dhcp-server-identifier, renew, rebind, expire

# Linux (NetworkManager)
nmcli device show eth0 | grep -E "IP4\.(ADDRESS|GATEWAY|DNS)"
nmcli connection show <con_name> | grep -E "ipv4\.(addresses|gateway|dns-search)"

# Windows
ipconfig /all | findstr /C:"DHCP" /C:"Lease" /C:"Server"
# → DHCP Enabled . . . . . . . . : Yes
# → Lease Obtained. . . . . . . . : 8/26/2026 12:00:00 PM
# → Lease Expires . . . . . . . . : 8/27/2026 12:00:00 PM

# macOS
ipconfig getpacket en0 | grep -E "lease_time|server_identifier"
```

### Проверка IPv6 и DAD

Если адрес помечен как `tentative`, возможно, механизм **DAD (Duplicate Address Detection)** обнаружил конфликт.

```bash
ip -6 addr show eth0
# → Ищем флаг "tentative" или "dadfailed"

# Проверка состояния DAD
ip -6 neigh show dev eth0
# → адрес в состоянии "INCOMPLETE" = DAD в процессе
# → "FAILED" = конфликт обнаружен
```

## Анализ на стороне сервера и Relay Agent

### Поиск в системных журналах

Наиболее частая ошибка — **Pool Exhaustion** (исчерпание пула).

```bash
# ISC DHCP: просмотр логов в реальном времени
journalctl -u isc-dhcp-server -f | grep -E "no free leases|abandoning|DHCPDECLINE"

# Kea DHCP
journalctl -u kea-dhcp4 -f | grep -E "alloc|fail|drop|subnet"

# Фильтрация по времени
journalctl -u isc-dhcp-server --since "1 hour ago" | grep -c "no free leases"
```

- **Abandoned Leases:** Если сервер помечает адрес как `abandoning`, значит он получил `DHCPDECLINE` (клиент обнаружил, что адрес занят).

### Проверка базы данных аренды

```bash
# ISC DHCP: просмотр текущих активных аренд
grep "lease" /var/lib/dhcp/dhcpd.leases -A 10

# Подсчёт активных/свободных/abandoned
grep -c "binding state active" /var/lib/dhcp/dhcpd.leases
grep -c "binding state free" /var/lib/dhcp/dhcpd.leases
grep -c "binding state abandoned" /var/lib/dhcp/dhcpd.leases

# Kea DHCP: просмотр через REST API (если настроен)
curl -s http://localhost:8000/ | jq '.[] | {ip: .ip-address, state: .state, hw: .hw-address}'
```

### Debug-режим ISC DHCP

Временное включение детального логирования:

```bash
# 1. Добавить в dhcpd.conf (временно!)
log-facility local7;

# 2. Создать syslog-правило
echo "local7.debug /var/log/dhcp-debug.log" >> /etc/syslog.d/dhcpd.conf
systemctl restart rsyslog

# 3. Запустить в debug-режиме (Foreground + Verbose)
dhcpd -d -f -cf /etc/dhcp/dhcpd.conf
# → -d: debug mode (запись в syslog)
# → -f: foreground (не become daemon)

# 4. После отладки: вернуть конфиг и перезапустить
systemctl restart isc-dhcp-server
```

**Пример вывода debug-режима:**
```text
DHCPDISCOVER from 00:50:56:b1:22:33 via 10.0.1.1
DHCPREQUEST for 10.0.10.50 from 00:50:56:b1:22:33 via 10.0.1.1
Abandoning IP address 10.0.10.50: ping timeout.
DHCPNAK on 10.0.10.50 to 00:50:56:b1:22:33 via 10.0.1.1
```

### Debug-режим Kea DHCP

```bash
# 1. Установить уровень логирования в kea-dhcp4.conf
"Dhcp4": {
    "loggers": [
        {
            "name": "kea-dhcp4",
            "output-options": [
                {
                    "output": "/var/log/kea-dhcp4.log"
                }
            ],
            "severity": "DEBUG",
            "debuglevel": 0  # 0=minimum, 99=maximum
        }
    ]
}

# 2. Перезапуск
systemctl restart kea-dhcp4

# 3. Просмотр логов
tail -f /var/log/kea-dhcp4.log | grep -E "ALLOC|SUBNET|CLASS"
```

## Анализ трафика (tcpdump и Wireshark)

### Рекомендуемые фильтры tcpdump

```bash
# === IPv4 DHCP ===

# Захват всех DHCP-пакетов с детализацией
sudo tcpdump -i eth0 -n udp port 67 or port 68 -vv

# Только DISCOVER/OFFER (первый этап DORA)
sudo tcpdump -i eth0 -n "udp port 67 and (udp[8:1] == 1 or udp[8:1] == 2)"

# Только REQUEST/ACK (второй этап DORA)
sudo tcpdump -i eth0 -n "udp port 67 and (udp[8:1] == 3 or udp[8:1] == 5)"

# Проверка прохождения через Relay (фильтрация по giaddr)
# giaddr = байты 24-27 в заголовке UDP-payload (DHCP-заголовок)
sudo tcpdump -i any -n "udp port 67 and ip[24:4] != 0"

# DHCPDECLINE (тип = 4)
sudo tcpdump -i any -n "udp port 67 and udp[8:1] == 4"

# DHCPNAK (тип = 6)
sudo tcpdump -i any -n "udp port 67 and udp[8:1] == 6"

# === IPv6 DHCP ===

# Все DHCPv6-пакеты
sudo tcpdump -i eth0 -n udp port 546 or port 547 -vv

# Solicit (тип = 1)
sudo tcpdump -i eth0 -n "udp port 547 and ip6[40:1] == 1"

# === Сохранение в файл для Wireshark ===

# Запись в pcap-файл (300 пакетов)
sudo tcpdump -i eth0 -n udp port 67 or port 68 -c 300 -w /tmp/dhcp.pcap

# Запись с фильтром по Relay (giaddr != 0)
sudo tcpdump -i any -n "udp port 67 and ip[24:4] != 0" -w /tmp/dhcp-relay.pcap
```

### Диагностика Relay через tcpdump

Когда клиент и сервер находятся в разных подсетях, Relay-агент заполняет поле `giaddr`. Проверка:

```bash
# На сервере: проверяем, что giaddr заполнен
sudo tcpdump -i any -n "udp port 67" -vv | grep "giaddr"

# Ожидаемый вывод:
# giaddr 10.0.1.1       ← Relay-агент в подсети клиента
# giaddr 0.0.0.0        ← ОШИБКА: Relay не заполнен!

# Фильтр: только пакеты с неверным giaddr (для поиска Rogue)
sudo tcpdump -i any -n "udp port 67 and ip[24:4] == 0" -c 5

# Запись Relay-трафика для анализа в Wireshark
sudo tcpdump -i any -n "udp port 67 and ip[24:4] != 0" -w /tmp/relay-analysis.pcap
```

### Wireshark: Display Filters для DHCP

| Цель | Display Filter | Описание |
| :--- | :--- | :--- |
| **Все DHCPv4** | `bootp \|\| dhcp` | Полный трафик DORA |
| **Только DISCOVER** | `dhcp.option.dhcp == 1` | Поиск клиентов |
| **Только OFFER** | `dhcp.option.dhcp == 2` | Ответы сервера |
| **Только REQUEST** | `dhcp.option.dhcp == 3` | Запросы клиентов |
| **Только ACK** | `dhcp.option.dhcp == 5` | Подтверждения |
| **Только NAK** | `dhcp.option.dhcp == 6` | Отказы сервера |
| **Только DECLINE** | `dhcp.option.dhcp == 4` | Конфликты IP |
| **Только RELEASE** | `dhcp.option.dhcp == 7` | Освобождения |
| **Relay (giaddr != 0)** | `bootp.giaddr != 0.0.0.0` | Трафик через ретранслятор |
| **Определённый клиент** | `bootp.chaddr == 00:50:56:b1:22:33` | Поиск по MAC |
| **Определённый сервер** | `bootp.ip.server == 10.0.0.1` | Поиск по IP сервера |
| **Определённая подсеть** | `bootp.yiaddr matches "10.0.10."` | Фильтр по выданным IP |
| **Опция 82 (Relay)** | `dhcp.option.agent_info` | Информация от Relay |
| **IPv6 DHCP** | `dhcpv6` | Все DHCPv6-пакеты |
| **IPv6 + IA_NA** | `dhcpv6.option.ia_na` | Назначения адресов |
| **RA (M/O флаги)** | `icmpv6.type == 134` | Router Advertisement |

### Анализ пакета в Wireshark: ключевые поля

```
DHCP: Dynamic Host Configuration Protocol
├── Message Type: Boot Reply (2)                    ← Тип сообщения (ACK=5, OFFER=2)
├── Hardware Type: Ethernet (0x01)
├── Hardware Address Length: 6
├── Hops: 0                                          ← =0 напрямую, >0 через Relay
├── Transaction ID: 0xabcdef01                      ← Correlation ID
├── Seconds: 0
├── Flags: 0x0000 (Unicast)                         ← Broadcast = 0x8000
├── Client IP Address: 0.0.0.0                      ← ciaddr (при продлении)
├── Your IP Address: 10.0.10.50                      ← yiaddr (предлагаемый IP)
├── Server IP Address: 10.0.0.1                      ← siaddr
├── Gateway IP Address: 10.0.1.1                     ← giaddr (Relay)
├── Client Hardware Address: 00:50:56:b1:22:33       ← MAC-адрес
├── Server Host Name: ""
├── Boot File Name: ""
├── Magic Cookie: 0x63825363
└── Options
    ├── Option 53: DHCP Message Type (ACK)           ← Тип DHCP-сообщения
    ├── Option 54: Server Identifier (10.0.0.1)      ← IP сервера
    ├── Option 51: IP Address Lease Time (86400)     ← Lease Time в секундах
    ├── Option 58: Renewal Time (43200)              ← T1
    ├── Option 59: Rebinding Time (75600)            ← T2
    ├── Option 1: Subnet Mask (255.255.255.0)
    ├── Option 3: Router (10.0.10.1)
    ├── Option 6: Domain Name Server (10.0.1.10)
    └── Option 55: Parameter Request List
```

## Диагностика DHCPv6 и взаимодействие с RA

В IPv6 DHCP работает в связке с Router Advertisements. Проверьте флаги в пакетах RA (ICMPv6 Type 134):
- **Managed Address Config (M-flag):** Если `1`, клиент должен запрашивать IP у DHCPv6 (Stateful).
- **Other Config (O-flag):** Если `1`, клиент запрашивает только опции (DNS, NTP) у DHCPv6 (Stateless).

Если флаги установлены неверно на маршрутизаторе, клиент никогда не отправит `Solicit`.

```bash
# Проверка RA на Linux-роутере
radvdump -I eth0 -o /tmp/ra.log
# → Смотрим M-flag и O-flag

# tcpdump для RA
sudo tcpdump -i eth0 -n "icmp6 and ip6[40] == 134" -vv
# → Fuld Router Advertisement, lifetime=1800, reachable=0
# → Prefix: 2001:db8:1::/64, L=1, A=1, valid=2592000, preferred=604800
# → RDNSS: 2001:db8::10, lifetime=9000

# Проверка через sysctl (Linux-клиент)
cat /proc/sys/net/ipv6/conf/eth0/accept_ra
# → 1 = принимать RA (норма)
# → 0 = RA отключены → клиент не узнает шлюз
```

### Типичные ошибки DHCPv6

| Проблема | Причина | Диагностика |
| :--- | :--- | :--- |
| **Нет IPv6-адреса** | RA не отправляются или M-flag=0 | `tcpdump`: есть ли RA? `radvdump` |
| **Есть адрес, нет шлюза** | RA без default gateway (_slAAC) | `ip -6 route show`: есть ли default route? |
| **DHCPv6 не работает** | UDP 546/547 заблокирован | `tcpdump`: приходят ли SOLICIT? |
| **DAD failed** | Конфликт Link-Local адреса | `ip -6 addr show`: tentative? |
| **DNS не работает** | Stateless DHCPv6 не настроен (O-flag=0) | `cat /etc/resolv.conf`: есть ли IPv6 DNS? |

## Типичные проблемы и методы решения

| Проблема | Вероятная причина | Метод диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **APIPA (169.254.x.x)** | Нет L2-связности или DHCP Snooping блокирует сервер | `tcpdump` на сервере: приходят ли запросы? | Проверить VLAN, порты коммутатора (Trusted/Untrusted). |
| **DHCP Discover не доходит до сервера** | Неверный PVID на порту — нетегированный DHCP Discover попадает в чужой broadcast-домен | `bridge vlan show` / `tcpdump -eni <iface> 'udp port 67 or 68'` на uplink | Исправить PVID на порту на нужную VLAN: `bridge vlan add dev <iface> vid <VLAN> pvid untagged` |
| **No Free Leases** | Исчерпание пула адресов | Лог: `no free leases` | Увеличить `range` или сократить `default-lease-time`. |
| **DHCP Relay Failure** | Неверный `giaddr` или отсутствие маршрута к нему | `tcpdump` на сервере: поле `giaddr` равно `0.0.0.0`? | Проверить конфиг ретранслятора (`ip helper-address`). |
| **Конфликт IP (NAK)** | Наличие статических IP внутри пула DHCP | `tcpdump`: пакет `DHCPNAK` или `DHCPDECLINE` | Исключить статику через `reserved-range` или `ping-check`. |
| **DNS не обновляется** | Ошибки DDNS или отсутствие прав в BIND | Лог сервера: `unable to add forward map` | Проверить `tsig` ключи и права доступа к зонам DNS. |
| **Медленный DORA** | Проблема с disk I/O на сервере, fsync в dhcpd.leases | `tcpdump`: задержка между DISCOVER и OFFER >1с | Проверить `iostat`, перейти на SSD или memfile (Kea). |
| **DHCP Snooping блокирует** | Клиент на Untrusted-порту без статической привязки | `show ip dhcp snooping binding` | Добавить static binding для серверов/Relay. |
| **Клиент получает чужой IP** | Rogue DHCP-сервер в сети | `tcpdump`: `dhcp.option.dhcp_server_id` ≠ ожидаемый | Включить DHCP Snooping, проверить `ip helper-address`. |

## Практический сценарий: DHCP не работает из-за неверного PVID

**Проблема:** Клиент подключается к сети — физический линк поднят, но IP-адрес не получает. DHCP-сервер работает, свободные адреса есть в пуле, однако DHCP Discover от клиента не достигает сервера.

**Архитектура:**
```
Клиент (нетегированный)
    │
    ▼
eth1 (access-порт)
    │
    ▼
VLAN-aware Bridge (br0) ← DHCP-сервер в VLAN 20
    └── VLAN 10 (PVID ошибочно назначен)
    └── VLAN 20 (требуемая)
```

**Корень проблемы:** DHCP Discover отправляется широковещательно без VLAN-тега. Коммутатор (или Linux bridge) принимает кадр и относит его к VLAN, заданному через PVID на порту. Если вместо требуемого VLAN 20 на порту установлен PVID = 10, Discover попадает в чужой broadcast-домен. DHCP-сервер в VLAN 20 его не видит.

### Где теряется DHCP Discover

Клиент отправляет DHCP Discover широковещательно (`255.255.255.255:67`), обычно без VLAN-тега. Коммутатор принимает кадр и относит его к VLAN, заданному через PVID. Если вместо VLAN 20 на порту стоит VLAN 10, Discover попадёт не в тот широковещательный домен.

DHCP-сервер в VLAN 20 его просто не увидит — широковещательные запросы не пересекают границы broadcast-домена без маршрутизации.

### Шаг 1: Проверка VLAN на порту

На Linux bridge с включённой VLAN-фильтрацией:

```bash
bridge vlan show
```

```text
# → port    vlan ids
# → eth0    10                       ← Trunk: тегированный трафик
# → eth1    10 PVID Egress Untagged  ← ОШИБКА: PVID = 10, а не 20
# →         20
```

Здесь нетегированные кадры с `eth1` попадают в VLAN 10, а не в VLAN 20. Если клиент должен находиться в VLAN 20, конфигурация порта неверна.

### Шаг 2: Исправление PVID

```bash
# Удаляем неверный PVID (VLAN 10)
sudo bridge vlan del dev eth1 vid 10 pvid untagged

# Добавляем правильный PVID (VLAN 20)
sudo bridge vlan add dev eth1 vid 20 pvid untagged

# Проверка
bridge vlan show
# → port    vlan ids
# → eth1    20 PVID Egress Untagged
```

### Шаг 3: Поиск DHCP Discover в трафике

```bash
# Захват DHCP-трафика на клиентском порту
sudo tcpdump -eni eth1 'udp port 67 or 68'
```

Ключ `-e` показывает Ethernet-заголовок, что позволяет увидеть наличие или отсутствие 802.1Q тега. На trunk-порту можно дополнительно проверить, с каким VLAN-тегом проходит DHCP-трафик.

```bash
# Захват на uplink для проверки, в каком VLAN проходит Discover
sudo tcpdump -eni eth0 'udp port 67 or 68'

# Фильтрация по конкретному VLAN (должен видеть Discover в VLAN 20)
sudo tcpdump -eni eth0 'vlan 20 and udp port 67'
```

Если Discover виден на клиентском порту, но отсутствует в нужном VLAN на uplink — проблема в PVID, VLAN membership или правилах тегирования.

### Шаг 4: Проверка на коммутаторах (Cisco/Juniper/Huawei)

Для аппаратных коммутаторов PVID называется иначе, но смысл тот же:

```cisco
# Cisco — проверка Native VLAN и Allowed VLAN на trunk-порту
show interfaces trunk
# → Port        Mode        Encapsulation  Status        Native vlan
# → Gi0/24      on          802.1q         trunking      10      ← ОШИБКА (должно быть 999 или no native)

show interfaces switchport | include Administrative Mode|Trunking Native
# → Administrative Mode: trunk
# → Trunking Native VLAN: 10
```

Исправление:

```cisco
interface GigabitEthernet0/24
  switchport trunk allowed vlan 20
  no switchport trunk native vlan 10
```

Для Huawei:

```huawei
display port vlan interface GigabitEthernet0/0/24
# → PVID: 10   ← ОШИБКА

# Исправление:
interface GigabitEthernet0/0/24
  port trunk pvid vlan 999
  port trunk allow-pass vlan 20
```

### Профилактика

- **Документируйте PVID/Native VLAN** для каждого порта — расхождения между портами приводят к потере broadcast-трафика в чужих VLAN.
- **Удаляйте VLAN 1** по умолчанию с всех портов (см. **[VLAN в Linux](./../VLAN/vlan_linux_diagnostics.md)**).
- **Проверяйте тегирование** через `tcpdump -e` на физических интерфейсах — это быстрее, чем ловить симптомы на уровне L3.
- **Для коммутаторов:** включяйте `vlan dot1q tag native` (Cisco) или аналог — это устраняет неоднозначность с Native VLAN.

**Важно:** DHCP Discover не знает, в какой VLAN ему нужно попасть. Для нетегированного кадра это решает коммутатор. Один неверный PVID может отправить весь DHCP-трафик в чужую сеть.

## Инструменты мониторинга и метрики

### ISC DHCP: Экспорт метрик

```bash
# dhcpd-leases-exporter (Prometheus)
# Экспортирует: dhcpd_leases_active, dhcpd_leases_abandoned, dhcpd_pool利用率

# Простой скрипт мониторинга
#!/bin/bash
ACTIVE=$(grep -c "binding state active" /var/lib/dhcp/dhcpd.leases)
ABANDONED=$(grep -c "binding state abandoned" /var/lib/dhcp/dhcpd.leases)
FREE=$(grep -c "binding state free" /var/lib/dhcp/dhcpd.leases)
echo "dhcp_active=$ACTIVE dhcp_abandoned=$ABANDONED dhcp_free=$FREE"
```

### Kea DHCP: REST API и метрики

```bash
# Kea DHCP: REST API (если настроен control-agent)
curl -s http://localhost:8000/ | jq '.[] | {ip: .ip-address, state: .state}'

# Kea: экспорт метрик черезkea-lfc
kea-lfc -4 -c /etc/kea/kea-lfc4.conf
# → Фоновая очистка и компактификация файла аренд
```

### Syslog/SNMP Trap

```bash
# ISC DHCP: отправка SNMP trap при критических ошибках
# dhcpd.conf:
option log-servers 10.0.0.100;
```

## Реальные примеры анализа пакетов

### Пример 1: Нормальный DORA-процесс

```text
# tcpdump -i eth0 -n udp port 67 or port 68 -vv

12:00:00.000001 IP 0.0.0.0.68 > 255.255.255.255.67: UDP, length 300
  BOOTP/DHCP, Request, htype Ethernet, hlen 6, hops 0, xid 0xabcdef01
  flags Broadcast (0x8000)
  client-addr 0.0.0.0
  giaddr 0.0.0.0
  chaddr 00:50:56:b1:22:33
  Magic-cookie 0x63825363
  Option 53 DHCP Message Type = DHCP Discover (1)
  Option 55 Parameter Request List: 1,3,6,15,43,51,58,59
  Option 60 Vendor Class Identifier = "Linux-5.15"
  Option 12 Host Name = "srv-web-01"

12:00:00.127456 IP 10.0.0.1.67 > 10.0.10.50.68: UDP, length 300
  BOOTP/DHCP, Reply, htype Ethernet, hlen 6, hops 0, xid 0xabcdef01
  your-addr 10.0.10.50
  giaddr 0.0.0.0
  chaddr 00:50:56:b1:22:33
  Magic-cookie 0x63825363
  Option 53 DHCP Message Type = DHCP Offer (2)
  Option 54 Server Identifier = 10.0.0.1
  Option 51 IP Address Lease Time = 86400 sec
  Option 1 Subnet Mask = 255.255.255.0
  Option 3 Router = 10.0.10.1
  Option 6 DNS Servers = 10.0.0.10, 10.0.0.11

# Анализ: DISCOVER (Broadcast) → OFFER (Unicast) за 127ms — НОРМА
# Клиент получил IP 10.0.10.50, шлюз 10.0.10.1, DNS 10.0.0.10
```

### Пример 2: DHCPNAK — неверная подсеть при продлении

```text
# tcpdump -i eth0 -n udp port 67 -vv

14:30:00.001234 IP 10.0.10.50.68 > 10.0.0.1.67: UDP, length 300
  BOOTP/DHCP, Request, htype Ethernet, hlen 6, hops 0, xid 0x12345678
  client-addr 10.0.10.50         ← Клиент запрашивает продление
  giaddr 0.0.0.0
  chaddr 00:50:56:b1:22:33
  Magic-cookie 0x63825363
  Option 53 DHCP Message Type = DHCP Request (3)
  Option 54 Server Identifier = 10.0.0.1
  Option 50 Requested IP Address = 10.0.10.50

14:30:00.050678 IP 10.0.0.1.67 > 10.0.10.50.68: UDP, length 300
  BOOTP/DHCP, Reply, htype Ethernet, hlen 6, hops 0, xid 0x12345678
  your-addr 0.0.0.0
  giaddr 0.0.0.0
  chaddr 00:50:56:b1:22:33
  Magic-cookie 0x63825363
  Option 53 DHCP Message Type = DHCP NAK (6)
  Option 54 Server Identifier = 10.0.0.1
  Option 56 Error Message = " Lease unknown"

# Анализ: Клиент переместился в другую подсеть, но запрашивает старый IP.
# Сервер отвечает NAK, клиент начинает полный DORA.
# РЕШЕНИЕ: На сервере добавить authoritative; или исправить subnets.
```

### Пример 3: DHCP Relay (giaddr != 0)

```text
# tcpdump -i eth0 -n "udp port 67" -vv

16:00:00.000001 IP 0.0.0.0.68 > 255.255.255.255.67: UDP, length 300
  BOOTP/DHCP, Request, htype Ethernet, hlen 6, hops 1, xid 0xdeadbeef
  flags Broadcast (0x8000)
  client-addr 0.0.0.0
  giaddr 10.0.1.1              ← Relay-агент (роутер) пометил подсеть
  hops 1                        ← Прошёл через 1 Relay
  chaddr aa:bb:cc:dd:ee:ff
  Magic-cookie 0x63825363
  Option 53 DHCP Message Type = DHCP Discover (1)
  Option 82 Agent Information:
    Circuit ID = "VLAN100-port3"
    Remote ID = "relay-core-sw"

16:00:00.045678 IP 10.0.0.1.67 > 10.0.10.80.68: UDP, length 300
  BOOTP/DHCP, Reply, htype Ethernet, hlen 6, hops 0, xid 0xdeadbeef
  your-addr 10.0.10.80
  giaddr 10.0.1.1              ← Сервер возвращает giaddr клиенту
  chaddr aa:bb:cc:dd:ee:ff
  Magic-cookie 0x63825363
  Option 53 DHCP Message Type = DHCP Offer (2)
  Option 54 Server Identifier = 10.0.0.1
  Option 82 Agent Information: ...  ← Echoed back

# Анализ: Клиент в подсети 10.0.1.0/24, Relay 10.0.1.1.
# Сервер (10.0.0.1) в ответе также указывает giaddr.
# Ожидаемое поведение: giaddr в REQUEST клиента ≠ 0, ACK возвращается через Relay.
```

### Пример 4: DHCP Starvation Attack

```text
# tcpdump -i eth0 -n "udp port 67" -c 50

17:00:00.001000 IP 0.0.0.0.68 > 255.255.255.255.67: BOOTP/DHCP, Request, xid 0x00000001, chaddr 00:11:22:33:44:01
17:00:00.002000 IP 0.0.0.0.68 > 255.255.255.255.67: BOOTP/DHCP, Request, xid 0x00000002, chaddr 00:11:22:33:44:02
17:00:00.003000 IP 0.0.0.0.68 > 255.255.255.255.67: BOOTP/DHCP, Request, xid 0x00000003, chaddr 00:11:22:33:44:03
... (47 más peticiones con MACs diferentes)

# Анализ: >50 DISCOVER с подряд идущими MAC-адресами за 3 секунды.
# Признаки: rand MAC, xid по порядку, нет OFFER от сервера.
# РЕШЕНИЕ: Включить DHCP Snooping + rate-limit на порту.
# Команда: ip dhcp snooping limit rate 10
```

### Шпаргалка: что искать в pcap

| Симптом | Что искать в Wireshark/tcpdump | Решение |
| :--- | :--- | :--- |
| **Клиент не получает OFFER** | DISCOVER есть, OFFER нет | Проверить сервер (dhcpd -t), firewall |
| **OFFER есть, ACK нет** | REQUEST отправлен, ACK не пришёл | Конфликт IP, сервер overloaded |
| **NAK вместо ACK** | DHCPNAK в ответ на REQUEST | Клиент в неверной подсети, нет authoritative |
| **APIPA (169.254.x.x)** | Нет DISCOVER вообще | L2-проблема, VLAN, физическая связность |
| **giaddr = 0.0.0.0** | Relay не заполнен | Конфиг Relay (ip helper-address) |
| **Повторяющиеся DECLINE** | Много DHCPDECLINE | IP-конфликт, статика в DHCP-пуле |
| **Медленный DORA** | DISCOVER→OFFER >1с | Диск сервера, fsync, классы |

## Дополнительная информация

- [Обзор DHCP](./dhcp_overview.md) — базовые принципы и процессы DORA/SARR.
- [Время аренды и типы сообщений](./dhcp_lease_time.md) — детальный разбор таймеров и типов пакетов.
- [Безопасность DHCP](./dhcp_security.md) — защита от Rogue DHCP и атак истощения.
- [DHCP Relay](./dhcp_relay.md) — работа через маршрутизаторы и диагностика ретрансляции.
- [ISC DHCP: Проверка и мониторинг](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_verification.md) — анализ файла `dhcpd.leases` и omshell.
- [ISC DHCP: Базовая настройка](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_basic_config.md) — конфигурация `dhcpd.conf`.
- [Kea DHCP: Архитектура и настройка](../../../Linux/Networking/Services/DHCP/kea_dhcp_overview.md) — modern alternative.
- [Мониторинг и наблюдаемость DHCP](./dhcp_monitoring_observability.md) — Prometheus, Grafana, SIEM.
- **Спецификации:**
  - [RFC 2131](https://datatracker.ietf.org/doc/html/rfc2131) — Dynamic Host Configuration Protocol (раздел 7 — Troubleshooting).
  - [RFC 2132](https://datatracker.ietf.org/doc/html/rfc2132) — DHCP Options and BOOTP Vendor Class Identifier.
  - [RFC 8415](https://datatracker.ietf.org/doc/html/rfc8415) — Dynamic Host Configuration Protocol for IPv6.
