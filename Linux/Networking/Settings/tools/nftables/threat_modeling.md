# nftables — моделирование угроз и схемы защиты

## Определения

**Моделирование угроз** — систематический процесс выявления, анализа и оценки потенциальных угроз безопасности для определения оптимальных мер противодействия на уровне сетевого фильтра.

**DoS/DDoS (Denial of Service)** — атака, направленная на исчерпание ресурсов узла (CPU, RAM, пропускная способность) или сетевого стека ядра, что приводит к отказу в обслуживании легитимных пользователей.

**IP-спуфинг (IP Spoofing)** — подмена IP-адреса источника для обхода фильтрации по адресу или организации атак типа «отражение» (reflection).

**SYN-флуд** — атака на транспортном уровне (L4), использующая механизм трехэтапного рукопожатия TCP для переполнения очереди полуоткрытых соединений (backlog).

**UDP-амплификация** — атака, использующая протоколы без установления соединения (DNS, NTP, Memcached) для отправки запроса с поддельным IP жертвы, что вызывает многократно больший ответ в сторону цели.

## Основные концепции

### Алгоритм разработки политики безопасности (Zero Trust подход)

При проектировании правил nftables рекомендуется следовать принципу «запрещено все, что не разрешено явно»:

1.  **Идентификация активов:** список критических сервисов (порты, протоколы) и легитимных потребителей.
2.  **Анализ рисков:** оценка уязвимости каждого сервиса к сканированию, брутфорсу или флуду.
3.  **Модель «Диода»:** четкое разделение на Ingress (входящий) и Egress (исходящий) фильтры.
4.  **Техническая реализация:** использование атомарных наборов (sets), словарей (maps) и конкатенаций для оптимизации производительности.
5.  **Непрерывный мониторинг:** логирование аномалий и интеграция с системами анализа (Wazuh, Suricata).

### Типовые угрозы и меры нейтрализации

| Угроза | Вектор атаки | Реализация в nftables |
| :--- | :--- | :--- |
| **SYN-флуд** | L4 (TCP) | Использование `synproxy` в таблице `raw` или ограничение частоты через `limit rate`. |
| **Сканирование портов** | Reconnaissance | Сброс пакетов в состоянии `invalid`, блокировка сканеров через динамические сеты. |
| **IP-спуфинг** | L3 (IP) | Проверка обратного пути (uRPF) и фильтрация **Bogon/Martians** адресов. |
| **Брутфорс** | L7 (App) | Динамические списки с флагом `timeout` для временной блокировки агрессивных IP. |
| **UDP-амплификация** | L4 (UDP) | Жесткое ограничение частоты ответов и фильтрация исходящих запросов. |
| **IPv6 NDP Spoofing** | L2/L3 (IPv6) | Фильтрация ICMPv6 сообщений Neighbor Discovery (только доверенные типы). |
| **Некорректные пакеты** | Стек ядра | Глубокая проверка TCP-флагов (например, `tcp flags & (fin|syn|rst|psh|ack|urg) == 0`). |

### Фильтрация Bogon и Martians

Bogon-адреса — это IP-пространства, которые еще не распределены IANA или зарезервированы для специальных целей. Пакеты с такими адресами в качестве источника не должны приходить из внешнего интернета.

```bash
define bogons = { 
    0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 
    169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 
    192.0.2.0/24, 192.168.0.0/16, 198.18.0.0/15, 
    198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/3 
}

# В цепочке input:
ip saddr $bogons drop
```

---

## Практические сценарии

### 1. Защита от SYN-флуда через Synproxy

Механизм `synproxy` перехватывает TCP-рукопожатие и подтверждает владение IP-адресом до того, как пакет попадет в стек приложения.

```bash
table inet raw {
    chain prerouting {
        type filter hook prerouting priority -300;
        
        # Направляем новые SYN пакеты на веб-порты в untracked состояние
        tcp dport { 80, 443 } tcp flags syn notrack
    }
}

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        
        # Обработка пакетов через synproxy (MSS и Sack обязательны)
        tcp dport { 80, 443 } ct state { invalid, untracked } synproxy mss 1460 wscale 7 sack-perm accept
        
        ct state established,related accept
    }
}
```

### 2. Защита от брутфорса и сканирования (Конкатенация)

Использование конкатенации IP и порта позволяет создавать более точные правила блокировки.

```bash
table inet filter {
    # Сет для блокировки пары IP + Порт
    set banned_pairs {
        type ipv4_addr . inet_service
        flags dynamic, timeout
        timeout 1h
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Проверка по списку блокировки
        ip saddr . tcp dport @banned_pairs drop

        ct state established,related accept
        ct state invalid drop

        # Защита SSH: более 5 попыток за 2 минуты -> бан на час
        tcp dport 22 ct state new \
            limit rate over 5/2minute \
            add @banned_pairs { ip saddr . tcp dport } \
            drop
        
        tcp dport 22 accept
    }
}
```

### 3. Защита IPv6: Neighbor Discovery и ICMPv6

IPv6 критически зависит от ICMPv6. Бездумное блокирование всех типов ICMPv6 приведет к неработоспособности сети.

```bash
table ip6 filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить необходимые типы Neighbor Discovery
        icmpv6 type { 
            destination-unreachable, packet-too-big, 
            time-exceeded, parameter-problem, 
            echo-request, echo-reply,
            nd-router-solicit, nd-router-advert,
            nd-neighbor-solicit, nd-neighbor-advert 
        } accept

        # Ограничение частоты для предотвращения ICMPv6-флуда
        icmpv6 type echo-request limit rate 10/second accept
    }
}
```

### 4. Фильтрация Egress (Защита от утечек и C2)

Ограничение исходящего трафика только доверенными направлениями.

```bash
table inet filter {
    chain output {
        type filter hook output priority 0; policy drop;

        # Разрешить ответы на установленные входящие соединения
        ct state established,related accept

        # Разрешить DNS (только к внутренним или доверенным серверам)
        udp dport 53 ip daddr 8.8.8.8 accept

        # Разрешить HTTP/HTTPS только к зеркалам обновлений
        tcp dport { 80, 443 } ip daddr @update_servers accept

        # Разрешить логирование во внешний SIEM
        udp dport 514 ip daddr 10.0.5.5 accept
    }
}
```

---

## Дополнительная информация

### См. также

- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md):** база для построения цепочек и таблиц.
- **[Практические сценарии nftables](./practical_scenarios.md):** готовые шаблоны для типовых задач.
- **[Тестирование правил nftables](./firewall_testing.md):** инструменты верификации защиты (nmap, hping3).
- **[Лучшие практики проектирования правил](../../../../../Networking/Concepts/firewall_rules_best_practices.md):** общие принципы сетевой безопасности.
- **[Bogon Reference (Team Cymru)](https://www.team-cymru.com/bogon-reference):** актуальные списки нераспределенных сетей.
