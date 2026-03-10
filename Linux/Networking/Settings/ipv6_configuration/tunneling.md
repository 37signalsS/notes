# Туннелирование IPv6 в Linux

## Обзор

Для передачи IPv6 через IPv4-сети используются туннели.

## Типы туннелей

| Технология | Описание | Протокол |
| :--- | :--- | :--- |
| **6to4** | Автоматические туннели | Proto 41 |
| **Teredo** | Через NAT/UDP | UDP 3544 |
| **ISATAP** | Внутри организации | Proto 41 |
| **6rd** | Быстрый 6to4 (ISP) | Proto 41 |
| **GRE** | Generic Routing Encapsulation | Proto 47 |
| **IP-in-IP** | Инкапсуляция IP в IP | Proto 4 |

**См. также:** [Туннели IPIP и SIT](../../../../Networking/Tunnels/ipip_and_sit/index.md).

## Настройка туннелей

### 6to4 туннель

**Требования:** публичный IPv4-адрес.

```bash
# Создание туннеля
ip tunnel add 6to4 mode sit remote any local <IPv4-адрес> ttl 64
ip link set 6to4 up
ip addr add 2002:<IPv4-адрес в hex>::1/16 dev 6to4

# Пример для IPv4 192.0.2.1 (c000:0201)
# ip addr add 2002:c000:0201::1/16 dev 6to4

# Маршрут по умолчанию
ip -6 route add 2000::/3 via ::192.0.2.1 dev 6to4
```

### GRE туннель

```bash
# Создание GRE туннеля
ip tunnel add gre6 mode gre remote <remote-IPv4> local <local-IPv4> ttl 64
ip link set gre6 up
ip addr add 2001:db8::1/64 dev gre6

# Маршрут
ip -6 route add 2001:db8:1::/64 via 2001:db8::2 dev gre6
```

### SIT туннель (IPv6-in-IPv4)

```bash
# Создание SIT туннеля
ip tunnel add sit1 mode sit remote <remote-IPv4> local <local-IPv4> ttl 64
ip link set sit1 up
ip addr add 2001:db8::1/64 dev sit1

# Маршрут
ip -6 route add 2001:db8:1::/64 via 2001:db8::2 dev sit1
```

## Настройка через systemd-networkd

### 6to4 туннель

```ini
# /etc/systemd/network/10-6to4.netdev
[NetDev]
Name=6to4
Kind=sit
TunnelLocal=<IPv4-адрес>
TunnelRemote=any

# /etc/systemd/network/10-6to4.network
[Match]
Name=6to4

[Network]
IPv6AcceptRA=no
Address=2002:<IPv4-адрес в hex>::1/16
```

### GRE туннель

```ini
# /etc/systemd/network/10-gre6.netdev
[NetDev]
Name=gre6
Kind=gre
TunnelLocal=<local-IPv4>
TunnelRemote=<remote-IPv4>

# /etc/systemd/network/10-gre6.network
[Match]
Name=gre6

[Network]
IPv6AcceptRA=no
Address=2001:db8::1/64
```

## Проверка туннелей

```bash
# Показать туннели
ip -6 tunnel show

# Статистика туннеля
ip -s -6 link show 6to4

# Проверка подключения
ping6 -I 6to4 2001:db8::1
```

## Проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Туннель не поднимается** | Блокировка протокола 41 | Разрешить в файрволе |
| **Пакеты не проходят** | Неправильный маршрут | Проверить `ip -6 route` |
| **Высокая задержка** | Дополнительная инкапсуляция | Использовать нативный IPv6 |

## Файрвол для туннелей

```bash
# Разрешить протокол 41 (6to4, ISATAP)
ip6tables -A INPUT -p 41 -j ACCEPT

# Разрешить GRE (протокол 47)
ip6tables -A INPUT -p 47 -j ACCEPT

# Разрешить SIT
ip6tables -A INPUT -p ipv6 -j ACCEPT
```

## Связанные темы

* **[Концепции](./concepts.md)** — типы IPv6-адресов
* **[Диагностика](./diagnostics.md)** — решение проблем
* **[Туннели IPIP и SIT](../../../../Networking/Tunnels/ipip_and_sit/index.md)** — базовая настройка туннелей
