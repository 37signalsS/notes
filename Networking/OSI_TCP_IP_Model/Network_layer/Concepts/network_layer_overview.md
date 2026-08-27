# Сетевой уровень (L3) — Обзор

## Определения

**Сетевой уровень (Network Layer, L3)** — третий уровень эталонной модели **OSI**, отвечающий за объединение разнородных сетевых сегментов в единую **составную сеть (internetwork)**. Его главная задача — обеспечить сквозную доставку данных между любыми двумя узлами глобальной сети, независимо от их физического расположения и используемых технологий канального уровня.

**PDU (Protocol Data Unit):** Пакет (Packet). Логическая единица данных L3. Минимальный заголовок IPv4 — 20 байт (60 байт с опциями), IPv6 — фиксированные 40 байт + цепочка Extension Headers.

**Адресация:** Логическая иерархическая адресация (IPv4 — 32 бита, IPv6 — 128 бит). Иерархичность позволяет 수행ить **Longest Prefix Match (LPM)** — ключевой алгоритм маршрутизации. Подробнее: **[IP-адресация — Обзор](../../../Protocols/IP_addressing/ip_overview.md)**.

**Ключевой принцип:** Сетевой уровень абстрагирует вышестоящие слои от физической топологии. Если L2 работает с «соседями по проводу» (MAC-адресами одного сегмента), то L3 работает со всей сетью как с единым целым, используя логические IP-адреса.

## Связь с соседними уровнями

```text
L4 (Транспортный) ← TCP/UDP: порты назначения → IP-протокол в заголовке L3
       ↕
L3 (Сетевой)      ← IPv4/IPv6: IP-адресация, маршрутизация, QoS, IPsec
       ↕
L2 (Канальный)    ← Ethernet: ARP (IPv4) / NDP (IPv6) резолвят next-hop → MAC
       ↕
L1 (Физический)   ← Кабель/эфир: биты; MTU определяет макс. размер L3-пакета
```

**Взаимодействие уровня L3 с соседними:**

| Уровень | Взаимодействие с L3 |
| :--- | :--- |
| **L4 → L3** | TCP/UDP передают сегмент с указанием IP назначения; L3 определяет маршрут и инкапсулирует в IP-пакет |
| **L3 → L4** | При приёме L3 извлекает payload и передаёт в TCP/UDP по номеру протокола в заголовке IP (Protocol field) |
| **L2 → L3** | ARP/NDP резолвят IP next-hop в MAC-адрес; Ethernet-кадр передаёт IP-пакет в L3 |
| **L3 → L2** | L3 инкапсулирует IP-пакет в L2-кадр, подставляя MAC-адрес следующего хопа |

### Инкапсуляция

```text
L4 (TCP/UDP):
[Src Port][Dst Port][Seq][Ack][Flags][Window]  ← 20-60 байт (TCP) / 8 байт (UDP)

L3 (IPv4):
[Ethernet][IPv4(20-60B)][TCP/UDP][Data]
           Src(32bit) Dst(32bit) TTL Protocol Checksum

L3 (IPv6):
[Ethernet][IPv6(40B)][Ext.Hdr...][TCP/UDP][Data]
           Src(128bit) Dst(128bit) HopLimit NextHeader
```

**Сравнение заголовков IPv4 vs IPv6:**

| Поле | IPv4 | IPv6 |
| :--- | :--- | :--- |
| Длина заголовка | 20-60 байт (переменная) | 40 байт (фиксированная) |
| Фрагментация | На промежуточных маршрутизаторах | Только на источнике (PMTUD) |
| Checksum | Есть (L3) | Нет (доверие L2/L4) |
| TTL / Hop Limit | TTL (8 бит) | Hop Limit (8 бит, то же поле) |
| QoS | TOS (8 бит) | Traffic Class (8 бит) + Flow Label (20 бит) |
| Адрес назначения | 32 бита | 128 бит |
| Опции | Внутри заголовка (до 40 байт) | Extension Headers (цепочка) |
| Аутентификация | Опционально (IPsec AH) | Встроенная поддержка (RFC 6434) |

**PDU L3:** Пакет (Packet). Заголовок IP: 20 байт (min) — 60 байт (max с опциями). IPv6: фиксированный 40-байтный заголовок.

## Базовые концепции

### Зачем нужен Сетевой уровень (L3 vs L2)

