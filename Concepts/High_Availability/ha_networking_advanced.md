# Продвинутые сетевые технологии для высокой доступности

**Актуально для:** Linux 5.4+/6.x, BIRD 2.17+/3.x, FRR 10.x, Open vSwitch 3.3 LTS/3.7+, EVPN RFC 7432, VXLAN RFC 7348

---

## Предварительные требования

Для полноценного понимания данного раздела предполагается знакомство с:
- Базовыми концепциями **[высокой доступности](./ha_overview.md)**: RTO, RPO, MTTR, SPOF, Active-Active vs Active-Passive
- Механизмами **[failover и heartbeat](./ha_failover_mechanisms.md)**: VRRP, кворум, STONITH, Keepalived
- Сетевым стеком Linux: sysctl, iptables/nftables, Namespaces, VLAN, bonding/LACP
- Протоколами маршрутизации: BGP, OSPF, ECMP — см. **[Сетевой уровень (L3)](../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md)**
- Инструментами мониторинга: Prometheus (blackbox exporter, node_exporter), Grafana, Zabbix
- Системой управления конфигурацией: Ansible, NAUTobot, GitOps-подходы к сетевым конфигурациям

---

## Определения

**BFD (Bidirectional Forwarding Detection)** — протокол обнаружения отказов на уровне линка (L1/L2), работающий независимо от любых сетевых протоколов. Обеспечивает обнаружение обрывов канала за миллисекунды (обычно 50-300 мс), что на порядок быстрее, чем стандартные таймауты OSPF/BGP (несколько секунд). BFD используется в паре с VRRP, OSPF, BGP, LACP для ускорения detection и failover.

**MLAG (Multi-Chassis Link Aggregation)** — технология объединения линков между несколькими коммутаторами в один логический порт (LAG). Позволяет использовать два коммутатора как единый logical device для балансировки и HA. Аналоги: Cisco vPC, Juniper MC-LAG, Arista MLAG, Cumulus VXLAN-MLAG, OVS EVPN Multi-Homing.

**EVPN (Ethernet VPN)** — протокол для распространения информации о MAC-адресах и VLAN через BGP. Используется в современных Data Center для построения overlay-сетей (VXLAN) с централизованным контролем. Обеспечивает Anycast Gateway, MAC mobility, symmetric IRB, ARP/ND suppression.

**VXLAN (Virtual Extensible LAN)** — технология overlay-сети, инкапсулирующая Ethernet-кадры в UDP-пакеты. Позволяет создавать логические L2-сегменты поверх L3-сети. VNI (VXLAN Network Identifier) — 24-битный идентификатор, поддерживающий до 16M сегментов. Стандартный порт: UDP 4789.

**ECMP (Equal-Cost Multi-Path)** — механизм балансировки нагрузки на маршрутизаторах, распределяющий трафик по нескольким равноправным путям. Используется для увеличения пропускной способности и HA.

**Anycast Gateway** — один и тот же IP-адрес (шлюз) анонсируется из нескольких точек Presence. Клиент автоматически подключается к ближайшему шлюзу. При отказе точки трафик перенаправляется на следующую ближайшую.

**LACP (Link Aggregation Control Protocol)** — протокол динамического объединения физических линков в логический канал (bond). При отказе одного линка трафик перераспределяется на оставшиеся. Интегрируется с BFD для ускорения detection.

---

## Основные концепции

### BFD (Bidirectional Forwarding Detection)

BFD работает независимо от любых протоколов и обнаруживает обрывы линка за миллисекунды.

**Как работает:**
1. Два соседних устройства обмениваются контрольными пакетами BFD
2. Если устройство не получает пакеты в течение `detect time` — линк считается упавшим
3. Это запускает failover в связанном протоколе (VRRP, OSPF, BGP)

**Архитектура компонентов:**
- **bfdd** — демон BFD (входит в состав FRR или доступен отдельно)
- ** peer-сессия** — двустороннее соединение между двумя точками
- **control plane** — взаимодействие с routing daemon через API или CLI

**Таймеры:**
| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **desired_min_tx_interval** | 300 мс | Как часто устройство хочет отправлять пакеты |
| **required_min_rx_interval** | 300 мс | Минимальный интервал, который устройство может принимать |
| **detect_multiplier** | 3 | Количество пропущенных пакетов перед объявлением сбоя |

**Формула detection time:**
```
detection_time = required_min_rx_interval × detect_multiplier
```

