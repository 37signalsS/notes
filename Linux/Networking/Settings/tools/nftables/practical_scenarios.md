# nftables: практические сценарии настройки

## Базовая настройка для сервера

```bash
# Создать базовую конфигурацию
sudo nft -f - <<'EOF'
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить установленные соединения
        ct state established,related accept

        # Разрешить loopback
        iif lo accept

        # Разрешить SSH, HTTP, HTTPS
        tcp dport {22, 80, 443} accept

        # Разрешить ICMP (ping)
        icmp type echo-request accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
EOF
```

---

## Динамический бан брутфорса SSH

Защита без `fail2ban` с использованием сетов:

```bash
sudo nft -f - <<'EOF'
flush ruleset

table inet filter {
    # Сет для забаненных IP с таймаутом 15 минут
    set ssh_bruteforce {
        type ipv4_addr
        flags timeout
        timeout 15m
    }

    chain input {
        type filter hook input priority 0; policy accept;

        # Разрешить установленные соединения
        ct state established,related accept

        # Блокировать забаненные IP
        ip saddr @ssh_bruteforce drop

        # Детектировать брутфорс: >5 новых соединений в минуту → бан
        tcp dport 22 ct state new limit rate over 5/minute \
          add @ssh_bruteforce { ip saddr } drop
    }
}
EOF
```

---

## Fail2ban интеграция

Интеграция `fail2ban` с `nftables` подробно описана в едином источнике: [fail2ban: Интеграция с nftables](../../../../Security/Tools/fail2ban.md#интеграция-с-nftables).

---

## Сохранение и загрузка правил

```bash
# Сохранить текущие правила
sudo nft list ruleset > /etc/nftables.conf

# Загрузить из файла
sudo nft -f /etc/nftables.conf

# Включить автозагрузку при старте
sudo systemctl enable --now nftables
```

---

## Работа с сетами (наборами)

```bash
# Создать таблицу с сетом разрешённых IP
sudo nft -f - <<'EOF'
table inet filter {
    set allowed_ips {
        type ipv4_addr
        elements = { 192.168.1.10, 192.168.1.20, 10.0.0.0/24 }
    }

    chain input {
        type filter hook input priority 0; policy drop;
        ip saddr @allowed_ips accept
        ct state established,related accept
    }
}
EOF
```

---

## NAT и Masquerading

```bash
sudo nft -f - <<'EOF'
table ip nat {
    chain postrouting {
        type nat hook postrouting priority 100; policy accept;

        # Masquerade для исходящего трафика
        oifname "eth0" masquerade

        # SNAT для конкретной подсети
        ip saddr 192.168.1.0/24 oifname "eth0" snat to 203.0.113.1
    }

    chain prerouting {
        type nat hook prerouting priority -100; policy accept;

        # DNAT: проброс порта 8080 на 192.168.1.100:80
        tcp dport 8080 dnat to 192.168.1.100:80
    }
}
EOF
```

---

## Логирование отброшенных пакетов

```bash
sudo nft -f - <<'EOF'
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Логирование с ограничением частоты (5 записей в минуту)
        limit rate 5/minute log prefix "INPUT dropped: " level warn

        ct state established,related accept
    }
}
EOF
```
