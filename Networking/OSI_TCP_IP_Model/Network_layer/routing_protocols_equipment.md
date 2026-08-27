# Протоколы и оборудование сетевого уровня (L3)

## Определения

**Маршрутизация (Routing)** — процесс выбора оптимального пути для передачи IP-пакета от источника к получателю через промежуточные узлы (хопы) на основе логической адресации (IP). Решение принимается на основе маршрутизационных протоколов (динамическая маршрутизация) или статических правил, внесённых администратором.

**Маршрутизатор (Router)** — интеллектуальное устройство сетевого уровня, объединяющее разнородные сети (L2-домены) и принимающее решение о пересылке пакетов на основе динамических или статических правил. В отличие от L2-коммутатора, маршрутизатор инкапсулирует пакеты при пересечении сетевых границ (разные L2-протоколы).

**Административная дистанция (Administrative Distance, AD)** — мера «доверия» к источнику маршрутной информации. Если один и тот же префикс получен из разных источников (например, OSPF и BGP), маршрутизатор выберет тот, у которого AD ниже. Не является метрикой — это лишь способ приоритизации.

**Метрика (Metric)** — числовая величина, используемая протоколом маршрутизации для сравнения альтернативных путей к назначению. Метрика определена внутри протокола и не имеет смысла за пределами одного протокола (в отличие от AD, который применим ко всем протоколам).

**Сходимость (Convergence)** — скорость, с которой маршрутизаторы обновляют свои таблицы маршрутизации после изменения топологии. Чем быстрее сходимость — тем меньше потеря трафика при отказе линка.

**ECMP (Equal-Cost Multi-Path)** — механизм переключения нагрузки между несколькими маршрутами с одинаковой метрикой. Позволяет балансировать трафик по нескольким uplink'ам без создания петель. В Linux: `ip route add default nexthop via 10.0.0.1 weight 1 nexthop via 10.0.0.2 weight 1`.

**PBR (Policy-Based Routing)** — маршрутизация по политике. Вместо стандартного longest prefix match трафик маршрутизируется на основе ACL, DSCP, TOS, VLAN ID или других критериев. Реализация в Linux: `ip rule` + `ip route` в RPDB (Routing Policy Database).

## Связь с соседними уровнями

```text
L4 (TCP/UDP) ← Маршрутизатор не инспектирует L4 (обычно); PBR может фильтровать по порту
       ↕
L3 (IP)      ← Маршрутизация = выбор next-hop для IP-пакета; ключевое поле: DST IP
       ↕               инкапсуляция: IP-заголовок перезаписывается (TTL-1, пересчёт checksum)
L2 (Ethernet)← Маршрутизатор устанавливает ARP для next-hop; переключает L2-заголовок
       ↕               на каждом хопе (SRC/DST MAC меняются; IP остаётся)
L1 (PHY)     ← Физический линк: Ethernet/Wi-Fi/Serial; MTU определяет max размер пакета
```

| Уровень | Что делает маршрутизатор |
| :--- | :--- |
| **L4 → L3** | PBR может маршрутизировать по TCP/UDP порту; stateful firewall (если включён) |
| **L3 → L3** | Ядро маршрутизации: longest prefix match в FIB; запись в FIB → выходной интерфейс |
| **L3 → L2** | ARP/NDP для next-hop; перезапись L2-заголовка (ether type = 0x0800 IPv4 / 0x86DD IPv6) |
| **L2 → L1** | Физическая передача кадра; скорость зависит от порта (1G/10G/100G) |

### PDU маршрутизатора

| PDU | Имя | Размер | Описание |
| :--- | :--- | :--- | :--- |
| **L3** | IP Packet | 20-65535 байт | Основная PDU маршрутизатора; заголовок содержит SRC/DST IP |
| **L2** | Ethernet Frame | 64-1518 байт (9018 jumbo) | Кадр, инкапсулирующий IP-пакет; MAC-адреса перезаписываются на каждом хопе |
| **L1** | Bits | Сигнал на линии | Физический сигнал (электрический/оптический) |

