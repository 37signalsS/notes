# Анализ NAT, conntrack и файрволов в Wireshark

> **SSoT:** Теория NAT — в **[NAT Overview](../../../Networking/Concepts/nat/overview.md)**. Практические сценарии NAT — в **[NAT Practical Scenarios](../../../Networking/Concepts/nat/practical_scenarios.md)**. Conntrack bypass — в **[Conntrack Bypass](../../../Networking/Concepts/nat/conntrack_bypass.md)**. Файрволы — в **[Firewall Concepts](../../../Networking/Concepts/firewall_concepts.md)**. Концепции захвата — в **[Основные концепции](./core_concepts.md)**.

## Определения

**NAT (Network Address Translation)** — трансляция IP-адресов и/или портов при прохождении пакетов через маршрутизатор или файрвол. Типы: SNAT (替换源адрес), DNAT (替换目的адрес), PAT/NAPT (替换 порт), MASQUERADE (динамический SNAT).

**Conntrack (Connection Tracking)** — механизм ядра Linux для отслеживания состояний активных соединений. Каждая сессия (TCP/UDP/ICMP) записывается в таблицу `nf_conntrack` с таймаутами. При переполнении таблицы новые соединения отбрасываются.

**nf_conntrack_max** — максимальное количество записей в таблице conntrack. По умолчанию 262144. Рекомендуется 524288-1048576 для высоконагруженных серверов.

**nf_conntrack_tcp_timeout_established** — таймаут для установленных TCP-соединений в таблице conntrack. По умолчанию 432000 сек (5 дней). Рекомендуется 3600-7200 сек.

**INVALID state** — состояние conntrack для пакетов, не принадлежащих ни одному известному соединению. Пример: TCP RST без предварительного соединения, ответ на несуществующий запрос.

**DROP vs REJECT** — DROP тихо отбрасывает пакет (отправитель ждёт таймаут), REJECT отправляет ICMP error или TCP RST (немедленный ответ).

**iptables/nftables** — утилиты управления Netfilter: фильтрация пакетов, NAT, маршрутизация, маркировка. iptables — классический интерфейс, nftables — современная замена.

**TPROXY** — прозрачный прокси-механизм, сохраняющий оригинальный destination IP (в отличие от REDIRECT). Требует policy routing (`ip rule`).

## Quick-Start: Чек-лист анализа NAT/conntrack

| Шаг | Действие | Как проверить |
| :--- | :--- | :--- |
| **1** | Определить NAT | Сравнить src/dst IP в Wireshark с реальными адресами |
| **2** | Проверить conntrack | `conntrack -S` на шлюзе |
| **3** | Найти RST от файрвола | `tcp.flags.reset == 1` + отсутствие предшествующего соединения |
| **4** | Найти ICMP unreachable | `icmp.type == 3` — Destination Unreachable |
| **5** | Проверить консистентность NAT | SYN → SYN-ACK с одинаковым NAT-транслированным адресом |
| **6** | Найти DROP vs REJECT | DROP = таймаут, REJECT = ICMP error или RST |

## Основные концепции

### Как распознать NAT в Wireshark

NAT транслирует IP-адреса и/или порты. В Wireshark это проявляется:

```bash
# 1. Src/Dst IP изменились на пути:
# Клиент (192.168.1.10) → NAT (10.0.0.1) → Сервер (172.16.0.5)
# На захвате сервера виден src IP = 10.0.0.1 (NAT), а не 192.168.1.10

# 2. Порт изменён (PAT/NAPT):
# Клиент:src_port=54321 → NAT:src_port=20001
# В SYN видно оригинальный порт, в SYN-ACK от сервера — NAT-транслированный

# 3. Поиск симметричного NAT:
# Разные клиенты за NAT получают разные транслированные порты
tshark -r capture.pcap -Y "tcp.flags.syn == 1 && tcp.flags.ack == 0" \
  -T fields -e ip.src -e tcp.srcport | sort -u
```

### Распознавание файрвола DROP vs REJECT