Пример: 300 мс × 3 = 900 мс обнаружения сбоя.

**Интеграция с routing daemons (кратко):**
- **VRRP:** через Keepalived — см. детальную конфигурацию в [Механизмы Failover и Heartbeat](./ha_failover_mechanisms.md)
- **BGP:** через FRR/BIRD — см. [BGP: Глубокое погружение](../../Networking/Protocols/bgp.md)
- **OSPF:** через FRR/BIRD — `bfd all-interfaces` в OSPF-конфигурации
- **LACP:** через `bond` параметры — `miimon` + `bfd` в bonding driver

**Системные требования для production:**
- NTP-синхронизация (дрейф < 10 мс) — BFD использует временные метки
- Выделенный CPU core для bfdd при нагрузке > 100K sessions
- `net.ipv4.ip_forward=1` для routed environments
- Firewall: разрешить UDP 3784 (single-hop) и 3785 (multi-hop) между пирами

**Преимущества BFD:**
- Обнаружение сбоя за **< 1 секунды** (против 3-30 секунд у OSPF/BGP)
- Работает на L1/L2 уровне, независимо от протоколов
- Поддерживается всеми современными коммутаторами и маршрутизаторами
- Стандартизирован (RFC 5880, RFC 7881)

### MLAG / vPC / MC-LAG

MLAG позволяет использовать два коммутатора как единый logical device.

**Архитектура:**
```
          ┌─────────────┐
          │  Switch 1   │
          │  (Primary)  │
          └──────┬──────┘
                 │ MLAG peer-link (LACP)
          ┌──────┴──────┐
          │  Switch 2   │
          │  (Secondary)│
          └──────┬──────┘
                 │
     ┌───────────┼───────────┐
     │           │           │
   Server1     Server2     Server3
     │           │           │
    LACP      LACP        LACP
```

**Ключевые компоненты:**
1. **Peer-link** — соединение между коммутаторами для обмена информацией о состоянии (LACP bundle, VXLAN tunnel, или dedicated physical link)
2. **Peer-keepalive** — контроль состояния партнера (через L3 или dedicated link)
3. **Domain** — логический домен, объединяющий два коммутатора

**Реализации по вендорам:**
| Вендор | Название | Особенности |
| :--- | :--- | :--- |
| **Cisco** | vPC / vPC+ | Peer-link + vPC peer-keepalive + virtual ARP |
| **Arista** | MLAG / MLAG+ | Peer-link Port-Channel + peer-address |
| **Juniper** | MC-LAG / VChassis | ICC (Inter-Chassis Control) protocol |
| **Cumulus / NVIDIA** | MLAG | на базе CLAG (Cumulus MLAG), peer-link + peer-keepalive |
| **OVS** | EVPN Multi-Homing | Symmetric IRB, Type 4 (Ethernet Segment) |

**Преимущества:**
- **Устранение SPOF** — отказ одного коммутатора не приводит к потере связности
- **Active-Active** — оба коммутатора могут forwarding трафик
- **Быстрый failover** — < 100 мс при отказе коммутатора/линка

**Ограничения:**
- Требует поддержки вендора (закрытые протоколы управления)
- Сложность настройки и troubleshooting
- Некоторые функции (Spanning Tree) могут не работать
- Peer-link — потенциальная точка contention

### EVPN + VXLAN

EVPN используется как control plane для VXLAN overlay-сетей.

**Архитектура:**
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   VTEP 1    │────▶│   VTEP 2    │────▶│   VTEP 3    │
│ (Switch 1)  │     │ (Switch 2)  │     │ (Switch 3)  │
└─────────────┘     └─────────────┘     └─────────────┘
        │                   │                   │
        │  VXLAN Tunnel     │                   │
        │  (UDP 4789)       │                   │
        │                   │                   │
    VM/Container          VM/Container        VM/Container
