# Меж-VLAN маршрутизация (Inter-VLAN Routing)

## Определения

**Меж-VLAN маршрутизация (Inter-VLAN Routing)** — процесс передачи трафика между логически изолированными сегментами (VLAN) через устройство третьего уровня (L3) модели OSI. Позволяет устройствам в разных широковещательных доменах взаимодействовать друг с другом.

**SVI (Switch Virtual Interface)** — логический интерфейс третьего уровня на коммутаторе, привязанный к конкретному VLAN. Используется как шлюз по умолчанию (Default Gateway) для хостов внутри этого VLAN.

**ROAS (Router-on-a-Stick)** — архитектурный метод, при котором один физический интерфейс маршрутизатора подключается к Trunk-порту коммутатора. Интерфейс разделяется на логические сабинтерфейсы (sub-interfaces), каждый из которых терминирует свой VLAN.

**Routed Port (Маршрутизируемый порт)** — физический порт L3-коммутатора, переведенный в режим "маршрутизатор" (без привязки к VLAN). На него можно назначить IP-адрес напрямую.

**FHRP (First Hop Redundancy Protocol)** — семейство протоколов (HSRP, VRRP, GLBP), обеспечивающих отказоустойчивость шлюза по умолчанию. Несколько маршрутизаторов/коммутаторов образуют виртуальный шлюз (VIP); при отказе активного узла трафик бесшовно переключается на резервный.

**VRF-lite (Virtual Routing and Forwarding)** — механизм виртуализации таблиц маршрутизации, позволяющий одному физическому устройству поддерживать несколько изолированных экземпляров RIB/FIB. Используется для multitenancy и изоляции трафика между клиентами/отделами.

## Основные концепции

### Механизм изоляции и связи
Без устройства L2/L3 (маршрутизатора или L3-коммутатора) пакеты из одной VLAN никогда не попадут в другую. Это фундаментальное свойство сегментации. Процесс маршрутизации включает в себя:
1.  **Ingress:** Прием кадра на интерфейсе L2, принадлежащем VLAN A.
2.  **L3 Lookup:** Поиск целевого IP-адреса в таблице маршрутизации (RIB).
3.  **L2 Rewrite:** Формирование нового заголовка кадра (изменение MAC-адресов источника и назначения) и инкапсуляция в тег целевой VLAN B.
4.  **Egress:** Отправка кадра в VLAN B.

### Поток пакета через SVI (ASIC)
На L3-коммутаторе маршрутизация выполняется аппаратно:
1.  Пакет поступает на порт (L2), попадает в TCAM (Тернарную CAM-память).
2.  ASIC определяет VLAN-тег порта и выполняет L3-lookup в FIB (Forwarding Information Base).
3.  Если назначение — другая VLAN, ASIC:
    - Удаляет старый L2-заголовок (Source/Dest MAC).
    - Инкрементирует TTL.
    - Пересчитывает FCS (Frame Check Sequence).
    - Инкапсулирует пакет в тег новой VLAN.
    - Отправляет на Egress-порт.

Это занимает **единицы микросекунд** (线速转发), в отличие от программной маршрутизации в CPU (миллисекунды).

### Сравнение методов реализации

| Метод | Уровень исполнения | Производительность | Масштаб | Применение |
| :--- | :--- | :--- | :--- | :--- |
| **Физические интерфейсы** | Software/Hardware | Ограничена портами | Низкий | Малые сети, легаси |
| **Router-on-a-Stick (ROAS)** | Software (CPU) | Низкая/Средняя | Средний | Небольшие офисы, Branch-офисы, Linux-шлюзы |
| **SVI (L3-Switching)** | Hardware (ASIC) | Экстремально высокая | Высокий | Enterprise, ЦОД, ядро сети |
| **Routed Ports** | Hardware (ASIC) | Высокая | Высокий | Связи Switch-to-Switch, Switch-to-Router |
| **VRF-lite** | Hardware (ASIC) | Высокая | Средний | Multitenancy, изоляция клиентов |

### Примерная пропускная способность

| Платформа | Метод | Throughput | Латентность |
| :--- | :--- | :--- | :--- |
| Linux (CPU) | ROAS (sub-interfaces) | 1–10 Gbps | 50–500 мкс |
| Cisco ISR (CPU) | ROAS | 1–5 Gbps | 100–1000 мкс |
| Cisco Catalyst 9300 | SVI (ASIC) | 480 Gbps (线速) | 3–10 мкс |
| Juniper QFX5100 | IRB (ASIC) | 2 Tbps (线速) | 2–5 мкс |