```bash
# REJECT (ICMP Unreachable)
tshark -r capture.pcap -Y "icmp.type == 3" -T fields \
  -e frame.number -e ip.src -e ip.dst -e icmp.type -e icmp.code

# ICMP Type 3 codes:
# 0 = Network Unreachable
# 1 = Host Unreachable
# 2 = Protocol Unreachable
# 3 = Port Unreachable (для UDP; для TCP — RST)
# 4 = Fragmentation Needed
# 13 = Communication Administratively Prohibited (файрвол)

# REJECT (TCP RST)
# Файрвол отправляет RST в ответ на SYN (пор закрыт или правило REJECT)
tshark -r capture.pcap -Y "tcp.flags.syn == 1 && tcp.flags.ack == 0 && tcp.flags.reset == 1" \
  -T fields -e frame.number -e ip.src -e ip.dst -e tcp.dstport

# DROP (таймаут)
# SYN уходит, ответа нет, затем retry SYN через ~1с, ~3с, ~7с
tshark -r capture.pcap -Y "tcp.flags.syn == 1 && tcp.flags.ack == 0" \
  -T fields -e frame.number -e ip.src -e tcp.dstport -e frame.time_relative
```

### Анализ conntrack через Wireshark

Conntrack проблемы проявляются в Wireshark как:

```bash
# 1. Пакеты "исчезают" после establishment
# SYN → SYN-ACK → ACK → [данные] → ... → таймаут
# Причина: conntrack удал запись из-за малого таймаута

# 2. RST без предшествующего соединения (INVALID state)
tshark -r capture.pcap -Y "tcp.flags.reset == 1" -T fields \
  -e frame.number -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport | \
  awk '{key=$2":"$4" -> "$3":"$5; if (!seen[key]++) print}'

# 3. Ответы на несуществующие сессии
# Пакет с ACK, но без предшествующего SYN → conntrack мог сбросить запись
tshark -r capture.pcap -Y "tcp.flags.ack == 1 && tcp.flags.syn == 0 && tcp.len == 0" \
  -T fields -e frame.number -e tcp.stream -e frame.time_relative | \
  awk 'NR>1 && $3 - prev[$2] > 10 {print "GAP:", $0} {prev[$2]=$3}'
```

### sysctl-параметры conntrack для Wireshark-диагностики

| Параметр | Значение по умолч. | Рекомендуемое | Влияние |
| :--- | :--- | :--- | :--- |
| `nf_conntrack_max` | 262144 | 524288-1048576 | Размер таблицы |
| `nf_conntrack_buckets` | 65536 | 131072-262144 | Хэш-таблица (max/4) |
| `nf_conntrack_tcp_timeout_established` | 432000 (5д) | 3600-7200 | Очистка старых записей |
| `nf_conntrack_tcp_timeout_time_wait` | 120 | 30-60 | Очистка TIME-WAIT |
| `nf_conntrack_tcp_timeout_close_wait` | 60 | 30-60 | Очистка close_wait |
| `nf_conntrack_udp_timeout` | 30 | 30-60 | Таймаут UDP |
| `nf_conntrack_icmp_timeout` | 30 | 30 | Таймаут ICMP |

## Практические сценарии

### Сценарий 1: Диагностика conntrack table full

```bash
# В Wireshark: видны SYN-пакеты, но нет ответов
# На сервере: dmesg | grep "nf_conntrack: table full"

# Проверка текущего состояния
conntrack -S
# → insert_failed 15  ← ключевой counter

# Увеличение таблицы
sudo sysctl -w net.netfilter.nf_conntrack_max=1048576
sudo sysctl -w net.netfilter.nf_conntrack_buckets=262144

# Мониторинг в реальном времени
watch -n 1 'conntrack -C'
# → 524280  ← при приближении к max будут дропы
```

### Сценарий 2: Диагностика NAT hairpin (internal access to service via external IP)

```bash
# Hairpin NAT: клиент внутри NAT обращается к сервису через внешний IP
# SYN от клиента (192.168.1.10) → NAT (public IP) → обратно к серверу (192.168.1.20)

# В Wireshark на сервере:
# SYN src=192.168.1.10:54321 → dst=192.168.1.20:80 (hairpin)
# SYN-ACK src=192.168.1.20:80 → dst=192.168.1.10:54321

# Проблема: conntrack может не записать hairpin, если dnat-правило не настроено
# Решение:DNAT + hairpin NAT правило

# Проверка hairpin в Wireshark:
tshark -r capture.pcap -Y "ip.src == <CLIENT_IP> && ip.dst == <SERVER_IP>" \
  -T fields -e frame.number -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport
```

### Сценарий 3: Анализ SNAT в Kubernetes

