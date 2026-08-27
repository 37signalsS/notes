## Определения

- **EVPN (Ethernet VPN)**: Контроль-плейн протокол для распространения MAC-адресов и IP-адресов в overlay сетях через BGP. Позволяет VTEP "учить" MAC без flooding (control-plane learning),替代传统的 flood-and-learn.
- **BGP EVPN (AFI 25, SAFI 70)**: Адресное семейство BGP для Ethernet VPN (RFC 7432). Использует MP-BGP для распространения MAC/IP routes между VTEP.
- **Route Type 2 (MAC/IP Advertisement)**: Тип маршрута EVPN, анонсирующий MAC-адрес + опциональный IP-адрес VTEP. Используется для learning host MAC/IP.
- **Route Type 5 (IP Prefix)**: Тип маршрута EVPN для анонсации IP-префиксов (L3 routes). Используется для symmetric IRB routing между VNI.
- **Route Distinguisher (RD)**: 8-битный идентификатор для различения одинаковых MAC/IP в разных VRF/tenant. Добавляется к BGP route для уникальности.
- **Route Target (RT)**: BGP community, определяющая, какие VTEP должны импортировать/экспортировать routes. Управляет isolation между tenant'ами.
- **VXLAN with EVPN (VXLAN-EVPN)**: Архитектура, где VXLAN используется как data plane (инкапсуляция), а BGP EVPN — как control plane (learning). Стандарт для современных DC fabrics.
- **Multi-Site EVPN**: Архитектура для соединения нескольких data center'ов (DCI) через EVPN. Каждый site имеет свою fabric, соединенную через EBGP EVPN between border switches.
- **Asymmetric IRB**: Routing между VNI выполняется на ingress VTEP. VTEP должен знать все VNI (не масштабируется).
- **Symmetric IRB**: Routing между VNI выполняется на каждом VTEP. Используется Transit VNI между VTEP (масштабируется, стандарт для EVPN-VXLAN).

---

## Основные концепции

### EVPN-VXLAN vs传统 VXLAN

| Критерий | Traditional VXLAN (flood-and-learn) | EVPN-VXLAN |
| :--- | :--- | :--- |
| **MAC learning** | Data plane (flooding + learning) | Control plane (BGP EVPN) |
| **Broadcast** | flooding на все VTEP | Control plane (ARP suppression) |
| **BUM traffic** | Всякий unknown unicast + broadcast | Минимальный (proxy ARP) |
| **Convergence time** | Медленная (MAC aging) | Быстрая (BGP fast convergence) |
| **Scaling** | Ограниченная (~500 VTEP) | Высокая (~10K+ VTEP) |
| **Multi-tenancy** | Ограниченная (VNI only) | Полная (RD/RT, VRF) |
| **Route type** | Нет | Type-2 (MAC/IP), Type-5 (IP prefix) |
| **DCI** | Сложная | Native (Multi-Site EVPN) |

### Типы маршрутов EVPN

| Route Type | Название | Данные | Когда используется |
| :--- | :--- | :--- | :--- |
| **Type 1** | Ethernet Auto-Discovery | MAC mobility, split-horizon | Multi-homing (ESI) |
| **Type 2** | MAC/IP Advertisement | MAC + IP + VTEP IP | Host learning, ARP |
| **Type 3** | Inclusive Multicast Ethernet Tag | VTEP list per VNI |BUM traffic handling |
| **Type 4** | Ethernet Segment Route | Multi-homing, DF election | Active-standby/active-active |
| **Type 5** | IP Prefix | IP prefix + VRF | L3 routing between VNI (symmetric IRB) |

**Наиболее используемые:** Type-2 (MAC learning) и Type-5 (IP routing).

### Symmetric IRB с EVPN