## Практические сценарии

### 1. Router-on-a-Stick (ROAS)
Классический метод для сценариев, где маршрутизатор является мощным универсальным устройством, а коммутатор — простым L2.

**Конфигурация (Cisco IOS):**
```cisco
# Настройка сабинтерфейса
interface GigabitEthernet0/0.10
 description *** Gateway for Sales VLAN ***
 # Привязка к VLAN ID 10
 encapsulation dot1Q 10
 ip address 192.168.10.1 255.255.255.0

interface GigabitEthernet0/0.20
 description *** Gateway for Engineering VLAN ***
 encapsulation dot1Q 20
 ip address 192.168.20.1 255.255.255.0
```

**Конфигурация (Juniper Junos):**
```juniper
# Настройка sub-interfaces на интерфейсе ge-0/0/0
set interfaces ge-0/0/0 unit 10 vlan-id 10
set interfaces ge-0/0/0 unit 10 family inet address 192.168.10.1/24
set interfaces ge-0/0/0 unit 20 vlan-id 20
set interfaces ge-0/0/0 unit 20 family inet address 192.168.20.1/24

# Включение интерфейса
set interfaces ge-0/0/0 unit 10 family inet filter input FILTER_VLAN10
```

**Конфигурация (Huawei VRP):**
```huawei
# Создание sub-interfaces
interface GigabitEthernet0/0/0.10
 dot1q termination vid 10
 ip address 192.168.10.1 255.255.255.0

interface GigabitEthernet0/0/0.20
 dot1q termination vid 20
 ip address 192.168.20.1 255.255.255.0

# Включение на родителе
interface GigabitEthernet0/0/0
 undo shutdown
```

**Конфигурация (Linux — программный шлюз):**
```bash
# Включение пересылки пакетов
sudo sysctl -w net.ipv4.ip_forward=1

# Создание VLAN-интерфейсов и назначение IP
sudo ip link add link eth0 name eth0.10 type vlan id 10
sudo ip link add link eth0 name eth0.20 type vlan id 20
sudo ip addr add 192.168.10.1/24 dev eth0.10
sudo ip addr add 192.168.20.1/24 dev eth0.20
sudo ip link set eth0.10 up
sudo ip link set eth0.20 up

# Проверка
ping -c 3 192.168.10.1
ip route show
# → 192.168.10.0/24 dev eth0.10 proto kernel ...
# → 192.168.20.0/24 dev eth0.20 proto kernel ...
```

### 2. Switch Virtual Interface (SVI)
Основной метод для современных корпоративных сетей. Маршрутизация выполняется на скорости портов коммутатора.

**Конфигурация (Cisco IOS):**
```cisco
# Глобальное включение маршрутизации
ip routing

# Создание интерфейса шлюза
interface Vlan 10
 description *** Marketing Gateway ***
 ip address 172.16.10.1 255.255.255.0
 no shutdown

interface Vlan 20
 description *** Server Gateway ***
 ip address 172.16.20.1 255.255.255.0
 no shutdown
```

**Конфигурация (Juniper Junos — IRB):**
```juniper
# Создание логического интерфейса (IRB — Integrated Routing and Bridging)
set interfaces irb unit 10 family inet address 172.16.10.1/24
set interfaces irb unit 20 family inet address 172.16.20.1/24

# Привязка VLAN к IRB
set vlans VLAN10 vlan-id 10 l3-interface irb.10
set vlans VLAN20 vlan-id 20 l3-interface irb.20

# Включение маршрутизации
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1
```

**Конфигурация (Huawei VRP):**
```huawei
# Создание VLANIF-интерфейсов
interface Vlanif10
 ip address 172.16.10.1 255.255.255.0

interface Vlanif20
 ip address 172.16.20.1 255.255.255.0

# Включение маршрутизации
ip routing
```

### 3. Routed Port
Используется для исключения избыточности протоколов L2 (STP) на линках между узлами ядра сети.

```cisco
interface GigabitEthernet1/0/1
 description *** P2P Link to Core-Router ***
 # Отключение функций L2 (VLAN)
 no switchport
 # Назначение IP напрямую
 ip address 10.1.1.2 255.255.255.252
```

