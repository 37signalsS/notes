# Настройка IPv6-адресов в Linux

## Определения

**Персистентная настройка сети** — конфигурация параметров сетевых интерфейсов, которая сохраняется после перезагрузки системы.

**Методы назначения адресов:**

- **SLAAC (Stateless Address Autoconfiguration)** — автоматическая генерация адреса на основе префикса сети от маршрутизатора (Router Advertisement).
- **DHCPv6** — получение адреса и параметров сети от специализированного сервера.
- **Static (Manual)** — ручное назначение фиксированного адреса администратором.

## Основные концепции

В современных дистрибутивах Linux управление сетью осуществляется через высокоуровневые менеджеры:

1. **NetworkManager (nmcli)** — стандарт для RHEL, CentOS, Fedora, Ubuntu Desktop.
2. **systemd-networkd** — легковесное решение для серверов и контейнеров (Ubuntu Server, Debian, Arch Linux).
3. **Netplan** — надстройка над NetworkManager и networkd в Ubuntu.

Для временной настройки и оперативного просмотра используется пакет `iproute2`. Подробно об инструментах просмотра см. в разделе **[ip address](../../Tools/iproute2/ip_address.md)** и **[ip neighbour](../../Tools/iproute2/ip_neighbour.md)**.

## Практические сценарии

### Настройка через NetworkManager (nmcli)

#### Просмотр текущих IPv6-параметров

```bash
nmcli connection show <имя_соединения> | grep ipv6
```

#### Статический IPv6 (Manual)

```bash
# Установка метода и адреса
nmcli connection modify <имя_соединения> ipv6.method manual ipv6.addresses 2001:db8::1/64

# Установка шлюза и DNS
nmcli connection modify <имя_соединения> ipv6.gateway 2001:db8::ffff ipv6.dns "2001:db8::1"

# Применение изменений
nmcli connection up <имя_соединения>
```

#### Включение Privacy Extensions (временные адреса)

```bash
nmcli connection modify <имя_соединения> ipv6.ip6-privacy 2
```

### Настройка через systemd-networkd

Файлы конфигурации обычно располагаются в `/etc/systemd/network/`.

#### Статический адрес (Manual)

```ini
# /etc/systemd/network/20-eth0.network
[Match]
Name=eth0

[Network]
IPv6AcceptRA=no
Address=2001:db8::1/64
Gateway=2001:db8::ffff
DNS=2001:db8::1
```

#### Автоконфигурация (SLAAC + DHCPv6)

```ini
[Match]
Name=eth0

[Network]
DHCP=ipv6
IPv6AcceptRA=yes
IPv6PrivacyExtensions=yes
```

#### Применение настроек

```bash
sudo systemctl restart systemd-networkd
networkctl status eth0
```

### Проверка конфигурации

После настройки необходимо убедиться, что адрес назначен корректно и связь установлена.

```bash
# Проверка наличия адреса (SSoT: ip address)
ip -6 addr show dev eth0

# Проверка маршрута (SSoT: ip route)
ip -6 route show

# Тестирование связности
ping6 -c 3 google.com
```

## Дополнительная информация

### Типичные проблемы

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Адрес в состоянии `tentative` | Идет проверка DAD (дубликаты) | Подождите 1-2 секунды |
| Нет шлюза по умолчанию | Заблокированы RA-пакеты | Проверьте настройки [Firewall](./firewall.md) |
| Конфликт менеджеров | NetworkManager и networkd запущены одновременно | Оставьте только один активный сервис |

### См. также

- **[Концепции IPv6 в Linux](./concepts.md)** — типы адресов и механизмы работы.
- **[Диагностика IPv6](./diagnostics.md)** — глубокая отладка сетевых проблем.
- **[Постоянная настройка сети](../index.md)** — общий обзор методов для Linux.
