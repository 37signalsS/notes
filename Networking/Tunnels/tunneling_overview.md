# Обзор сетевых туннелей и инкапсуляции

## Определения

**Сетевой туннель** — логическое соединение, созданное путём инкапсуляции пакетов одного протокола в пакеты другого для их передачи через промежуточную сетевую инфраструктуру (Underlay).

**Инкапсуляция** — процесс упаковки «пассажирского» пакета (внутреннего) в поле полезной нагрузки «несущего» пакета (внешнего).

**Оверлейная сеть (Overlay)** — виртуальная топология, построенная поверх физической инфраструктуры с использованием туннелирования. Позволяет абстрагировать логику сети от физических ограничений (например, растянуть L2-сегмент через L3-маршрутизаторы).

**VTEP (VXLAN Tunnel End Point)** — логическая сущность (интерфейс), выполняющая функции инкапсуляции и декапсуляции трафика на границе оверлея.

> **См. также:** [MTU и фрагментация](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md), [TUN vs TAP](./tun_vs_tap.md), [Протокол GRE](./gre/gre.md)

---

## Предварительные требования

### Необходимые знания

Перед изучением туннелирования рекомендуется владеть следующими темами:

| Тема | Ссылка | Уровень |
| :--- | :--- | :--- |
| Модель OSI и TCP/IP | [Модель OSI](../OSI_TCP_IP_Model/osi_model.md), [Модель TCP/IP](../OSI_TCP_IP_Model/tcp_ip_model.md) | Базовый |
| Сетевой уровень (L3) | [Обзор L3](../OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md) | Базовый |
| Маршрутизация | [Маршрутизация](../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md) | Базовый |
| MTU и фрагментация | [MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) | Средний |
| Интерфейсы Linux | [ip link](../../Linux/Networking/Tools/iproute2/ip_link.md) | Средний |
| Таблицы маршрутизации | [ip route](../../Linux/Networking/Tools/iproute2/ip_route.md) | Средний |

### Программное обеспечение

Для работы с туннелями в Linux необходимы следующие компоненты:

| Компонент | Назначение | Минимальная версия |
| :--- | :--- | :--- |
| **Ядро Linux** | Модули туннелирования (ipip, gre, vxlan, sit) | 5.10+ |
| **iproute2** | Управление туннелями через `ip link` | 5.15+ |
| **nftables / iptables** | Фильтрация туннельного трафика | Любая |
| **tcpdump** | Диагностика инкапсулированного трафика | 4.0+ |

### Проверка готовности системы

```bash
# Проверка загруженных модулей туннелирования
lsmod | grep -E "^(ipip|gre|vxlan|sit|geneve|fou)"
# → gre    32768  0
# → ipip   20480  0
# → vxlan  90112  0

# Проверка доступных типов интерфейсов
ip link help | grep -oE "(ipip|sit|gre|gretap|vxlan|geneve|erspan)" | sort -u
# → geneve
# → gre
# → gretap
# → ipip
# → sit
# → vxlan

# Включение IP-форвардинга (обязательно для маршрутизации через туннели)
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/90-tunnel-forward.conf
sudo sysctl -p /etc/sysctl.d/90-tunnel-forward.conf

# Установка зависимостей
# Debian/Ubuntu
sudo apt update && sudo apt install iproute2 nftables tcpdump

# RHEL/CentOS/Rocky
sudo dnf install iproute nftables tcpdump
```

---

## Основные концепции

### Архитектура и уровни OSI

Туннели классифицируются по уровню полезной нагрузки, которую они переносят:

-   **L2-туннели (Bridging):** Передают Ethernet-кадры. Позволяют объединить удалённые узлы в один широковещательный домен.
    -   *Протоколы:* VXLAN, GENEVE, GRETAP, L2TPv3.
-   **L3-туннели (Routing):** Передают IP-пакеты. Используются для маршрутизации между удалёнными подсетями.
    -   *Протоколы:* GRE, IPIP, SIT (6in4), WireGuard.
