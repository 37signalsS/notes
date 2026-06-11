# nftables — практические сценарии настройки

## Определения

**NAT (Network Address Translation — преобразование сетевых адресов)** — механизм в сетях TCP/IP, позволяющий преобразовывать IP-адреса транзитных пакетов.

**Masquerading (Маскарадинг)** — частный случай [SNAT](#snat-и-masquerading), используемый для динамических IP-адресов. Автоматически подставляет IP-адрес выходного интерфейса.

**DNAT (Destination Network Address Translation)** — изменение адреса назначения пакета. Используется для проброса портов (Port Forwarding) из внешней сети во внутреннюю.

**SNAT (Source Network Address Translation)** — изменение адреса источника пакета. Используется для предоставления доступа в интернет узлам с частными IP-адресами.

**Сеты (Sets — наборы)** — именованные коллекции элементов (например, IP-адресов или портов), которые позволяют nftables эффективно обрабатывать большое количество значений в одном правиле.

## Основные концепции

В nftables практические сценарии реализуются через создание таблиц, цепочек и правил. В отличие от iptables, здесь нет предопределённых таблиц; каждая конфигурация строится "с нуля", что обеспечивает максимальную гибкость.

Ключевые принципы реализации:

- **Семейства**: Использование `inet` для одновременной поддержки IPv4 и IPv6.
- **Хуки и приоритеты**: Точное определение места обработки пакета (например, `prerouting` для DNAT, `postrouting` for SNAT).
- **Состояние соединений**: Использование `ct state` (Connection Tracking) для создания Stateful Firewall.

---

## Практические сценарии

### Базовая настройка для сервера

Типовая конфигурация Stateful Firewall (межсетевого экрана с отслеживанием состояния), разрешающая стандартные веб-службы и SSH (Secure Shell).

```bash
# Создать базовую конфигурацию
sudo nft -f - <<'EOF'
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить установленные и связанные соединения
        ct state established,related accept

        # Разрешить loopback (локальную петлю)
        iif lo accept

        # Разрешить SSH, HTTP (HyperText Transfer Protocol), HTTPS (Secure)
        tcp dport {22, 80, 443} accept

        # Разрешить ICMP (Internet Control Message Protocol) — ping
        icmp type echo-request accept
        
        # Разрешить ICMPv6 для корректной работы IPv6
        icmpv6 type { destination-unreachable, packet-too-big, time-exceeded, parameter-problem, echo-request, echo-reply, nd-router-solicit, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert } accept
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

### Динамический бан брутфорса SSH

Защита от перебора паролей (brute-force) без использования внешних инструментов (таких как fail2ban) с помощью динамических наборов (sets).

```bash
sudo nft -f - <<'EOF'
flush ruleset

table inet filter {
    # Сет для заблокированных IP с таймаутом (временем жизни) 15 минут
    set ssh_bruteforce {
        type ipv4_addr
        flags timeout
        timeout 15m
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить установленные соединения
        ct state established,related accept

        # Блокировать IP-адреса из списка ssh_bruteforce
        ip saddr @ssh_bruteforce drop

        # Детектировать брутфорс: более 5 новых соединений в минуту → бан
        tcp dport 22 ct state new limit rate over 5/minute \
          add @ssh_bruteforce { ip saddr } drop
        
        tcp dport 22 accept
    }
}
EOF
```

### Интеграция с fail2ban

Интеграция fail2ban с nftables подробно описана в едином источнике: **[fail2ban: Интеграция с nftables](../../../Linux/Security/Tools/fail2ban.md#интеграция-с-nftables)**.

### Сохранение и загрузка правил

Механизмы обеспечения персистентности (сохранения после перезагрузки) конфигурации.

```bash
# Сохранить текущие правила в файл
sudo nft list ruleset > /etc/nftables.conf

# Загрузить правила из файла
sudo nft -f /etc/nftables.conf

# Включить службу для автозагрузки при старте системы
sudo systemctl enable --now nftables
```

### Работа с наборами (Sets)

Использование именованных списков для упрощения управления правилами доступа.

```bash
# Создать таблицу с набором разрешённых IP-адресов
sudo nft -f - <<'EOF'
table inet filter {
    set allowed_ips {
        type ipv4_addr
        elements = { 192.168.1.10, 192.168.1.20, 10.0.0.0/24 }
    }

    chain input {
        type filter hook input priority 0; policy drop;
        
        # Разрешить трафик от IP из набора allowed_ips
        ip saddr @allowed_ips accept
        
        ct state established,related accept
    }
}
EOF
```

### SNAT и Masquerading

Настройка трансляции адресов для организации доступа внутренней сети в интернет.

```bash
sudo nft -f - <<'EOF'
table ip nat {
    chain postrouting {
        type nat hook postrouting priority 100; policy accept;

        # Masquerade (маскарадинг) для исходящего трафика через интерфейс eth0
        oifname "eth0" masquerade

        # SNAT (Source NAT) для конкретной подсети на статический IP
        ip saddr 192.168.1.0/24 oifname "eth0" snat to 203.0.113.1
    }

    chain prerouting {
        type nat hook prerouting priority -100; policy accept;

        # DNAT (Destination NAT): проброс порта 8080 на внутренний сервер 192.168.1.100:80
        tcp dport 8080 dnat to 192.168.1.100:80
    }
}
EOF
```

### Логирование отброшенных пакетов

Настройка журналирования попыток несанкционированного доступа.

```bash
sudo nft -f - <<'EOF'
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Логирование с ограничением частоты (не более 5 записей в минуту), чтобы избежать переполнения логов
        limit rate 5/minute log prefix "INPUT dropped: " level warn

        ct state established,related accept
    }
}
EOF
```

---

## Дополнительная информация

### См. также

- **[nftables — моделирование угроз и схемы защиты](./threat_modeling.md)** — планирование правил на основе угроз.
- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — устройство таблиц, цепочек и хуков.
- **[Тестирование правил nftables](./firewall_testing.md)** — методы проверки работоспособности конфигурации.
- **[NAT — Теория и общие сценарии](../../../../../Networking/Concepts/nat/overview.md)** — концептуальный обзор трансляции адресов.
