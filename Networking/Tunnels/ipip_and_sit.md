# Туннели IPIP и SIT

## Определения

**IPIP (IP-in-IP)** — протокол туннелирования, инкапсулирующий пакеты IPv4 в пакеты IPv4 для передачи через промежуточную IPv4-сеть.

**SIT (Simple Internet Transition)** — протокол, инкапсулирующий пакеты IPv6 в пакеты IPv4 для транзита IPv6-трафика через IPv4-сети.

**Общие характеристики:**
| Параметр | IPIP | SIT |
|----------|------|-----|
| **Протокол** | IP (номер `4`) | IP (номер `41`) |
| **Внутренний протокол** | IPv4 | IPv6 |
| **Внешний протокол** | IPv4 | IPv4 |
| **Топология** | Point-to-Point | Point-to-Point |
| **Шифрование** | Отсутствует | Отсутствует |
| **RFC** | [RFC 2003](https://datatracker.ietf.org/doc/html/rfc2003) | [RFC 4213](https://datatracker.ietf.org/doc/html/rfc4213) |

## Базовые концепции

### Принцип работы

**IPIP:**
```
[IPv4-пакет] → [Внешний IPv4-заголовок] → Передача → Декапсуляция
```

**SIT (6in4):**
```
[IPv6-пакет] → [Внешний IPv4-заголовок] → Передача → Декапсуляция
```

**Overhead:** ~20 байт (размер IPv4-заголовка)

### Особенности IPIP

- **Копирование флагов:** Копирует бит DF (Don't Fragment) из внутреннего пакета во внешний
- **Прозрачность:** Внутренний пакет не модифицируется
- **Ограничение:** Только IPv4 внутри IPv4

### Особенности SIT

- **6in4 туннелирование:** Базовый механизм IPv6-over-IPv4
- **6to4:** Автоматическое туннелирование через префикс `2002::/16` (устарело)
- **Ограничение:** Не копирует флаги из-за различий IPv4/IPv6

### Сравнение с GRE

| Критерий | IPIP | SIT | GRE |
|----------|------|-----|-----|
| **Гибкость** | Только IPv4 | Только IPv6 | Любые протоколы |
| **Key/ID** | Нет | Нет | Да (32 бит) |
| **L2-режим** | Нет | Нет | Да (GRETAP) |
| **Overhead** | 20 байт | 20 байт | 24+ байта |

## Практические сценарии

### 1. Настройка IPIP-туннеля

**Сценарий:** Соединение двух IPv4-сетей через IPv4-инфраструктуру.

```bash
# Сторона 1 (192.0.2.1)
ip tunnel add ipip1 mode ipip remote 192.0.2.2 local 192.0.2.1
ip link set ipip1 up
ip address add 10.0.0.1/30 dev ipip1
ip route add 10.0.1.0/24 dev ipip1

# Сторона 2 (192.0.2.2)
ip tunnel add ipip1 mode ipip remote 192.0.2.1 local 192.0.2.2
ip link set ipip1 up
ip address add 10.0.0.2/30 dev ipip1
ip route add 10.0.2.0/24 dev ipip1
```

**Параметры:**
- `mode ipip` — тип туннеля
- `remote` / `local` — внешние IP-адреса точек
- `10.0.0.0/30` — адресация туннеля

### 2. Настройка SIT-туннеля

**Сценарий:** Транзит IPv6 через IPv4-сеть (например, для подключения к IPv6-интернету).

```bash
# Сторона 1 (192.0.2.1)
ip tunnel add sit1 mode sit remote 192.0.2.2 local 192.0.2.1
ip link set sit1 up
ip address add fc00::1/64 dev sit1
ip route add 2001:db8::/32 dev sit1

# Сторона 2 (192.0.2.2)
ip tunnel add sit1 mode sit remote 192.0.2.1 local 192.0.2.2
ip link set sit1 up
ip address add fc00::2/64 dev sit1
```

**Адресация:**
- `fc00::/64` — [Unique Local Address (ULA)](../Protocols/ip.md) для IPv6
- `2001:db8::/32` — документационный префикс IPv6

### 3. Проверка и диагностика

```bash
# Статус туннеля
ip -d tunnel show
ip -d link show <tun_if>

# Проверка связности
ping -I <tun_if> <remote_tunnel_ip>

# Трассировка
traceroute -6 -I <tun_if> <ipv6_dst>  # для SIT

# Мониторинг трафика
tcpdump -i <tun_if> -n
tcpdump proto 4 -n    # IPIP
tcpdump proto 41 -n   # SIT
```

## Дополнительная информация

### Недостатки

**Общие:**
- **Нет шифрования:** Трафик передаётся открыто — требуется IPsec для безопасности
- **Point-to-Point:** Только две конечные точки на туннель
- **Один протокол:** IPIP — только IPv4, SIT — только IPv6

**SIT специфичные:**
- **6to4 устарел:** Автоматические 6to4-туннели не рекомендуются из-за проблем с надёжностью
- **NAT traversal:** Проблемы при прохождении через NAT

### Когда использовать

| Сценарий | Рекомендуемый протокол |
|----------|----------------------|
| IPv4 через IPv4 (просто) | IPIP |
| IPv6 через IPv4 | SIT |
| Мультипротокол | [GRE](./gre.md) |
| L2-оверлей | [GRETAP](./gre.md) / [VXLAN](./vxlan.md) |
| Безопасный туннель | [WireGuard](../../Vpn/wireguard.md) / IPsec |

### MTU considerations

**IPIP/SIT overhead:** 20 байт

| Базовый MTU | Эффективный MTU туннеля |
|-------------|------------------------|
| 1500 | 1480 |

**Настройка:**
```bash
ip link set <tun_if> mtu 1480
```

### Ссылки

- [RFC 2003 — IP Encapsulation within IP](https://datatracker.ietf.org/doc/html/rfc2003)
- [RFC 4213 — Basic Transition Mechanisms for IPv6](https://datatracker.ietf.org/doc/html/rfc4213)
- [Linux IP Tunneling HOWTO](https://tldp.org/HOWTO/IP- Tunneling-HOWTO/)