-   **L2.5 (Labels):** **[MPLS](./mpls.md)** — использует метки (labels) для коммутации, занимая промежуточное положение между канальным и сетевым уровнями.

### Плоскость управления (Control Plane)

Определяет, как узлы узнают о маршрутах и расположении удалённых точек (VTEP/Endpoints):

1.  **Статическая:** Ручное указание IP-адресов удалённых точек (характерно для IPIP, базового GRE).
2.  **Динамическая (Multicast):** Использование мультикаст-рассылок для автоматического обнаружения соседей (например, VXLAN Flood-n-Learn).
3.  **SDN / BGP EVPN:** Использование внешнего контроллера или протоколов маршрутизации (**[BGP EVPN](../Protocols/bgp.md)**) для централизованного распространения информации о доступности MAC/IP.

### Современные механизмы инкапсуляции

Для решения проблем NAT и производительности в Linux внедрены дополнительные механизмы:

-   **FOU (Foo Over UDP):** Инкапсуляция протоколов без портов (IPIP, GRE) в UDP-пакеты. Это делает их «дружелюбными» к NAT и позволяет использовать ECMP-балансировку на основе хеша портов.
-   **GUE (Generic UDP Encapsulation):** Более продвинутый вариант инкапсуляции в UDP с поддержкой дополнительных метаданных в заголовке.
-   **Segment Routing (SR):** Маршрутизация от источника, где путь пакета кодируется непосредственно в заголовке (SR-MPLS или SRv6).

---

## Практические сценарии

### Выбор технологии (Дерево решений)

При проектировании сети используйте следующий алгоритм:

```text
Требуется L2-связность (объединение в один коммутатор)?
|-- Да -> Нужно масштабирование и мультитенантность (Облако/K8s)?
|         |-- Да -> VXLAN или GENEVE
|         `-- Нет -> GRETAP (простота)
`-- Нет (L3 Routing) -> Нужно шифрование?
         |-- Да -> WireGuard (производительность) или IPsec (стандарт)
         `-- Нет -> Требуется мультикаст/динамическая маршрутизация?
                  |-- Да -> GRE
                  `-- Нет -> IPIP (минимальный оверхед)
```

### Сравнение оверхеда и MTU

| Технология | Оверхед (байт) | MTU (при физическом 1500) | Формула расчёта |
| :--- | :--- | :--- | :--- |
| **IPIP** | 20 | 1480 | 1500 - 20 (IPv4 header) |
| **GRE (без ключа)** | 24 | 1476 | 1500 - 20 (IP) - 4 (GRE header) |
| **GRE (с ключом)** | 28 | 1472 | 1500 - 20 (IP) - 4 (GRE) - 4 (Key) |
| **SIT (6in4)** | 20 | 1480 | 1500 - 20 (IPv4 header) |
| **VXLAN** | 50 | 1450 | 1500 - 20 (IP) - 8 (UDP) - 8 (VXLAN) - 14 (Ethernet) |
| **GENEVE** | 38 | 1462 | 1500 - 20 (IP) - 8 (UDP) - 16 (GENEVE) - 14 (Ethernet) |
| **WireGuard** | 60 | 1440 | 1500 - 20 (IP) - 8 (UDP) - 32 (WG header) |
| **IPsec (ESP)** | 50-70 | 1430-1450 | 1500 - 20 (IP) - 8 (ESP) - 16-36 (ICV) |

> **Важно:** Если суммарный пакет превышает физический MTU, пакет будет фрагментирован или отброшен. Подробнее: [MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md).

### Управление и диагностика в Linux

В современных системах настройка выполняется через `ip link` (пакет `iproute2`).

```bash
# Создание туннеля (пример GRE)
sudo ip link add dev gre0 type gre local 1.1.1.1 remote 2.2.2.2
sudo ip link set gre0 up

# Проверка параметров и оверхеда
ip -d link show gre0
# → gre remote 2.2.2.2 local 1.1.1.1 ttl inherit pmtudisc

# Просмотр статистики (ошибки, дропы из-за MTU)
ip -s link show gre0
# → RX:  bytes=1234 packets=10 errors=0 dropped=0
# → TX:  bytes=5678 packets=8 errors=0 dropped=0

# Проверка MTU туннельного интерфейса
ip link show gre0 | grep mtu
# → mtu 1476

# Просмотр всех туннельных интерфейсов
ip -d link show type gre
ip -d link show type ipip
ip -d link show type vxlan
```

