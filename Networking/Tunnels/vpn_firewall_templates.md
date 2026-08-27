# VPN Firewall Templates — шаблоны правил

## Определения

Данный документ содержит готовые шаблоны правил firewall (nftables и iptables) для различных VPN-протоколов. Шаблоны включают правила INPUT (для VPN-серверов), FORWARD (для маршрутизации трафика) и NAT (для маскарада).

> **См. также:** [VPN Troubleshooting](./vpn_troubleshooting_universal.md), [WireGuard](./wireguard_practical.md), [IPsec](./ipsec/ipsec.md)

---

## nftables (рекомендуется)

### WireGuard сервер

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить established/related
        ct state established,related accept

        # Разрешить loopback
        iif "lo" accept

        # Разрешить SSH (ограничить по IP!)
        tcp dport 22 ip saddr { 10.0.0.0/8, 192.168.0.0/16 } accept

        # Разрешить WireGuard (UDP 51820) от доверенных IP
        udp dport 51820 ip saddr { 198.51.100.0/24, 203.0.113.0/24 } accept

        # ICMP (пинг)
        ip protocol icmp accept

        # Остальное отбросить
    }

    chain forward {
        type filter hook forward priority 0; policy drop;

        # Разрешить трафик от WireGuard к локальной сети
        iifname "wg0" accept

        # Разрешить established/related
        ct state established,related accept
    }
}

table inet nat {
    chain postrouting {
        type nat hook postrouting priority 100;

        # Маскарад для WireGuard-клиентов
        oifname "eth0" ip saddr 10.0.0.0/24 masquerade
    }
}
```

### OpenVPN сервер

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif "lo" accept

        # SSH
        tcp dport 22 ip saddr { 10.0.0.0/8, 192.168.0.0/16 } accept

        # OpenVPN (UDP 1194)
        udp dport 1192 accept

        # OpenVPN (TCP 443 — для обхода firewall)
        tcp dport 443 accept

        ip protocol icmp accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;

        # Трафик от OpenVPN клиентов
        iifname "tun0" accept
        ct state established,related accept
    }
}

table inet nat {
    chain postrouting {
        type nat hook postrouting priority 100;
        oifname "eth0" ip saddr 10.8.0.0/24 masquerade
    }
}
```

### IPsec сервер (strongSwan)

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif "lo" accept

        # SSH
        tcp dport 22 ip saddr { 10.0.0.0/8, 192.168.0.0/16 } accept

        # IKE (UDP 500)
        udp dport 500 ip saddr { 198.51.100.0/24 } accept

        # IKE NAT-T (UDP 4500)
        udp dport 4500 ip saddr { 198.51.100.0/24 } accept

        # ESP (IP protocol 50)
        ip protocol esp ip saddr { 198.51.100.0/24 } accept

        # ICMP
        ip protocol icmp accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;

        # Трафик через IPsec tunnel
        iifname "xfrm0" accept
        ct state established,related accept
    }
}

table inet nat {
    chain postrouting {
        type nat hook postrouting priority 100;
        oifname "eth0" ip saddr 192.168.1.0/24 masquerade
    }
}
```

### GRE + IPsec сервер

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif "lo" accept

        # SSH
        tcp dport 22 ip saddr { 10.0.0.0/8, 192.168.0.0/16 } accept

        # GRE (IP protocol 47)
        ip protocol 47 ip saddr { 198.51.100.0/24 } accept

        # IKE + NAT-T
        udp dport { 500, 4500 } ip saddr { 198.51.100.0/24 } accept

        # ESP
        ip protocol esp ip saddr { 198.51.100.0/24 } accept

        ip protocol icmp accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
        iifname "gre0" accept
        ct state established,related accept
    }
}
```

### DMVPN (mGRE + NHRP + IPsec)

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif "lo" accept

        # SSH
        tcp dport 22 ip saddr { 10.0.0.0/8, 192.168.0.0/16 } accept

        # GRE (protocol 47) — для mGRE
        ip protocol 47 accept

        # NHRP (UDP 544 для FRRouting)
        udp dport 544 accept

        # OSPF (IP protocol 89)
        ip protocol 89 accept

        # IKE + NAT-T + ESP
        udp dport { 500, 4500 } accept
        ip protocol esp accept

        ip protocol icmp accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
        iifname "tunnel0" accept
        ct state established,related accept
    }
}
```

---

## iptables (legacy)

### WireGuard сервер

```bash
#!/bin/bash

# Очистка
iptables -F
iptables -t nat -F

# INPUT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -p tcp --dport 22 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p udp --dport 51820 -s 198.51.100.0/24 -j ACCEPT
iptables -A INPUT -p icmp -j ACCEPT
iptables -P INPUT DROP

# FORWARD
iptables -A FORWARD -i wg0 -j ACCEPT
iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -P FORWARD DROP

# NAT
iptables -t nat -A POSTROUTING -o eth0 -s 10.0.0.0/24 -j MASQUERADE

# Сохранение
iptables-save > /etc/iptables/rules.v4
```

### OpenVPN сервер

```bash
#!/bin/bash

iptables -F
iptables -t nat -F

# INPUT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -p tcp --dport 22 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p udp --dport 1194 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT
iptables -A INPUT -p icmp -j ACCEPT
iptables -P INPUT DROP

# FORWARD
iptables -A FORWARD -i tun0 -j ACCEPT
iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -P FORWARD DROP

# NAT
iptables -t nat -A POSTROUTING -o eth0 -s 10.8.0.0/24 -j MASQUERADE

iptables-save > /etc/iptables/rules.v4
```

### MSS Clamping (универсальный)

```bash
# Автоматическая подстройка MSS
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o wg0 -j TCPMSS --clamp-mss-to-pmtu

# Жёсткая установка MSS
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o wg0 -j TCPMSS --set-mss 1360

# Сохранение
iptables-save > /etc/iptables/rules.v4
```

---

## pf (OpenBSD/FreeBSD/macOS)

### WireGuard сервер

```bash
# /etc/pf.conf

# Интерфейсы
ext_if = "eth0"
wg_if = "wg0"

# NAT
nat on $ext_if from $wg_if:network to any -> ($ext_if)

# Правила
pass in on $ext_if proto udp from any to any port 51820
pass in on $ext_if proto tcp from any to any port 22
pass out on $ext_if
block all
```

---

## Дополнительная информация

### Связанные документы

- **[WireGuard](./wireguard_practical.md)** — настройка WireGuard с PostUp/PostDown правилами
- **[OpenVPN](./openvpn.md)** — настройка OpenVPN сервера
- **[IPsec](./ipsec/ipsec.md)** — настройка IPsec с firewall правилами
- **[GRE](./gre/gre.md)** — настройка GRE с firewall правилами
- **[VPN Troubleshooting](./vpn_troubleshooting_universal.md)** — диагностика firewall проблем