### 4. VRF-lite: Multitenancy на одном коммутаторе
Позволяет изолировать таблицы маршрутизации разных клиентов/отделов на одном физическом устройстве.

**Конфигурация (Cisco IOS):**
```cisco
# Создание VRF
vrf definition TENANT_A
 rd 65000:100
 route-target export 65000:100
 route-target import 65000:100

vrf definition TENANT_B
 rd 65000:200
 route-target export 65000:200
 route-target import 65000:200

# Привязка SVI к VRF
interface Vlan 10
 vrf forwarding TENANT_A
 ip address 10.0.10.1 255.255.255.0

interface Vlan 20
 vrf forwarding TENANT_B
 ip address 10.0.20.1 255.255.255.0

# Проверка изоляции
show ip route vrf TENANT_A
# → Видит только маршруты TENANT_A
ping vrf TENANT_A 10.0.10.100
```

**Конфигурация (Linux VRF):**
```bash
# Создание VRF
sudo ip link add vrf-red type vrf table 100
sudo ip link set vrf-red up

# Привязка VLAN к VRF
sudo ip link set eth0.10 master vrf-red
sudo ip addr add 10.0.10.1/24 dev eth0.10

# Маршрутизация в контексте VRF
sudo ip route add default via 10.0.10.254 dev eth0.10 table 100
sudo ip vrf exec vrf-red ping 10.0.10.100
```

### 5. Policy-Based Routing (PBR): маршрутизация по политике
Позволяет направлять трафик из VLAN по разным шлюзам на основе ACL, DSCP, TOS или VLAN ID.

**Конфигурация (Cisco IOS):**
```cisco
# Создание ACL для определения трафика
ip access-list extended VLAN10_TO_DMZ
 permit ip 192.168.10.0 0.0.0.255 10.100.0.0 0.0.255.255

# Создание route-map
route-map PBR_VLAN10 permit 10
 match ip address VLAN10_TO_DMZ
 set ip next-hop 10.0.0.100

# Применение к SVI
interface Vlan 10
 ip policy route-map PBR_VLAN10
```

**Конфигурация (Linux PBR):**
```bash
# Таблица для VLAN 10
sudo ip route add default via 10.0.10.254 table 100

# Правило: трафик из VLAN 10 → таблица 100
sudo ip rule add from 192.168.10.0/24 table 100 priority 100

# Проверка
ip rule show | grep 100
ip route show table 100
```

## Тюнинг и безопасность

### Меж-VLAN ACL
Для предотвращения несанкционированного доступа (например, из VLAN "Гости" в VLAN "Бухгалтерия") ACL применяются непосредственно на интерфейсах SVI или сабинтерфейсах.

```cisco
ip access-list extended SECURE_SERVERS
 permit tcp 192.168.10.0 0.0.0.255 host 192.168.20.100 eq 80
 deny ip any 192.168.20.0 0.0.0.255
 permit ip any any

interface Vlan 10
 ip access-group SECURE_SERVERS in
```

### DHCP Relay (IP Helper)
Хосты в разных VLAN часто нуждаются в централизованном DHCP-сервере. Поскольку широковещательные запросы не проходят через шлюз, используется ретранслятор.

**Cisco IOS:**
```cisco
interface Vlan 10
 ip address 192.168.10.1 255.255.255.0
 # Пересылка DHCP-запросов на сервер в другом VLAN/сети
 ip helper-address 10.200.0.5
```

**Linux (dhcrelay):**
```bash
# Установка
sudo apt install isc-dhcp-relay

# Конфигурация (/etc/default/isc-dhcp-relay)
SERVERS="10.200.0.5"
INTERFACES="eth0.10 eth0.20"

# Запуск
sudo systemctl enable --now isc-dhcp-relay
```

**Детали Option 82 (Relay Agent Information):**
DHCP Relay добавляет Option 82 в DHCP-запрос, содержащий:
- **Circuit ID:** Идентификатор интерфейса (например, `GigabitEthernet0/0.10`).
- **Remote ID:** MAC-адрес ретранслятора (или hostname).

Это позволяет DHCP-серверу определить, из какого VLAN и с какого порта пришёл запрос, и выдать IP из правильного пула.

### Динамическая маршрутизация на SVI (OSPF/EIGRP)