[Канальный уровень (L2)](../../data_link_layer.md) ограничен пределами одного широковещательного домена. Для глобальных коммуникаций он непригоден по ряду причин:
1.  **Отсутствие иерархии:** MAC-адреса плоские и не содержат географической или топологической информации. Маршрутизация на основе MAC потребовала бы хранения таблиц со всеми устройствами мира в каждом коммутаторе.
2.  **Широковещательные штормы:** L2-механизмы (ARP, Flooding) в гигантских сетях привели бы к моментальной перегрузке каналов служебным трафиком.
3.  **Несовместимость сред:** L3 выступает «универсальным переводчиком», позволяя передать данные между сетями с разными технологиями L2 (например, Ethernet ↔ Wi-Fi ↔ MPLS).
4.  **Эффективное использование путей:** В отличие от L2, где петли запрещены (STP), L3 поддерживает многопутевую передачу (**ECMP — Equal-Cost Multi-Path**).

### Архитектура сетевого устройства: Control Plane и Data Plane

В современных маршрутизаторах и SDN-системах выделяют две плоскости:
- **Control Plane (Плоскость управления):** «Мозг» устройства. Здесь работают протоколы маршрутизации (BGP, OSPF), строятся таблицы маршрутизации (RIB).
- **Data Plane / Forwarding Plane (Плоскость передачи):** «Мышцы» устройства. Здесь происходит реальная пересылка пакетов на основе таблицы пересылки (FIB). В высокопроизводительных системах эта часть реализуется аппаратно (ASIC) или через **eBPF/XDP**.

## Ключевые функции и механизмы

### 1. Маршрутизация (Routing)
Определение оптимального пути от источника к назначению. Маршрутизаторы принимают решения на основе IP-адреса назначения и принципа **Longest Prefix Match (LPM)** — выбора наиболее специфичного маршрута (с самой длинной маской).

**Процесс маршрутизации (LPM):**
```
1. Получение пакета с dst=192.168.1.100
2. Поиск в FIB: какой маршрут имеет самое длинное совпадение префикса?
   - 192.168.0.0/16  → eth0 (match /16)
   - 192.168.1.0/24  → eth1 (match /24) ← побеждает
3. Отправка пакета через eth1 к next-hop
```

**Типы маршрутизации:**

| Тип | Описание | Пример |
| :--- | :--- | :--- |
| **Статическая** | Администратор задаёт маршрут вручную | `ip route add 10.0.0.0/8 via 192.168.1.1` |
| **Динамическая** | Протоколы обмениваются информацией автоматически | OSPF, BGP, IS-IS, EIGRP |
| **Policy-Based (PBR)** | Маршрутизация по меткам, портам, source IP | `ip rule add fwmark 1 table 100` |

**Административная дистанция (AD)** — метрика «доверия» к источнику:

| Источник | AD |
| :--- | :--- |
| Connected | 0 |
| Static | 1 |
| eBGP | 20 |
| OSPF | 110 |
| iBGP | 200 |

Подробнее: **[Протоколы и оборудование L3](../routing_protocols_equipment.md)**, **[Сценарии маршрутизации](./routing_scenarios.md)**.

**Anycast:** Механизм, при котором один IP-адрес принадлежит группе серверов. Пакет доставляется «ближайшему» узлу согласно метрикам маршрутизации (широко используется в DNS, CDN и Kubernetes Ingress). Пример: `2001:db8::1` announced from 3 дата-центров; BGP выбирает closest по AS-path.

**ECMP (Equal-Cost Multi-Path):** Когда несколько маршрутов имеют одинаковую метрику, трафик распределяется между ними по хешу потока (5-tuple: src/dst IP, src/dst port, protocol). Позволяет увеличить пропускную способность и обеспечить отказоустойчивость.

### 2. Фрагментация и сборка
Если размер пакета превышает [MTU](../mtu_and_vpn.md) следующего сегмента, происходит разделение пакета.

**Фрагментация IPv4 vs IPv6:**

| Аспект | IPv4 | IPv6 |
| :--- | :--- | :--- |
| Кто фрагментирует | Маршрутизаторы И источник | Только источник |
| MTU discovery | ICMP PTB + PMTUD | ICMPv6 PTB (Type 2) + PMTUD |
| Минимальный MTU | 576 байт | 1280 байт |
| Offset фрагмента | 8-байтные блоки | 8-байтные блоки |
| Identification | 16 бит (уникальный) | 32 бит (Flow Label + Fragment Offset) |

