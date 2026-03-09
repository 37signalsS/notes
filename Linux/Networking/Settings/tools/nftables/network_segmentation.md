# nftables: сегментирование сети

## Маршрутизатор с файрволом

### Сценарий

Разделение сети на пользовательский и серверный сегменты с разграничением доступа.

### Архитектура

- Пользовательский сегмент: `192.168.0.0/24`
- Серверный сегмент: `172.30.0.0/24`
- Файрвол-маршрутизатор: два интерфейса, по одному в каждом сегменте

### Матрица доступа (пример)

| Пользователь | Серверы | Протокол/Порт | Роль |
| :--- | :--- | :--- | :--- |
| User1 (192.168.0.101) | Server1-2 (172.30.0.101-102) | TCP 80 | all_web |
| User2 (192.168.0.102) | Server1-2 (172.30.0.101-102) | TCP 22 | all_ssh |
| User1, User2 | DNS (172.30.0.2) | UDP 53 | DNS |

### Конфигурация nftables

```bash
#!/usr/sbin/nft -f

flush ruleset

table ip firewall {
    # Роль: all_web
    set all_web_users {
        type ipv4_addr
        flags interval
        elements = { 192.168.0.101 }
    }

    set all_web_servers {
        type ipv4_addr . inet_proto . inet_service
        flags interval
        elements = { 172.30.0.101-172.30.0.102 . tcp . 80 }
    }

    # Роль: all_ssh
    set all_ssh_users {
        type ipv4_addr
        flags interval
        elements = { 192.168.0.102 }
    }

    set all_ssh_servers {
        type ipv4_addr . inet_proto . inet_service
        flags interval
        elements = { 172.30.0.101-172.30.0.102 . tcp . 22 }
    }

    # Роль: DNS
    set DNS_users {
        type ipv4_addr
        flags interval
        elements = { 192.168.0.101, 192.168.0.102 }
    }

    set DNS_servers {
        type ipv4_addr . inet_proto . inet_service
        flags interval
        elements = { 172.30.0.2 . udp . 53 }
    }

    chain fw_forward {
        type filter hook forward priority filter; policy drop;

        # Разрешить установленные соединения
        ct state established,related accept

        # Применить роли
        ip saddr @all_web_users ip daddr . meta l4proto . th dport @all_web_servers accept
        ip saddr @all_ssh_users ip daddr . meta l4proto . th dport @all_ssh_servers accept
        ip saddr @DNS_users ip daddr . meta l4proto . th dport @DNS_servers accept
    }
}
```

### Активация маршрутизации

```bash
# В /etc/sysctl.conf раскомментировать
net.ipv4.ip_forward=1

# Применить
sysctl -p
```

---

## Прозрачный файрвол (сегментирование коммутатором)

### Сценарий

Сегментирование сети без изменения IP-адресации (transparent/stealth firewall).

### Особенности

- Все узлы в одной IP-подсети
- Файрвол работает на уровне L2 (bridge)
- Не требует изменения маршрутизации
- **Недостаток:** не ограничивает широковещательный трафик

### Конфигурация bridge

```bash
# Установка bridge-utils
apt install bridge-utils

# Конфигурация /etc/network/interfaces
auto lo
iface lo inet loopback

iface ens33 inet manual
iface ens36 inet manual

auto br0
iface br0 inet manual
bridge_ports ens33 ens36
```

### Конфигурация nftables (bridge family)

```bash
#!/usr/sbin/nft -f

flush ruleset

table bridge firewall {
    set all_web_users {
        type ipv4_addr
        flags interval
        elements = { 172.30.0.11 }
    }

    set all_web_servers {
        type ipv4_addr . inet_proto . inet_service
        flags interval
        elements = { 172.30.0.101-172.30.0.102 . tcp . 80 }
    }

    set all_ssh_users {
        type ipv4_addr
        flags interval
        elements = { 172.30.0.12 }
    }

    set all_ssh_servers {
        type ipv4_addr . inet_proto . inet_service
        flags interval
        elements = { 172.30.0.101-172.30.0.102 . tcp . 22 }
    }

    set DNS_users {
        type ipv4_addr
        flags interval
        elements = { 172.30.0.11, 172.30.0.12 }
    }

    set DNS_servers {
        type ipv4_addr . inet_proto . inet_service
        flags interval
        elements = { 172.30.0.2 . udp . 53 }
    }

    chain fw_forward {
        type filter hook forward priority filter; policy drop

        # Разрешить ARP трафик
        ether type arp accept

        # Разрешить установленные соединения
        ct state established,related accept

        # Применить роли
        ip saddr @all_web_users ip daddr . meta l4proto . th dport @all_web_servers accept
        ip saddr @all_ssh_users ip daddr . meta l4proto . th dport @all_ssh_servers accept
        ip saddr @DNS_users ip daddr . meta l4proto . th dport @DNS_servers accept
    }
}
```

### Ключевые отличия от router-based

- Тип таблицы: `bridge` вместо `ip`
- Добавлено правило: `ether type arp accept`
- IP-адреса в сетах обновляются (так как все узлы в одной подсети)
