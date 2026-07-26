# nftables — практические сценарии настройки

## Определения

**NAT (Network Address Translation — преобразование сетевых адресов)** — механизм, позволяющий изменять IP-адреса в заголовках пакетов при их прохождении через маршрутизатор.

**Masquerading (Маскарадинг)** — динамический вид SNAT, используемый для интерфейсов с непостоянным (получаемым по DHCP или PPPoE) IP-адресом.

**DNAT (Destination NAT)** — изменение адреса и/или порта назначения. Применяется для "проброса портов" (Port Forwarding) из внешней сети во внутреннюю.

**SNAT (Source NAT)** — изменение адреса источника. Используется для предоставления доступа в интернет устройствам из приватных подсетей.

**Сеты (Sets)** — именованные наборы элементов (IP, порты), позволяющие эффективно обрабатывать списки в одном правиле.

**Мапы (Maps)** — словари "ключ-значение", используемые для привязки критерия к конкретному параметру (например, порт → внутренний IP) или вердикту (vmap).

**Flowtable (Флоу-таблица)** — механизм ускорения обработки пакетов (Fastpath), позволяющий передавать установленные соединения в обход классического сетевого стека для повышения производительности.

**Квота (Quota)** — ограничение объема передаваемого трафика (в байтах) для конкретного правила или адреса.

## Основные концепции

Конфигурация nftables строится по принципу полной гибкости: в системе нет предопределенных таблиц, их структура создается пользователем.

**Ключевые принципы:**
*   **Семейство `inet`:** Позволяет писать правила одновременно для IPv4 и IPv6.
*   **Хуки (Hooks):** Точки входа в сетевой стек (`prerouting`, `input`, `forward`, `output`, `postrouting`).
*   **Приоритеты:** Порядок обработки таблиц на одном и том же хуке.
*   **Connection Tracking (`ct`):** Механизм отслеживания состояний, на основе которого строятся Stateful-файрволы.

---

## Практические сценарии

### 1. Эталонный Stateful-файрвол для сервера

Базовая защита, разрешающая стандартные службы и корректную работу ICMP для обоих стеков (IPv4/IPv6).

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить установленные и связанные соединения
        ct state established,related accept
        
        # Отбросить некорректные пакеты
        ct state invalid drop

        # Разрешить локальную петлю
        iif "lo" accept

        # Разрешить SSH (22) и стандартный веб (80, 443)
        tcp dport { 22, 80, 443 } accept

        # Разрешить ICMP (Internet Control Message Protocol)
        icmp type echo-request accept
        
        # Разрешить ICMPv6 (критично для функционирования IPv6)
        icmpv6 type { 
            destination-unreachable, packet-too-big, time-exceeded, 
            parameter-problem, echo-request, echo-reply, 
            nd-router-solicit, nd-router-advert, 
            nd-neighbor-solicit, nd-neighbor-advert 
        } accept
    }
}
```

### 2. Защита от брутфорса с динамическими списками

Автоматическая блокировка IP-адресов, превышающих лимит попыток подключения к SSH.

```bash
table inet filter {
    # Динамический сет для временной блокировки
    set blacklist {
        type ipv4_addr
        flags dynamic, timeout
        timeout 1h
    }

    chain input {
        type filter hook input priority 0; policy drop;
        
        ct state established,related accept
        
        # Проверка по черному списку
        ip saddr @blacklist drop

        # Если более 3 новых соединений в минуту — бан на час
        tcp dport 22 ct state new \
            limit rate over 3/minute \
            add @blacklist { ip saddr } \
            log prefix "SSH Brute Force: " drop
            
        tcp dport 22 accept
    }
}
```

### 3. Проброс портов и NAT через мапы (Port-to-IP Mapping)

Использование мап позволяет компактно описать проброс множества портов на разные внутренние серверы.

```bash
table ip nat {
    # Мапа для проброса портов: внешний_порт : внутренний_IP
    map port_forwarding {
        type inet_service : ipv4_addr
        elements = { 8080 : 192.168.1.10, 9090 : 192.168.1.20 }
    }

    chain prerouting {
        type nat hook prerouting priority -100; policy accept;
        
        # DNAT на основе мапы
        dnat to tcp dport map @port_forwarding
    }

    chain postrouting {
        type nat hook postrouting priority 100; policy accept;
        
        # Маскарадинг для выхода из локальной сети
        oifname "eth0" masquerade
    }
}
```

### 4. Оптимизация производительности (Flowtables)

Позволяет разгрузить CPU, передавая трафик установленных сессий в "ускоренный" путь.

```bash
table inet filter {
    # Определение флоу-таблицы для интерфейсов
    flowtable f {
        hook ingress priority 0
        devices = { eth0, eth1 }
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
        
        # Передача установленных TCP/UDP соединений во флоу-таблицу
        ip protocol { tcp, udp } flow add @f
        
        ct state established,related accept
    }
}
```

### 5. Управление квотами трафика

Ограничение объема данных для конкретных хостов (например, гостевой сети).

```bash
table inet filter {
    # Именованная квота на 10 Гигабайт
    quota guest_limit { 10 gb }

    chain forward {
        type filter hook forward priority 0; policy drop;
        
        # Применение квоты для подсети
        ip saddr 192.168.2.0/24 quota name guest_limit accept
    }
}
```

### 6. Фильтрация VLAN в режиме моста (Bridge)

Пример блокировки трафика между конкретными VLAN внутри программного моста.

```bash
table bridge filter {
    chain forward {
        type filter hook forward priority 0; policy accept;

        # Запретить трафик из VLAN 10 в VLAN 20
        vlan id 10 vlan id 20 drop
        
        # Разрешить только HTTP внутри VLAN 30
        vlan id 30 tcp dport != 80 drop
    }
}
```

---

## Дополнительная информация

### Сохранение и загрузка конфигурации

В большинстве современных дистрибутивов nftables работает как системная служба, читающая правила из `/etc/nftables.conf`.

```bash
# Сохранение текущего набора правил (runtime) в файл конфигурации
nft list ruleset | sudo tee /etc/nftables.conf

# Проверка синтаксиса файла без применения изменений
sudo nft -c -f /etc/nftables.conf

# Применение правил из файла
sudo nft -f /etc/nftables.conf

# Включение автозагрузки при старте системы
sudo systemctl enable --now nftables
```

### См. также

- **[nftables — моделирование угроз и схемы защиты](./threat_modeling.md)** — архитектурное планирование защиты.
- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — база: хуки, таблицы, семейства.
- **[Тестирование правил nftables](./firewall_testing.md)** — верификация настроек (nmap, ss, nc).
- **[NAT — Теория и общие сценарии](../../../../../Networking/Concepts/nat/overview.md)** — концептуальный обзор технологий трансляции.
- **[fail2ban: Интеграция с nftables](../../../Linux/Security/Tools/fail2ban.md#интеграция-с-nftables)** — автоматизация блокировок.
