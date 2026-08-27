# Проектирование VLAN: production-ready топологии и best practices

## Определения

**Логическая топология** — расположение VLAN, Trunk и Access портов в сети без привязки к физическому расположению. Определяет broadcast домены, пути трафика и fault tolerance.

**Сегментация по функции (Function-based Segmentation)** — принцип разделения сети на VLAN по назначению: `User`, `Server`, `DMZ`, `Management`, `Storage`, `Backup`. Каждая функция изолирована и имеет свою политику доступа.

**PVLAN (Private VLAN)** — расширение VLAN, позволяющее изолировать хосты внутри одного широковещательного домена. Состоит из Promiscuous (общается со всеми), Isolated (общается только с promiscuous) и Community (группы внутри одного уровня).

**VLAN Design Matrix** — таблица сопоставления VLAN ID → подсеть → назначение → security policy. Single source of truth для сетевого администратора.

> **Назначение:** Этот документ — SSoT для production-проектирования VLAN. Охватывает: enterprise campus, leaf-spine L2, PVLAN для multitenancy, VLAN sizing, inter-VLAN routing design и QoS marking внутри VLAN.

## Базовые концепции

### Принцип проектирования: "Один VLAN = одна подсеть = одна функция"

Это фундаментальное правило упрощает:
- Маршрутизацию (один SVI на VLAN)
- Фаервол (одна policy на подсеть)
- Диагностику (трафик всегда через шлюз)
- Изоляцию (нарушитель в одной подсети не затрагивает другую)

### Диапазоны VLAN ID

| Диапазон | Использование | Примечание |
| :--- | :--- | :--- |
| **1** | Default VLAN (Cisco) | Отключить всегда |
| **2-99** | Management / Service | STP, routing, NTP, syslog |
| **100-499** | Servers / DMZ | High-security segments |
| **500-999** | User Access | Основной пул конечных пользователей |
| **1000-1999** | Wireless / Guest | Изолированные сегменты |
| **2000-3999** | IoT / Printer | Низкая доверенность |
| **4000-4094** | Native / Black Hole | Reserved для Native VLAN |

### Правило размера подсети

| Тип сегмента | Размер подсети | Пример | Обоснование |
| :--- | :--- | :--- | :--- |
| **Users** | /24 (256 хостов) | 10.10.50.0/24 | ARP table manageable; 1 broadcast domain |
| **Servers** | /24 - /25 | 10.10.100.0/24 | Static IP, predictable sizing |
| **DMZ** | /26 - /27 | 10.10.200.0/26 | Smallest possible, security-critical |
| **Management** | /28 - /29 | 10.10.1.0/29 | < 10 устройств, high security |

## Практические сценарии

### Сценарий 1: Enterprise Campus VLAN Design

#### Топология

```
[Core SW] — (trunk) — [Distribution SW] — (access) — [Access SW] — (access) — [Server / PC]
```

#### VLAN Design Matrix

| VLAN ID | Subnet | Name | Purpose | Security Level |
| :--- | :--- | :--- | :--- | :--- |
| 2 | 10.10.1.0/29 | MGMT | Switch/router management | HIGH |
| 10 | 10.10.10.0/24 | USERS | General office users | MEDIUM |
| 20 | 10.10.20.0/24 | SERVERS | Internal application servers | HIGH |
| 30 | 10.10.30.0/24 | DB | Database servers | CRITICAL |
| 40 | 10.10.40.0/26 | DMZ | Public-facing web | HIGH |
| 999 | 10.10.99.0/24 | BLACKHOLE | Unused ports | — |

#### Конфигурация Core Switch (Cisco)

