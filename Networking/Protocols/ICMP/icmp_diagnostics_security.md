# ICMP: Диагностика и безопасность

## Определения

**Диагностика ICMP** — использование служебных сообщений протокола ICMP для анализа топологии сети, выявления узких мест, измерения задержек и отладки проблем MTU.

**Безопасность ICMP** — стратегия настройки сетевых экранов и параметров ядра ОС для минимизации рисков сетевой разведки, DoS-атак и несанкционированного управления маршрутизацией при сохранении критической функциональности сети.

**Критический ICMPv6** — набор сообщений (NDP, RA/RS, Packet Too Big), без которых работа стека IPv6 невозможна. В отличие от IPv4, полное блокирование ICMPv6 делает узел неработоспособным в IPv6-сети.

## Основные концепции

### Последствия некорректной блокировки (ICMP Black Hole)

Полная блокировка ICMP-трафика ("Security through obscurity") — одна из самых частых ошибок системного администрирования.

*   **Проблема PMTUD:** При блокировке `Destination Unreachable` (Type 3 Code 4 в IPv4 или Type 2 в IPv6) отправитель не узнает, что пакет слишком велик для канала. В результате TCP-сессия устанавливается (маленькие пакеты проходят), но передача данных (большие пакеты) "зависает".
*   **Слепая трассировка:** Запрет `Time Exceeded` (Type 11) делает невозможной работу `traceroute` и `mtr`, что критично при поиске места разрыва связи.
*   **Ложные срабатывания мониторинга:** Блокировка `Echo` лишает возможности быстрого контроля доступности узла (L3-check).

### Рекомендуемая политика фильтрации

Для современных серверов рекомендуется разрешать только необходимые типы сообщений с применением ограничений скорости (Rate Limiting).

| Тип (v4 / v6) | Код | Название | Действие | Обоснование |
| :--- | :--- | :--- | :--- | :--- |
| **8 / 128** | 0 | Echo Request | **Accept + Limit** | Разрешить для мониторинга (L3-проверка доступности), ограничить для защиты от флуда. |
| **0 / 129** | 0 | Echo Reply | **Accept + Limit** | Необходим для работы ping; ограничить чтобы предотвратить abuse в качестве отражателя. |
| **3 / 1** | 4 / — | Fragmentation Needed / Packet Too Big | **Accept** | **Критично для PMTUD.** Без него соединения с большими пакетами зависнут (Black Hole). |
| **3 / 1** | 3 / 4 | Port Unreachable | **Accept** | Быстрая реакция TCP/UDP на закрытые порты; экономит ресурсы стека. |
| **3 / 1** | 0 / 0 | Net/Host Unreachable | **Accept** | Информирует об отсутствии маршрута; сокращает время ожидания приложений. |
| **11 / 3** | 0 | Time Exceeded | **Accept** | Обязательно для `traceroute` и обнаружения петел маршрутизации. |
| **11 / 3** | 1 | Fragment Reassembly Timeout | **Accept** | Диагностика проблем фрагментации. |
| **12 / 4** | 0 | Parameter Problem | **Accept** | Обнаружение ошибок в заголовке IP; редко, но важно. |
| **5 / 137** | 0–3 | Redirect | **Drop** | Блокировать всегда. Предотвращает MITM-атаки через подмену маршрута. |
| **4** | 0 | Source Quench | **Drop** | Устаревший тип (deprecated RFC 6633), не поддерживается современными стеками. |
| **13/14** | 0 | Timestamp / Reply | **Drop (или Rate Limit)** | Используется для OS fingerprinting и измерения RTT; риски превосходят пользу. |
| **— / 133-137** | — | NDP (RS/RA/NS/NA/Redirect) | **Accept (Local)** | **Критично для IPv6.** Разрешать только на `link-local` уровне и только с Trusted Router. |
| **— / 130–132** | — | MLD | **Accept (Local)** | Управление мультикастом в IPv6; без него работа IGMP/MLD-групп нарушена. |

## Практические сценарии

### Настройка через nftables (Современный стандарт)

