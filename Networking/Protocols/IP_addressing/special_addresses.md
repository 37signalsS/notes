# Специальные и частные IP-адреса

**Необходимые знания:**
- Понимание структуры IPv4 и IPv6 адресов
- Основы подсетей и CIDR-нотации
- Базовые понятия маршрутизации (таблица маршрутизации, Gateway)
- Знакомство с работой DHCP-сервера

## Определения

**IANA (Internet Assigned Numbers Authority)** — организация, отвечающая за глобальное распределение IP-адресов и поддержку реестров параметров протоколов. IANA выделяет блоки адресов региональным регистраторам (RIR) и резервирует диапазоны для специальных нужд.

**RFC (Request for Comments)** — стандарты интернета, в которых задокументированы технические спецификации. Специальные диапазоны IP жестко закреплены в RFC и имеют уникальные правила обработки сетевым стеком.

**Частные (приватные) IP-адреса** — диапазоны для локальных сетей (LAN), не маршрутизируемые в публичном интернете. Описаны в **RFC 1918** (IPv4) и **RFC 4193** (IPv6 ULA).

**Link-Local адреса** — адреса, предназначенные для связи только в пределах одного физического или логического (VLAN) сегмента сети.

## Основные концепции

### Базовые системные адреса

| Версия | Адрес / Префикс | RFC | Описание |
| :--- | :--- | :--- | :--- |
| **IPv4** | `127.0.0.1` | RFC 1122 | **Loopback:** локальная петля. Резервируется вся сеть `127.0.0.0/8`. |
| **IPv6** | `::1/128` | RFC 4291 | **Loopback:** эквивалент в IPv6. |
| **IPv4** | `0.0.0.0` | RFC 1122 | **Unspecified:** «любой адрес» или «все интерфейсы» при прослушивании портов. |
| **IPv6** | `::` | RFC 4291 | **Unspecified:** эквивалент в IPv6. |
| **IPv4** | `0.0.0.0/8` | RFC 1122 | **This Network:** используется только как адрес источника (например, в начале DHCP-процесса). |
| **IPv4** | `0.0.0.0/0` | RFC 1812 | **Default Route:** маршрут «в мир» (шлюз по умолчанию). |
| **IPv6** | `::/0` | RFC 4291 | **Default Route:** аналог в IPv6. |