**Инкапсуляция при маршрутизации:**
```
[ L1: Bits ] → [ L2: Ethernet Header (14B) | L3: IP Header (20B) | L4: TCP/UDP (20-8B) | Payload ] → L2: FCS (4B)
                                        ↑ MAC меняется на каждом хопе
                IP Header: SRC/DST IP — неизменны (обычно); TTL уменьшается на 1
```

## Базовые концепции

### Базовые протоколы сетевого уровня

Для обеспечения функционирования L3, помимо самих протоколов маршрутизации, используются вспомогательные службы:

| Протокол | Назначение | SSoT |
| :--- | :--- | :--- |
| **[IP (Internet Protocol)](../../Protocols/IP_addressing/ip_overview.md)** | Глобальная адресация и доставка пакетов. | [Обзор IP](../../Protocols/IP_addressing/ip_overview.md) |
| **[ICMP (Control Message)](../../Protocols/ICMP/icmp_overview.md)** | Диагностика и сообщения об ошибках (Unreachable, TTL Exceeded). | [Обзор ICMP](../../Protocols/ICMP/icmp_overview.md) |
| **[ARP (Address Resolution)](../../Protocols/arp.md)** | Связка IP (L3) и MAC (L2) в широковещательных сегментах. | [Обзор ARP](../../Protocols/arp.md) |
| **[DHCP (Host Configuration)](../../Protocols/DHCP/dhcp_overview.md)** | Автоматизация настройки сетевых параметров узлов. | [Обзор DHCP](../../Protocols/DHCP/dhcp_overview.md) |

### Типы маршрутизации

1.  **Статическая маршрутизация:** Маршруты прописываются администратором вручную (`ip route ...`).
    - *Применение:* Default Gateway на хостах, тупиковые сети (Stub), резервные каналы (Floating Static).
    - *Преимущества:* Предсказуемость, отсутствие overhead, контроль над каждым маршрутом.
    - *Недостатки:* Не масштабируется, ручное управление, нет автоматического failover.
    - **Floating Static:** Статический маршрут с искусственно завышенным AD (например, `AD=200`). Используется как запасной, когда OSPF/BGP отказывает: `ip route 10.0.0.0/8 192.168.1.1 200`.
2.  **Динамическая маршрутизация:** Автоматический обмен информацией о топологии между роутерами.

#### IGP (Interior Gateway Protocols) — внутри одной организации (AS)

**Классификация по алгоритму:**
- **Distance-Vector (Дистанционно-векторный):** Каждый маршрутизатор отправляет соседям свою таблицу целиком. Просто, но медленно сходится и склонен к петлям. Пример: RIP, EIGRP (гибридный).
- **Link-State (Состояние каналов):** Каждый маршрутизатор строит полную LSDB (Link-State Database) и вычисляет SPF-дерево. Быстрая сходимость, масштабируемость. Пример: OSPF, IS-IS.

- **[OSPF (Open Shortest Path First)](../../Protocols/ospf.md):** Алгоритм Link-State (SPF). Стандарт для корпоративных сетей. Быстрая сходимость (секунды). RFC 2328 (IPv4), RFC 5340 (IPv6). Использует IP Protocol 89 (не TCP/UDP). Поддерживает зоны (Areas) для иерархии. Метрика = cost (10^8 / bandwidth).
  - **OSPFv2** — для IPv4 (RFC 2328)
  - **OSPFv3** — для IPv6 (RFC 5340)
  - **Hello:** 10 секунд (Broadcast), 30 секунд (NBMA). Dead: 4×Hello.
  - **Конфигурация (Cisco):** `router ospf 1` → `network 10.0.0.0 0.0.0.255 area 0`
  - **Конфигурация (Linux/FRRouting):** `router ospf` → `network 10.0.0.0/24 area 0`
  - **Конфигурация (MikroTik):** `/routing ospf network add network=10.0.0.0/24 area=backbone`