Использование семейства `inet` позволяет управлять обоими стеками (IPv4/IPv6) в одном месте.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # 1. Разрешить установленные соединения и отбросить некорректные
        ct state established,related accept
        ct state invalid drop

        # 2. Разрешить критический ICMPv4 (PMTUD + traceroute)
        icmp type {
            destination-unreachable, time-exceeded,
            parameter-problem, fragmentation-needed
        } accept

        # Лимит для защиты от Ping Flood (Echo Request/Reply)
        icmp type { echo-request, echo-reply } \
            limit rate 5/second burst 10 packets accept

        # 3. Разрешить критический ICMPv6 (SLAAC, NDP, PMTUD)
        icmpv6 type {
            destination-unreachable, packet-too-big,
            time-exceeded, parameter-problem,
            echo-request, echo-reply, nd-router-advert,
            nd-router-solicit, nd-neighbor-solicit,
            nd-neighbor-advert
        } accept

        # Rate limiting для Echo Request v6
        icmpv6 type echo-request limit rate 5/second burst 10 packets accept
    }
}
```

### Настройка через iptables (Legacy, still widely deployed)

Для систем с iptables вместо nftables применяйте аналогичную логику через отдельные правила для IPv4 и IPv6.

```bash
# === IPv4 ===

# 1. Разрешить loopback
iptables -A INPUT -i lo -j ACCEPT -m comment --comment "Allow loopback"

# 2. Разрешить установленные соединения (stateful)
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 3. Разрешить критический ICMPv4
# Destination Unreachable (Type 3) — для PMTUD и Port Unreachable
iptables -A INPUT -p icmp --icmp-type destination-unreachable -j ACCEPT
# Time Exceeded (Type 11) — для traceroute
iptables -A INPUT -p icmp --icmp-type time-exceeded -j ACCEPT
# Parameter Problem (Type 12)
iptables -A INPUT -p icmp --icmp-type parameter-problem -j ACCEPT

# 4. Rate-limited Echo Request/Reply (защита от флуда)
iptables -A INPUT -p icmp --icmp-type echo-request \
    -m limit --limit 5/second --limit-burst 10 -j ACCEPT
iptables -A INPUT -p icmp --icmp-type echo-reply \
    -m limit --limit 5/second --limit-burst 10 -j ACCEPT

# 5. Блокировать Redirect (Type 5) и Source Quench (Type 4)
iptables -A INPUT -p icmp --icmp-type redirect -j DROP
iptables -A INPUT -p icmp --icmp-type source-quench -j DROP

# 6. Блокировать остальной ICMP (явный запрет)
iptables -A INPUT -p icmp -j DROP -m comment --comment "Drop all other ICMP"
```

```bash
# === IPv6 (ip6tables) ===

# 1. Разрешить loopback
ip6tables -A INPUT -i lo -j ACCEPT

# 2. Разрешить установленные соединения
ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 3. Разрешить критический ICMPv6
# Packet Too Big (Type 2) — для PMTUD
ip6tables -A INPUT -p icmpv6 --icmpv6-type packet-too-big -j ACCEPT
# Time Exceeded (Type 3)
ip6tables -A INPUT -p icmpv6 --icmpv6-type time-exceeded -j ACCEPT
# Destination Unreachable (Type 1)
ip6tables -A INPUT -p icmpv6 --icmpv6-type destination-unreachable -j ACCEPT
# Parameter Problem (Type 4)
ip6tables -A INPUT -p icmpv6 --icmpv6-type parameter-problem -j ACCEPT
# NDP (Neighbor Discovery) — для работы IPv6
ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-neighbor-solicit -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-neighbor-advert -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-router-advert \
    -m limit --limit 10/minute -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-router-solicit -j ACCEPT
# MLD (Type 130-132)
ip6tables -A INPUT -p icmpv6 --icmpv6-type 130 -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type 131 -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type 132 -j ACCEPT

# 4. Rate-limited Echo Request/Reply
ip6tables -A INPUT -p icmpv6 --icmpv6-type echo-request \
    -m limit --limit 5/second --limit-burst 10 -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type echo-reply \
    -m limit --limit 5/second --limit-burst 10 -j ACCEPT

# 5. Блокировать Redirect (Type 137) и остальной ICMPv6
ip6tables -A INPUT -p icmpv6 --icmpv6-type redirect -j DROP
ip6tables -A INPUT -p icmpv6 -j DROP
```

**Важно:** при применении этих правил всегда оставляйте SSH-сессию открытой или используйте таймер на откат:

```bash
# Защита от случайной потери доступа (автоматический откат через 60 сек)
(sleep 60 && iptables -F && ip6tables -F && echo "Firewall reset (rollback)") &
# Применяйте правила, проверяйте связь, затем убейте фоновой задачи:
# kill %1
```

**Валидация правил:**

```bash
# Проверка загруженных правил (iptables)
sudo iptables -L INPUT -n -v --line-numbers
sudo ip6tables -L INPUT -n -v --line-numbers

