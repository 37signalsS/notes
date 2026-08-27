# Сетевой Troubleshooting: Flowchart

## Определения

**Network Troubleshooting Flowchart** — визуализированный алгоритм диагностики сетевых проблем, основанный на модели OSI. Каждый уровень проверяется последовательно (Bottom-Up подход): сначала физическая связность, потом L2/L3, затем L4/L7. Цель — быстро локализовать проблему, а не проверять всё подряд.

**Bottom-Up Approach** — стратегия диагностики, начинающаяся с физического уровня (L1) и продвигающаяся вверх. Преимущество: физические проблемы (кабель, link state) часто являются корневой причиной и проверяются за секунды.

**Divide-and-Conquer** — стратегия, при которой проблема разделяется пополам: проверяется уровень в середине стека (обычно L3), что позволяет сразу отсечь нижние или верхние уровни.

## Основные концепции

### Три стратегии диагностики

| Стратегия | Направление | Когда использовать |
| :--- | :--- | :--- |
| **Bottom-Up** | L1 → L7 | Неизвестна причина, нужно найти с начала |
| **Top-Down** | L7 → L1 | Приложение сообщает ошибку, нужно дойти до L1 |
| **Divide-and-Conquer** | L4/L3 (середина) | Быстрая локализация: «проблема выше или ниже L3?» |

### Flowchart: Bottom-Up диагностика

```text
                        ┌──────────────────────┐
                        │   Начало диагностики   │
                        └──────────┬───────────┘
                                   │
                        ┌──────────▼───────────┐
                        │  L1: Проверка link     │
                        │  state на интерфейсе   │
                        └──────────┬───────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │               │
              ┌─────▼─────┐ ┌─────▼─────┐  ┌─────▼─────┐
              │ Link DOWN  │ │ Link UP,   │  │ Link UP,   │
              │            │ │ но нет     │  │ есть       │
              │            │ │ connectivity│  │ connectivity│
              └─────┬─────┘ └─────┬─────┘  └─────┬─────┘
                    │              │               │
           ┌───────▼───────┐ ┌────▼────┐   ┌──────▼──────┐
           │ Проверить      │ │ L2:     │   │ L4/L7:     │
           │ кабель/SFP/    │ │ MAC,    │   │ Порты,     │
           │ интерфейс      │ │ VLAN,   │   │ DNS,       │
           │ (ethtool -S)   │ │ ARP     │   │ Firewall   │
           └───────┬───────┘ └────┬────┘   └──────┬──────┘
                   │              │                │
            ┌──────▼──────┐  ┌────▼────┐    ┌──────▼──────┐
            │ Решение:     │  │ Решение:│    │ Решение:    │
            │ замена кабеля│  │ VLAN,   │    │ iptables,   │
            │ переключение │  │ STP,    │    │ DNS, порт   │
            │ порта, SFP   │  │ MAC     │    │ сервиса     │
            └─────────────┘  └─────────┘    └─────────────┘
```

## Практические сценарии

### Уровень 1 (L1): Physical — «Есть ли link?»

```bash
# 1. Проверить link state
ip link show eth0
# UP/DOWN → физическая проблема

# 2. Проверить скорость и дуплекс
ethtool eth0 | grep -E "Speed|Duplex|Link detected"
# Speed: 1000Mb/s, Duplex: Full, Link detected: yes

# 3. Проверить ошибки на интерфейсе
ethtool -S eth0 | grep -E "error|drop|miss|crc|collision"
# crc errors → проблема с кабелем/SFP
# collisions → дуплекс mismatch

# 4. Проверить оптический уровень (SFP DOM)
ethtool -m eth0
# TX Power / RX Power → если RXelow threshold → проблема с оптикой
```

**Решения:**
- Link DOWN → заменить кабель, проверить порт на коммутаторе, заменить SFP
- CRC errors → заменить кабель, проверить разъёмы
- Duplex mismatch → принудительно настроить `ethtool -s eth0 speed 1000 duplex full`