- **IS-IS (Intermediate System to Intermediate System):** Аналог OSPF, работающий напрямую над L2 (не поверх IP!). Основной протокол в сетях провайдеров для построения IP-фабрик. RFC 1195 (ISO 10589 + IP extensions). Использует TLV (Type-Length-Value) — легко расширяется без изменения протокола. Метрика = cost ((Scene IPv4: narrow, wide). CLNS (Connectionless Network Service) — нативный протокол IS-IS; IP работает как «пассажир». Высокая масштабируемость: >10 000 роутеров в одной области.
  - **Конфигурация (Cisco):** `router isis NET 49.0001.0000.0000.0001.00` → `interface Loopback0 isis enable`
  - **Конфигурация (FRRouting):** `router isis net 49.0001.0000.0000.0001.00` → `interface eth0 isis enable`

- **EIGRP (Enhanced Interior Gateway Routing Protocol):** Гибридный протокол (Cisco proprietary, открытый стандарт RFC 7868 с 2013 г.). Оптимизирован для быстрой реакции на изменения. Использует DUAL (Diffusing Update Algorithm) — немедленная сходимость без петель. Метрика = composite (bandwidth, delay, reliability, load). По умолчанию: K1=K3=1, K2=K4=K5=0 → bandwidth + delay. Fast Stuck-in-Active: мгновенный failover. Мультикаст: 224.0.0.10. Классификация: Distance-Vector (но с link-state-like behavior).
  - **Конфигурация (Cisco):** `router eigrp 100` → `network 10.0.0.0` → `no auto-summary`

- **RIP (Routing Information Protocol):** Простейший distance-vector протокол. Метрика = hop count (макс. 15 хопов = «бесконечность»). Медленная сходимость (30 сек обновления). Устарел, но используется в малых сетях и как learning tool. RIPv2 (RFC 2453) — classless, аутентификация. RIPng (RFC 2080) — для IPv6.
  - **Конфигурация (Cisco):** `router rip` → `version 2` → `network 10.0.0.0` → `no auto-summary`
  - **Конфигурация (FRRouting):** `router rip` → `network 10.0.0.0/24`

#### EGP (Exterior Gateway Protocols) — между автономными системами

- **[BGP (Border Gateway Protocol)](../../Protocols/bgp.md):** Протокол вектора пути (Path-Vector). Единственный протокол, на котором держится глобальный Интернет. Управляется политиками (Attributes), а не просто метриками. RFC 4271 (BGP-4). Транспорт: TCP/179. Кэширование маршрутов: 30 минут (RFC 4271).
  - **iBGP** (внутренний) — между роутерами одной AS. Обмен маршрутами без изменения AS_PATH.
  - **eBGP** (внешний) — между AS (internet peering). AS_PATH добавляется.
  - **Атрибуты BGP:** AS_PATH, Next Hop, Local Preference (iBGP), MED, Weight, Community.
  - **BGP-4+** (RFC 4760) — MP-BGP для IPv6, VPN, EVPN, MPLS.
  - **Конфигурация (Cisco):** `router bgp 65001` → `neighbor 10.0.0.2 remote-as 65002` → `address-family ipv4 unicast`
  - **Конфигурация (FRRouting):** `router bgp 65001` → `neighbor 10.0.0.2 remote-as 65002`

#### Сравнение протоколов маршрутизации

| Протокол | Тип | Метрика | Сходимость | Масштаб | Транспорт | Мультикаст | Год |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **RIPv2** | Distance-Vector | Hop count (15) | ~120 сек | Малые (<50) | UDP/520 | 224.0.0.9 | 1988 |
| **OSPF** | Link-State | Cost (10^8/bw) | 1-5 сек | Средние (1000+) | IP proto 89 | 224.0.0.5/6 | 1989 |
| **IS-IS** | Link-State | Cost (TLV) | 1-5 сек | Крупные (10000+) | L2 native | Локально | 1990 |
| **EIGRP** | Hybrid (DUAL) | Composite (BW+DLY) | 0 сек (feasible successor) | Средние (500) | IP proto 88 | 224.0.0.10 | 1988→开放 2013 |
| **BGP** | Path-Vector | AS_PATH + policy | 30-60 сек (MRAI) | Глобальный (1.2M+) | TCP/179 | Нет | 1989 |

### Таблица административных дистанций (Типовые значения)

| Источник | AD (Cisco/Std) | AD (Linux/FRR) | Приоритет |
| :--- | :--- | :--- | :--- |
| **Connected (Прямое подключение)** | 0 | 0 | Максимальный |
| **Static Route** | 1 | 1 | Очень высокий |
| **eBGP (Внешний BGP)** | 20 | 20 | Высокий |
| **OSPF** | 110 | 110 | Средний |
| **IS-IS** | 115 | 115 | Средний |
| **iBGP (Внутренний BGP)** | 200 | 200 | Низкий |
| **EIGRP (суммарная)** | 90 | N/A (Cisco) | Средний (выше OSPF) |
| **EIGRP (внешний)** | 170 | N/A (Cisco) | Ниже OSPF |
| **RIP** | 120 | 120 | Низкий |
| **OSPF (NSSA)** | 110 | 110 | Как OSPF |
| **OSPF (внешний)** | 110 | 110 | Как OSPF |
| **Directly Connected (кэш ARP)** | 0 | 0 | Максимальный |

> **Важно:** Если два маршрута к одному назначению имеют разные AD — побеждает меньший. Если AD одинаковы — побеждает меньшая метрика (внутри одного протокола).

## Архитектура и оборудование L3

### Уровни обработки (Planes)

Современные маршрутизаторы (2026+) строго разделяют ресурсы для стабильности:

```text
┌──────────────────────────────────────────────────────────────────┐
│ Management Plane (SSH/SNMP/API)                                  │
│ ┌──────────────────────────────────────────────────────────────┐  │
│ │ Control Plane (CPU + RIB)                                    │  │
│ │  OSPF/BGP/IS-IS → [ Routing Information Base (RIB) ]        │  │
│ │  Таблица маршрутизации от ВСЕХ протоколов                    │  │
│ └───────────────────────┬──────────────────────────────────────┘  │
│                         ↓ (FIB install)                          │
│ ┌──────────────────────────────────────────────────────────────┐  │
│ │ Data Plane (ASIC/TCAM + FIB)                                │  │
│ │  [ Forwarding Information Base (FIB) ] →高速转发 пакетов     │  │
│ │  Wire-speed: 10Gbps/100Gbps на каждом порту                  │  │
│ └──────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

1.  **Management Plane:** Доступ для администратора (SSH, API, SNMP). Не влияет на forwarding.
2.  **Control Plane:** Работа протоколов маршрутизации. Здесь CPU вычисляет пути и строит таблицу **RIB (Routing Information Base)** — общую базу всех известных маршрутов. RIB включает маршруты от ВСЕХ протоколов (OSPF + BGP + Static + Connected).
3.  **Data Plane (Forwarding Plane):** Непосредственная пересылка пакетов. Использует таблицу **FIB (Forwarding Information Base)** — «выжимку» из RIB, оптимизированную для максимально быстрого поиска (Longest Prefix Match за 1 такт).

**RIB vs FIB — ключевые отличия:**

| Характеристика | RIB | FIB |
| :--- | :--- | :--- |
| **Расположение** | CPU (Control Plane) | ASIC/TCAM (Data Plane) |
| **Содержит** | Все маршруты от всех протоколов (кандидаты) | Только «победившие» маршруты (install в FIB) |
| **Аптдэйт** | Медленный ( зависит от CPU и convergence) | Мгновенный (после вычисления Control Plane) |
| **Поиск** | Медленный (software) | Мгновенный (hardware, 1 такт) |
| **Cisco CLI** | `show ip route` | `show ip cef` |
| **Linux CLI** | `ip route show` | `ip route get <dst>` |
| **FRRouting CLI** | `show ip route` | `show ip fib` |

**Важный нюанс:** Наличие маршрута в RIB не гарантирует прохождение пакета. Если между Control Plane и Data Plane возникает рассинхронизация (например, при сложных изменениях BGP, ECMP или PBR), запись в FIB может отсутствовать или указывать на неверный next-hop. Диагностика требует проверки обеих таблиц:
- **RIB:** `show ip route <prefix>` (решение процесса маршрутизации).
- **FIB:** `show ip cef <destination>` (реальное решение forwarding).
- **Linux:** `ip route show table all` (RIB) → `ip route get 10.0.0.1` (FIB для конкретного IP)

**MPLS:** Работает между L2 и L3 (include 2.5). Таблица **LFIB (Label Forwarding Information Base)** — аналог FIB для меток. `show mpls forwarding-table`.

### Аппаратное ускорение

-   **ASIC (Application-Specific Integrated Circuit):** Специализированные чипы, выполняющие поиск в FIB на аппаратной скорости порта (Wire-speed). Примеры: Broadcom Memory Trident/Trident 3/5 (whitebox), Cisco Silicon One, Juniper Trio. Стоимость: ASIC определяет 60-80% стоимости маршрутизатора.
-   **TCAM (Ternary Content-Addressable Memory):** Сверхбыстрая память, позволяющая выполнять поиск по маске (**Longest Prefix Match**) за один такт. Количество записей в TCAM определяет масштаб сети, которую может обслуживать устройство. Характеристики: ~50-100 нс access time; высокое энергопотребление; дорогая ($0.01-0.1 за entry).
-   **NPU (Network Processor):** Программируемые чипы, занимающие промежуточное положение между CPU и ASIC (гибкость софта + скорость железа). Примеры: Intel NP4G, Marvell Prestera. Используются для PBR, QoS и других задач, где гибкость важнее raw speed.
-   **SmartNIC / DPU:** Сетевые карты с встроенным процессором (ARM). Выполняют OVS, VXLAN, IPsec offload. Примеры: NVIDIA BlueField-2/3, AMD Pensando, Intel IPU. Позволяют выносить Data Plane из CPU хоста.

**Размер TCAM и масштаб:**

| Устройство | Типичный TCAM | Вместимость | Пример |
| :--- | :--- | :--- | :--- |
| L2-коммутатор | 8-32K entries | 8K IPv4 | Cisco Catalyst 2960 |
| L3-коммутатор | 64-256K entries | 128K IPv4 | Cisco Catalyst 9300 |
| Средний роутер | 256K-1M entries | 512K IPv4 | Juniper MX204 |
| Тяжёлый роутер | 1M-4M entries | 4M IPv4 | Cisco CRS-X, Juniper PTX10008 |
| DFZ Core | >4M entries | 10M+ IPv4 | Juniper T4000, Cisco NCS-5500 |

### Типы оборудования

-   **Классический роутер (Services Router):** Максимальный набор функций (VPN, QoS, глубокая инспекция, MPLS), но часто ниже плотность портов. Примеры: Cisco ASR 1000/9000, Juniper MX, Huawei NE. Используется для WAN/ISP, не для дата-центров.
-   **L3-коммутатор (Layer 3 Switch):** Коммутатор, умеющий маршрутизировать трафик между VLAN на аппаратной скорости. Дешевле роутера на порт, но ограничен в функциях WAN и размере таблиц. Примеры: Cisco Catalyst 9300/9500, Arista 7050, Juniper QFX5100. Ситуация: дата-центр (Leaf/Spine), корпоративная сеть.
-   **Whitebox Switch:** Стандартное железо без ОС. Инженер сам выбирает сетевую ОС (SONiC, DENT, VyOS, vYOS), что позволяет избежать vendor lock-in. Примеры железа: Edgecore, Celestica, Delta Networks. Софт: SONiC (Microsoft), DENT (Linux Foundation), Extention NOS. Стоимость: 30-70% от vendor-решений.
-   **vRouter (Виртуальный роутер):** Инстанс в облаке или контейнере. Позволяет строить сложные топологии внутри виртуальной инфраструктуры. Примеры: FRRouting (Linux), VyOS (Debian), BIRD2 (Linux), OpenWrt, Cisco CSR1000v.
-   **Data Center Router:** Высокоплотные (100G/400G) роутеры для core/spine-слоя. Примеры: Cisco Nexus 9000, Juniper PTX, Arista 7280R3. Используются для сверхбыстрой маршрутизации в ЦОД.
-   **SD-WAN Edge:** Устройства для WAN-маршрутизации с централизованным управлением. Примеры: Cisco vEdge/Viptela, VMware VeloCloud, Fortinet, Juniper SRX. Автоматическое создание overlay-туннелей (IPsec), политики QoS.

### Программируемые роутеры (2026+)

| Решение | Описание | Применение |
| :--- | :--- | :--- |
| **FRRouting (FRR)** | Linux-демон; BGP/OSPF/IS-IS/RIP/Babel/EIGRP/Zebra. Заменяет Quagga. | vRouter, лаборатории, серверы |
| **BIRD2** | Lightweight routing daemon; BGP/OSPF/RPKI. Ориентирован на IX (Internet Exchange). | Провайдеры, IXP |
| **FreeRtr** | Полноценный виртуальный маршрутизатор (Cisco-like CLI) поверх Linux. | Тестирование, lab |
| **VyOS** | Router/Firewall на Linux; CLI-style. Поддержка OSPF/BGP/VXLAN/WireGuard/VPN. | VPN-шлюз, border router |
| **Open vSwitch (OVS)** | Виртуальный L2/L3 коммутатор для KVM/VMware. OpenFlow + CLI. | VNF, cloud networking |
| **SONiC (SONiC)** | Сетевая ОС для whitebox; поддержка BGP, VXLAN, VLAN, ACL. | Дата-центры, spine-leaf |

## Диагностика маршрутизации

### Linux (FRRouting + ip)

```bash
# Просмотр всех маршрутов (RIB)
ip route show
ip route show table all                     # все таблицы (включая PBR)

# Конкретный маршрут
ip route get 10.0.0.1                       # FIB-решение для конкретного IP
ip route get 10.0.0.1 fibmatch              # FIB с match-информацией

# Добавление статического маршрута
ip route add 172.16.0.0/16 via 10.0.0.1     # nexthop
ip route add default via 10.0.0.1            # default gateway

# Добавление ECMP-маршрута (равновесная нагрузка)
ip route add default nexthop via 10.0.0.1 weight 1 \
    nexthop via 10.0.0.2 weight 1

# Добавление floating static route (AD = 200)
ip route add 172.16.0.0/16 via 10.0.0.3 metric 200

# Удаление маршрута
ip route del 172.16.0.0/16 via 10.0.0.1

# Таблица ARP (L3 → L2)
ip neigh show
ip neigh show dev eth0

# Статистика маршрутизации
nstat -az | grep -E "Route|Forward"
cat /proc/net/snmp | grep -E "Ip:|Forwarding"

# PBR (Policy-Based Routing)
ip rule show                                # все правила RPDB
ip rule add fwmark 1 table 100              # маршрут по метке
ip route add default via 10.0.2.1 table 100 # таблица для PBR
ip route add 10.0.0.0/8 via 10.0.3.1 table 100

# Мониторинг таблицы маршрутизации (live)
watch -n 1 "ip route show | grep '10.0.0.0'"
```

### Cisco IOS

```bash
# Просмотр таблицы маршрутизации (RIB)
show ip route
show ip route 10.0.0.0
show ip route ospf                          # только OSPF-маршруты
show ip route summary                       # статистика по протоколам

# Просмотр FIB (CEF)
show ip cef
show ip cef 10.0.0.1
show ip cef exact-route 10.0.1.1 10.0.2.1   # точный путь

# Соседи (BGP)
show ip bgp summary
show ip bgp neighbors

# OSPF
show ip ospf neighbor
show ip ospf database
show ip ospf interface brief

# Проблемы и отладка
debug ip routing                            # отладка маршрутизации (ОСТОРОЖНО!)
debug ip ospf events
debug bgp updates

# Проверка AD
show ip route 10.0.0.0 255.255.0.0         # покажет откуда взят маршрут
```

### MikroTik RouterOS

```bash
# Таблица маршрутизации
/ip route print
/ip route print where dst-address=10.0.0.0/24

# Статический маршрут
/ip route add dst-address=10.0.0.0/24 gateway=192.168.1.1 distance=1

# OSPF
/routing ospf network add network=10.0.0.0/24 area=backbone
/routing ospf instance set 0 router-id=10.0.0.1

# BGP
/routing bgp instance set 0 as=65001 router-id=10.0.0.1
/routing bgp peer add remote-as=65002 remote-address=10.0.0.2

# Соседи
/ip arp print
/ipv6 neighbor print

# Статистика
/tool netwatch
/ip route statistics
```

### FRRouting (Linux)

```bash
# Вход в vtysh (Virtual Terminal Shell)
vtysh

# Просмотр всех маршрутов
show ip route
show ipv6 route
show ip bgp summary
show ip ospf neighbor

# Добавление BGP-соседа
router bgp 65001
  neighbor 10.0.0.2 remote-as 65002
  address-family ipv4 unicast
    network 172.16.0.0/16

# Проверка FIB
show ip fib
show ip fib 10.0.0.1

# Мониторинг
show ip route summary
show bgp summary
show ospf neighbor state
```

## Практические концепции (2026+)

### Default-Free Zone (DFZ)
Область Интернета, где роутеры (Core) не используют маршрут по умолчанию. Они хранят **Full View** — полную таблицу всех публичных префиксов мира (~1.2M записей в 2026г). DFZ роутеры обязаны поддерживать **RPKI (Resource Public Key Infrastructure)** для фильтрации маршрутов с неверным origin AS. AS-announcements через IRR (Internet Routing Registry).

### Segment Routing (SRv6)
Новая парадигма управления трафиком. Маршрут задается непосредственно в заголовке пакета IPv6 в виде списка сегментов (SID — Segment ID). Это заменяет сложный MPLS и позволяет Control Plane быть полностью централизованным (SDN). SR-MPLS — версия для MPLS-транспорта. SRv6 — native для IPv6. Используется в backbone-сетях крупных провайдеров (Cloudflare, Google, Rostelecom).

### EVPN (Ethernet VPN)
Протокол управления для Overlay-сетей (VXLAN). Использует BGP для передачи информации не только об IP, но и о MAC-адресах, обеспечивая бесшовную мобильность нагрузок в ЦОД. Route Types: Type 2 (MAC/IP advertisement), Type 3 (Inclusive Multicast Ethernet Tag), Type 5 (IP Prefix). Заменяет L2-first модели (L2TPv3, VPLS).

### MPLS (Multi-Protocol Label Switching)
Технология L2.5-уровня (между Ethernet и IP). Маршрутизация по меткам (Label), а не по IP-адресу. Используется в WAN-сетях провайдеров для построения VPN (L3VPN, L2VPN), TE (Traffic Engineering) и QoS. MPLS Forwarding: swap label → push label → pop label. Метки расслаиваются через LDP или RSVP-TE (Control Plane). В 2026г замещается SR-MPLS/SRv6.

### VRF (Virtual Routing and Forwarding)
Изоляция таблиц маршрутизации на одном физическом роутере. Каждый VRF — виртуальный роутер со своей RIB/FIB. Используется для: мульти-tenant сред, изоляции клиентов (ISP), CE-PE взаимодействия (L3VPN). В Linux: `ip link add vrf0 type vrf table 100`.

## Безопасность маршрутизации

| Атака | Описание | Защита |
| :--- | :--- | :--- |
| **BGP Hijacking** | Захват префикса чужой AS через объявление в BGP | RPKI ROA + BGP Origin Validation; IRR фильтрация |
| **Route Injection** | Внедрение ложных маршрутов через compromised router | MD5 аутентификация BGP-сессий (TCP-AO);стаatic filtering |
| **OSPF LSA Spoofing** | Поддельные LSA-пакеты для изменения SPF-дерева | OSPF аутентификация (MD5/SHA); area containment |
| **IS-IS Authentication** | Перехват/подмена IS-IS PDUs | MD5/SHA authentication на circuit level |
| **Blackhole Route** | Перенаправление трафика в «чёрную дыру» | BGP Blackhole Community (RTBH); RPKI |
| **Prefix Length Attack** | Объявление сверх-длинных префиксов (/32, /128) | Prefix filtering на AS boundary |
| **ECMP Load Imbalance** | Неравномерная нагрузка через одинаковые метрики | Unequal Cost ECMP; PBR; traffic engineering |

### Меры защиты на маршрутизаторах

```bash
# BGP MD5 аутентификация (Cisco)
router bgp 65001
  neighbor 10.0.0.2 password MySecretKey

# OSPF аутентификация (Cisco)
interface eth0
  ip ospf authentication message-digest
  ip ospf message-digest-key 1 md5 MySecretKey

# OSPF аутентификация (FRRouting)
router ospf
  area 0 authentication message-digest
interface eth0
  ip ospf message-digest-key 1 md5 MySecretKey

# Prefix filtering (FRRouting)
router bgp 65001
  neighbor 10.0.0.2 prefix-list FILTER in
  neighbor 10.0.0.2 route-map FILTER-RM in

# RPKI на FRRouting
rpki
  rpki remote 192.0.2.1 port 323
  rpki polling_period 10
  rpki timeout 10
```

## Типичные проблемы и чеклист

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Трафик не маршрутизируется** | Нет маршрута в RIB/FIB | `ip route show` + `ip route get <dst>` | Добавить маршрут (статика или динамика) |
| **BGP сессия не устанавливается** | Firewall блокирует TCP/179 | `telnet 10.0.0.2 179` + `tcpdump port 179` | Разрешить TCP/179; проверить AS |
| **OSPF не видит соседей** | Hello не доходит; area mismatch | `tcpdump -i eth0 proto ospf` + `show ip ospf neighbor` | Проверить area, network type, MTU |
| **Маршруты «прыгают» (route flapping)** | Нестабильный линк; split-horizon | `ping` + `tcpdump` на проблемном линке | `ip link set eth0 down/up`; проверить MTU |
| **ECMP не балансирует** | Разные метрики; hash policy | `ip route get 10.0.0.1` (множественные nexthop) | `ip route change default nexthop ...` |
| **FIB не синхронизирован с RIB** | Аппаратная проблема; TCAM overflow | `show ip cef exact-route` | Reload; firmware update |
| **PBR не работает** | Отсутствует table в RPDB | `ip rule show` + `ip route show table 100` | Добавить `ip rule add fwmark 1 table 100` |

## Сводная таблица

| Характеристика | Значение |
| :--- | :--- |
| **OSPF Hello Interval** | 10 сек (Broadcast), 30 сек (NBMA) |
| **OSPF Dead Interval** | 4 × Hello (40/120 сек) |
| **BGP Hold Timer** | 180 сек (RFC 4271 default) |
| **BGP MRAI (eBGP)** | 30 сек (RFC 4271); уменьшается в IX |
| **IS-IS Hello** | 10 сек (LAN), 30 сек (p2p, default) |
| **RIP Timer** | 30 сек обновления; 180 сек dead |
| **EIGRP K-values** | K1=1, K2=0, K3=1, K4=0, K5=0 (default) |
| **PMTU Cache** | 10 мин (IPv4), ~10 мин (IPv6) |
| **TCAM lookup** | 1 такт (~50 нс) |
| **DFZ Full View (2026)** | ~1.2M IPv4 + ~250K IPv6 префиксов |
| **Linux RPDB default tables** | local(255), main(256), default(257) |

## Дополнительная информация

### См. также
- **[Обзор сетевого уровня (L3)](./Concepts/network_layer_overview.md)** — фундаментальные механизмы: PDU, инкапсуляция, маршрутизация, QoS, IPsec.
- **[BGP: Глубокое погружение](../../Protocols/bgp.md)** — атрибуты, сессии, EVPN, MP-BGP.
- **[OSPF: Полное описание](../../Protocols/ospf.md)** — зоны, LSA, SPF, аутентификация.
- **[Практические сценарии маршрутизации](./Concepts/routing_scenarios.md)** — PBR, VRF, Anycast, 10 сценариев с bash-командами.
- **[Маршрутизация в Linux](../../../Linux/SystemAdministration/routing.md)** — команды `ip route`, `ip rule`, diagnostics.
- **[Меж-VLAN маршрутизация](../../Protocols/VLAN/vlan_inter_vlan_routing.md)** — SVI и ROAS.
- **[MTU и VPN](./mtu_and_vpn.md)** — overhead туннелей, MSS Clamping, PMTUD.
- **[IPv4/IPv6 Dual Stack](./Concepts/ipv4_ipv6_dual_stack.md)** — переходные технологии, OSPFv3, BGP-4+.
- **[MPLS и туннелирование](../../Tunnels/mpls.md)** — Label Switching, L3VPN, L2VPN.
- **[SDN и сетевая автоматизация](../../Concepts/sdn/network_automation.md)** — controller-based routing,_intent-based.
- **[EVPN и VXLAN](../../Tunnels/vxlan.md)** — overlay-маршрутизация в дата-центрах.