### Лаборатория: Сравнение протоколов в Network Namespaces

Полный пример создания и сравнения различных типов туннелей между двумя изолированными пространствами имён:

```bash
# ============================================
# Создание лабораторной среды
# ============================================

# Создание пространств имён
ip netns add ns1
ip netns add ns2

# Создание физических пар (veth) для «внешней» сети
ip link add veth1-outer type veth peer name veth2-outer

# Перемещение в пространства имён
ip link set veth1-outer netns ns1
ip link set veth2-outer netns ns2

# Настройка «внешних» адресов
ip netns exec ns1 ip addr add 192.168.100.1/24 dev veth1-outer
ip netns exec ns1 ip link set veth1-outer up
ip netns exec ns1 ip link set lo up

ip netns exec ns2 ip addr add 192.168.100.2/24 dev veth2-outer
ip netns exec ns2 ip link set veth2-outer up
ip netns exec ns2 ip link set lo up

# Проверка связности «внешней» сети
ip netns exec ns1 ping -c 1 192.168.100.2
# → 64 bytes from 192.168.100.2: icmp_seq=1 ttl=64 time=0.05 ms

# ============================================
# Сценарий 1: IPIP-туннель (внутренняя сеть 10.0.0.0/30)
# ============================================

ip netns exec ns1 ip link add ipip1 type ipip local 192.168.100.1 remote 192.168.100.2
ip netns exec ns1 ip link set ipip1 up
ip netns exec ns1 ip addr add 10.0.0.1/30 dev ipip1
ip netns exec ns1 ip route add 10.0.0.0/30 dev ipip1

ip netns exec ns2 ip link add ipip1 type ipip local 192.168.100.2 remote 192.168.100.1
ip netns exec ns2 ip link set ipip1 up
ip netns exec ns2 ip addr add 10.0.0.2/30 dev ipip1
ip netns exec ns2 ip route add 10.0.0.0/30 dev ipip1

# Тест IPIP-туннеля
ip netns exec ns1 ping -c 2 10.0.0.2
# → PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.
# → 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.12 ms

# Проверка заголовков
ip netns exec ns1 tcpdump -ni veth1-outer proto 4 -c 2
# → 192.168.100.1 > 192.168.100.2: IP (..., proto IPIP (4), length: 84)

# ============================================
# Сценарий 2: GRE-туннель (внутренняя сеть 10.0.1.0/30)
# ============================================

ip netns exec ns1 ip link add gre1 type gre local 192.168.100.1 remote 192.168.100.2
ip netns exec ns1 ip link set gre1 up
ip netns exec ns1 ip addr add 10.0.1.1/30 dev gre1
ip netns exec ns1 ip route add 10.0.1.0/30 dev gre1

ip netns exec ns2 ip link add gre1 type gre local 192.168.100.2 remote 192.168.100.1
ip netns exec ns2 ip link set gre1 up
ip netns exec ns2 ip addr add 10.0.1.2/30 dev gre1
ip netns exec ns2 ip route add 10.0.1.0/30 dev gre1

# Тест GRE-туннеля
ip netns exec ns1 ping -c 2 10.0.1.2
# → 64 bytes from 10.0.1.2: icmp_seq=1 ttl=64 time=0.15 ms

# Проверка MTU (ожидается 1476 для GRE)
ip netns exec ns1 ip link show gre1 | grep mtu
# → mtu 1476

# ============================================
# Сравнение: IPIP vs GRE
# ============================================

# Сравнение MTU
echo "=== IPIP MTU ==="
ip netns exec ns1 ip link show ipip1 | grep mtu
# → mtu 1480

echo "=== GRE MTU ==="
ip netns exec ns1 ip link show gre1 | grep mtu
# → mtu 1476

# Сравнение размера заголовков через tcpdump
echo "=== IPIP packet size ==="
ip netns exec ns1 tcpdump -ni veth1-outer proto 4 -c 1 -s0
# → ... length 84 (IPIP: 20 outer + 64 inner)

echo "=== GRE packet size ==="
ip netns exec ns1 tcpdump -ni veth1-outer proto 47 -c 1 -s0
# → ... length 88 (GRE: 20 outer + 4 GRE + 64 inner)

# ============================================
# Очистка
# ============================================

ip netns exec ns1 ip link delete ipip1
ip netns exec ns2 ip link delete ipip1
ip netns exec ns1 ip link delete gre1
ip netns exec ns2 ip link delete gre1
ip netns exec ns1 ip link delete veth1-outer
ip netns del ns1
ip netns del ns2
```