```
Host A (10.0.1.10, VNI 100) → Host B (10.0.2.20, VNI 200):

1. Host A → VTEP1 (ingress):
   - L2 lookup: VNI 100 → L3 interface (10.0.1.1/24)
   - IP routing: 10.0.1.10 → 10.0.2.20 (next-hop: VTEP2)
   - Encap: VXLAN VNI 100 (transit) + BGP EVPN Type-2 (MAC/IP)

2. VTEP1 → VTEP2:
   - VXLAN encapsulation (VNI 100)
   - Transit VNI между VTEP

3. VTEP2 (egress) → Host B:
   - Decap: VXLAN VNI 100
   - L3 routing: 10.0.2.20 (connected route VNI 200)
   - L2 lookup: VNI 200 → Host B MAC

BGP EVPN Type-2 анонсирует:
  - MAC A + IP A → VTEP1 (VNI 100)
  - MAC B + IP B → VTEP2 (VNI 200)

BGP EVPN Type-5 анонсирует:
  - 10.0.1.0/24 → VTEP1 (L3 VNI 1000)
  - 10.0.2.0/24 → VTEP2 (L3 VNI 1000)
```

### Multi-Site EVPN (DCI)

```
Site A (DC1)                      Site B (DC2)
┌──────────────────────┐          ┌──────────────────────┐
│ Spine-Spine Fabric   │          │ Spine-Spine Fabric   │
│  Leaf1  Leaf2        │          │  Leaf1  Leaf2        │
│   │      │           │          │   │      │           │
│ Border1 ── Border2   │          │ Border1 ── Border2   │
└───────────┬──────────┘          └──────────┬──────────┘
            │                                 │
            └──── EBGP EVPN (over L3) ───────┘
                 (WAN/DCI link)

Каждый site имеет:
  - ASN:自治系统番号 (Site A: 65001, Site B: 65002)
  - Route Distinguisher: уникальный per-site
  - Route Target: уникальный per-tenant

Border Leaf выполняет:
  - EVPN route exchange (Type-2/Type-5)
  - VXLAN encapsulation/decapsulation
  - Route filtering (RT-based)
```

---

## Практические сценарии

### Сценарий 1: EVPN-VXLAN на Cisco NX-OS

```cisco
! 1. Настройка BGP EVPN на Spine
feature bgp
feature nv overlay
feature vn-segment-vlan-based
feature fabric forwarding

! Создание VLAN с VNI mapping
vlan 100
  name TENANT-A
  vn-segment 10100

vlan 200
  name TENANT-B
  vn-segment 10200

! Настройка NVE interface (VTEP)
interface nve1
  no shutdown
  host-reachability protocol bgp
  source-interface loopback0
  member vni 10100
    ingress-replication protocol bgp
  member vni 10200
    ingress-replication protocol bgp

! 2. BGP EVPN configuration
router bgp 65001
  neighbor 10.0.0.10
    remote-as 65001
    address-family l2vpn evpn
      send-community both

  ! VRF definition для tenant isolation
  vrf TenantA
    rd 65001:100
    address-family ipv4 unicast
      route-target both 65001:100
      advertise L2VPN EVPN

! 3. Verification
show bgp l2vpn evpn summary
show bgp l2vpn evpn
show nve peers
show vxlan interface nve1
```

### Сценарий 2: EVPN на FRRouting (Linux)

```bash
# Установка FRRouting
sudo apt install frr frr-pythontools

# Конфигурация BGP EVPN (/etc/frr/frr.conf)
cat > /tmp/frr.conf << 'EOF'
frr defaults traditional
hostname leaf01
log syslog informational
no ipv6 forwarding

router bgp 65001
 bgp router-id 10.0.0.1
 bgp bestpath as-path multipath-relax
 neighbor VTEP peer-group
 neighbor VTEP remote-as 65001
 neighbor VTEP update-source lo
 neighbor 10.0.0.10 peer-group VTEP
 neighbor 10.0.0.11 peer-group VTEP

 address-family l2vpn evpn
  neighbor VTEP activate
  advertise-all-vni
  advertise-default-gw
 exit-address-family

router bgp 65001 vrf TENANT-A
 bgp router-id 10.0.0.1
 address-family ipv4 unicast
  redistribute connected
 exit-address-family
EOF

sudo cp /tmp/frr.conf /etc/frr/frr.conf
sudo systemctl restart frr

# Проверка EVPN routes
sudo vtysh -c "show bgp l2vpn evpn"
# → Route Distinguisher: 10.0.0.1:100
# → *> [2]:[0]:[0]:[48]:[aa:bb:cc:dd:ee:ff]:[32]:[10.0.1.10]/224
# →   Nexthop: 10.0.0.1
# →   Localpref: 100
# →   Weight: 0

# Проверка VNI
sudo vtysh -c "show evpn vni"
# → VNI      Type    Endpoint_ip    MAC地址
# → 10100    L2      10.0.0.1       aa:bb:cc:dd:ee:ff
# → 10100    L2      10.0.0.2       aa:bb:cc:dd:ee:00
```