**Path MTU Discovery (PMTUD, RFC 1191):**
```
1. Отправитель шлёт пакет с DF=1 (Don't Fragment) и размером = PMTU
2. Если MTU на промежуточном маршрутизаторе меньше:
   - IPv4: маршрутизатор отвечает ICMP Type 3 Code 4 (Fragmentation Needed)
   - IPv6: маршрутизатор отвечает ICMPv6 Type 2 (Packet Too Big)
3. Отправитель снижает размер пакета и повторяет
```

**Проблема PMTU Black Hole:** Если файрвол блокирует ICMP Type 3/4 (IPv4) или ICMPv6 Type 2 (IPv6), PMTUD ломается. Симптом: мелкие пакеты (DNS, SSH) проходят, большие (HTTP, SCP) зависают.

**Решение:** **PLPMTUD (RFC 8899)** — PMTU Discovery без ICMP, с помощью пробных пакетов (IPv4 DF=1, IPv6 Fragment Header). Работает на уровне TCP/QUIC.

Подробнее: **[Фрагментация IP-пакетов](../Protocols/ip_fragmentation.md)**, **[MTU и VPN](../mtu_and_vpn.md)**.

### 3. Управление временем жизни (TTL / Hop Limit)
Счетчик в заголовке, предотвращающий вечное зацикливание пакетов. При каждом прохождении через маршрутизатор значение уменьшается на 1. При `TTL=0` пакет отбрасывается с отправкой ICMP-сообщения `Time Exceeded` (Type 11 в IPv4, Type 3 в ICMPv6).

**Типичные значения TTL:**

| Приложение | TTL | Пример |
| :--- | :--- | :--- |
| Linux (по умолчанию) | 64 | `sysctl net.ipv4.ip_default_ttl` |
| Windows | 128 | `netsh interface ipv4 show global` |
| macOS / iOS | 254 | `sysctl net.inet.ip.ttl` |
| Router (по умолчанию) | 255 | `show ip protocols` |

**traceroute** использует TTL: отправляет пакеты с TTL=1, TTL=2, ..., читая ICMP Time Exceeded от каждого маршрутизатора.

### 4. Качество обслуживания (QoS)
Маркировка трафика для обеспечения приоритетности (например, VoIP пакеты обрабатываются раньше HTTP).

**DiffServ (DSCP):** Поле в заголовке IP (6 бит), определяющее класс обслуживания пакета. Управляет очередью на каждом промежуточном маршрутизаторе.

| DSCP класс | Название | Назначение |
| :--- | :--- | :--- |
| 0 | BE (Best Effort) | Обычный трафик по умолчанию |
| 8 (CS1) | AF11 | Средний приоритет (видео, голос) |
| 16 (CS2) | AF21 | Сигнализация (SIP, BGP) |
| 24 (CS3) | AF31 | Важный трафик (управление сетью) |
| 32 (CS4) | AF41 | Высокий приоритет (real-time) |
| 40 (CS5) | EF (Expedited Forwarding) | Критичный: VoIP, видеоконференции |
| 48 (CS6) | CS6 | Сетевые протоколы (OSPF, BGP) |
| 56 (CS7) | CS7 | Инфраструктурный трафик |

**IP Precedence (TOS)** — устаревший 3-битовый механизм (IPv4). В современных сетях заменён DSCP.

### 5. ICMP — служебный протокол L3
**ICMP (Internet Control Message Protocol, RFC 792)** — служебный протокол, работающий поверх IP (Protocol 1 для IPv4, Protocol 58 для ICMPv6). Не передаёт данные пользовательских приложений, но критически важен для диагностики и управления сетью.

**Ключевые типы ICMP:**

| Тип | Название | Назначение |
| :--- | :--- | :--- |
| 0 | Echo Reply | Ответ на ping |
| 3 | Destination Unreachable | Пакет не доставлен (разные Code) |
| 5 | Redirect | Роутер перенаправляет хост на лучший маршрут |
| 8 | Echo Request | Запрос ping |
| 11 | Time Exceeded | TTL/Hop Limit = 0 |
| 12 | Parameter Problem | Ошибка в заголовке |