```cisco
! --- VLAN Creation ---
vlan 2
 name MGMT
vlan 10
 name USERS
vlan 20
 name SERVERS
vlan 30
 name DB
vlan 40
 name DMZ

! --- SVI (виртуальные интерфейсы L3) ---
interface Vlan2
 description Management
 ip address 10.10.1.1 255.255.255.248
 no ip proxy-arp
 hwap

interface Vlan10
 description Users
 ip address 10.10.10.1 255.255.255.0

interface Vlan20
 description Servers
 ip address 10.10.20.1 255.255.255.0

interface Vlan30
 description Database
 ip address 10.10.30.1 255.255.255.0
 ip access-group DB-IN in

interface Vlan40
 description DMZ
 ip address 10.10.40.1 255.255.255.192

! --- Inter-VLAN ACLs ---
ip access-list extended DB-IN
 deny tcp any host 10.10.30.10 eq 1433
 deny tcp any host 10.10.30.10 eq 3306
 permit ip any any

! --- Trunk to Distribution ---
interface range TenGigabitEthernet1/1 - 2
 description *** Trunks to Distribution ***
 switchport mode trunk
 switchport nonegotiate
 switchport trunk native vlan 999
 switchport trunk allowed vlan 2,10,20,30,40,999
 spanning-tree portfast trunk disable
```

#### Ожидаемый результат (Validation)

```bash
show ip interface brief
! → Vlan10  10.10.10.1    YES  up   up
! → Vlan20  10.10.20.1    YES  up   up
! → Vlan30  10.10.30.1    YES  up   up
! → Vlan40  10.10.40.1    YES  up   up

show vlan brief | include active
! → 2    MGMT          active    ...
! → 10   USERS         active    ...
! → 20   SERVERS       active    ...
! → 30   DB            active    ...
! → 40   DMZ           active    ...

show interfaces trunk
! → Port       Mode      Allowed
! → Te1/1      trunk     2,10,20,30,40,999(P)
```

### Сценарий 2: Private VLAN для изоляции внутри одной сети

#### Зачем нужен PVLAN

Когда VLAN содержит много хостов, которые не должны видеть друг друга на L2 (например, клиенты в hosting, жильцы в дата-центре):

- **Promiscuous (P-port):** может общаться с любыми портами (обычно uplink).
- **Isolated (I-port):** общается только с promiscuous, не видит других isolated.
- **Community (C-port):** общается с promiscuous и другими портами в той же community.

#### Конфигурация (Cisco)

```cisco
! 1. Создание PVLAN
vlan 100
 name SHARED_SUBNET
 private-vlan community
!
vlan 101
 name SERVERS
 private-vlan isolated
!
vlan 102
 name CLIENT_A
 private-vlan community
!
vlan 103
 name CLIENT_B
 private-vlan community
!
vlan 100
 private-vlan primary
 private-vlan association 101,102,103

! 2. Привязка портов
interface range Gi1/0/1
 description *** Server Access (Isolated) ***
 switchport mode private-vlan
 switchport private-vlan host-association 100 101
 switchport private-vlan host
 spanning-tree portfast

interface range Gi1/0/2-5
 description *** Client Group A (Community) ***
 switchport mode private-vlan
 switchport private-vlan host-association 100 102
 switchport private-vlan host
 spanning-tree portfast

interface range Gi1/0/6-10
 description *** Client Group B (Community) ***
 switchport mode private-vlan
 switchport private-vlan host-association 100 103
 switchport private-vlan host
 spanning-tree portfast

interface Gi1/0/24
 description *** Uplink to Router ***
 switchport mode private-vlan
 switchport private-vlan mapping 100 101,102,103
```

#### Ожидаемый результат (Validation)

```bash
show vlan private-vlan
! → Primary  Secondary  Type          Ports
! → 100    101        isolated      ...
! → 100    102        community     ...
! → 100    103        community     ...

show interfaces switchport | include Private
! → Administrative Private VLAN Host Association: 100-101
! → Private Operational Version: 1
```

### Сценарий 3: VLAN-aware Bridge в Linux для production (Leaf-Spine эмуляция)

#### Архитектура

В Linux-хосте (гипервизор или edge-router) создаём VLAN-aware Bridge с:
- STP для fault tolerance
- Storm Control через tc
- FDB limit для безопасности
- VLAN pruning (только нужные VLAN на trunk)