# Проверка загруженных правил (nftables)
sudo nft list table inet filter

# Проверка политики по умолчанию
sudo iptables -L INPUT | grep policy
# → Chain INPUT (policy DROP)  ← должна быть DROP

# Проверка, что критический ICMP разрешен
sudo iptables -L INPUT -n -v | grep "icmp"
sudo ip6tables -L INPUT -n -v | grep "ipv6-icmp"
```

### Защита от специфических атак

#### 1. ICMP Redirect Attack (MITM через перенаправление)

ICMP Redirect (Type 5 для IPv4, Type 137 для IPv6) используются для динамической оптимизации маршрутов, но также представляют серьезную угрозу безопасности. Злоумышленник может отправить поддельный Redirect, заставив хост направлять трафик через подконтрольный узел.

**Защита на уровне ядра Linux:**
```bash
# Отключение приема ICMP Redirect (для хостов, а не роутеров)
sysctl -w net.ipv4.conf.all.accept_redirects=0
sysctl -w net.ipv4.conf.default.accept_redirects=0
sysctl -w net.ipv6.conf.all.accept_redirects=0
sysctl -w net.ipv6.conf.default.accept_redirects=0

# Отключение отправки Redirect (хосты не должны их генерировать)
sysctl -w net.ipv4.conf.all.send_redirects=0
sysctl -w net.ipv4.conf.default.send_redirects=0
```

**Диагностика подозрительных Redirect:**
```bash
# Захват всех ICMP Redirect в реальном времени
sudo tcpdump -i eth0 -nn 'icmp[0] == 5'
# → IP 10.0.0.1 > 10.0.0.5: ICMP redirect, length 32

# Проверка таблицы маршрутизации на host-маршруты (установленные через Redirect)
ip route show | grep 'proto redirect\|proto 2'

# Очистка кэша маршрутов и Redirect
sudo ip route flush cache
```

Подробнее: [ICMP Redirect](./icmp_redirect.md).

#### 2. Smurf Attack (Усиление через широковещательный пинг)

Отправка Echo Request на широковещательный адрес сети с подменой IP-адреса источника на адрес жертвы. Жертва заваливается ответами от всей сети.

**Защита:**
```bash
# Запрет ответа на широковещательные ping запросы
sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=1

# Bloquer broadcast/multicast ping через iptables
iptables -A INPUT -d 255.255.255.255 -j DROP
iptables -A INPUT -d 224.0.0.0/4 -j DROP
```

#### 3. ICMP Flood (Переполнение канала ICMP)

Массированная отправка ICMP Echo Request для перегрузки канала или CPU.

**Защита через rate limiting:**
```bash
# sysctl: общий rate limit для всех ICMP сообщений
sysctl -w net.ipv4.icmp_ratelimit=100    # 100 сообщений/сек
# Маска: 880 = 0x370 (типы 4, 5, 6, 7, 8, 9 — Source Quench, Redirect, Echo Request и др.)
sysctl -w net.ipv4.icmp_ratelimit_mask=880

# iptables: строгий rate limit только на Echo
iptables -A INPUT -p icmp --icmp-type echo-request \
    -m limit --limit 3/second --limit-burst 5 -j ACCEPT
iptables -A INPUT -p icmp --icmp-type echo-request -j DROP

# nftables: аналогичный подход
nft add rule inet filter input icmp type echo-request \
    limit rate 3/second burst 5 packets accept