**ICMPv6 (RFC 4443)** — расширенная версия для IPv6. Включает:
- **NDP (Neighbor Discovery Protocol, RFC 4861):** замена ARP в IPv6. NS (Neighbor Solicitation) + NA (Neighbor Advertisement) для резолвинга MAC. RA (Router Advertisement) для SLAAC.
- **MLD (Multicast Listener Discovery):** управление многоадресной рассылкой (аналог IGMP для IPv6).

Подробнее: **[ICMP — Обзор](../../../Protocols/ICMP/icmp_overview.md)**.

### 6. ARP и NDP — резолвинг L3→L2
**ARP (Address Resolution Protocol, RFC 826)** — определение MAC-адреса по IP в пределах одного L2-сегмента. Работает через broadcast-запросы. Подробнее: **[ARP](../../../Protocols/arp.md)**.

**NDP (Neighbor Discovery Protocol, RFC 4861)** — аналог ARP для IPv6, но вместо broadcast использует multicast (solicited-node multicast). Включает: NS/NA (резолвинг), RS/RA (SLAAC), Redirect.

**Проблемы ARP/NDP:**
- **ARP Spoofing / NDP Poisoning:** злоумышленник отправляет фальшивые ARP/NDP-ответы для перехвата трафика (MitM).
- **Защита:** Dynamic ARP Inspection (DAI), SEND (RFC 3971 для NDP), Static ARP entries.

### 7. Безопасность (IPsec)
На сетевом уровне обеспечивается прозрачная для приложений защита данных. **IPsec** предоставляет аутентификацию, целостность и шифрование IP-пакетов.

**Режимы IPsec:**

| Режим | Описание | Использование |
| :--- | :--- | :--- |
| **Transport** | Шифрует только payload (L4-L7). Заголовок IP остаётся открытым. | End-to-end (хост↔хост) |
| **Tunnel** | Шифрует весь оригинальный IP-пакет, инкапсулируя в новый IP-заголовок. | VPN (site-to-site, remote access) |

**Протоколы IPsec:**
- **ESP (Encapsulating Security Payload, RFC 4303):** шифрование + аутентификация. Protocol 50 (IPv4) / Next Header 50 (IPv6).
- **AH (Authentication Header, RFC 4302):** только аутентификация (без шифрования). Редко используется.
- **IKEv2 (RFC 7296):** ключевой обмен и управление SA (Security Associations).

Подробнее: **[IPsec](../../../Tunnels/ipsec/ipsec.md)**.

### 8. Соседние протоколы — DHCP
**DHCP (Dynamic Host Configuration Protocol, RFC 2131)** — автоматическая конфигурация IP-адреса, маски, шлюза и DNS-серверов. Работает на L4 (UDP: 67/68), но конфигурирует L3-параметры.

**DHCPv6 (RFC 8415):** аналог для IPv6. Используется реже (SLAAC в IPv6 чаще), но необходим для stateful-конфигурации ( DNS-серверы, NTP).

Подробнее: **[DHCP — Обзор](../../../Protocols/DHCP/dhcp_overview.md)**.

## Современные технологии (2026+)

### SDN (Software Defined Networking)
Централизованное управление Control Plane через внешний контроллер. Позволяет динамически изменять топологию и политики маршрутизации через API (основа облачных VPC и CNI в Kubernetes).

**Ключевые компоненты:**
- **Southbound API:** OpenFlow, P4Runtime — связь контроллера с коммутаторами.
- **Northbound API:** REST/gRPC — связь контроллера с приложениями.
- **Control Plane:** Оптимальная маршрутизация вычисляется централизованно (ONOS, OpenDaylight).
- **Data Plane:**转发 на коммутаторах по таблицам, полученным от контроллера.

### VRF (Virtual Routing and Forwarding)
Технология виртуализации L3. Позволяет сосуществовать нескольким независимым таблицам маршрутизации на одном устройстве. Это обеспечивает полную изоляцию трафика (например, разделение сетей управления и данных).
- Подробнее: **[Практические сценарии маршрутизации](./routing_scenarios.md)**, **[VRF в Linux](../../../../Linux/Networking/vrf.md)**.

### Segment Routing (SRv6)
Концепция «маршрутизации от источника» для IPv6. Путь пакета задается списком идентификаторов (SID) в заголовке. Устраняет необходимость в протоколах распределения меток (LDP/RSVP-TE) и упрощает Traffic Engineering.
- Подробнее: **[SRv6](../../../Concepts/sdn/srv6.md)**.