```bash
# 1. Создание моста с оптимизациями для production
sudo ip link add name br-prod type bridge \
  vlan_filtering 1 \
  stp_state 1 \
  forward_delay 400 \
  max_age 600 \
  priority 4096

sudo ip link set eth0 master br-prod

# 2. Trunk порт — только production VLAN (VLAN pruning)
sudo bridge vlan del dev eth0 vid 1 self  # удаляем default
sudo bridge vlan add dev eth0 vid 10
sudo bridge vlan add dev eth0 vid 20
sudo bridge vlan add dev eth0 vid 30

# 3. Access порты для ВМ (PVID + Egress Untagged)
sudo bridge vlan add dev vnet0 vid 10 pvid untagged
sudo bridge vlan add dev vnet1 vid 20 pvid untagged

# 4. Storm Control через tc (аналог Cisco storm-control)
sudo tc qdisc replace dev br-prod clsact
sudo tc filter add dev br-prod ingress \
  protocol all flower dst_mac ff:ff:ff:ff:ff:ff \
  police rate 50mbit burst 100k drop

# 5. FDB limit (аналог Port Security на коммутаторе)
sudo ip link set br-prod type bridge fdb_max_global 10000
sudo ip link set br-prod type bridge fdb_max_per_port 50

# 6. Активация
sudo ip link set br-prod up
```

#### Персистентность (systemd-networkd)

```ini
# /etc/systemd/network/30-br-prod.netdev
[NetDev]
Name=br-prod
Kind=bridge

[Bridge]
STP=true
VLANFiltering=true
ForwardDelay=400
MaxAge=600
Priority=4096
FDBMaxGlobal=10000
FDBMaxPerPort=50
```

```ini
# /etc/systemd/network/31-br-prod-eth0.network
[Match]
Name=eth0

[Network]
Bridge=br-prod

[BridgeVLAN]
VLAN=10
[BridgeVLAN]
VLAN=20
[BridgeVLAN]
VLAN=30
```

#### Ожидаемый результат (Validation)

```bash
# Проверка конфигурации моста
bridge vlan show
# → port    vlan ids
# → eth0    10 20 30
# → vnet0   10 PVID Egress Untagged
# → vnet1   20 PVID Egress Untagged

# Проверка STP состояния
bridge link show
# → 2: eth0 state forwarding priority 32 cost 4
# → 3: vnet0 state forwarding priority 32 cost 50

# Проверка FDB limit
ip link show br-prod
# → bridge vlan_filtering 1 stp_state 1 fdb_max_global 10000 fdb_max_per_port 50
```

### Сценарий 4: QoS marking внутри VLAN (PCP)

#### Зачем нужно

802.1Q тег содержит поле **PCP (Priority Code Point)** — 3 бита для классификации трафика (0-7). Позволяет приоритизировать трафик на уровне L2 без L3-маршрутизации.

#### Конфигурация на коммутаторе

```cisco
! Включение trust на trunk-портах для передачи PCP
interface range Te1/1 - 2
 mls qos trust
!
! Политика для access-портов: маркируем трафик перед отправкой в сеть
interface range Gi1/0/1 - 48
 mls qos trust dscp
```

#### Конфигурация в Linux (tc + skb priority)

```bash
# 1. Создание qdisc на VLAN-интерфейсе
tc qdisc add dev eth0.10 root handle 1: htb default 30

# 2. Классы для разных приоритетов
tc class add dev eth0.10 parent 1: classid 1:1 htb rate 100mbit
tc class add dev eth0.10 parent 1:1 classid 1:10 htb rate 10mbit ceil 100mbit prio 0  # Voice (PCP 5)
tc class add dev eth0.10 parent 1:1 classid 1:20 htb rate 30mbit ceil 100mbit prio 1  # Data (PCP 0)
tc class add dev eth0.10 parent 1:1 classid 1:30 htb rate 10mbit ceil 50mbit  prio 2  # Best-effort (PCP 0)

# 3. Фильтры по PCP (vlan priority в 802.1Q теге)
tc filter add dev eth0.10 protocol 802_1q parent 1: \
  prio 1 u32 match u16 0x0005 0x0007 at -2 \
  flowid 1:10  # PCP 5 → Voice
```