### Уровень 2 (L2): Data Link — «Есть ли L2-связность?»

```bash
# 1. Проверить ARP-таблицу (есть ли MAC-адреса)
arp -a
ip neigh show

# 2. Проверить VLAN
cat /proc/net/vlan/config
bridge vlan show

# 3. Проверить MAC-адреса на интерфейсах
ip link show | grep ether

# 4. Проверить STP (заблокирован ли порт?)
bridge link show | grep -i forwarding

# 5. Проверить commutator ( если есть доступ)
show mac address-table
show vlan brief
```

**Решения:**
- ARP-таблица пуста → проблема с L2-связностью (VLAN, STP, кабель)
- STP заблокировал порт → проверить priority, topology changes
- MAC не учится → проверить port security, MAC filtering

### Уровень 3 (L3): Network — «Маршрутизируется ли?»

```bash
# 1. Проверить IP-адрес
ip addr show eth0

# 2. Проверить таблицу маршрутизации
ip route show
ip route get <destination_ip>

# 3. Проверить связность ( ping с отслеживанием маршрута)
ping -c 3 <gateway_ip>         # Шаг 1: до шлюза
ping -c 3 <remote_ip>          # Шаг 2: до удалённого хоста
traceroute <remote_ip>         # Шаг 3: где теряется?

# 4. Проверить DNS
dig example.com A
nslookup example.com

# 5. Проверить conntrack (для NAT)
conntrack -L -p tcp --dport 80
conntrack -S

# 6. Проверить firewall
iptables -L -n -v
nft list ruleset
```

**Решения:**
- Не пингуется gateway → проблема L2 или gateway не работает
- Gateway пингуется, remote нет → проблема маршрутизации (проверить `ip route`)
- DNS не резолвится → проверить `/etc/resolv.conf`, CoreDNS, firewall для порта 53
- NAT не работает → проверить `iptables -t nat -L`, conntrack满溢

### Уровень 4 (L4): Transport — «Открыт ли порт?»

```bash
# 1. Проверить, слушает ли сервис
ss -lntp | grep :80
netstat -tlnp | grep :80

# 2. Проверить доступность порта извне
nc -zv <host> 80
nmap -sT -p 80 <host>

# 3. Проверить TCP-соединения
ss -tnp | grep :80
ss -s  # общая статистика

# 4. Проверить state-машину TCP
ss -tnp state established | grep :80
ss -tnp state time-wait | wc -l  # много TIME_WAIT?

# 5. Проверить TCP-ошибки
nstat -az | grep -E "Retrans|Timeout|Fail"

# 6. Захват пакетов (诊断 TCP handshake)
tcpdump -i eth0 -nn 'tcp port 80 and (tcp[tcpflags] & (tcp-syn) != 0)'
```

**Решения:**
- Порт не слушает → сервис не запущен, неверный bind address
- SYN уходит, нет ответа → firewall на стороне сервера
- RST приходит → сервис отклоняет соединение
- Много TIME_WAIT → `net.ipv4.tcp_tw_reuse=1`

### Уровень 5-7 (L5-L7): Session / Presentation / Application

```bash
# 1. Проверить HTTP-ответ
curl -v https://example.com
curl -I https://example.com

# 2. Проверить TLS
openssl s_client -connect example.com:443 -servername example.com

# 3. Проверить DNS + HTTP вместе
curl -v --resolve example.com:443:10.0.0.1 https://example.com

# 4. Проверить заголовки и расшифровку
tshark -r capture.pcap -Y "http.response.code >= 400" -T fields -e http.response.code -e http.host

# 5. Проверить Latency
curl -o /dev/null -s -w "DNS: %{time_namelookup}s\nConnect: %{time_connect}s\nTLS: %{time_appconnect}s\nTotal: %{time_total}s\n" https://example.com
```

**Решения:**
- HTTP 502/503 → бэкенд не работает или не доступен
- TLS handshake fails → проблема с сертификатом, cipher suite mismatch
- Timeout → проверить MTU, firewall, NAT timeouts