```

#### 4. ICMP Exfiltration и Tunneling

Данные кодируются в поле `Data` Echo Request/Reply и exfiltrируются через ICMP для обхода брандмауэров. Трафик выглядит как обычный ping.

**Механизм атаки:**
1. Данные кодируются в Base64 или hex и помещаются в поле `Data` ICMP Echo Request.
2. Запросы отправляются к controlled-узлу (например, через DNS, указанный в ICMP опциях).
3. Управляющий сервер отвечает ICMP Echo Reply с закодированными данными.
4. Поток данных прячется в обычном ping-трафике.

**Защита:**

*   **Ограничение размера пакета:** заблокировать аномально большие Echo Request/Reply (стандартный размер данных = 56 байт).
    ```bash
    # iptables: блокировка echo-request с размером данных > 128 байт
    iptables -A INPUT -p icmp --icmp-type echo-request -m length --length 128: -j DROP
    
    # nftables: аналогичное правило
    nft add rule inet filter input icmp type echo-request ip length > 128 drop
    ```

*   **Ограничение частоты:** допустим максимум 5 запросов/сек.
    ```bash
    iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 5/second --limit-burst 10 -j ACCEPT
    iptables -A INPUT -p icmp --icmp-type echo-request -j DROP
    ```

*   **DPI (Deep Packet Inspection):** анализ структуры поля данных на нестандартные паттерны.
    ```bash
    # Захват аномальных ICMP пакетов для анализа
    sudo tcpdump -i eth0 'icmp and greater 500' -nn
    
    # Анализ паттернов в payload
    sudo tcpdump -i eth0 'icmp and icmp[0] == 8' -X -nn
    ```

*   **Мониторинг аномалий:** использовать SIEM/Suricata для обнаружения аномального количества ICMP с нестандартными данными.

#### 5. Ping of Death (Историческая)

Отправка специально сформированного пакета или фрагментов, размер которых превышает 65535 байт при сборке. Это вызывало переполнение буфера в старых стеках TCP/IP. Современные ОС устойчивы к этой атаке, но защита рекомендуется на старом оборудовании.

**Защита:**
```bash
# Ограничение размера входящих пакетов на уровне файрвола
iptables -A INPUT -p icmp --icmp-type echo-request -m length --length 65535: -j DROP
```

#### 6. OS Fingerprinting (Разведка через ICMP)

Разные ОС по-разному формируют ICMP-ответы (TTL, размер данных, интервалы, флаги). Злоумышленники используют это для определения типа ОС и поиска целей.

| Параметр | Linux | Windows | Cisco/Juniper |
| :--- | :--- | :--- | :--- |
| **Начальный TTL** | 64 | 128 | 255 |
| **Размер ответа** | 84B (56B данных) | 84B (56B данных) | 84B |
| **ICMP ID в Echo Reply** | = PID отправителя | фиксированный | = ID запроса |
| **Временные интервалы** | точные, ровные | с jitter | с jitter |

**Защита:** ограничьте информацию, предоставляемую в ответах; используйте rate limiting и BPF-фильтры для нормализации ответов.

### Мониторинг ICMP-трафика и аномалий

Проактивный мониторинг ICMP-сообщений позволяет обнаружить атаки и проблемы сети до их критического ухудшения.

#### tcpdump: захват и анализ ICMP-трафика

```bash
# 1. Захват всех ICMP-сообщений с фильтрацией по типу
# Type 8 = Echo Request (ping запрос)
sudo tcpdump -i eth0 'icmp[0] == 8' -nn
# → IP 10.0.0.5 > 8.8.8.8: ICMP echo request, id 1234, seq 1, length 64

# Type 11 = Time Exceeded (traceroute)
sudo tcpdump -i eth0 'icmp[0] == 11' -nn

# Type 3 = Destination Unreachable (PMTUD, port unreachable)
sudo tcpdump -i eth0 'icmp[0] == 3' -nn

# Type 5 = Redirect (подозрительно!)
sudo tcpdump -i eth0 'icmp[0] == 5' -nn

# ICMPv6 аналогично (isp6[0] вместо icmp[0])
sudo tcpdump -i eth0 'icmp6 and icmp6[0] == 2' -nn  # Packet Too Big
sudo tcpdump -i eth0 'icmp6 and icmp6[0] == 137' -nn  # Redirect
```

```bash
# 2. Поиск аномально больших Echo Request (возможный exfiltration)
sudo tcpdump -i eth0 'icmp and icmp[0] == 8 and greater 1000' -nn

# 3. Поиск ICMP Flood (большое количество Echo Request за короткий промежуток)
sudo tcpdump -i eth0 'icmp and icmp[0] == 8' -nn | stdbuf -oL wc -l
# Подсчитывает запросы в секунду; если >100 — вероятно злоупотребление

# 4. Анализ паттернов данных (поиск туннелирования)
# Статусные коды в payload могут указывать на скрытую передачу данных
sudo tcpdump -i eth0 'icmp and icmp[0] == 8' -X -nn | head -20
# -X выводит payload в hex+ASCII

# 5. Захват с ограничением по времени и размеру
sudo tcpdump -i eth0 -c 100 -W 1 -w /tmp/icmp_capture.pcap 'icmp'
# -c 100: максимум 100 пакетов
# -W 1: один файл вывода
# -w: сохранить в pcap для дальнейшего анализа в Wireshark
```

#### Статистика ICMP из ядра Linux

```bash
# Стандартная статистика ICMP (IPv4)
cat /proc/net/snmp | grep Icmp
# → Icmp:  InMsgs  InErrors  InDestUnreachs  InTimeExcds  InEchoReps  ...
#   12345   0       3             1             1000
#
# InMsgs      — общее количество полученных ICMP-сообщений
# InErrors    — количество с ошибками контрольной суммы
# InDestUnreachs — Destination Unreachable (PMTUD, port closed)
# InTimeExcds  — Time Exceeded (traceroute)
# InEchos     — Echo Request получено
# InEchoReps  — Echo Reply получено