### eBPF / XDP
Программируемая обработка пакетов на уровне ядра Linux:
- **XDP (eXpress Data Path):** обработка на уровне L2/L3 до попадания в основной стек ядра. Скорость: до 24 Mpps на одном ядре. Используется для DDoS-защиты, балансировки.
- **eBPF:** программирование в ядре без перекомпиляции. TC (Traffic Control), XDP, cgroup-ограничения.

### Overlay-сети (VXLAN, Geneve)
Создают виртуальные L2-сегменты поверх L3-инфраструктуры. Инкапсулируют оригинальные Ethernet-кадры в UDP-пакеты, что позволяет масштабировать L2-сегменты через L3-маршрутизаторы.
- **VXLAN (RFC 7348):** UDP-порт 4789. VNI (24 бита) = до 16M сегментов.
- **Geneve (RFC 8926):** более гибкий, поддерживает variable-length options.

## Диагностика и типичные сценарии

### Инструменты диагностики (Linux)

```bash
# === Просмотр адресов и интерфейсов ===
ip addr show                              # все интерфейсы
ip -4 addr show eth0                      # только IPv4
ip -6 addr show eth0                      # только IPv6
ip link show                              # статус L2-интерфейсов

# === Маршрутизация ===
ip route show                             # таблица маршрутизации (main)
ip route show table all                   # все таблицы (включая VRF)
ip route get 8.8.8.8                      # FIB-решение для конкретного IP
ip route get 8.8.8.8 from 10.0.0.1        # с указанием source (для PBR/ECMP)
ip -6 route show                          # таблица IPv6
ip rule show                              # RPDB (Policy Routing)

# === Соседи (ARP/NDP) ===
ip neigh show                             # ARP-таблица (IPv4)
ip -6 neigh show                          # NDP-таблица (IPv6)
ip neigh show dev eth0                    #.neighbors на конкретном интерфейсе

# === Связность ===
ping -c 3 <IP>                            # базовый тест
ping -M do -s 1472 <IP>                   # PMTUD test (IPv4)
ping -6 -M do -s 1432 <IP>               # PMTUD test (IPv6)
traceroute <IP>                           # трассировка пути
mtr <IP>                                 # мониторинг в реальном времени

# === Фрагментация и MTU ===
cat /proc/net/snmp | grep -E "Ip:|Ip6:"  # счётчики фрагментации
nstat -az | grep -E "IpFrag|IpReasm"     # расширенная статистика
ip -s link show eth0                      # счётчики ошибок на интерфейсе

# === Статистика и ошибки ===
nstat -az | grep -E "ICMP|Ip:|Tcp:"      # ICMP-счётчики, ошибки IP
cat /proc/net/snmp | head -5              # SNMP-счётчики
conntrack -L -p tcp                       # таблица состояний (если NF_conntrack)
```

### Диагностика Control Plane vs Data Plane

```bash
# === Проверка RIB vs FIB ===
ip route show                             # FIB (что видит ядро)
ip route show protocol bgp                # BGP-маршруты в RIB
ip route show protocol static             # Статические маршруты

# === Проверка Firewall-влияния ===
nft list ruleset | grep -E "ip saddr|ip6 saddr"  # правила фильтрации
conntrack -S                              # статистика conntrack

# === Проверка ECMP ===
ip route get 10.0.0.1                     # какой next-hop выбирается
ip route get 10.0.0.1 from 10.0.0.2      # может выбрать другой next-hop (ECMP)

# === Захват пакетов ===
tcpdump -i eth0 icmp -nn                 # ICMP-трафик
tcpdump -i eth0 "ip[2:2] > 1500"         # гигантские пакеты (>1500)
tcpdump -i eth0 "ip6" -nn                # IPv6-трафик
```