```

**Компоненты:**
1. **VTEP (VXLAN Tunnel Endpoint)** — терминация VXLAN туннеля на коммутаторе/хосте
2. **VNI (VXLAN Network Identifier)** — идентификатор логической сети (24 бита = 16M сетей)
3. **EVPN Type 2 (MAC/IP advertisement)** — распространение MAC/IP через BGP
4. **Anycast Gateway** — единый шлюз для всей overlay-сети
5. **Ethernet Segment (Type 4)** — для Multi-Homing (MLAG-аналоги в EVPN)

**Route Types (основные):**
| Type | Назначение |
| :--- | :--- |
| **Type 2** | MAC/IP advertisement — анонс MAC и IP хоста |
| **Type 3** | Inclusive Multicast — подписка на VNI (multicast group) |
| **Type 4** | Ethernet Segment — для Multi-Homing (MLAG) |
| **Type 5** | IP Prefix — маршрутизация между VNI (L3-VNI) |

**Преимущества:**
- **Масштабируемость** — 16M логических сетей (против 4094 VLAN)
- **Гео-распределение** — L2-сеть поверх L3 инфраструктуры
- **Автоматизация** — интеграция с CNI (Calico, Cilium, OVN-Kubernetes)
- **Anycast Gateway** — единый шлюз во всей сети
- **MAC Mobility** — отслеживание миграции VM между VTEP

**MAC/VLAN mobility:**
- При миграции VM MAC-адрес перемещается между VTEP
- EVPN анонсирует новый VTEP с флагом mobility
- Старые VTEP отзывают MAC-запись через timeout
- Настройка: `mac-mobility` в FRR или `mac_limit` в OVS

**VXLAN и Geneve (сравнение):**
| Протокол | Оверхед | Масштаб | Транспорт | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **VXLAN** | 50 B | 16M VNI | UDP 4789 | Стандарт для DC |
| **Geneve** | 50+ B | 16M VNI | UDP 6081 | Гибкий (TLV), стандарт в OVN |

### ECMP (Equal-Cost Multi-Path)

ECMP балансирует трафик по нескольким равноправным путям.

**Архитектура:**
```
              ┌─────────────┐
              │   Router    │
              │   (ECMP)    │
              └──────┬──────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
       Link A      Link B      Link C
         │           │           │
     ┌───▼───┐   ┌───▼───┐   ┌───▼───┐
     │ Dest  │   │ Dest  │   │ Dest  │
     │  via  │   │  via  │   │  via  │
     │ A     │   │ B     │   │ C     │
     └───────┘   └───────┘   └───────┘
```

**Алгоритмы хэширования:**
- **Source/Dest IP** — классический round-robin по потоку
- **5-tuple** — IP + port + protocol для лучшей балансировки
- **ECMP Consistent Hashing** — минимизирует перераспределение при изменении путей
- **L4-aware hashing** — учитывает порты для TCP/UDP трафика

**Hashing в Linux:**
```
sysctl net.ipv4.fib_multipath_hash_policy=1  # 5-tuple (src/dst IP + ports + protocol)
sysctl net.ipv4.fib_multipath_hash_policy=0  # только src/dst IP
```

**Преимущества ECMP:**
- Увеличение пропускной способности в N раз (где N — количество путей)
- Автоматическая балансировка без внешних балансировщиков
- HA — при отказе одного пути трафик перетекает на остальные

### Anycast Gateway

Anycast Gateway — один и тот же IP/MAC анонсируется из нескольких VTEP/коммутаторов.

**Как работает:**
1. На каждом VTEP настраивается один и тот же SVI (Switched Virtual Interface) с одинаковым IP
2. При отправке ARP/ND request VTEP отвечает локально (ARP Suppression)
3. Клиент получает MAC ближайшего VTEP
4. При отказе VTEP BGP удаляет Type 2/Type 5 route, трафик перенаправляется на другой VTEP

**Преимущества:**
- Локальный выход для трафика (lower latency)
- Автоматический failover через BGP
- Поддержка mobility (VM миграция между racks)

---

## Практические сценарии

### Сценарий 1: LACP + BFD для быстрого failover линка

LACP сам обнаруживает отказ линка за ~3 секунды (LACP timeout). BFD сокращает это до < 1 секунды.

```bash
# Создание bond с LACP + BFD
# /etc/network/interfaces или NetworkManager
bond0:
  mode: 802.3ad
  miimon: 100        # LACP heartbeat каждые 100мс
  updelay: 200       # ждать 200мс перед подъемом линка
  downdelay: 200     # ждать 200мс перед опусканием
  bfd: true          # BFD для каждого линка
  bfd_interval: 300  # 300мс
  bfd_min_rx: 300
  bfd_multiplier: 3
```

**Валидация:**
```bash
# Проверка bond status
cat /proc/net/bonding/bond0
# → Slave Interface: eth1
# → MII Status: up
# → BFD Status: up