### Технические нюансы и ограничения

1.  **Проблема MTU и фрагментации:**
    -   Инкапсуляция добавляет оверхед (IPIP: 20B, GRE: 24-28B, VXLAN: 50B).
    -   Если суммарный пакет > физического MTU (обычно 1500), пакет будет фрагментирован или отброшен.
    -   **Решение:** Установка MSS Clamping (обычно до 1440-1410) на шлюзах. Подробнее: **[MTU в VPN-сетях](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)**.
2.  **Безопасность и Spoofing:**
    -   Бездисковые (Stateless) туннели (IPIP, GRE) уязвимы для подмены IP-адресов.
    -   **Решение:** Обязательная настройка `rp_filter` (Reverse Path Filtering) и правил Firewall для проверки источника инкапсулированного трафика.
3.  **NAT Traversal:**
    -   Протоколы без L4-портов (GRE, IPIP) часто не проходят через домашние роутеры.
    -   **Решение:** Использование UDP-инкапсуляции (FOU, VXLAN, WireGuard).
4.  **Производительность и аппаратное ускорение:**
    -   Многие NIC поддерживают аппаратную инкапсуляцию/декапсуляцию (NIC offload) для GRE, VXLAN, WireGuard.
    -   Проверка: `ethtool -k <interface> | grep -E "(tx-udp_tso|tx-gre-segmentation|rx-vxlan-nostat)"`

---

## Диагностика

### Базовые команды

```bash
# Просмотр всех туннельных интерфейсов
ip -d link show | grep -E "(ipip|gre|vxlan|sit|geneve)" -A2

# Просмотр статистики ошибок
ip -s link show <tunnel_if>
# → RX:  bytes=... packets=... errors=... dropped=...
# → TX:  bytes=... packets=... errors=... dropped=...

# Проверка маршрута через туннель
ip route get <remote_tunnel_IP>
# → <remote> dev <tunnel_if> src <local_IP> uid 0

# Прослушивание инкапсулированного трафика
sudo tcpdump -ni <physical_if> proto <protocol_number> -c 10
# → proto 4 (IPIP), proto 47 (GRE), proto 41 (SIT)
# → proto 17 port 4789 (VXLAN), port 6081 (GENEVE)
```

### Проверка PMTUD

```bash
# Проверка Path MTU с DF bit
ping -M do -s 1452 -c 1 <remote_tunnel_IP>
# → Формула: payload + 28 (IP+ICMP) + <tunnel_overhead> <= физ_MTU

# Пример для GRE (охват 24B): 1452 + 28 + 24 = 1504 > 1500 → проблема!
ping -M do -s 1448 -c 1 <remote_tunnel_IP>
# → 1448 + 28 + 24 = 1500 → ОК
```

---

