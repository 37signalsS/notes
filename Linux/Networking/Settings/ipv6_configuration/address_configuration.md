# Настройка IPv6-адресов в Linux

## Просмотр IPv6-адресов

```bash
# Показать все адреса (включая IPv6)
ip address show

# Показать только IPv6-адреса
ip -6 address show

# Показать маршруты IPv6
ip -6 route show

# Просмотр соседей NDP (аналог ARP)
ip -6 neigh show
```

## Настройка через NetworkManager (nmcli)

Конфигурация сетевых интерфейсов в RHEL/CentOS выполняется через NetworkManager.

### Просмотр текущих настроек

```bash
nmcli connection show
nmcli connection show <имя_соединения> | grep ipv6
```

### Настройка статического IPv6 (Manual)

```bash
nmcli connection edit <имя_соединения>
set ipv6.method manual
set ipv6.addresses 2001:db8::1/64
set ipv6.gateway 2001:db8::ffff
set ipv6.dns "2001:db8::1"
save
quit
```

### Настройка ULA (Unique Local Address)

```bash
# Пример: сеть fc00::/124 (16 хостов)
nmcli connection edit <имя_соединения>
set ipv6.method manual
set ipv6.addresses fc00::1/124
quit

# Активация изменений
nmcli connection down <имя_соединения>
nmcli connection up <имя_соединения>
```

### Настройка Link-Local (автоматическая)

```bash
nmcli connection edit <имя_соединения>
set ipv6.method link-local
save
quit
```

### Включение Privacy Extensions

```bash
nmcli connection modify <имя_соединения> ipv6.ip6-privacy 2
```

## Настройка через systemd-networkd

### Статический IPv6

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
# IPv4 (опционально)
Address=10.10.10.10/24
Gateway=10.10.10.1

# IPv6 статический
IPv6AcceptRA=no
Address=2001:db8::1/64
Gateway=2001:db8::ffff
DNS=2001:db8::1

# ULA для локальной сети
Address=fc00::1/124
```

### SLAAC (автоконфигурация)

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
# Принимать RA от роутера
IPv6AcceptRA=yes
# Включить Privacy Extensions
IPv6PrivacyExtensions=yes
```

### DHCPv6

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
DHCP=yes
# IPv6 через SLAAC + DHCPv6
IPv6AcceptRA=yes
```

### Управление systemd-networkd

```bash
# Перезапуск
sudo systemctl restart systemd-networkd

# Проверка статуса
networkctl status eth0

# Журнал
journalctl -u systemd-networkd -f
```

## Проверка доступности по IPv6

```bash
# Ping по IPv6 (используется ICMPv6)
ping6 <ipv6-адрес>
ping -6 <ipv6-адрес>

# Traceroute по IPv6
traceroute6 <ipv6-адрес>
tracepath6 <ipv6-адрес>

# Проверка DNS AAAA записей
dig AAAA example.com
host -t AAAA example.com
```

## Связанные темы

* **[Концепции](./concepts.md)** — типы адресов, Privacy Extensions
* **[Firewall](./firewall.md)** — настройка файрвола для IPv6
* **[Настройка сервисов](./services_configuration.md)** — конфигурация демонов
* **[Постоянная настройка сети](./persistent_network_configuration.md)** — персистентная конфигурация