# Расширенная статистика (современная альтернатива netstat -s)
nstat -az | grep -E 'Icmp|Icmp6'
# → Icmp: InMsgs  12345
# → Icmp: InErrors  0
# → Icmp6: OutMsgs  678

# Анализ динамики: выполняем каждые 5 секунд
watch -n 5 'cat /proc/net/snmp | grep Icmp'

# Статистика для IPv6
cat /proc/net/snmp6 | grep -i icmp6
# → Icmp6InMsgs  Icmp6InErrors  Icmp6InPktTooBigs  Icmp6InTimeExcds  ...
```

#### Мониторинг с использованием nstat и sar

```bash
# Использование nstat для построения графиков
nstat -az -y second -c 60 | grep -E 'Icmp:|Icmp6:'
# Собирает статистику каждую секунду в течение 60 секунд

# Использование sar для долгосрочного мониторинга
sar -n DEV 1 10   # сетевые интерфейсы
sar -q            # загрузка системы (для корреляции с ICMP flood)
```

#### Интеграция с SIEM и IDS/IPS

Для production-сред нужно настраивать централизованный сбор и анализ ICMP-логов:

```bash
# Настройка удаленного syslog для ICMP-событий (iptables LOG target)
iptables -A INPUT -p icmp --icmp-type echo-request \
    -m limit --limit 5/minute -j LOG --log-prefix "ICMP_PING: " --log-level 4

# В rsyslog отправляем ICMP-события на SIEM
# /etc/rsyslog.d/30-icmp.conf:
# :msg, contains, "ICMP_PING" @@siem.example.com:514

# Suricata rule для обнаружения ICMP exfiltration (high volume)
# alert icmp $HOME_NET any -> any any (
#   msg:"ICMP Possible Tunneling";
#   flow:established;
#   byte_test:1,>,100,0,relative;
#   threshold:type threshold, track by_src, count 100, seconds 60;
#   classtype:policy-violation; sid:900001; rev:1;
# )
```

Если `ping` проходит, а `curl`, `ssh` или передача файлов виснут — это классический признак **ICMP Black Hole** (проблема PMTUD).

**Симптомы:**
- SSH работает (мелкие команды), но `SCP` или `cat` большого файла «вешают» сессию.
- Веб-страницы открываются частично (без картинок) или HTTPS виснет на обмене сертификатами.
- POST-запросы API с большими данными уходят в таймаут.

**Инструменты диагностики:**
```bash
# 1. Поиск узкого места в MTU (Path MTU Discovery)
tracepath -n google.com

# 2. Ручная проверка с запретом фрагментации (DF-бит)
# Если 1472 не проходит, уменьшайте размер, пока не получите ответ.
ping -s 1472 -M do 8.8.8.8

# 3. Захват SYN-пакетов для анализа MSS (Maximum Segment Size)
sudo tcpdump -i <interface> 'tcp[tcpflags] & tcp-syn != 0' -v
```

Подробный разбор причин и способов решения (MSS Clamping): **[MTU, PMTUD и диагностика в VPN](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)**.

### ICMP в Cloud-окружениях (AWS, Azure, GCP)

В облачных провайдерах ICMP часто частично или полностью блокируется на уровне Security Groups (SG) и Network ACLs. Это приводит к проблемам с диагностикой и PMTUD.

#### AWS (EC2)

```bash
# Security Group: разрешить All ICMP (тип 8, 11, 3) для диагностики
# В GUI AWS Console:
# SG Rules → Inbound Rules → Add Rule:
#   Type: All ICMP - IPv4
#   Protocol: icmp
#   Port Range: N/A
#   Source: 0.0.0.0/0 (или конкретная подсеть)

# Через AWS CLI:
aws ec2 authorize-security-group-ingress \
    --group-id sg-xxxxxxxx \
    --protocol icmp \
    --port -1 \
    --cidr 10.0.0.0/8

# Network ACL: по умолчанию блокирует весь ICMP
# Проверить NACL:
aws ec2 describe-network-acls --filters "Name=vpc-id,Values=vpc-xxxxxxxx"