В production SVIAlmost always runs dynamic routing protocols для автоматического обмена маршрутами между VLAN.

**OSPF на SVI (Cisco):**
```cisco
router ospf 1
 router-id 10.200.0.1
 network 192.168.10.0 0.0.0.255 area 0
 network 192.168.20.0 0.0.0.255 area 0
 passive-interface Vlan 10
 passive-interface Vlan 20
```

**OSPF на SVI (Juniper Junos):**
```bash
set protocols ospf area 0 interface irb.10
set protocols ospf area 0 interface irb.20
set protocols ospf area 0 interface lo0.0 passive
```

**OSPF на SVI (Huawei VRP):**
```huawei
ospf 1 router-id 10.200.0.1
 area 0.0.0.0
  network 192.168.10.0 0.0.0.255
  network 192.168.20.0 0.0.0.255
```

> **Важно:** `passive-interface` на SVI — чтобы не отправлять OSPF-Hello через хосты. OSPF-сессия работает только на point-to-point линках (trunk).

### FHRP: Отказоустойчивость шлюза
При использовании одного маршрутизатора/L3-коммутатора как шлюза — это single point of failure. FHRP решает эту проблему.

| Протокол | Тип | Балансировка | Платформа |
| :--- | :--- | :--- | :--- |
| **HSRP** | Cisco-проприетарный | Active/Standby | Cisco IOS |
| **VRRP** | Стандартный (RFC 5798) | Active/Standby | Cisco, Juniper, Huawei, Linux |
| **GLBP** | Cisco-проприетарный | Active/Active (AVG + AVFs) | Cisco IOS |

**HSRP (Cisco — Hot Standby Router Protocol):**
```cisco
# Active-узел
interface Vlan 10
 ip address 192.168.10.2 255.255.255.0
 standby 1 ip 192.168.10.1
 standby 1 priority 110
 standby 1 preempt

# Standby-узел
interface Vlan 10
 ip address 192.168.10.3 255.255.255.0
 standby 1 ip 192.168.10.1
 standby 1 priority 100
 standby 1 preempt
```

**VRRP (стандарт — Virtual Router Redundancy Protocol, RFC 5798):**
```cisco
# Master-узел
interface Vlan 10
 ip address 192.168.10.2 255.255.255.0
 vrrp 10 ip 192.168.10.1
 vrrp 10 priority 110
 vrrp 10 preempt

# Backup-узел
interface Vlan 10
 ip address 192.168.10.3 255.255.255.0
 vrrp 10 ip 192.168.10.1
 vrrp 10 priority 100
```

**GLBP (Cisco — Gateway Load Balancing Protocol):**

GLBP Unlike HSRP/VRRP, provides Active/Active балансировку: один виртуальный IP, но несколько физических шлюзов распределяют трафик.

```cisco
# AVG (Active Virtual Gateway) —选举 Leader
interface Vlan 10
 ip address 192.168.10.2 255.255.255.0
 glbp 1 ip 192.168.10.1
 glbp 1 priority 110
 glbp 1 preempt
 glbp 1 load-balancing round-robin

# AVF (Active Virtual Forwarder) — второй узел
interface Vlan 10
 ip address 192.168.10.3 255.255.255.0
 glbp 1 ip 192.168.10.1
 glbp 1 priority 100
 glbp 1 preempt
 glbp 1 load-balancing round-robin
```

**VRRP на Linux (Keepalived):**
```bash
# /etc/keepalived/keepalived.conf
vrrp_instance VLAN10_GW {
    state MASTER
    interface eth0.10
    virtual_router_id 51
    priority 110
    advert_int 1
    virtual_ipaddress {
        192.168.10.1/24
    }
}
```

### QoS-маркировка на границе VLAN
При переходе трафика между VLAN рекомендуется пересчитывать DSCP/PCP:

```cisco
# Маркировка входящего трафика из VLAN 10
policy-map MARK_VLAN10
 class VLAN10_USER
  set dscp af21

interface Vlan 10
 service-policy input MARK_VLAN10
```

## Диагностика и устранение неисправностей

### Типичные ошибки

