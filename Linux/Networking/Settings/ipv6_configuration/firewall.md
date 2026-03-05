# Настройка firewall для IPv6 в Linux

## Важное замечание

Правила `iptables` для IPv4 **НЕ применяются** к IPv6. Необходимо настраивать `ip6tables` или `nftables` с поддержкой IPv6.

## Настройка через firewalld

### Разрешение ICMPv6

ICMPv6 необходим для работы IPv6 (NDP, Path MTU Discovery):

```bash
# Разрешить ICMPv6
firewall-cmd --permanent --add-protocol=icmpv6

# Перезагрузить правила
firewall-cmd --reload
```

### Разрешение трафика на портах

```bash
# Разрешить трафик на конкретном порту для IPv6
firewall-cmd --permanent --add-port=80/tcp --ipv6
firewall-cmd --permanent --add-port=443/tcp --ipv6

# Перезагрузить правила
firewall-cmd --reload
```

### Проблема с drop target

При использовании зоны с `target: drop` входящие пакеты IPv6 могут блокироваться, включая ответы на ping.

**Решение:**

```bash
# Добавить протокол IPv6-ICMP
firewall-cmd --permanent --add-protocol=icmpv6
firewall-cmd --reload
```

### Проверка статуса

```bash
# Проверка активных зон
firewall-cmd --get-active-zones

# Проверка правил для IPv6
firewall-cmd --list-all --ipv6
```

## Настройка через ip6tables

### Базовые правила

```bash
# Разрешить установленные соединения
sudo ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Разрешить loopback
sudo ip6tables -A INPUT -i lo -j ACCEPT

# Разрешить ICMPv6 (необходимо для работы IPv6)
sudo ip6tables -A INPUT -p icmpv6 -j ACCEPT

# Разрешить SSH
sudo ip6tables -A INPUT -p tcp --dport 22 -j ACCEPT

# Разрешить HTTP/HTTPS
sudo ip6tables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo ip6tables -A INPUT -p tcp --dport 443 -j ACCEPT

# Отклонить остальные
sudo ip6tables -P INPUT DROP
```

### Сохранение правил

**Debian/Ubuntu:**

```bash
# Установка пакета
sudo apt-get install -y iptables-persistent

# Сохранение правил
sudo netfilter-persistent save
```

**RHEL/CentOS:**

```bash
# Установка пакета
sudo yum install -y iptables-services

# Сохранение правил
sudo service ip6tables save
sudo systemctl enable ip6tables
```

### Проверка правил

```bash
# Просмотр правил
sudo ip6tables -L -n -v

# Просмотр с номерами строк
sudo ip6tables -L -n --line-numbers
```

## Настройка через nftables

### Базовая конфигурация

```bash
# Создание таблицы
sudo nft add table ip6 filter

# Создание цепочки
sudo nft add chain ip6 filter input { type filter hook input priority 0 \; policy drop \; }

# Разрешение установленных соединений
sudo nft add rule ip6 filter input ct state established,related accept

# Разрешение loopback
sudo nft add rule ip6 filter input iif lo accept

# Разрешение ICMPv6
sudo nft add rule ip6 filter input ip6 nexthdr icmpv6 accept

# Разрешение SSH
sudo nft add rule ip6 filter input tcp dport 22 accept
```

### Сохранение конфигурации

```bash
# Сохранение правил
sudo nft list ruleset > /etc/nftables.conf

# Загрузка при загрузке
sudo systemctl enable nftables
```

## Проверка firewall

```bash
# Проверка доступности порта
nc -6 -zv example.com 80

# Проверка через telnet
telnet -6 example.com 80

# Проверка через nmap
nmap -6 -p 80,443 example.com
```

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Не работает ping** | Блокировка ICMPv6 | Разрешить `icmpv6` в файрволе |
| **Нет IPv6-соединения** | Блокировка исходящих | Проверить OUTPUT chain |
| **Firewall не применяется** | Правила не сохранены | Использовать `netfilter-persistent save` |

## Связанные темы

* **[Настройка адресов](./address_configuration.md)** — конфигурация IPv6
* **[iptables основы](./tools/iptables_basics.md)** — базовая настройка
* **[nftables](./tools/nftables.md)** — современный firewall
* **[Диагностика](./diagnostics.md)** — решение проблем