# Диагностика в AWS:
# 1. VPC Reachability Analyzer:
#    AWS Console → VPC → Reachability Analyzer → Create
#    Source: ваш EC2, Destination: 8.8.8.8, Protocol: ICMP
```

**Критические правила для SG (по умолчанию):**
| Тип ICMP | Code | Зачем | Разрешить? |
| :--- | :--- | :--- | :--- |
| **8** | 0 | Echo Request (ping) | Да (ограничить source) |
| **0** | 0 | Echo Reply | Да |
| **3** | 4 | Fragmentation Needed | **Да** (PMTUD!) |
| **3** | 3 | Port Unreachable | Да |
| **11** | 0 | Time Exceeded | Да (traceroute) |
| **11** | 1 | Fragment Reassembly Timeout | Опционально |

#### Microsoft Azure

```bash
# Network Security Group (NSG) — по умолчанию блокирует ICMP
# Через Azure CLI:
az network nsg rule create \
    --resource-group myRG \
    --nsg-name myNSG \
    --name AllowICMP \
    --protocol Icmp \
    --priority 1010 \
    --direction Inbound \
    --access Allow \
    --source-address-prefixes 10.0.0.0/8 \
    --source-port-ranges '*' \
    --destination-address-prefixes '*' \
    --destination-port-ranges '*'

# Проверка:
az network nsg rule list --resource-group myRG --nsg-name myNSG -o table
```

#### GCP (Google Cloud)

```bash
# VPC Firewall Rules
gcloud compute firewall-rules create allow-icmp \
    --network default \
    --allow icmp \
    --source-ranges 10.0.0.0/8

# Проверка:
gcloud compute firewall-rules list --filter="icmp"
```

#### Проверка ICMP в cloud

```bash
# Проверка доступности в cloud (если ICMP заблокирован)
# Использовать альтернативы: TCP-ping на порт 22/443
nc -zv 10.0.0.5 22
curl -s -o /dev/null -w "%{http_code}" http://10.0.0.5:80

# Проверка PMTUD в cloud (ICMP PTB может быть заблокирован)
# Используй mtr с TCP-режимом:
mtr -T -P 443 -n -c 10 10.0.0.5
```

### ICMP в Kubernetes

В Kubernetes сетевая политика (NetworkPolicy) управляет трафиком между подами. ICMP требует специального подхода:

```yaml
# NetworkPolicy: разрешить только необходимый ICMP между подами
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-monitoring-icmp
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: web
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      protocol: ICMP
      icmp:
        type: 8  # Echo Request
        code: 0
```

**С CNI-плагинами:**
- **Calico:** поддерживает GlobalNetworkPolicy с дополнительными возможностями для ICMP.
- **Cilium (eBPF):** может фильтровать ICMP на уровне L3/L4 с глубокой инспекцией.

```bash
# Проверка, работает ли ICMP внутри пода
kubectl exec -it my-pod -n production -- ping -c 3 8.8.8.8

# Если ping не работает:
# 1. Проверить NetworkPolicy в namespace
kubectl get networkpolicy -n production

# 2. Проверить, включена ли поддержка ICMP в CNI
kubectl exec -it my-pod -n production -- /bin/sh -c "cat /proc/sys/net/ipv4/ping_group_range"

# 3. Отключить ICMP Redirect для bridge (Docker desktop / kind)
kubectl debug my-pod -n production --image=busybox -- ping -c 3 8.8.8.8
```

### Таблица устранения неполадок

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `* * *` на всех хопах traceroute, но `nc` работает | ICMP полностью заблокирован | `traceroute -T -p 443 <ip>` (TCP-режим) | Разрешить ICMP Type 11 или использовать TCP-трассировку |
| 100% потерь на конкретных хопах, 0% на цели | ICMP Rate Limiting на роутере | `mtr -n -c 20 <dst>` — потери только на промежуточных | Это норма; анализировать конечный RTT и потери |
| SSH работает, но `SCP`/`curl` висит на больших файлах | PMTU Black Hole (ICMP Type 3 Code 4 заблокирован) | `ping -M do -s 1472 <dst>` + `tcpdump 'icmp[0]==3 and icmp[1]==4'` | Разрешить ICMP PTB; настроить MSS Clamping |
| Подозрительные ICMP Redirect в tcpdump | MITM-атака или misconfigured router | `sudo tcpdump -i eth0 'icmp[0]==5'` + `ip route show \| grep redirect` | Отключить прием Redirect: `sysctl -w net.ipv4.conf.all.accept_redirects=0` |
| Аномально высокая нагрузка на CPU при ping | ICMP Flood атака | `cat /proc/net/snmp \| grep Icmp` + `sudo tcpdump -i eth0 'icmp and icmp[0]==8' \| wc -l` | Rate limiting через iptables/nftables |
| Большие ICMP пакеты (>500 байт) в обычном ping | Возможный ICMP tunneling | `sudo tcpdump -i eth0 'icmp and greater 500' -nn` | DPI; ограничение размера пакета на firewall` |
### Жёсткая настройка Linux (Hardening)

