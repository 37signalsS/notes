# nftables — практические сценарии настройки

## Определения

**NAT (Network Address Translation)** — механизм преобразования IP-адресов и портов в заголовках пакетов. В nftables реализуется через типы `snat`, `dnat`, `masquerade` и `redirect`.

**Masquerading** — динамический вид SNAT, автоматически подставляющий IP-адрес исходящего интерфейса. Идеален для каналов с DHCP (PPPoE, LTE).

**Сеты (Sets)** — именованные наборы элементов (адреса, порты, интерфейсы), позволяющие обрабатывать тысячи объектов за один проход за счет использования хэш-таблиц.

**Мапы (Maps)** — структуры «ключ-значение», позволяющие сопоставлять данные (например, IP-адрес источника → вердикт или IP → порт).

**Flowtable** — технология Fastpath в ядре Linux, позволяющая передавать пакеты установленных соединений (L4) напрямую между сетевыми интерфейсами, минуя классический стек фильтрации, что снижает нагрузку на CPU.

## Основные концепции

Конфигурация nftables полностью модульная. Для построения эффективного файрвола необходимо понимать иерархию объектов:

1.  **Таблицы (Tables):** контейнеры для цепочек, привязанные к семейству протоколов (`ip`, `ip6`, `inet`, `bridge`, `netdev`).
2.  **Цепочки (Chains):** группы правил, привязанные к системным хукам (точки прохождения пакета).
3.  **Выражения (Expressions):** условия сопоставления данных пакета.
4.  **Действия (Verdicts):** решение по пакету (`accept`, `drop`, `reject`, `jump`, `goto`).

---

## Практические сценарии

### 1. Эталонный Stateful-файрвол (IPv4 + IPv6)

Базовая защита сервера, использующая семейство `inet` для атомарного управления обоими стеками.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # 1. Разрешить установленные и связанные соединения
        ct state established,related accept
        
        # 2. Сброс некорректных пакетов (INVALID)
        ct state invalid drop

        # 3. Разрешить Loopback
        iif "lo" accept

        # 4. Разрешить ICMP и ICMPv6 (необходимы для диагностики и IPv6)
        icmp type echo-request limit rate 5/second accept
        icmpv6 type { 
            destination-unreachable, packet-too-big, time-exceeded, 
            parameter-problem, echo-request, echo-reply, 
            nd-neighbor-solicit, nd-neighbor-advert, 
            nd-router-solicit, nd-router-advert 
        } accept

        # 5. Открытие портов сервисов
        tcp dport { 22, 80, 443 } accept
    }
}
```

### 2. Защита от DDoS на раннем этапе (Netdev Ingress)

Семейство `netdev` позволяет отбрасывать пакеты сразу после их получения драйвером сетевой карты, что значительно экономит ресурсы CPU при атаках.

```bash
table netdev filter {
    chain ingress {
        type filter hook ingress device "eth0" priority -500;
        
        # Сброс фрагментированных пакетов
        ip frag-off & 0x3fff != 0 drop

        # Лимит на общее количество входящих пакетов
        limit rate over 50000/second drop
    }
}
```

### 3. Балансировка нагрузки (Load Balancing)

Nftables поддерживает нативную балансировку трафика без использования сторонних инструментов.

```bash
table ip nat {
    chain prerouting {
        type nat hook prerouting priority -100; policy accept;
        
        # Балансировка HTTP трафика между двумя серверами (Round-robin)
        tcp dport 80 dnat to numgen inc mod 2 map { 0 : 192.168.1.10, 1 : 192.168.1.11 }
    }
}
```

### 4. Поддержка HA-кластеров (VRRP/Keepalived)

При использовании Keepalived необходимо разрешить специфичный VRRP трафик (протокол 112).

```bash
table inet filter {
    chain input {
        ...
        # Разрешить VRRP пакеты от партнеров по кластеру
        ip protocol vrrp accept
        # Для IPv6
        ip6 nexthdr vrrp accept
    }
}
```

### 5. Сложная фильтрация через конкатенацию (Concatenation)

Объединение нескольких критериев в один сет для повышения производительности.

```bash
table inet filter {
    # Сет, содержащий пары IP-адрес и порт назначения
    set whitelist {
        type ipv4_addr . inet_service
        elements = { 1.2.3.4 . 22, 5.6.7.8 . 443 }
    }

    chain input {
        # Разрешить только если IP и порт совпадают с парой в сете
        ip saddr . tcp dport @whitelist accept
    }
}
```

### 6. Проброс портов (DNAT) и Маскарадинг

```bash
table ip nat {
    chain prerouting {
        type nat hook prerouting priority -100;
        
        # Внешний порт 8080 -> Внутренний IP 10.0.0.5:80
        tcp dport 8080 dnat to 10.0.0.5:80
    }

    chain postrouting {
        type nat hook postrouting priority 100;
        
        # Маскарадинг для трафика, уходящего через eth0
        oifname "eth0" masquerade
    }
}
```

### 7. Оптимизация через Flowtables

Для маршрутизаторов с высокой нагрузкой (L3 Forwarding).

```bash
table ip filter {
    flowtable f {
        hook ingress priority 0
        devices = { eth0, eth1 }
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
        
        # Передача установленных соединений в Fastpath
        ct state established flow add @f
        
        ct state established,related accept
    }
}
```

---

## Дополнительная информация

### Управление и диагностика

```bash
# Проверка текущих счетчиков правил
nft list ruleset

# Мониторинг новых соединений в реальном времени
sudo nft monitor

# Очистка конкретной таблицы
nft flush table inet filter
```

### Сохранение персистентности

Стандартный метод для большинства дистрибутивов (Systemd-based):
1.  Выгрузить текущие правила: `nft list ruleset > /etc/nftables.conf`
2.  Активировать службу: `systemctl enable --now nftables`

### См. также

- **[nftables — моделирование угроз](./threat_modeling.md):** стратегии проектирования правил безопасности.
- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md):** детальный разбор хуков и приоритетов.
- **[Тестирование правил nftables](./firewall_testing.md):** верификация настроек (nmap, ss, nc).
- **[NAT — Теория и общие сценарии](../../../../../Networking/Concepts/nat/overview.md):** глубокий разбор механизмов трансляции.
- **[Интеграция Fail2ban с nftables](../../../../Security/Tools/fail2ban.md):** автоматизация блокировок.