1.  **L2/L3 Mismatch:** VLAN создан на коммутаторе, но интерфейс SVI находится в статусе `down/down`, так как в этом VLAN нет ни одного активного (UP) порта (правило Autostate).
2.  **Encapsulation Error:** В схеме ROAS номер VLAN в команде `encapsulation dot1q` на маршрутизаторе не совпадает с реальным тегом трафика.
3.  **MTU Overhead:** При использовании ROAS поверх туннелей или специфических линков может потребоваться корректировка MTU для учета 4-байтового тега.
4.  **Native VLAN Mismatch:** Нетегированный трафик (ARP, DHCP) попадает в неправильный VLAN, теряется связь.
5.  **Gateway Not Responding:** Шлюз (SVI/ROAS) не отвечает на ARP — проверьте, что интерфейс UP и IP назначен корректно.
6.  **Asymmetric Routing:** Трафик идёт через один шлюз, а возврат — через другой (при FHRP с двумя активными paths). Может вызвать проблемы с stateful firewall.
7.  **FHRP Split-Brain:** Оба узла в состоянии MASTER из-за блокировки VRRP-трафика (протокол 112) в firewall.

### Команды проверки

**Cisco IOS:**
```cisco
# Проверка состояния SVI
show ip interface brief | include Vlan
# → Vlan10  192.168.10.1    YES manual  up  up

# Проверка VLAN, активных для маршрутизации
show vlans
show interfaces trunk

# Проверка таблицы маршрутизации
show ip route
show ip route 192.168.20.0

# Проверка ARP-таблицы
show arp | include 192.168.10

# Проверка FHRP
show standby brief
show vrrp brief

# Трассировка пути
traceroute 192.168.20.100

# Проверка ACL counters
show access-lists SECURE_SERVERS
```

**Juniper Junos:**
```bash
# Проверка интерфейсов
show interfaces irb brief
show vlans

# Проверка маршрутов
show route 192.168.20.0/24
show route table inet.0

# Проверка ARP
show arp | match 192.168.10

# Трассировка
traceroute 192.168.20.100
```

**Huawei VRP:**
```bash
# Проверка VLANIF
display ip interface brief | include Vlanif
display vlan

# Проверка маршрутов
display ip routing-table 192.168.20.0

# Проверка ARP
display arp all | include 192.168.10

# Трассировка
tracert 192.168.20.100
```

**Linux:**
```bash
# Проверка интерфейсов и IP
ip -d link show type vlan
ip addr show eth0.10

# Проверка маршрутов
ip route show
ip route get 192.168.20.100

# Проверка пересылки
cat /proc/sys/net/ipv4/ip_forward
# → 1

# Проверка ARP
ip neigh show dev eth0.10

# Трассировка
traceroute 192.168.20.100

# Захват трафика (поиск тегов, ARP)
sudo tcpdump -i eth0 -e -nn vlan 10 -c 10
sudo tcpdump -i eth0.10 -e -nn arp -c 5

# Проверка iptables (firewall)
iptables -L FORWARD -n -v
```

### Пошаговая процедура диагностики

```
1. ФИЗИЧЕСКИЙ УРОВЕНЬ
   └─ show interfaces <iface> (state, speed, duplex)
   └─ ip link show <iface> (Linux: state UP?)

2. VLAN-КОНФИГУРАЦИЯ
   └─ show interfaces trunk (Trunk allows VLAN?)
   └─ show vlan brief (VLAN exists, ports assigned?)
   └─ bridge vlan show (Linux: VLAN table на порту)

3. L3-ИНТЕРФЕЙС
   └─ show ip interface brief (SVI/ROAS UP, IP assigned?)
   └─ ip addr show (Linux: IP на интерфейсе)
   └─ show interfaces <subif> (encapsulation matches VLAN ID?)

4. МАРШРУТИЗАЦИЯ
   └─ show ip route <dest> (маршрут есть?)
   └─ ip route show (Linux: все маршруты)
   └─ traceroute <dest> (где теряется?)

5. ARP / L2-СВЯЗНОСТЬ
   └─ show arp | include <ip> (MAC резолвится?)
   └─ ip neigh show (Linux:邻居 reaching?)
   └─ ping -c 3 <gateway> (шлюз отвечает?)

6. FHRP
   └─ show standby brief / show vrrp brief (активный узел?)
   └─ show standby / show vrrp (роли, таймеры, VIP)

7. FIREWALL / ACL
   └─ show access-lists (counters растут?)
   └─ iptables -L FORWARD -n -v (Linux: DROP/REJECT?)
```

## Edge Cases