В современных системах рекомендуется жёстко ограничивать прием ICMP-сообщений. Полный набор `sysctl`-настроек для базовой защиты. Сохраняйте в `/etc/sysctl.d/99-network-hardening.conf`:

```bash
# === /etc/sysctl.d/99-network-hardening.conf ===

# Защита от IP Spoofing (Strict Reverse Path Filtering)
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.default.rp_filter=1

# Отключение ICMP Redirect (защита от MITM)
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.default.accept_redirects=0
net.ipv6.conf.all.accept_redirects=0
net.ipv6.conf.default.accept_redirects=0

# Запрет на отправку Redirect (для хостов, а не роутеров)
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0

# Защита от ICMP Flood и Smurf Attack
net.ipv4.icmp_echo_ignore_broadcasts=1
net.ipv4.icmp_ratelimit=100
net.ipv4.icmp_ratelimit_mask=880

# Отключение Source Routing (источниковый маршрут)
net.ipv4.conf.all.accept_source_route=0
net.ipv4.conf.default.accept_source_route=0
net.ipv6.conf.all.accept_source_route=0

# Защита от немаршрутизируемых адресов
net.ipv4.conf.all.route_localnet=0
```

```bash
# Применить настройки
sudo sysctl --system

# Проверить текущие значения
sysctl net.ipv4.icmp_ratelimit
sysctl net.ipv4.icmp_echo_ignore_broadcasts
sysctl net.ipv4.conf.all.accept_redirects
```

### Тонкая настройка ICMP Rate Limiting

Стандартные значения `icmp_ratelimit` (1000/сек) часто слишком агрессивны для highload-серверов или слишком мягки для border-router. Вот рекомендации по тюнингу:

| Тип сервера | icmp_ratelimit | icmp_ratelimit_mask | Комментарий |
| :--- | :--- | :--- | :--- |
| **Web-сервер (публичный)** | 100 | 880 | Только Echo Request/Reply + базировать на маске |
| **Внутренний сервер** | 1000 | 0 | Полный rate limiting только для Echo |
| **Border Router / Core** | 50 | 880 | Очень строгий лимит для защиты Control Plane |
| **Хост без ping** | 1 | 0 | Минимум — только критические ICMP (PMTUD, traceroute) |

```bash
# Пример для публичного веб-сервера:
# Разрешить 100 Echo/sec с burst до 20, остальной ICMP без лимита
sysctl -w net.ipv4.icmp_ratelimit=100
sysctl -w net.ipv4.icmp_ratelimit_mask=880

# Проверка эффективности:
# Симуляция flood через другой хост:
# sudo hping3 -1 -c 1000 -i u1 8.8.8.8
# Затем проверить статистику:
cat /proc/net/snmp | grep Icmp
# Обратите внимание на рост InErrors — это означает срабатывание rate limiting
```

### ICMP и stateful firewall (conntrack)

Одна из самых частых ошибок в продакшене — использование политики `policy drop` вместе с правилом `-m conntrack --ctstate ESTABLISHED,RELATED accept` без явного разрешения критических ICMP-сообщений.

**Проблема:** ядро Linux (nf_conntrack) **не отслеживает ICMP** как stateful-соединение. ICMP-error-сообщения (Type 3, 11, 12) не матчатся по `ESTABLISHED,RELATED`, потому что у ICMP нет портов и 4-кортежа `(src_ip, src_port, dst_ip, dst_port)`.

**Результат:** при `policy drop` ICMP-error-пакеты отбрасываются, что ломает PMTUD и диагностику.

```bash
# Правильная конфигурация INPUT chain:
# 1. Разрешить loopback
iptables -A INPUT -i lo -j ACCEPT

# 2. Разрешить установленные соединения
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 3. Явно разрешить критический ICMP (не матчится по conntrack!)
iptables -A INPUT -p icmp --icmp-type destination-unreachable -j ACCEPT
iptables -A INPUT -p icmp --icmp-type time-exceeded -j ACCEPT
iptables -A INPUT -p icmp --icmp-type parameter-problem -j ACCEPT
iptables -A INPUT -p icmp --icmp-type fragmentation-needed -j ACCEPT

# 4. Rate-limited Echo
iptables -A INPUT -p icmp --icmp-type echo-request \
    -m limit --limit 5/second --limit-burst 10 -j ACCEPT

# 5. Все остальное дропается
iptables -A INPUT -j DROP
```