## Типичные ошибки и их устранение

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Tunnel is down / NOARP** | Интерфейс не поднят | `ip link show <tunnel>` | `ip link set <tunnel> up` |
| **Нет connectivity через туннель** | IP-форвардинг отключен | `sysctl net.ipv4.ip_forward` | `sysctl -w net.ipv4.ip_forward=1` |
| **Фрагментация пакетов** | MTU туннеля не уменьшен | `ping -M do -s <size> -c 1 <remote>` | Уменьшить MTU / настроить MSS Clamping |
| **rp_filter блокирует трафик** | Strict reverse path filtering | `sysctl net.ipv4.conf.all.rp_filter` | `sysctl -w net.ipv4.conf.all.rp_filter=0` или `=2` |
| **FOU не работает** | Модуль fou не загружен | `lsmod \| grep fou` | `sudo modprobe fou` |
| **NAT-транзит не работает** | GRE/IPIP без FOU через NAT | `tcpdump -ni any proto 4` | Использовать FOU / VXLAN / WireGuard |
| **Пакеты отбрасываются firewall** | nftables/iptables блокируют протокол | `nft list ruleset \| grep -E "(ipip\|gre\|vxlan)"` | Добавить правила разрешения |
| **VXLAN не работает** | Мультикаст не настроен | `ip maddr show` | `ip maddr add <mcast_addr> dev <iface>` |
| **GRE-туннель с ключом не работает** | Ключ не совпадает на обоих концах | `ip -d link show <gre_if>` | Проверить ключи на обоих узлах |
| **TTL туннеля = 1** | По умолчанию TTL не задан | `ip -d link show <tunnel> \| grep ttl` | Указать TTL при создании: `ttl 64` |

---

## Лучшие практики

### Безопасность

1. **Фильтрация по внешнему IP:**
   ```bash
   # Разрешить GRE только от доверенного peer
   sudo nft add rule ip filter input ip saddr 2.2.2.2 ip protocol 47 accept
   sudo nft add rule ip filter input ip protocol 47 drop
   ```

2. **Настройка rp_filter для туннельных интерфейсов:**
   ```bash
   # Loose mode (рекомендуется для туннелей)
   sudo sysctl -w net.ipv4.conf.all.rp_filter=2

   # Или strict для конкретного интерфейса
   sudo sysctl -w net.ipv4.conf.gre0.rp_filter=1
   ```

3. **Ограничение TTL:**
   ```bash
   # Отбрасывать пакеты с TTL < 64 (защита от loopback)
   sudo nft add rule ip filter input ip ttl lt 64 drop
   ```

### MTU-тюнинг

```bash
# MSS Clamping через nftables (для GRE с MTU 1476)
nft add rule inet filter forward oifname "gre0" tcp flags syn tcp option maxseg size set 1436

# Установка MTU на туннельном интерфейсе
sudo ip link set gre0 mtu 1476

# Проверка MTU после настройки
ip link show gre0 | grep mtu
# → mtu 1476
```

### Персистентность

**systemd-юнит для GRE-туннеля:**
```ini
# /etc/systemd/system/gre0.service
[Unit]
Description=GRE tunnel gre0
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/sbin/ip link add dev gre0 type gre local 1.1.1.1 remote 2.2.2.2 ttl 64
ExecStart=/sbin/ip link set gre0 up
ExecStart=/sbin/ip addr add 10.0.0.1/30 dev gre0
ExecStop=/sbin/ip link delete gre0
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable gre0.service
sudo systemctl start gre0.service
```

### Очистка

```bash
# Удаление туннельного интерфейса
sudo ip link delete <tunnel_if>

# Проверка, что интерфейс удалён
ip link show <tunnel_if>
# → Device "<tunnel_if>" does not exist.

# Остановка systemd-юнита
sudo systemctl stop gre0.service
sudo systemctl disable gre0.service
sudo rm /etc/systemd/system/gre0.service
sudo systemctl daemon-reload

# Отключение IP-форвардинга (если не нужен)
sudo sysctl -w net.ipv4.ip_forward=0
```

---

## Граничные случаи и ограничения

1. **GRE и NAT:** GRE не работает через NAT без FOU-инкапсуляции. Используйте FOU, VXLAN или WireGuard для NAT-транзита.

2. **IPIP и multicast:** IPIP не поддерживает multicast. Для multicast-трафика используйте GRE или VXLAN.