```bash
# externalTrafficPolicy: Cluster → SNAT (теряется оригинальный IP клиента)
# externalTrafficPolicy: Local → без SNAT (сохраняется IP клиента)

# В Wireshark: SNAT проявляется как изменение src IP
# До NAT: src=10.244.0.5 (Pod IP)
# После NAT: src=192.168.1.100 (Node IP)

# Поиск SNAT:
tshark -r capture.pcap -Y "tcp.flags.syn == 1 && tcp.flags.ack == 0" \
  -T fields -e ip.src -e tcp.srcport | sort -u | head -20
```

### Сценарий 4: Диагностика iptables DROP

```bash
# Фильтрация трафика через nftables trace
# 1. Включить трассировку ядра
echo 1 > /proc/sys/net/netfilter/nf_log_all_netns

# 2. Запустить захват
sudo tshark -i eth0 -f "host <BLOCKED_IP>" -w blocked.pcapng

# 3. Проверить логи ядра
dmesg | grep -i "nft\|nf_tables\|DROP"

# 4. Поиск "невидимых" DROP
# SYN отправлен, но нет SYN-ACK → пакет отброшен файрволом
tshark -r blocked.pcapng -Y "tcp.flags.syn == 1 && tcp.flags.ack == 0" -T fields \
  -e frame.number -e ip.src -e ip.dst -e tcp.dstport -e frame.time_relative
```

### Сценарий 5: Анализ TPROXY vs REDIRECT

```bash
# REDIRECT (iptables -j REDIRECT) заменяет dst IP на localhost
# В Wireshark: dst IP = 127.0.0.1, а оригинальный dst потерян

# TPROXY (iptables -j TPROXY) сохраняет оригинальный dst IP
# В Wireshark: dst IP = оригинальный адрес назначения

# Диагностика:
tshark -r capture.pcap -Y "ip.dst == 127.0.0.1 && tcp.dstport == 8080" \
  -T fields -e frame.number -e ip.src -e ip.dst -e tcp.dstport
# Если dst = 127.0.0.1 → используется REDIRECT
# Если dst = оригинальный IP → используется TPROXY
```

## Дополнительная информация

### Таблица состояний conntrack (TCP)

| State | Описание | Таймаут по умолч. |
| :--- | :--- | :--- |
| **SYN_SENT** | SYN отправлен, ожидание SYN-ACK | 60 сек |
| **SYN_RECV** | SYN-ACK получен, ожидание ACK | 60 сек |
| **ESTABLISHED** | Соединение установлено | 432000 сек (5 дн) |
| **FIN_WAIT** | FIN отправлен | 120 сек |
| **CLOSE_WAIT** | FIN получен, ожидание FIN от приложения | 60 сек |
| **LAST_ACK** | FIN отправлен после получения FIN | 30 сек |
| **TIME_WAIT** | Ожидание 2MSL | 120 сек |
| **CLOSE** | Соединение закрыто | 10 сек |
| **UDP** | Один Datagram → Timeout | 30 сек |

### Команды диагностики conntrack

```bash
# Просмотр таблицы
conntrack -L
conntrack -L -p tcp --dport 80          # фильтрация по порту
conntrack -L --src-nat                   # только SNAT записи
conntrack -L --dst-nat                   # только DNAT записи

# Статистика
conntrack -S
# → insert_failed  → conntrack не может вставить запись (дубли или переполнение)
# → drop           → пакеты отброшены (table full)
# → early_drop     → записи удалены досрочно (pressure)

# Мониторинг в реальном времени
conntrack -E

# Очистка таблицы (ОСТОРОЖНО: сбросит все соединения)
conntrack -F

# Статус
conntrack -C  # текущее количество
cat /proc/sys/net/netfilter/nf_conntrack_max  # максимум
```

### См. также
- **[NAT Overview](../../../Networking/Concepts/nat/overview.md)** — теория NAT
- **[NAT Practical Scenarios](../../../Networking/Concepts/nat/practical_scenarios.md)** — практика NAT
- **[Conntrack Bypass](../../../Networking/Concepts/nat/conntrack_bypass.md)** — NOTRACK и оптимизация
- **[Firewall Concepts](../../../Networking/Concepts/firewall_concepts.md)** — теория файрволов
- **[Основные концепции](./core_concepts.md)** — захват трафика
- **[TCP Performance Diagnostics](./tcp_performance/tcp_performance_diagnostics.md)** — анализ TCP-проблем