# Проверка BFD peer
bfddcli show peer
# → Peer 10.0.0.2: State Up, Latency 0.3ms

# Тест failover: отключение линка
ip link set eth1 down
# → bond0 переключается на eth2 за < 1 секунду
```

### Сценарий 2: MLAG для Data Center

```bash
# Arista EOS: настройка MLAG
mlag configuration
  domain-id DC1
  local-interface Vlan4094
  peer-address 10.0.0.2
  peer-link Port-Channel1000

interface Port-Channel1000
  switchport mode trunk
  channel-group 1000 mode active

interface Ethernet1
  channel-group 1 mode active
  spanning-tree portfast
```

**Для OVS (EVPN Multi-Homing):**
```bash
# Создание Ethernet Segment (Type 4) в FRR
router bgp 65000
  neighbor 10.0.0.2 remote-as 65000
  !
  address-family evpn
    neighbor 10.0.0.2 activate
    advertise-all-vni
    advertise-svi-ip
    !
    # Multi-Homing: Ethernet Segment
    segment DC1-SITE1
      esi 00:11:22:33:44:55:66:77:88:99
      esi-label 100
  exit-address-family
```

### Сценарий 3: EVPN + VXLAN для K8s

```bash
# FRR: настройка EVPN как underlay для K8s
# /etc/frr/frr.conf
router bgp 65000
  bgp router-id 10.0.0.1
  neighbor 10.0.0.2 remote-as 65000
  neighbor 10.0.0.2 fall-over bfd
  !
  address-family l2vpn evpn
    neighbor 10.0.0.2 activate
    advertise-all-vni
    advertise-svi-ip
    advertise-mac-mobility
    !
    # Anycast Gateway
    vni 1000
      rd 10.0.0.1:1000
      route-target import 65000:1000
      route-target export 65000:1000
  exit-address-family
```

**Валидация:**
```bash
# Проверка EVPN соседства
vtysh -c "show bgp evpn summary"
# → Neighbor    AS    Up/Down  St/PfxRcd
# → 10.0.0.2    65000 00:01:23 5

# Проверка MAC advertisement
vtysh -c "show bgp evpn route-type mac-ip"
# → Route type 2, mac 00:11:22:33:44:55, ip 192.168.1.10

# Проверка VXLAN FDB
bridge fdb show dev vxlan1000
# → 00:11:22:33:44:55 dst 10.0.0.2 dev vxlan1000 self permanent
```

### Сценарий 4: ECMP для redundant uplinks

```bash
# BIRD: ECMP с consistent hashing
# /etc/bird/bird.conf
router id 10.0.0.1;

protocol kernel {
    export all;
}

protocol ospf {
    area 0 {
        interface "eth0" {
            cost 10;
        };
    };
}

# ECMP к Dest via two next-hops
protocol static {
    route 192.168.1.0/24 next-hop 10.0.0.10;
    route 192.168.1.0/24 next-hop 10.0.0.11;
}
```

**Валидация:**
```bash
# Проверка ECMP таблицы
ip route show
# → default proto static
# →  nexthop via 10.0.0.10 dev eth0 weight 1
# →  nexthop via 10.0.0.11 dev eth0 weight 1

# Проверка конкретного потока
ip route get 192.168.1.5 from 10.0.0.100
# → 192.168.1.5 via 10.0.0.10 dev eth0