Подробности: [Сетевые интерфейсы в Linux](../../../Linux/Networking/Concepts/linux_network_interfaces.md#2-виртуальные-интерфейсы) и [Маршрутизация в Linux](../../../Linux/SystemAdministration/routing.md#4-маршрут-по-умолчанию-default-gateway).

### Частные (приватные) сети

Эти диапазоны не маршрутизируются в интернете напрямую и требуют [NAT](../../Concepts/nat/overview.md) для выхода во внешнюю сеть.

| Тип | Диапазон / Префикс | RFC | Кол-во хостов (IPv4) |
| :--- | :--- | :--- | :--- |
| **IPv4 Class A** | `10.0.0.0/8` | RFC 1918 | 16,777,214 |
| **IPv4 Class B** | `172.16.0.0/12` | RFC 1918 | 1,048,574 |
| **IPv4 Class C** | `192.168.0.0/16` | RFC 1918 | 65,534 |
| **IPv4 CGNAT** | `100.64.0.0/10` | RFC 6598 | 4,194,302 (Shared Address Space) |
| **IPv6 ULA** | `fc00::/7` | RFC 4193 | ~$1,2 \times 10^{36}$ подсетей `/64` |

### Адреса Link-Local

| Версия | Диапазон / Префикс | RFC | Описание |
| :--- | :--- | :--- | :--- |
| **IPv4 (APIPA)** | `169.254.0.0/16` | RFC 3927 | Назначается автоматически при отсутствии DHCP. |
| **IPv6** | `fe80::/10` | RFC 4291 | **Обязательны** для каждого интерфейса; используются для NDP. |

### Групповая рассылка (Multicast)

| Версия | Диапазон / Префикс | RFC | Описание |
| :--- | :--- | :--- | :--- |
| **IPv4** | `224.0.0.0/4` | RFC 1112 | От `224.0.0.0` до `239.255.255.255`. |
| **IPv6** | `ff00::/8` | RFC 4291 | Используется вместо Broadcast в IPv6. |

Подробности: [MAC-адреса](../../Concepts/mac_address.md#2-групповой-multicast).

### Специализированные и технологические диапазоны

| Адрес / Префикс | RFC | Назначение |
| :--- | :--- | :--- |
| `192.0.0.0/24` | RFC 6890 | IETF Protocol Assignments (служебные адреса протоколов). |
| `198.18.0.0/15` | RFC 2544 | **Benchmarking:** тестирование производительности оборудования. |
| `192.0.2.0/24` | RFC 5737 | Documentation (TEST-NET-1) — только для примеров. |
| `198.51.100.0/24` | RFC 5737 | Documentation (TEST-NET-2). |
| `203.0.113.0/24` | RFC 5737 | Documentation (TEST-NET-3). |
| `2001:db8::/32` | RFC 3849 | Documentation IPv6. |
| `::ffff:0:0/96` | RFC 4291 | **IPv4-Mapped:** IPv4-адреса внутри IPv6 стека. |
| `64:ff9b::/96` | RFC 6052 | **NAT64:** префикс для трансляции IPv6 -> IPv4. |
| `2001::/32` | RFC 4380 | **Teredo:** туннелирование IPv6 через NAT IPv4. |
| `240.0.0.0/4` | RFC 1122 | Зарезервировано для будущего использования (Class E). |

## Практические сценарии

### Диагностика APIPA (169.254.x.x)

Если команда `ip addr` показывает такой адрес, это индикатор того, что:
1. Сетевой линк (L1/L2) поднят, но ответ от DHCP-сервера не получен.
2. Пул адресов на DHCP-сервере исчерпан.
3. Широковещательные пакеты (DHCP Discover) блокируются в L2-сегменте или на Firewall.

### Проблема «Двойного NAT» при CGNAT

Когда провайдер выдает адрес из `100.64.0.0/10`, клиент находится за NAT оператора.
- **Следствие:** Прямой проброс портов (Port Forwarding) на домашнем роутере не будет работать для доступа из интернета.
- **Решение:** Использование VPN, Cloudflare Tunnel или аренда «белого» статического IP.

### Приоритет Loopback и привязка сервисов (Binding)

- `bind 127.0.0.1` — сервис (например, Redis или БД) доступен только процессам внутри этой же ОС. Это критическая мера безопасности.
- `bind 0.0.0.0` — сервис слушает все доступные IPv4 интерфейсы.
- `bind ::` — сервис слушает все доступные IPv6 интерфейсы.

### Тестирование производительности (Benchmarking)

При проведении нагрузочных тестов сети (например, через `iperf3` или специализированные тестеры) следует использовать диапазон `198.18.0.0/15`. Это предотвращает случайную утечку тестового трафика в продакшн-сети или глобальный интернет.

### Диагностика Loopback (127.0.0.0/8)

```bash
# Проверка работоспособности TCP/IP стека
ping -c 3 127.0.0.1
# → 64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.029 ms

# Проверка доступности сервиса на loopback
ss -tlnp | grep :80
# → LISTEN  0  128  127.0.0.1:80  0.0.0.0:*  users:(("nginx",pid=1234,fd=6))

# Проверка, слушает ли сервис ТОЛЬКО на loopback (безопасно)
ss -tlnp | grep :5432
# → LISTEN  0  128  127.0.0.1:5432  0.0.0.0:*  users:(("postgres",pid=5678,fd=5))
# Если видно 0.0.0.0:5432 — сервис доступен извне (potential risk)

# Проверка всех loopback-интерфейсов
ip addr show lo
# → 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
# →     inet 127.0.0.1/8 scope host lo
# →     inet6 ::1/128 scope host
```

### Диагностика и настройка Link-Local (fe80::/10)

```bash
# Просмотр Link-Local адресов
ip -6 addr show | grep fe80
# → inet6 fe80::250:56ff:feb3:1234/64 scope link
# → inet6 fe80::1/64 scope link

# Ping через Link-Local (обязательно указывать% интерфейс)
ping6 -I eth0 fe80::1
# → 64 bytes from fe80::1%eth0: icmp_seq=1

# Просмотр таблицы соседей (NDP)
ip -6 neigh show
# → fe80::1 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE

# Диагностика Link-Local в dual-stack среде
ip addr show | grep -A2 "inet6 fe80"
```

### Диагностика CGNAT (100.64.0.0/10)

```bash
# Определение, находитесь ли вы за CGNAT
# 1. Сравните внешний IP с IP на интерфейсе роутера
curl -s https://ifconfig.me && echo ""
# → 100.64.0.1  (если провайдер использует CGNAT)

# 2. Проверка IP на WAN-интерфейсе роутера
# Если WAN = 100.64.x.x, вы за CGNAT

# Проверка traceroute до发现了 CGNAT
traceroute -n 8.8.8.8 | head -5
# → 1  100.64.0.1  (первый хоп = CGNAT gateway)

# Проверка порта через CGNAT
# Если порт недоступен извне, вероятно CGNAT
nc -zv 8.8.8.8 80
```

### Диагностика Documentation-адресов (192.0.2.0/24, 198.51.100.0/24)

```bash
# Проверка, является ли IP документационным
is_documentation_ip() {
    local ip=$1
    
    # Преобразование в число
    local ip_num=$(echo "$ip" | awk -F. '{print ($1*2^24)+($2*2^16)+($3*2^8)+$4}')
    
    # Проверка диапазонов
    # 192.0.2.0/24 = 3221225984 - 3221226239
    if [ $ip_num -ge 3221225984 ] && [ $ip_num -le 3221226239 ]; then
        echo "$ip — TEST-NET-1 (RFC 5737)"
    # 198.51.100.0/24 = 3323069440 - 3323069695
    elif [ $ip_num -ge 3323069440 ] && [ $ip_num -le 3323069695 ]; then
        echo "$ip — TEST-NET-2 (RFC 5737)"
    # 203.0.113.0/24 = 3405774848 - 3405775103
    elif [ $ip_num -ge 3405774848 ] && [ $ip_num -le 3405775103 ]; then
        echo "$ip — TEST-NET-3 (RFC 5737)"
    else
        echo "$ip — НЕ документационный адрес"
    fi
}

# Использование
is_documentation_ip 192.0.2.1    # TEST-NET-1
is_documentation_ip 198.51.100.5 # TEST-NET-2
is_documentation_ip 203.0.113.10 # TEST-NET-3
is_documentation_ip 8.8.8.8      # НЕ документационный
```

### Диагностика IPv4-Mapped адресов (::ffff:0:0/96)

```bash
# Просмотр IPv4-mapped IPv6 адресов
ss -t6lnp | grep ::ffff
# → LISTEN  0  128  :::80  :::*  users:(("nginx",pid=1234,fd=6))

# Проверка строки состояния соединения
ss -t6 state established | grep ::ffff
# → ESTAB  0  0  ::ffff:192.168.1.100:80  ::ffff:192.168.1.200:54321

# Diagnostics: определение dual-stack vs IPv6-only
ip -6 addr show | grep -c "inet6 ::ffff:"
# → 0 = IPv6-only стек
# → >0 = dual-stack (есть IPv4-mapped)

# Проверка dual-stack через curl
curl -6 http://[::ffff:192.168.1.100]
# Если работает — dual-stack настроен корректно
```

### Настройка привязки сервисов к Loopback

```bash
# Правильная привязка к loopback для безопасности

# Redis — только localhost
# /etc/redis/redis.conf:
bind 127.0.0.1 ::1

# PostgreSQL — только localhost  
# /etc/postgresql/*/main/postgresql.conf:
listen_addresses = 'localhost'

# MySQL/MariaDB — только localhost
# /etc/mysql/mariadb.conf.d/50-server.cnf:
bind-address = 127.0.0.1

# MongoDB — только localhost
# /etc/mongod.conf:
net:
  bindIp: 127.0.0.1

# Проверка привязки после настройки
ss -tlnp | grep -E "127.0.0.1|::1"
```

### Использование документационных адресов в примерах

```bash
# Безопасные примеры конфигураций с документационными адресами

# Пример IP-адресации (RFC 5737)
# Используйте TEST-NET-1, TEST-NET-2, TEST-NET-3 в документации

# Пример конфигурации Cisco IOS
interface GigabitEthernet0/0
 ip address 192.0.2.1 255.255.255.0  # TEST-NET-1
 description Example Interface

# Пример конфигурации Linux (netplan)
network:
  version: 2
  ethernets:
    eth0:
      addresses:
        - 198.51.100.100/24  # TEST-NET-2

# Пример для Kubernetes
apiVersion: v1
kind: Pod
metadata:
  name: example
spec:
  containers:
  - name: nginx
    image: nginx
    ports:
    - containerPort: 80
    # Используйте документационные адреса в примерах
```

## Troubleshooting

### Частые ошибки со специальными адресами

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Loopback не отвечает** | `ping 127.0.0.1` — timeout | TCP/IP стек поврежден | Переустановка драйверов, проверка firewall |
| **APIPA вместо DHCP** | `169.254.x.x` в ip addr | DHCP-сервер недоступен | Проверить DHCP-сервер, кабель, VLAN |
| **Double NAT** | Проблемы с Port Forwarding | CGNAT у провайдера | Аренда белого IP, VPN, Cloudflare Tunnel |
| **Link-Local не работает** | `fe80::` не пингуется | Интерфейс не UP | `ip link set eth0 up`, проверка NDP |
| **Multicast не проходит** | Групповые сервисы не работают | Multicast routing не настроен | PIM, IGMP snooping на коммутаторах |
| **Документационный IP в проде** | Сайт/сервис не доступен | Использован TEST-NET-1/2/3 | Заменить на реальный IP |

### Диагностика Loopback проблем

```bash
# Проверка целостности TCP/IP стека
ping -c 5 127.0.0.1
# → Если нет ответа — проблема с ядром ОС

# Проверка интерфейса lo
ip link show lo
# → 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
# Если нет UP — интерфейс не активен

# Проверка маршрута до loopback
ip route get 127.0.0.1
# → 127.0.0.1 dev lo table local src 127.0.0.1

# Восстановление loopback (если удалён)
sudo ip link add lo type loopback 2>/dev/null
sudo ip link set lo up
sudo ip addr add 127.0.0.1/8 dev lo

# Проверка всех сервисов на loopback
ss -tlnp | grep "127.0.0.1"
```

### Диагностика APIPA проблем

```bash
# Проверка текущего IP-адреса
ip addr show | grep "inet "
# → inet 169.254.10.5/16 brd 169.254.255.255 scope link dynamic
# Если видно 169.254.x.x — проблема с DHCP

# Определение состояния DHCP
journalctl -u NetworkManager | grep -i dhcp
# → Aug 26 10:00:00 hostname dhclient[1234]: DHCPDISCOVER on eth0
# → Aug 26 10:00:10 hostname dhclient[1234]: No DHCPOFFERS

# Принудительное обновление DHCP
sudo dhclient -v eth0
# → DHCPDISCOVER on eth0 to 255.255.255.255 port 67

# Проверка VLAN-тегирования (частая причина APIPA)
ethtool -i eth0 | grep driver
# → driver: e1000e

# Проверка Duplex mismatch
ethtool eth0 | grep Speed
# → Speed: 1000Mb/s
# → Duplex: Full
# Если Duplex: Half — возможна проблема

# Очистка и повторное получение IP
sudo ip addr flush dev eth0
sudo dhclient -r eth0 && sudo dhclient eth0
```

### Диагностика CGNAT проблем

```bash
# Определение CGNAT по внешнему IP
curl -s https://ifconfig.me
# → 100.64.0.15 (если 100.64.0.0/10 — это CGNAT)

# Проверка через traceroute
traceroute -n 8.8.8.8 | head -5
# → 1  100.64.0.1  ← CGNAT gateway

# Проверка MTU (часто проблема в CGNAT)
ping -M do -s 1472 8.8.8.8
# → Нужно уменьшить MTU если не проходит

# Проверка порта извне
# Если порт недоступен — CGNAT блокирует входящие

# Обход CGNAT: проверка Tailscale/WireGuard
tailscale status | head -5
# → 100.64.0.1  hostname  user@  linux  -
```

### Диагностика Link-Local (IPv6) проблем

```bash
# Проверка наличия Link-Local адреса
ip -6 addr show | grep "fe80"
# → inet6 fe80::250:56ff:feb3:1234/64 scope link
# Если нет — проблема с автоконфигурацией

# Проверка состояния интерфейса
ip link show eth0
# → 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
# Если нет UP — интерфейс не активен

# Проверка NDP-таблицы
ip -6 neigh show
# → fe80::1 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE
# Если STALE — проблема с связностью

# Принудительное обновление NDP
ip -6 neigh flush dev eth0
ping6 -I eth0 fe80::1

# Проверка RA (Router Advertisement)
rdisc6 -1 eth0
# → Нет RA — проблема с router advertisements
```

### Диагностика Multicast проблем

```bash
# Проверка multicast-маршрутизации
ip maddr show
# → 1: lo
# →     link-local  01:00:5e:00:00:01
# →     inet  224.0.0.1

# Проверка IGMP на интерфейсе
ip link show multicast eth0
# → multicast on

# Проверка PIM (если нужна маршрутизация multicast)
ip mroute show
# → (пусто — multicast routing не настроен)

# Включение multicast на интерфейсе
sudo ip link set multicast on eth0

# Проверка IGMP snooping на коммутаторе
# (зависит от.vendor: Cisco, MikroTik, etc.)
```

### Проверка и настройка Service Binding

```bash
# Проверка, какие сервисы слушают на каких интерфейсах
ss -tlnp | awk '{print $4, $6}' | sort

# Пример вывода:
# 0.0.0.0:22 sshd:  (estead)  ← Слушает на ВСЕХ интерфейсах (опасно!)
# 127.0.0.1:5432 postgres:  ← Только loopback (безопасно)
# 192.168.1.100:80 nginx:  ← Только на конкретном IP

# Проверка через netstat (устаревший способ)
netstat -tlnp | grep -E "LISTEN|Local"

# Поиск сервисов, слушающих на 0.0.0.0 (опасно)
ss -tlnp | grep "0.0.0.0:" | awk '{print $6}' | cut -d'/' -f1 | sort -u
```

### Автоматизация диагностики

```bash
# Скрипт полной диагностики специальных адресов
diagnose_special_addresses() {
    echo "=== Диагностика специальных IP-адресов ==="
    echo ""
    
    echo "--- Loopback (127.0.0.1) ---"
    ping -c 1 -W 1 127.0.0.1 >/dev/null 2>&1 && echo "✓ Loopback работает" || echo "✗ Loopback НЕ работает"
    
    echo ""
    echo "--- APIPA (169.254.x.x) ---"
    ip addr show | grep -q "169.254" && echo "⚠ Обнаружен APIPA адрес" || echo "✓ APIPA не используется"
    
    echo ""
    echo "--- Link-Local IPv6 (fe80::) ---"
    ip -6 addr show | grep -q "fe80" && echo "✓ Link-Local IPv6 настроен" || echo "⚠ Link-Local IPv6 отсутствует"
    
    echo ""
    echo "--- Private IP (10.x, 172.16-31.x, 192.168.x) ---"
    ip addr show | grep -qE "inet (10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)" && echo "✓ Private IP используется" || echo "⚠ Private IP не обнаружен"
    
    echo ""
    echo "--- CGNAT (100.64.0.0/10) ---"
    ip addr show | grep -q "100.64" && echo "⚠ Обнаружен CGNAT адрес" || echo "✓ CGNAT не используется"
    
    echo ""
    echo "--- Documentation IPs ---"
    ip addr show | grep -qE "inet (192\.0\.2\.|198\.51\.100\.|203\.0\.113\.)" && echo "⚠ Обнаружен документационный IP" || echo "✓ Документационные IP не используются"
}

# Запуск диагностики
diagnose_special_addresses
```

## Best Practices

### Безопасность специальных адресов

| Практика | Описание | Пример |
| :--- | :--- | :--- |
| **Привязка к Loopback** | Всегда привязывайте сервисы к `127.0.0.1`, если внешний доступ не требуется | `bind 127.0.0.1` для Redis, PostgreSQL |
| **Блокировка APIPA** | Отключайте APIPA в корпоративных сетях через GPO/registry | `HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\IPAutoconfigurationEnabled=0` |
| **Фильтрация CGNAT** | Используйте ACL для блокировки трафика из `100.64.0.0/10` | `access-list 101 deny ip 100.64.0.0 0.63.255.255 any` |
| **Multicast Isolation** | Изолируйте multicast-трафик в отдельные VLAN | VLAN для IPTV, видеоконференций |

### Планирование адресного пространства

1. **Документирование:** Ведите реестр используемых специальных диапазонов.
2. **Мониторинг:** Отслеживайте появление APIPA-адресов в сети.
3. **Резервирование:** Не используйте специальные диапазоны для production.
4. **Тестирование:** Используйте только документационные адреса (RFC 5737) в примерах.

### Оптимизация производительности

- **Loopback:** Используйте `127.0.0.1` для внутри-системных соединений (без сетевого стека).
- **Link-Local:** Не используйте для production-сервисов (только для discovery, NDP).
- **Multicast:** Настройте IGMP snooping для предотвращения flooding.

### Совместимость

- **Dual-stack:** Учитывайте IPv4-mapped адреса при настройке сервисов.
- **Legacy:** Старое оборудование может не поддерживать ULA (`fc00::/7`).
- **Cloud:** Облачные провайдеры могут резервировать специальные диапазоны.

## Edge Cases

### Loopback в контейнерах (Docker, Kubernetes)

**Особенности:**
- В контейнерах loopback работает по-разному в зависимости от network mode.
- `host` network mode использует хостовый loopback.
- `bridge` mode создаёт изолированный loopback.

```bash
# Проверка loopback в контейнере
docker run --rm alpine ping -c 1 127.0.0.1
# → 127.0.0.1 — работает в bridge mode

# Проверка в host mode
docker run --rm --network host alpine ping -c 1 127.0.0.1
# → 127.0.0.1 — хостовый loopback

# Проверка в Kubernetes Pod
kubectl exec <pod> -- ping -c 1 127.0.0.1
# → 127.0.0.1 — изолированный loopback пода
```

### APIPA и Windows vs Linux

**Различия поведения:**
- Windows: APIPA отключается при получении DHCP-ответа.
- Linux: APIPA может сохраняться после получения DHCP (зависит от NetworkManager).
- macOS: APIPA отключается при подключении к сети с DHCP.

```bash
# Отключение APIPA на Linux
sudo ip addr del 169.254.x.x/16 dev eth0

# Проверка состояния APIPA на Windows
ipconfig /all | findstr "169.254"
# → Autoconfiguration IP Address: 169.254.10.5

# Отключение APIPA через реестр (Windows)
reg add "HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters" /v IPAutoconfigurationEnabled /t REG_DWORD /d 0 /f
```

### CGNAT и Double NAT

**Проблемы:**
- Port Forwarding не работает на домашнем роутере.
- VPN-серверы могут быть недоступны извне.
- Online-игры могут иметь проблемы с NAT traversal.

**Решения:**
```bash
# 1. Проверка Double NAT
traceroute -n 8.8.8.8 | head -3
# → 1  100.64.0.1  (CGNAT)
# → 2  192.168.1.1 (Home Router)
# → 3  ...

# 2. Обход через VPN (Tailscale, WireGuard)
tailscale up
# → Теперь трафик идёт через туннель, минуя CGNAT

# 3. Использование Cloudflare Tunnel
cloudflared tunnel --url http://localhost:8080
# → Без портов, без Port Forwarding
```

### Multicast в Kubernetes

**Особенности:**
- Kubernetes не поддерживает multicast по умолчанию.
- Требуется CNI-плагин с поддержкой multicast (Calico, Cilium).

```bash
# Включение multicast в Calico
kubectl patch installation default --type=merge -p '{"spec": {"calicoNetwork": {"multicast": {"enabled": true}}}}'

# Проверка multicast в Pod
kubectl exec <pod> -- ping -c 1 224.0.0.1
# → multicast работает

# Использование multicast для service discovery
kubectl exec <pod> -- python3 -c "
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
sock.sendto(b'hello', ('239.0.0.1', 5000))
"
```

### Dual-Stack и IPv4-mapped

**Проблемы:**
- Сервис может слушать только IPv4 или только IPv6.
- Клиенты с dual-stack могут подключаться через неправильный протокол.

```bash
# Проверка dual-stack конфигурации
ss -tlnp | grep :80
# → LISTEN  0  128  0.0.0.0:80  0.0.0.0:*  (IPv4-only)
# → LISTEN  0  128  :::80  :::*  (IPv6-only или dual-stack)

# Настройка dual-stack в nginx
server {
    listen 80;
    listen [::]:80;  # IPv6
}

# Проверка dual-stack через curl
curl -4 http://example.com  # Принудительно IPv4
curl -6 http://example.com  # Принудительно IPv6
```

### Специальные адреса в облаках (AWS, GCP, Azure)

**Особенности:**
- Облачные провайдеры резервируют специальные диапазоны.
- VPC/VNet использует private IP из RFC 1918.
- Public IP — это NAT к private IP.

```bash
# AWS: проверка EC2-инстанса
curl -s http://169.254.169.254/latest/meta-data/local-ipv4
# → 10.0.1.15 (private IP)

# AWS: проверка public IP
curl -s http://169.254.169.254/latest/meta-data/public-ipv4
# → 52.10.10.1 (public IP)

# GCP: проверка metadata
curl -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip
# → 10.128.0.2

# Azure: проверка private IP
curl -H "Metadata:true" http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/privateIpAddress?api-version=2021-02-01
# → 10.0.0.4
```

## Дополнительная информация

### Сводная таблица ключевых RFC

| RFC | Описание |
| :--- | :--- |
| **RFC 6890** | Реестр специальных IP-адресов (заменил RFC 5735 и 5156). |
| **RFC 1918** | Выделение адресов для частных сетей (IPv4). |
| **RFC 4193** | Unique Local IPv6 Unicast Addresses (ULA). |
| **RFC 6598** | IANA-Reserved IPv4 Prefix for Shared Address Space (CGNAT). |
| **RFC 3927** | Dynamic Configuration of IPv4 Link-Local Addresses. |
| **RFC 5737** | IPv4 Addresses for Documentation and Examples. |
| **RFC 3849** | IPv6 Address Prefix Reserved for Documentation. |

**Навигация по разделу:**
- **[IP-адресация — точка входа](./index.md)**
- **[Обзор IP-адресации](./ip_overview.md)** — структура и заголовки.
- **[Методы расчета подсетей](./subnetting_calculation.md)** — гайд по VLSM.
- **[Специальные маски](./special_masks.md)** — CIDR и маски PtP.

### Связанные темы

- **[NAT и CGNAT](../../Concepts/nat/overview.md)** — трансляция адресов и_DOUBLE NAT.
- **[DHCP и APIPA](../DHCP/dhcp_overview.md)** — автоматическое назначение адресов.
- **[Dual-Stack (IPv4 + IPv6)](../../OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md)** — совместная работа протоколов.
- **[Маршрутизация в Linux](../../../Linux/SystemAdministration/routing.md)** — настройка маршрутов.