#### Проверка

```bash
tc -s filter show dev eth0.10 root
# → filter: ... priority 1 ... flowid 1:10

# Проверка PCP в tcpdump
sudo tcpdump -i eth0.10 -e 'vlan' | head -10
# → 10:00:00 aa:bb:cc:dd:ee:ff vlan 10 p 5, length 100  ← PCP=5
```

## Дополнительная информация

### Production checklist: перед вводом VLAN в эксплуатацию

| Шаг | Что проверяем | Инструмент |
| :--- | :--- | :--- |
| **1. VLAN Inventory** | Все новые VLAN зарегистрированы в Design Matrix | NetBox / IPAM |
| **2. Subnet CIDR** | /24 для users, /26 для DMZ, /29 для management | ipcalc, whois |
| **3. Native VLAN** | Совпадает на обоих концах trunk | `show interfaces trunk` |
| **4. VLAN Pruning** | Trunk разрешает только нужные VLAN | `show interfaces trunk` |
| **5. DHCP Snooping** | Trunk = trusted, Access = untrusted | `show ip dhcp snooping` |
| **6. STP** | Root Bridge назначен, portfast на access | `show spanning-tree` |
| **7. Storm Control** | broadcast < 2%, multicast < 2% | `show storm-control` |
| **8. BPDU Guard** | Включён на всех access портах | `show spanning-tree` |
| **9. FDB Limit** | Per-port limit установлен | `bridge fdb show` |
| **10. MTU** | 1500 или 9000 (jumbo) на всей цепочке | `ip link`, `show interfaces` |

### Распространённые interview вопросы (DevOps / SRE / Network Engineer)

1. **"В чём разница между MAC-flap и MAC-move?"** — Flap = запись удаляется/добавляется; Move = MAC перемещается на другой порт. Причины: петля, LACP, VM migration.
2. **"Что будет при Native VLAN mismatch?"** — нетегированный трафик попадает в разные VLAN, теряется связь между устройствами в Native VLAN; может вызвать STP TCN.
3. **"Когда применять PVST+ vs MSTP?"** — PVST+ для небольших сетей (<500 VLAN), MSTP для enterprise (>500 VLAN), чтобы снизить CPU нагрузку.
4. **"Как настроить VLAN-aware bridge в Linux?"** — `ip link add br0 type bridge vlan_filtering 1`, `bridge vlan add dev eth0 vid 10`.
5. **"В чём разница между `bridge vlan add` и `ip link add type vlan`?"** — `bridge vlan` работает с существующим портом внутри моста (VLAN-aware); `ip link add type vlan` создаёт отдельный сабинтерфейс.

### Связанные документы

- **[VLAN — обзор](../vlan.md)** — фундаментальные принципы сегментации, VTP, QinQ, VXLAN.
- **[Spanning Tree Protocol (STP)](../stp.md)** — профилактика петел, Root Bridge выбор, альтернативы в Leaf-Spine.
- **[Агрегация каналов (Link Aggregation)](../../Concepts/link_aggregation.md)** — LACP, bonding, transmit hash policy.
- **[Меж-VLAN маршрутизация](./vlan_inter_vlan_routing.md)** — SVI, routed port, Router-on-a-Stick.
- **[QoS и приоритизация L2](../qos.md)** — PCP marking, TCAM, traffic classes.
- **[Spanning Tree Protocol (STP)](../stp.md)** — STP hardening и альтернативы в современных ЦОД.

### См. также

- **[VXLAN](../Tunnels/vxlan.md)** — масштабируемая альтернатива VLAN для ЦОД.
- **[Linux Bridge](../../../Linux/Networking/Concepts/linux_bridge.md)** — архитектура программных мостов.