# Проверка хэша
ip route get 192.168.1.5 from 10.0.0.101
# → 192.168.1.5 via 10.0.0.11 dev eth0
```

---

## Диагностика и устранение неисправностей

| Проблема | Вероятная причина | Диагностические команды | Решение |
| :--- | :--- | :--- | :--- |
| **BFD session DOWN** | Firewall блокирует UDP 3784/3785, NTP дрейф > 10 мс | `bfddcli show peer`, `journalctl -u frr -u bfdd` | Разрешить UDP 3784/3785 между пирами, настроить chrony |
| **ECMP: неравномерная балансировка** | Неправильный хэш, asymmetric routing | `ip route get`, `ss -ti` | Настроить 5-tuple hashing, проверить rp_filter |
| **MLAG: traffic не балансируется** | Peer-link не активен, конфигурация не синхронизирована | `show mlag` (vendor CLI), `ovs-vsctl show` | Проверить peer-link, VLAN consistency |
| **VXLAN: пакеты не доходят** | VTEP недоступен, firewall блокирует UDP 4789 | `tcpdump -i any udp port 4789`, `bridge fdb show` | Проверить VTEP IP, firewall, VNI, MTU |
| **EVPN: MAC не анонсируется** | BGP сессия не установлена, VNI не настроен | `show bgp evpn summary`, `vtysh -c "show bgp evpn route-type mac-ip"` | Проверить BGP, VNI mapping, MAC mobility |
| **Anycast: ARP storm** | Отсутствует ARP Suppression, BUM-трафик flood | `tcpdump -i vxlan10 arp -c 100` | Включить ARP Suppression в EVPN, уменьшить количество VNI |
| **BFD: ложные срабатывания** | Сетевые задержки > detect time, CPU starvation | `bfddcli show peer`, `mpstat -P ALL 1` | Увеличить detect_multiplier или интервалы, выделить CPU affinity |
| **LACP + BFD: bond не переключается** | BFD session не поднимается, неправильный driver | `cat /proc/net/bonding/bond0`, `ethtool -S bond0` | Проверить BFD peer, убедиться что bonding driver поддерживает BFD |
| **ECMP: asymmetric routing** | rp_filter=1, connection tracking不对称 | `sysctl net.ipv4.conf.all.rp_filter`, `conntrack -L` | Установить rp_filter=2, отключить conntrack для ECMP трафика |
| **VXLAN: фрагментация** | MTU overlay > underlay MTU, jumbo frames отключены | `ping -M do -s 1472 <remote>`, `ip link show` | Установить MTU=1450 на VXLAN-интерфейсе, включить jumbo frames |

---

## Лучшие практики (Best Practices)

1. **Используйте BFD с VRRP/BGP/OSPF/LACP:** BFD сокращает время обнаружения сбоя с секунд до миллисекунд. Обязателен для production. Настройте NTP с дрейфом < 10 мс.

2. **MLAG требует планирования:** Убедитесь, что peer-link имеет достаточную пропускную способность (не менее 2x суммарной ширины downstream-линков). Используйте отдельный VLAN для peer-link.

3. **EVPN для автоматизации:** Используйте EVPN как control plane для VXLAN в K8s и Data Center. Интегрируйте с CNI (Calico, Cilium, OVN-Kubernetes) для автоматического назначения IP и MAC.

4. **ECMP consistent hashing:** Используйте consistent hashing или 5-tuple hashing для ECMP, чтобы минимизировать перераспределение потоков при изменении топологии. Настройте `fib_multipath_hash_policy=1`.

5. **Мониторинг BFD и EVPN:** Настройте алерты на `bfd_state != Up`, `evpn_peer_down`, `mlag_peer_link_down`. BFD и EVPN — критичные компоненты для быстрого failover.

6. **Anycast Gateway для глобальных сервисов:** Используйте Anycast Gateway для шлюзов в Data Center. Это обеспечивает локальный выход для трафика и автоматический failover через BGP.

7. **VXLAN MTU:** Увеличьте MTU на всех интерфейсах до 9000 (jumbo frames) для underlay, чтобы избежать фрагментации. Настройте MTU=1450 на VXLAN-интерфейсах.

8. **Разделение сетей:** Выделяйте отдельные VLAN/подсети для разных типов трафика (management, replication, client). Используйте VNI для логической изоляции в overlay.

9. **Конфигурация в Git:** Храните конфигурации keepalived, FRR/BIRD, OVS в Git. Используйте Ansible/NAUTobot для deployment и валидации. Сетевая конфигурация — критическая инфраструктура.

10. **Тестирование failover:** Регулярно выполняйте плановый failover: отключение линка, коммутатора, VTEP. Используйте Chaos Engineering-подходы: `iptables -A INPUT -p vrrp -j DROP`, `echo c > /proc/sysrq-trigger`.

---

## Граничные случаи и ограничения (Edge Cases)

- **BFD и высокие задержки:** При RTT > 100 мс между узлами увеличьте `desired_min_tx_interval` до 1-3 секунд, чтобы избежать ложных срабатываний. Для cross-datacenter используйте BFD multi-hop (UDP 3785).

- **MLAG и STP:** В некоторых конфигурациях STP может блокировать порты. Убедитесь, что STP настроен правильно (rapid-pvst, portfast) или отключен на peer-link.

- **VXLAN и фрагментация:** VXLAN добавляет 50 байт оверхеда. При MTU 1500 доступно только 1450 байт для полезных данных. Настройте jumbo frames. Geneve добавляет еще больше оверхеда из-за TLV.

- **ECMP и asymmetric routing:** При использовании ECMP убедитесь, что return traffic идет через тот же путь. Установите `net.ipv4.conf.all.rp_filter=2` (loose mode) для разрешения асимметрии.

- **EVPN и MAC mobility:** При миграции VM MAC-адрес может быстро перемещаться между VTEP. Настройте `mac-mobility` и `mac-limit` для предотвращения flapping и табличного переполнения.

- **Anycast и BGP convergence:** BGP конвергенция занимает 30-60 секунд. Для быстрого failover используйте BFD + BGP. Настройте `maximum-paths` и `bgp bestpath bandwidth ignore` для ECMP.

- **BFD и CPU starvation:** При большом количестве BFD sessions (> 1000) выделите отдельный CPU core для bfdd (`cpumask` в systemd). Мониторьте `bfd_session_up` метрики.

- **LACP + BFD: race condition:** При быстром переключении линка LACP и BFD могут генерировать конфликтующие события. Настройте `updelay`/`downdelay` для debouncing.

- **ECMP и conntrack:** При использовании ECMP таблица `nf_conntrack` может переполниться. Мониторьте `conntrack -C` и увеличьте `nf_conntrack_max`. Для known traffic используйте `-j NOTRACK`.

- **VXLAN и multicast в облаке:** В облачных средах (AWS, GCP) IP-multicast часто заблокирован. Используйте HER (Head-End Replication) или BGP EVPN вместо multicast.

---

## Дополнительная информация

### Связь с другими концепциями

- **[Механизмы Failover и Heartbeat](./ha_failover_mechanisms.md)** — VRRP, STONITH, Keepalived, кворум
- **[Балансировка нагрузки](./ha_clustering_and_load_balancing.md)** — L4/L7 балансировка, IPVS, HAProxy
- **[Сетевой стек Linux](../../Linux/Networking/Concepts/linux_network_interfaces.md)** — sysctl, iptables, nftables, bonding
- **[BGP: Глубокое погружение](../../Networking/Protocols/bgp.md)** — EVPN, Anycast, BFD
- **[VXLAN (Virtual Extensible LAN)](../../Networking/Tunnels/vxlan.md)** — детали инкапсуляции, MTU, offload
- **[VRRP/HSRP/GLBP](../../Networking/Protocols/vrrp_hsrp_glbp.md)** — FHRP протоколы
- **[Сетевой уровень (L3)](../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md)** — ECMP, Anycast, маршрутизация
- **[Практические сценарии маршрутизации](../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/routing_scenarios.md)** — ECMP, Anycast, PBR
- **[MTU и VPN](../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — fragmentation, MSS clamping

### Полезные ссылки

- [BFD RFC 5880](https://tools.ietf.org/html/rfc5880)
- [VXLAN RFC 7348](https://tools.ietf.org/html/rfc7348)
- [EVPN RFC 7432](https://tools.ietf.org/html/rfc7432)
- [BIRD Documentation](https://bird.network.cz/)
- [FRRouting Documentation](https://docs.frrouting.org/)
- [Open vSwitch Documentation](https://docs.openvswitch.org/)
- [Open vSwitch Releases](https://www.openvswitch.org/releases/)

---

## Контрольный список проектирования сетевой HA

- [ ] BFD настроен для всех критичных линков (VRRP, BGP, OSPF, LACP)
- [ ] NTP синхронизирован (дрейф < 10 мс) — обязательно для BFD
- [ ] MLAG/EVPN Multi-Homing развернут для Data Center (если требуется)
- [ ] VXLAN MTU настроен: jumbo frames 9000 в underlay, 1450 в overlay
- [ ] ECMP настроен для redundant uplinks с 5-tuple hashing
- [ ] Anycast Gateway развернут для критичных сервисов
- [ ] Firewall разрешает UDP 3784/3785 (BFD) и UDP 4789 (VXLAN)
- [ ] Sysctl tuned: `net.ipv4.ip_forward=1`, `rp_filter=2`, `fib_multipath_hash_policy=1`
- [ ] Настроен мониторинг BFD-сессий, EVPN peers, MLAG state
- [ ] Тестирован failover: отключение линка, коммутатора, VTEP
- [ ] Конфигурация хранится в Git (Ansible/NAUTobot)
- [ ] Валидация конфигурации автоматизирована (`vtysh -c "show run"`, `keepalived -C`)