3. **VXLAN и габаритные кадры (Jumbo Frames):** При использовании VXLAN на сети с Jumbo Frames (MTU 9000) убедитесь, что оверхед VXLAN (50B) не превышает доступный бюджет MTU.

4. **Двойная инкапсуляция:** При использовании GRE-over-VXLAN или VXLAN-over-GRE суммарный оверхед может значительно превышать MTU. Планируйте MTU с учётом всех уровней инкапсуляции.

5. **Geneve vs VXLAN:** Geneve более гибкий (поддерживает TLV-метаданные), но менее распространён. VXLAN — де-факто стандарт для дата-центров.

6. **Проблема соSplice-шлюзами:** Некоторые провайдеры отбрасывают пакеты с нестандартными протоколами (47 для GRE, 4 для IPIP). Проверяйте транзит через `traceroute -P gre` или `traceroute -P ipip`.

7. **Конфликт имен интерфейсов:** При создании нескольких туннелей одного типа используйте уникальные имена (gre0, gre1, ...). Автоматические имена (gre0) могут конфликтовать с ранее созданными интерфейсами.

---

## Дополнительная информация

### Сравнение протоколов

| Технология | Уровень | Шифрование | Транспорт | Сценарий |
| :--- | :--- | :--- | :--- | :--- |
| **IPIP / SIT** | L3 | Нет | IP (4/41) | Простейший транзит IPv4/IPv6. |
| **GRE** | L2/L3 | Нет | IP (47) | Универсальные туннели, DMVPN, OSPF/BGP. |
| **VXLAN** | L2 | Нет | UDP (4789) | Стандарт для дата-центров, облаков и K8s. |
| **GENEVE** | L2 | Нет | UDP (6081) | Современный гибкий оверлей (OVN/Cilium). |
| **WireGuard** | L3 | Да | UDP (dyn) | Высокопроизводительные VPN каналы. |
| **IPsec** | L3 | Да | IP (50/51) | Корпоративный стандарт защиты каналов. |

### Связанные документы

**Основные протоколы:**
-   **[Протокол GRE](./gre/gre.md)** — универсальная инкапсуляция и DMVPN.
-   **[Технология VXLAN](./vxlan.md)** — архитектура L2-оверлеев в ЦОД.
-   **[IPIP и SIT](./ipip_and_sit.md)** — простейшие L3-туннели.
-   **[MPLS](./mpls.md)** — коммутация по меткам.
-   **[TUN vs TAP](./tun_vs_tap.md)** — виртуальные интерфейсы.

**VPN-протоколы:**
-   **[WireGuard — практическое руководство](./wireguard_practical.md)** — пошаговые сценарии site-to-site и remote access.
-   **[OpenVPN](./openvpn.md)** — PKI, site-to-site, remote access.
-   **[L2TP/IPsec](./l2tp_ipsec.md)** — комбинация L2TP и IPsec для legacy-устройств.
-   **[IPsec](./ipsec/ipsec.md)** — IKEv2, site-to-site, remote access.
-   **[GRE vs WireGuard](./gre/gre_vs_wireguard.md)** — сравнение протоколов.

**Сравнения и выбор:**
-   **[Remote Access VPN — сравнение](./remote_access_vpn.md)** — WireGuard vs OpenVPN vs IPsec vs L2TP/IPsec.
-   **[DMVPN](./gre/dmvpn.md)** — динамический multipoint VPN (mGRE + NHRP).

**Диагностика и безопасность:**
-   **[VPN Troubleshooting](./vpn_troubleshooting_universal.md)** — universальный чек-лист.
-   **[Firewall templates](./vpn_firewall_templates.md)** — шаблоны правил nftables/iptables.
-   **[MTU и фрагментация](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — глубокий разбор PMTUD и MSS Clamping.

**Автоматизация и контейнеры:**
-   **[VPN Automation](./vpn_automation.md)** — Ansible и Terraform.
-   **[VPN в контейнерах](./vpn_in_containers.md)** — Docker и Kubernetes.
