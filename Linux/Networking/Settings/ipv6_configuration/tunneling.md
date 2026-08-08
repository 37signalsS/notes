# Туннелирование IPv6 в Linux

## Определения

**Туннелирование IPv6** — технология передачи IPv6-пакетов через сетевую инфраструктуру, поддерживающую другие протоколы (обычно IPv4), путем их инкапсуляции в «несущие» пакеты.

**Основные протоколы и технологии:**

- **WireGuard**: современный высокопроизводительный VPN-протокол с нативной поддержкой IPv6. Рекомендуемый стандарт безопасности и производительности.
- **SIT (Simple Internet Transition, 6in4)**: инкапсуляция IPv6 в IPv4 (протокол IP 41). Широко используется для подключения к брокерам IPv6 (например, Tunnelbroker).
- **GRE (Generic Routing Encapsulation)**: универсальный протокол (IP 47). Поддерживает L3 (GRE) и L2 (GRETAP) туннелирование.
- **6rd (IPv6 Rapid Deployment)**: механизм быстрого развертывания IPv6 через IPv4-сети провайдеров ([RFC 5969](https://datatracker.ietf.org/doc/html/rfc5969)).
- **MAP-E / MAP-T**: современные методы трансляции и инкапсуляции для обеспечения связи IPv6-only клиентов с IPv4-интернетом.
- **FOU / GUE (Foo Over UDP / Generic UDP Encapsulation)**: инкапсуляция SIT/GRE в UDP-пакеты для обхода NAT и улучшения балансировки (RSS/ECMP).
- **6to4 / Teredo**: автоматические механизмы, считающиеся **устаревшими** ([RFC 7526](https://datatracker.ietf.org/doc/html/rfc7526)). Не рекомендуются для промышленного использования.

## Основные концепции

### Реализация в современном Linux

В современных дистрибутивах (ядро 6.x+) управление туннелями выполняется через универсальные интерфейсы:

1.  **ip link (iproute2)**: основной инструмент. Позволяет создавать туннели как виртуальные сетевые устройства.
2.  **NetworkManager (nmcli)**: стандарт для персистентных настроек на серверах.
3.  **systemd-networkd**: предпочтительный метод для облачных сред и инфраструктуры как код (IaC).

### Технические нюансы и ограничения

- **MTU (Maximum Transmission Unit)**: Инкапсуляция добавляет дополнительные заголовки, уменьшая полезный объем данных (Payload).
    - **SIT/IPIP**: 20 байт (IPv4-header) → MTU 1480.
    - **WireGuard**: ~60-80 байт → MTU 1420.
    - **GRE**: 24-28 байт → MTU 1476.
- **PMTUD (Path MTU Discovery)**: Для корректной работы туннелей необходимо разрешать **ICMPv6 Type 2 (Packet Too Big)**. Блокировка этого типа сообщений приводит к «зависанию» TCP-сессий при передаче крупных пакетов.
- **MSS Clamping**: Механизм принудительного уменьшения значения MSS (Maximum Segment Size) в TCP SYN пакетах. Это гарантирует, что хосты не будут отправлять пакеты больше, чем может пропустить туннель.

## Практические сценарии

### 1. WireGuard (IPv6 через UDP)

Обеспечивает нативную поддержку IPv6 и высокую скорость.

```bash
# Создание интерфейса
sudo ip link add dev wg0 type wireguard

# Настройка (подробности в Vpn/wireguard.md)
sudo wg set wg0 private-key ./private.key peer <PublicKey> endpoint <IPv4>:51820 allowed-ips 2001:db8:1::/64

# Активация
sudo ip addr add 2001:db8:1::1/64 dev wg0
sudo ip link set wg0 up
```

### 2. SIT-тунлель (6in4) через ip link

Классический метод инкапсуляции (протокол 41).

```bash
# Создание устройства SIT
sudo ip link add name sit1 type sit remote <remote_ipv4> local <local_ipv4> ttl 64

# Поднятие интерфейса и назначение адреса
sudo ip link set sit1 up
sudo ip addr add 2001:db8:abc::2/64 dev sit1

# Установка маршрута по умолчанию
sudo ip -6 route add default dev sit1
```

### 3. Настройка MSS Clamping (nftables)

Рекомендуемый способ решения проблем с MTU в туннелях.

```bash
# /etc/nftables.conf
table inet filter {
    chain forward {
        type filter hook forward priority 0;
        # Ограничение MSS для трафика, проходящего через туннель
        tcp flags syn tcp option maxseg size set 1400
    }
}
```

Для классического `iptables`:
```bash
sudo ip6tables -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
```

### 4. systemd-networkd (Персистентная настройка)

Идеально для серверов.

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

### Анализ состояния туннеля

```bash
# Просмотр параметров и оверхеда
ip -d link show sit1

# Просмотр статистики ошибок (дропы из-за MTU)
ip -s link show sit1

# Список всех активных туннелей IPv6
ip -6 tunnel show
```

### Проверка MTU

```bash
# Трассировка с определением MTU на пути
tracepath6 -n 2001:db8:beef::2

# Проверка прохождения пакетов заданного размера без фрагментации
ping6 -M do -s 1452 2001:db8:beef::2
```

## Дополнительная информация

### Настройка файрвола

Для работы туннелей необходимо разрешить транспортные протоколы.

| Технология | Протокол/Порт | Правило nftables |
| :--- | :--- | :--- |
| **SIT** | IP 41 | `ip protocol 41 accept` |
| **GRE** | IP 47 | `ip protocol 47 accept` |
| **WireGuard** | UDP 51820 | `udp dport 51820 accept` |
| **FOU/GUE** | UDP (custom) | `udp dport 6666 accept` |

### См. также

- **[Firewall для IPv6](./firewall.md)** — критические правила ICMPv6 и фильтрация.
- **[Диагностика IPv6](./diagnostics.md)** — методы отладки NDP и PMTUD.
- **[WireGuard — подробное руководство](../../../../Vpn/wireguard.md)** — архитектура и генерация ключей.
- **[ip tunnel vs ip link](../../Tools/iproute2/ip_tunnel.md)** — сравнение инструментов управления.
- **[Туннели IPIP и SIT](../../../../Networking/Tunnels/ipip_and_sit.md)** — глубокая теория инкапсуляции.