**Проверка:**

```bash
# Создать сценарий PMTUD Black Hole:
# 1. Включить strict policy drop
iptables -P INPUT DROP
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -i lo -j ACCEPT

# 2. БЕЗ явного разрешения ICMP Type 3 Code 4:
# → SCP больших файлов зависнет

# 3. Добавить правило:
iptables -A INPUT -p icmp --icmp-type fragmentation-needed -j ACCEPT
# → SCP заработает

# Статистика conntrack:
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max
```

### Логирование ICMP через auditd и rsyslog

Для compliance и расследования инцидентов нужно централизованно собирать события ICMP.

**auditd правила:**

```bash
# Логирование всех ICMP-системных вызовов
sudo auditctl -a exit,always -S socket -F icmp_type=8  # Echo Request
sudo auditctl -a exit,always -S socket -F icmp_type=3  # Destination Unreachable

# Просмотр логов
sudo ausearch -i -sc socket -f icmp
# → type=SYSCALL msg=audit(1700000000.000:123): arch=c000003e syscall=44 ...
```

**rsyslog правила:**

```bash
# /etc/rsyslog.d/30-icmp.conf

# ICMP Flood detection (если используется iptables LOG target)
:msg, contains, "ICMP_PING" @@siem.example.com:514
:msg, contains, "ICMP_FLOOD" @@siem.example.com:514

# Локальное сохранение
if $programname == "kernel" and $msg contains "ICMP" then {
    action(type="omfile" file="/var/log/icmp.log")
    stop
}
```

### ICMP и eBPF/XDP

eBPF/XDP позволяют обрабатывать ICMP-пакеты в пространстве ядра до полного стека TCP/IP, что критично для DDoS-mitigation и high-performance мониторинга.

**Cilium (eBPF-based CNI):**

Cilium перехватывает ICMP на уровне XDP/eBPF и может:
- Отбрасывать ICMP Redirect (Type 5) до обработки стеком
- Ведсти статистику ICMP без участия userspace
- Применять rate limiting через BPF-программы

```bash
# Проверка, что Cilium обрабатывает ICMP через eBPF:
sudo bpftool prog list | grep -i icmp
# → 1234: cgroup_skb  tag abcdef1234567890

# Cilium metrics
cilium metrics list | grep -i icmp
# → icmp_total{type="echo_request"} 1000
# → icmp_total{type="echo_reply"} 980
# → icmp_drop_total{reason="rate_limit"} 20
```

**Пользовательские BPF-программы для ICMP:**

```c
// Пример XDP-программы: отбрасывать ICMP Redirect
SEC("xdp")
int icmp_redirect_filter(struct xdp_md *ctx) {
    struct ethhdr *eth = bpf_hdr_start(ctx);
    struct iphdr *ip = (void *)(eth + 1);
    
    if (eth->h_proto != bpf_htons(ETH_P_IP))
        return XDP_PASS;
    
    if (ip->protocol != IPPROTO_ICMP)
        return XDP_PASS;
    
    struct icmphdr *icmp = (void *)(ip + 1);
    if (icmp->type == ICMP_REDIRECT)
        return XDP_DROP;  // Блокируем Redirect на уровне XDP
    
    return XDP_PASS;
}
```

**Traffic Control (tc) с BPF:**

```bash
# Классификация ICMP-трафика через tc-bpf
sudo tc qdisc add dev eth0 clsact
sudo tc filter add dev eth0 ingress bpf da obj icmp_filter.o sec classifier
```

## Дополнительная информация

*   **[ICMP: Диагностика и безопасность](./icmp_diagnostics_security.md)** — firewall-правила.
*   **[ICMP и namespaces/cgroups](./icmp_namespaces_cgroups.md)** — изоляция ICMP.
*   **[ICMP: Мониторинг в продакшене](./icmp_monitoring.md)** — метрики и алертинг.
*   **[nftables](../../../Linux/Networking/Settings/tools/nftables/)** — современный firewall.
*   **[Hardening сетевого стека Linux](../../../Linux/Networking/Security/network_hardening.md)** — сводный sysctl-референс для hardening.
*   **[Cilium документация](https://docs.cilium.io/)** — eBPF-based networking.