### Быстрая локализация: Divide-and-Conquer

```text
         Проблема: "не работает сервис"
                     │
         ┌───────────▼───────────┐
         │  ping -c3 <gateway>   │
         └───────────┬───────────┘
                     │
            ┌────────┼────────┐
         работает  не работает
            │         │
     ┌──────▼──────┐  │
     │ ping -c3    │  └──► Проблема L1/L2
     │ <remote_ip> │
     └──────┬──────┘
            │
       ┌────┼────┐
    работает  не работает
       │         │
  ┌────▼────┐    └──► Проблема L3 (маршрутизация)
  │nc -zv   │
  │<host>:80│
  └────┬────┘
       │
  ┌────┼────┐
 работает  не работает
    │         │
┌───▼───┐     └──► Проблема L4 (порт/firewall)
│curl -v│
│<host> │
└───┬───┘
    │
┌───┼────┐
200 4xx/5xx
│      │
OK   └──► Проблема L7 (приложение, конфигурация)
```

## Дополнительная информация

### USE-методология (Brendan Gregg)

Для каждого ресурса проверять:

| Метрика | Что проверить | Инструмент |
| :--- | :--- | :--- |
| **U**tilization | % времени использования | `sar -n DEV 1`, `ethtool -S` |
| **S**aturation | Очередь переполнена | `nstat -az \| grep -i drop`, `ethtool -S \| grep -i miss` |
| **E**rrors | Количество ошибок | `ethtool -S \| grep -i error`, `ip -s link show` |

### RED-методология (Tom Wilkie)

Для каждого сервиса:

| Метрика | Что проверить | Инструмент |
| :--- | :--- | :--- |
| **R**ate | Количество запросов/сек | Prometheus, nginx access log |
| **E**rrors | % ошибок | `curl -s ... \| jq .errors` |
| **D**uration | Латентность (p50/p99) | Prometheus histogram, curl timing |

### Таблица симптомов → уровень OSI

| Симптом | Вероятный уровень | Первые шаги |
| :--- | :--- | :--- |
| Interface DOWN | L1 | `ethtool eth0`, проверить кабель |
| crc errors, collisions | L1 | `ethtool -S eth0`, заменить кабель |
| ARP timeout | L2 | `ip neigh show`, `arp -a` |
| `Destination Host Unreachable` | L3 | `ip route get <dest>`, `ping <gateway>` |
| `Connection refused` | L4 | `ss -lntp`, проверить порт сервиса |
| `Connection timed out` | L3/L4 | `tcpdump`, проверить firewall/NAT |
| `No route to host` | L3 | `ip route get <dest>`, traceroute |
| `Name or service not known` | L7 (DNS) | `dig`, `/etc/resolv.conf` |
| HTTP 502/503 | L7 | `curl -v`, проверить бэкенд |
| TLS handshake failure | L6 | `openssl s_client`, сертификат |
| Slow response | L4/L7 | `ss -tn`, `tcpdump`, `curl -w` |

### Смотрите также

- **[Модель OSI](./osi_model.md)** — levels для навигации по flowchart.
- **[Пакетный анализ: Шпаргалка](./packet_analysis_cheatsheet.md)** — BPF-фильтры для диагностики.
- **[Troubleshooting в Linux](../../Linux/Networking/network_troubleshooting_order.md)** — Bottom-Up подход с командами.
- **[Общая методология](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md)** — USE, RED, Golden Signals.
- **[Диагностические инструменты](../../Linux/Networking/network_diagnostics_tools.md)** — полный список инструментов.
- **[Альтернативы ping](../Troubleshooting/ping_alternatives.md)** — TCP/UDP ping, mtr, gping.
- **[Реальный кейс: DNS](../Troubleshooting/real_case_troubleshooting_dns_misconfig.md)** — пример диагностики DNS-проблемы.
- **[Реальный кейс: Kafka+DB](../Troubleshooting/real_case_troubleshooting_kafka_db.md)** — пример распределённой диагностики.