### Сценарий 3: EVPN на OVN (Kubernetes)

```bash
# OVN поддерживает EVPN через BGP integration
# Настройка EVPN в OVN:

# 1. Настройка BGP на каждом узле
cat <<EOF > /etc/frr/frr.conf
router bgp 65100
 bgp router-id <node-ip>
 bgp bestpath as-path multipath-relax
 neighbor K8S peer-group
 neighbor K8S remote-as 65100
 neighbor K8S update-source lo
 neighbor 10.244.0.0/16 peer-group K8S

 address-family l2vpn evpn
  neighbor K8S activate
  advertise-all-vni
 exit-address-family
EOF

# 2. Настройка OVN для EVPN
ovn-nbctl set NB_Global . options:["bgp-enabled"]="true"
ovn-nbctl set NB_Global . options:["bgp-as"]="65100"

# 3. Проверка
ovn-sbctl show | grep "tunnel"
# → Encap: VXLAN, IP: 10.0.0.1, Options: {key=flow}
# → Encap: VXLAN, IP: 10.0.0.2, Options: {key=flow}
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **EVPN route not advertised** | Host MAC not learned remotely | `show bgp l2vpn evpn` - нет route | Проверить BGP peering; проверить VNI mapping; проверить `advertise-all-vni` |
| **MAC flapping** | MAC moves between VTEPs | `show mac address-table` - multiple ports | Проверить duplicate VNI; исключить loop; включить MAC mobility |
| **Multi-homing ESI failure** | Link redundancy not working | `show bgp evpn esi` - ESI down | Проверить ESI configuration; проверить DF election |
| **Asymmetric IRB not routing** | Traffic between VNI dropped | `show ip route vrf ...` - no routes | Настроить symmetric IRB; проверить VRF definition |
| **BGP convergence slow** | Long time after failure | `show bgp l2vpn evpn summary` - uptime long | Enable BGP fast-convergence; adjust timers |
| **Route Target mismatch** | Routes not imported/exported | `show bgp l2vpn evpn` - missing routes | Проверить RT configuration on both VTEPs |

### Команды верификации

```bash
# BGP EVPN routes
show bgp l2vpn evpn summary          # BGP peers status
show bgp l2vpn evpn                   # All EVPN routes
show bgp l2vpn evpn route-type 2      # Type-2 routes (MAC/IP)
show bgp l2vpn evpn route-type 5      # Type-5 routes (IP prefix)

# EVPN details
show bgp l2vpn evpn rd 10.0.0.1:100  # Routes per RD
show bgp l2vpn evpn vni 10100         # Routes per VNI

# VXLAN tunnel
show nve peers                        # NVE peers
show nve vni                          # VNI status
show vxlan interface nve1             # NVE interface details

# MAC table
show mac address-table                 # MAC addresses per VLAN
show mac address-table dynamic         # Dynamic MAC entries
```

---

## Дополнительная информация

**Производственные рекомендации:**
- EVPN-VXLAN рекомендуется для современных DC fabrics (замена flood-and-learn VXLAN).
- Используйте symmetric IRB для масштабируемости (не asymmetric).
- Включите ARP suppression для снижения BUM traffic.
- Multi-Site EVPN используется для DCI (связь между DC).

**Связанные темы:**
- **[VXLAN/Geneve](./vxlan_geneve.md)** — data plane для EVPN-VXLAN.
- **[BGP basics](../../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md)** — основы BGP.
- **[SDN Overview (Segment Routing)](./sdn_overview.md#segment-routing-srv6-и-traffic-engineering)** — SRv6 как альтернатива.
- **[OVN (Kubernetes)](./sdn_overview.md#деплой-ovn-для-виртуальных-сетей)** — OVN EVPN integration.
- **[FRRouting](./network_automation.md)** — FRR для BGP automation.
