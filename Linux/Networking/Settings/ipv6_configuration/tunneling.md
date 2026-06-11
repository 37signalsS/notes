# Туннелирование IPv6 в Linux

## Определения

**Туннелирование IPv6** — механизм передачи IPv6-пакетов через сетевую инфраструктуру, поддерживающую только IPv4 (или наоборот), путем инкапсуляции.

**Основные протоколы:**

- **SIT (Simple Internet Transition, 6in4)** — инкапсуляция IPv6 в IPv4 (протокол IP 41).
- **GRE (Generic Routing Encapsulation)** — универсальный протокол инкапсуляции (протокол IP 47), поддерживающий IPv6.
- **6to4** — механизм автоматического туннелирования (префикс `2002::/16`), использующий SIT. Считается устаревшим (RFC 7526).

Теоретические основы и сравнение протоколов см. в разделах: **[Туннели IPIP и SIT](../../../../Networking/Tunnels/ipip_and_sit.md)** и **[Обзор GRE](../../../../Networking/Tunnels/gre/gre.md)**.

## Основные концепции

### Особенности реализации в Linux

В Linux управление туннелями осуществляется через пакет `iproute2` (команды `ip tunnel` или `ip link`) или через системные менеджеры конфигурации, такие как `systemd-networkd` и NetworkManager.

**Ключевые аспекты:**

- **MTU (Maximum Transmission Unit)**: инкапсуляция добавляет заголовок (20 байт для SIT, 24+ байта для GRE), что требует уменьшения MTU туннельного интерфейса (обычно до 1480 или 1476 байт).
- **Протоколы IP**: для работы туннелей необходимо разрешить соответствующие протоколы в файрволе (41 для SIT, 47 для GRE).
- **TTL (Time to Live)**: при настройке туннеля часто указывается `ttl 64` или `ttl inherit` для корректной трассировки.

## Практические сценарии

### Настройка через iproute2

#### SIT-туннель (6in4)

Классический способ соединения с IPv6-брокером (например, Hurricane Electric).

```bash
# Создание туннеля
sudo ip tunnel add sit1 mode sit remote <remote_ipv4> local <local_ipv4> ttl 64
sudo ip link set sit1 up

# Назначение IPv6-адреса
sudo ip addr add 2001:db8::1/64 dev sit1

# Настройка маршрутизации
sudo ip -6 route add default dev sit1
```

#### GRE-туннель с поддержкой IPv6

Используется для объединения сетей с поддержкой различных протоколов.

```bash
# Создание GRE туннеля
sudo ip tunnel add gre6 mode gre remote <remote_ipv4> local <local_ipv4> ttl 64
sudo ip link set gre6 up

# Назначение адреса
sudo ip addr add 2001:db8:abc::1/64 dev gre6
```

### Настройка через systemd-networkd

Для персистентной настройки используются файлы `.netdev` (описание устройства) и `.network` (настройка интерфейса).

#### Конфигурация SIT-туннеля

```ini
# /etc/systemd/network/10-sit1.netdev
[NetDev]
Name=sit1
Kind=sit

[Tunnel]
Local=<local_ipv4>
Remote=<remote_ipv4>

# /etc/systemd/network/10-sit1.network
[Match]
Name=sit1

[Network]
Address=2001:db8::1/64
```

#### Конфигурация GRE-туннеля

```ini
# /etc/systemd/network/10-gre6.netdev
[NetDev]
Name=gre6
Kind=gre

[Tunnel]
Local=<local_ipv4>
Remote=<remote_ipv4>

# /etc/systemd/network/10-gre6.network
[Match]
Name=gre6

[Network]
Address=2001:db8:abc::1/64
```

## Дополнительная информация

### Диагностика

Проверка состояния туннелей:

```bash
# Просмотр всех туннелей
ip -6 tunnel show

# Статистика интерфейса
ip -s link show sit1

# Проверка связности (обязательно указывать интерфейс для Link-Local)
ping6 -I sit1 2001:db8::2
```

Подробнее см. в разделе **[Диагностика IPv6](./diagnostics.md)**.

### Настройка файрвола

Для работы туннелей необходимо разрешить прохождение пакетов инкапсуляции.

**iptables:**

```bash
# Разрешить SIT (протокол 41)
sudo iptables -A INPUT -p 41 -j ACCEPT

# Разрешить GRE (протокол 47)
sudo iptables -A INPUT -p 47 -j ACCEPT
```

### См. также

- **[Концепции IPv6 в Linux](./concepts.md)** — типы адресов и основы.
- **[Настройка адресов](./address_configuration.md)** — управление интерфейсами через nmcli.
- **[Туннели IPIP и SIT](../../../../Networking/Tunnels/ipip_and_sit.md)** — подробная теория и сравнение.