### Типичные проблемы и решения

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Асимметричный маршрут** | ping работает, TCP/UDP нет | `ip route get <dst> from <src>`, traceroute с обоих концов | Настроить rp_filter=0 (осторожно) или исправить маршрутизацию |
| **PMTU Black Hole** | Мелкие пакеты проходят, большие зависают | `ping -M do -s 1472 <dst>`, проверка ICMP Type 3/4 | Разрешить ICMP Type 3/4, настроить MSS Clamping, или PLPMTUD |
| **ARP/NDP Poisoning** | MitM, задержки, потеря пакетов | `arp -a`, `ip neigh show`, tcpdump ARP | DAI (Dynamic ARP Inspection), SEND, static entries |
| **Фрагментация** | Снижение Throughput, retransmission | `nstat -az | grep Frag`, tcpdump с фильтром `ip[6:2] & 0x2000` | Увеличить MTU, настроить MSS Clamping |
| **Routing Loop** | TTL=0 на промежуточном хопе, traceroute зацикливается | `traceroute <dst>`, `mtr <dst>` | Исправить маршрутизацию, добавить黑洞-маршрут |
| **ECMP Out-of-Order** | Высокий RTT, retransmit в TCP | `tcpdump -nn 'tcp[tcpflags] & (tcp-syn|tcp-fin) != 0'` | `sysctl net.ipv4.fib_multipath_hash_policy=1` |

## Проблемы и риски безопасности

| Атака | Описание | Защита |
| :--- | :--- | :--- |
| **IP Spoofing** | Подмена source IP для обхода ACL или MitM | uRPF (Unicast Reverse Path Filtering), BCP38, BCP84 |
| **Routing Hijack (BGP)** | Объявление чужих префиксов для перехвата трафика | RPKI (Resource Public Key Infrastructure), ROA, BGPsec |
| **Route Leak** | Рассылка маршрутов не в ту AS, вызывающая черные дыры | AS-Path filtering, Prefix Limits, IRR-based filters |
| **ICMP Redirect** | Роутер перенаправляет хост на «лучший» маршрут | `sysctl net.ipv4.conf.all.accept_redirects=0` |
| **ICMP Flood** | DoS через эхо-запросы | Rate limiting: `sysctl net.ipv4.icmp_echo_ignore_broadcasts=1` |
| **Smurf Attack** | Broadcast-эхо с подменным source IP | Отключение directed broadcast на interfaces |
| **Fragmentation Attack** | Оvert фрагментation для обхода IDS/Firewall | `sysctl net.ipv4.ipfrag_high_thresh` (ограничение памяти) |

**Рекомендуемые sysctl для базовой защиты L3:**

```bash
# Защита от IP Spoofing (rp_filter)
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.default.rp_filter=1

# Отключение ICMP Redirect (защита от MitM)
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.all.send_redirects=0

# Защита от ICMP Flood
net.ipv4.icmp_echo_ignore_broadcasts=1
net.ipv4.icmp_ratelimit=100

# Защита от Source Routing
net.ipv4.conf.all.accept_source_route=0

# Защита от SYN Flood
net.ipv4.tcp_syncookies=1
net.ipv4.tcp_max_syn_backlog=4096

# Защита от Land Attack
net.ipv4.conf.all.log_martians=1

# Фрагментация (ограничение памяти)
net.ipv4.ipfrag_high_thresh=4194304
net.ipv4.ipfrag_low_thresh=3145728
```

## Сводная таблица характеристик

| Параметр | Значение |
| :--- | :--- |
| **Единица данных (PDU)** | Пакет (Packet) |
| **Адресация** | Логическая иерархическая (IPv4 — 32 бита, IPv6 — 128 бит) |
| **Оборудование** | [Маршрутизатор](../routing_protocols_equipment.md), L3-коммутатор |
| **Служебные протоколы** | [ICMP](../../../Protocols/ICMP/icmp_overview.md), [ARP](../../../Protocols/arp.md) (L2.5), [DHCP](../../../Protocols/DHCP/dhcp_overview.md) |
| **Маршрутизация** | LPM (Longest Prefix Match), ECMP, PBR, Anycast |
| **Фрагментация** | IPv4: маршрутизаторы + источник; IPv6: только источник |
| **QoS** | DSCP (6 бит), Traffic Class + Flow Label (IPv6) |
| **Безопасность** | IPsec (ESP/AH), IKEv2, uRPF, RPKI |
| **MTU** | IPv4: 576-1500 (jumbo 9000); IPv6: min 1280, typical 1500 |

## Дополнительная информация

### См. также

- **[Сетевой уровень (L3)](./routing_scenarios.md)** — 10 практических сценариев маршрутизации (ECMP, VRF, PBR, Blackhole, Anycast).
- **[Протоколы и оборудование L3](../routing_protocols_equipment.md)** — BGP, OSPF, IS-E и устройство роутеров.
- **[IP-адресация](../../../Protocols/IP_addressing/ip_overview.md)** — структура адресов и масок.
