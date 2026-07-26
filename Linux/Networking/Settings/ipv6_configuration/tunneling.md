# Туннелирование IPv6 в Linux

---

**Reliability Score: 10** (SSoT + Современные стандарты 2026 года)  
**Freshness: Актуально на июль 2026**

---

## Определения

**Туннелирование IPv6** — технология передачи IPv6-пакетов через сетевую инфраструктуру, поддерживающую другие протоколы (обычно IPv4), путем их инкапсуляции в «несущие» пакеты.

**Основные протоколы и технологии:**

- **WireGuard**: современный высокопроизводительный VPN-протокол с нативной поддержкой IPv6. Рекомендуется как стандарт для 2026 года.
- **SIT (Simple Internet Transition, 6in4)**: инкапсуляция IPv6 в IPv4 (протокол IP 41). Стандарт для подключения к IPv6-брокерам.
- **GRE (Generic Routing Encapsulation)**: универсальный протокол (IP 47). Поддерживает L3 (GRE) и L2 (GRETAP) туннелирование IPv6 поверх IPv4 и наоборот.
- **FOU / GUE (Foo Over UDP)**: инкапсуляция SIT/GRE в UDP-пакеты для обхода NAT и улучшения балансировки (ECMP).
- **6to4 / Teredo**: автоматические механизмы. Считаются **устаревшими** и не рекомендуются для использования в современных сетях ([RFC 7526](https://datatracker.ietf.org/doc/html/rfc7526)).

## Основные концепции

### Реализация в современном Linux

В современных дистрибутивах (Kernel 6.x+) управление туннелями сместилось от специализированных утилит к универсальным интерфейсам:

1.  **ip link (iproute2)**: современный синтаксис (рекомендуется). Позволяет создавать туннели как полноценные сетевые устройства с поддержкой всех атрибутов ядра.
2.  **NetworkManager (nmcli)**: стандарт для управления персистентными соединениями на серверах и десктопах.
3.  **systemd-networkd**: предпочтительный метод для облачных инстансов и контейнерных сред.

### Технические нюансы

- **MTU (Maximum Transmission Unit)**: Инкапсуляция добавляет заголовок, что уменьшает полезный объем данных (Payload).
    - **SIT/IPIP**: 20 байт (IPv4-header) → MTU 1480.
    - **WireGuard**: 60-80 байт → MTU 1420.
    - **GRE**: 24-28 байт → MTU 1476.
- **PMTUD (Path MTU Discovery)**: Для работы туннелей критически важно разрешить **ICMPv6 Type 2 (Packet Too Big)**. Без этого TCP-сессии будут зависать при передаче больших данных.
- **MSS Clamping**: Если PMTUD не работает, необходимо принудительно ограничивать размер TCP-сегментов на туннельном интерфейсе.

## Практические сценарии

### 1. WireGuard (Рекомендуемый метод)

WireGuard обеспечивает максимальную производительность и безопасность.

```bash
# Создание интерфейса
sudo ip link add dev wg0 type wireguard

# Настройка (SSoT: Vpn/wireguard.md)
sudo wg set wg0 private-key ./private.key peer <PublicKey> endpoint <IPv4>:51820 allowed-ips 2001:db8:1::/64

# Активация и назначение адреса
sudo ip addr add 2001:db8:1::1/64 dev wg0
sudo ip link set wg0 up
```

### 2. SIT-туннель (6in4) через ip link

Современный способ создания классического туннеля (например, для Hurricane Electric).

```bash
# Создание туннеля с использованием ip link (современный метод)
sudo ip link add name sit1 type sit remote <remote_ipv4> local <local_ipv4> ttl 64

# Активация и адресация
sudo ip link set sit1 up
sudo ip addr add 2001:db8:abc::2/64 dev sit1

# Маршрут по умолчанию через туннель
sudo ip -6 route add default dev sit1
```

### 3. Настройка через NetworkManager (nmcli)

Предпочтительно для обеспечения персистентности в RHEL/Ubuntu.

```bash
# Создание IP6GRE туннеля (IPv6 поверх IPv4)
sudo nmcli connection add type ip-tunnel \
    ifname gre6 con-name gre6 \
    mode ip6gre \
    remote <remote_ipv4> local <local_ipv4>

# Настройка IPv6 адресации внутри туннеля
sudo nmcli connection modify gre6 ipv6.addresses "2001:db8:cafe::1/64" ipv6.method manual

sudo nmcli connection up gre6
```

### 4. systemd-networkd (Контейнеры / Cloud)

```ini
# /etc/systemd/network/10-sit.netdev
[NetDev]
Name=sit1
Kind=sit

[Tunnel]
Local=<local_ipv4>
Remote=<remote_ipv4>

# /etc/systemd/network/10-sit.network
[Match]
Name=sit1

[Network]
Address=2001:db8:beef::1/64
```

## Диагностика и проверка

### Мониторинг состояния

```bash
# Детальный просмотр параметров инкапсуляции
ip -d link show sit1

# Статистика ошибок (полезно при проблемах с MTU)
ip -s link show sit1

# Просмотр всех туннелей в системе
ip -6 tunnel show
```

### Тестирование связности

```bash
# Трассировка с контролем MTU
tracepath6 -n 2001:db8:beef::2

# Проверка прохождения больших пакетов без фрагментации
ping6 -M do -s 1452 2001:db8:beef::2
```

## Дополнительная информация

### Настройка файрвола (nftables)

Для работы туннелей необходимо разрешить внешние протоколы инкапсуляции.

```bash
table inet filter {
    chain input {
        # Разрешить WireGuard (UDP)
        udp dport 51820 accept

        # Разрешить SIT (протокол 41)
        ip protocol 41 accept

        # Разрешить GRE (протокол 47)
        ip protocol 47 accept
    }
}
```

### См. также

- **[Firewall для IPv6](./firewall.md)** — подробная настройка правил и ICMPv6.
- **[Диагностика IPv6](./diagnostics.md)** — методы отладки NDP и маршрутизации.
- **[WireGuard — подробное руководство](../../../../Vpn/wireguard.md)** — архитектура и генерация ключей.
- **[ip tunnel vs ip link](../../Tools/iproute2/ip_tunnel.md)** — детальное сравнение команд управления.
- **[Туннели IPIP и SIT](../../../../Networking/Tunnels/ipip_and_sit.md)** — теоретические основы протоколов.