### 1. Double 802.1Q tagging (VLAN Hopping)
Если на интерфейсе маршрутизатора/коммутатора приходят кадры с двойным тегом (QinQ или атака), L3-lookup может обработать только внутренний тег. Убедитесь, что:
- На Trunk-порту разрешены только нужные VLAN.
- Используйте `switchport trunk allowed vlan` для ограничения.

### 2. ARP Proxy и нативный VLAN
Если на двух разных SVI в одном VLAN включен ARP Proxy, хосты могут получить неверные MAC-адреса шлюза. Отключайте ARP Proxy на интерфейсах шлюза.

### 3. MTU и Path MTU Discovery
При ROAS каждый 802.1Q тег добавляет 4 байта. Если MTU физического интерфейса = 1500, полезная нагрузка = 1496. При QinQ = 1492. Это критично для TCP (PMTUD) и туннелей (GRE, IPsec, WireGuard).

### 4. Blackhole Routes при VRF-lite
Если в VRF нет маршрута по умолчанию (default route), трафик за пределы подсети будет отброшен. Всегда проверяйте `show ip route vrf <name>` после настройки.

### 5. ICMP Redirect
Если в сети несколько маршрутизаторов, Linux/Windows могут генерировать ICMP Redirect, направляя трафик напрямую. Для шлюза это нежелательно:
```bash
sudo sysctl -w net.ipv4.conf.all.send_redirects=0
sudo sysctl -w net.ipv4.conf.<iface>.send_redirects=0
```

### 6. IGMP Snooping и multicast в inter-VLAN
Если multicast-проигрыватель (например, IPTV) работает через inter-VLAN, убедитесь, что IGMP Snooping включён на L3-коммутаторе и multicast-router yerleşён на SVI.

## Best Practices

1. **Используйте SVI** вместо ROAS при количестве VLAN > 10 или при пропускной способности > 1 Gbps.
2. **Настройте FHRP** (VRRP/HSRP) на каждом VLAN с шлюзом — это исключает single point of failure.
3. **Ограничивайте Trunk:** `switchport trunk allowed vlan 10,20,30` — не пропускайте все VLAN.
4. **Удаляйте VLAN 1** с интерфейсов шлюза, если она не используется.
5. **Корректируйте MTU** при ROAS поверх туннелей (GRE, IPsec): `ip mtu 1400` на сабинтерфейсах.
6. **Документируйте VLAN-таблицу:** VLAN ID ↔ Name ↔ Subnet ↔ Gateway IP для каждого сегмента.
7. **Используйте PBR** для маршрутизации по политике (например, трафик в DMZ через отдельный шлюз).
8. **Мониторьте FHRP:** настройте SNMP/Syslog на событиях переключения Master/Backup.
9. **Используйте VRF-lite** для multitenancy вместо ACL — это надёжнее и проще в аудите.
10. **Проверяйте ARP:** если ping до шлюза не работает,首先 проверьте ARP-таблицу (`show arp`, `ip neigh show`).

## Дополнительная информация

### Смежные темы
- **[VLAN — обзор](../vlan.md)** — основы сегментации и типы портов.
- **[Trunk и Native VLAN](./vlan_trunk_native.md)** — настройка магистралей для ROAS.
- **[Настройка VLAN в Linux](./vlan_linux_diagnostics.md)** — реализация маршрутизации на программных роутерах.
- **[VRF в сетевых технологиях](../../../Linux/Networking/vrf.md)** — виртуализация таблиц маршрутизации для полной изоляции.
- **[QoS и приоритезация](../../Concepts/qos.md)** — управление качеством обслуживания при переходе между сетями.
- **[DHCP Relay](../../Protocols/DHCP/dhcp_relay.md)** — ретрансляция DHCP-запросов через VLAN.
- **[Keepalived и VRRP](../../ServicesAndTools/keepalived_overview.md)** — высокая доступность шлюзов на Linux.
- **[Policy-Based Routing](../../../Linux/Networking/Policy_Based_Routing/scenarios.md)** — маршрутизация по политике.
- **[OSPF](../../Protocols/ospf.md)** — динамическая маршрутизация на SVI.
- **[Агрегация каналов (LACP)](../../Concepts/link_aggregation.md)** — Port-Channel для отказоустойчивых транков.
- **[Ansible — сетевая автоматизация](../../../Ansible/ansible_network_automation.md)** — управление VLAN и routing через Ansible.
