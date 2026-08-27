## Определения

- **Segment Routing (SR)**: Маршрутизационный подход, где маршрут пакета задается набором сегментов (segment list) в заголовке пакета. Каждый сегмент — это идентификатор (SID) узла, интерфейса или сервиса. SR позволяет реализовать Traffic Engineering без RSVP-TE и LDP.
- **SRv6 (Segment Routing over IPv6)**: Реализация Segment Routing поверх IPv6. Сегменты (SIDs) кодируются в hop-by-hop заголовке IPv6 (SRH, Routing Header Type 4). Позволяет маршрутизировать пакеты через указанные промежуточные узлы без MPLS.
- **SID (Segment Identifier)**: Уникальный идентификатор сегмента. В SRv6 SID — это 128-битный IPv6-адрес с拇指定ой структурой (Locator + Function + Args). Locator определяет узел, Function — сервис на узле.
- **SRH (Segment Routing Header)**: IPv6 extension header (Routing Header Type 4), содержащий список SID'ов (Segment List). Пакет проходит через каждый SID в списке, пока не достигнет终点.
- **SL (Segment List)**: Упорядоченный список SID'ов в SRH. Пакет маршрутизируется по的第一个 SID (active segment), после чего active segment decrement.
- **Traffic Engineering (TE)**: Управление маршрутизацией трафика для оптимизации use of network resources. В SRv6 TE реализуется через указание промежуточных SID'ов в SRH.
- **SR-MPLS**: Реализация Segment Routing поверх MPLS. Сегменты кодируются как MPLS labels (88-bit SID). Используется в традиционных MPLS сетях для замены LDP/RSVP-TE.
- **uSID (micro-SID)**: Сжатый формат SID в SRv6 (RFC 9252). Уменьшает размер SRH с 16 байт на SID до 4 байт, что снижает overhead.
- **PSP (Penultimate Segment Pop)**: Механизм, где предпоследний узел в segment list удаляет SRH перед отправкой на终点. Аналог PHP в MPLS.
- **SRv6 Mobile User Plane**: Использование SRv6 для мобильных сетей (4G/5G). SRv6 SID определяют tunnel endpoint для user plane traffic.

---

## Основные концепции

### SRv6 vs传统 MPLS/RSVP-TE

| Критерий | MPLS + RSVP-TE | SRv6 |
| :--- | :--- | :--- |
| **Протокол транспорта** | MPLS (L2.5) | IPv6 (L3) |
| **Управление трафиком** | RSVP-TE (signaling) | SRv6 (source routing) |
| **Label Stack** | MPLS labels (4 байта) | SRH (16+ байт на SID) |
| **Memory state** | Per-LSP state на каждом узле | Stateless (state only на source) |
| **Scaling** | Ограниченная (per-LSP state) | Высокая (stateless) |
| **IPv6 support** | Требует dual-stack | Native IPv6 |
| **Программируемость** | Ограниченная | Полная (SL list) |
| **Назначение** | Legacy DC, MPLS WAN | Modern DC, 5G, cloud-native |

### Структура SRv6 SID

```
128-bit IPv6 SID Structure:
┌────────────────────────────────────────────────────────────────┐
│ Locator (48-64 bits)        │ Function (16-32 bits) │ Args    │
│ (Topology/Node ID)          │ (Service identifier)  │ (Variable) │
│                             │                        │         │
│ Example: 2001:db8:1::/48    │ :100 (End)            │         │
│          2001:db8:2::/48    │ :200 (End.X)          │         │
└────────────────────────────────────────────────────────────────┘

Common SRv6 SIDs:
  End        - Transit node (intermediate SID)
  End.X      - Cross-connect to specific interface
  End.DT4    - Decapsulation + IPv4 lookup in VRF
  End.DT6    - Decapsulation + IPv6 lookup in VRF
  End.DX4    - Decapsulation + IPv4 directly connected
  End.DX6    - Decapsulation + IPv6 directly connected
  End.DT46   - Decapsulation + dual-stack lookup
```

### SRH (Segment Routing Header) в пакете

```
IPv6 Packet with SRH:
┌────────────────────────────────────────────────────┐
│ IPv6 Header (40 bytes)                             │
│   Next Header: 43 (Routing Header)                │
│   Hop Limit: 64                                    │
│   Source: 2001:db8:1::1 (ingress)                  │
│   Destination: 2001:db8:3::1 (active SID)         │
├────────────────────────────────────────────────────┤
│ SRH (Segment Routing Header)                       │
│   Routing Type: 4 (SRv6)                           │
│   Segments Left: 2 (index of active SID)           │
│   Last Entry: 2 (index of last SID)                │
│   Flags: O (OAM), P (PSP)                         │
│   Segment List[0]: 2001:db8:3::1 (endpoint)       │
│   Segment List[1]: 2001:db8:2::1 (transit)        │
│   Segment List[2]: 2001:db8:1::1 (source)         │
└────────────────────────────────────────────────────┘

Processing:
  Segments Left = 2 → Destination = SL[0] = 2001:db8:3::1
  At node 2001:db8:3::1: Segments Left = 1 → Dest = SL[1] = 2001:db8:2::1
  At node 2001:db8:2::1: Segments Left = 0 → Dest = SL[2] = 2001:db8:1::1 (decap)
```

### SRv6 Traffic Engineering

**Пример: изменение маршрута трафика через промежуточные узлы**

```
Without TE (shortest path):
  Source (A) → B → D → Destination (E)
  Path: A-B-D-E

With SRv6 TE (explicit path):
  Source (A) → B → C → D → E
  SRH: [E, D, C, B] (reversed)
  Segments Left: 3 → Active SID = B (first in list)
  At B: Segments Left = 2 → Next SID = C
  At C: Segments Left = 1 → Next SID = D
  At D: Segments Left = 0 → Last SID = E (decap)
```

### SRv6 в Kubernetes (K8s)

SRv6 используется в K8s для service mesh и multi-cluster networking:
- **Cilium**: Поддерживает SRv6 для service routing (L3LB, cluster mesh).
- **Calico**: SRv6 для overlay networking (замена VXLAN).
- **Kube-router**: SRv6 для network policy enforcement.

---

## Практические сценарии

### Сценарий 1: SRv6 на Linux (iproute2)

```bash
# 1. Проверка поддержки SRv6
ip -6 route show | grep seg6
# → 2001:db8:1::/64 dev eth0 proto kernel metric 256

# 2. Настройка SRv6 на узле (End function)
ip -6 route add 2001:db8:100::/128 dev lo
ip -6 route add 2001:db8:200::/128 dev lo

# 3. Добавление SRv6 route с explicit path
ip -6 route add 2001:db8:3::1/128 \
    encap seg6 mode inline \
    segs 2001:db8:1::1,2001:db8:2::1 \
    dev eth0

# 4. Просмотр SRv6 routes
ip -6 route show encap seg6
# → 2001:db8:3::1/128 via ... dev eth0
# →   encap seg6 segments 2001:db8:1::1,2001:db8:2::1

# 5. Проверка SRv6 SRH в пакете
sudo tcpdump -i eth0 -nn ip6 proto 43
# → 2001:db8:1::1 > 2001:db8:3::1: route[2] ip6 2001:db8:2::1, 2001:db8:1::1
```

### Сценарий 2: SRv6 Traffic Engineering через FRRouting

```bash
# Конфигурация SRv6 на FRRouting (/etc/frr/frr.conf)
cat > /tmp/frr.conf << 'EOF'
frr defaults traditional
hostname node01
log syslog informational

! SRv6 configuration
segment-routing
 sr-v6-localers
  name main locator 2001:db8:1::/48
  behavior End
 exit-sr-v6-locators
 exit-segment-routing

router bgp 65001
 bgp router-id 10.0.0.1
 neighbor 10.0.0.2 remote-as 65001
 address-family ipv6 unicast
  neighbor 2001:db8:2::2 activate
  advertise sr-v6-sids
 exit-address-family
EOF

sudo cp /tmp/frr.conf /etc/frr/frr.conf
sudo systemctl restart frr

# Просмотр SRv6 SIDs
sudo vtysh -c "show segment-routing sr-v6 locator"
# → Locator: 2001:db8:1::/48
# → Behavior: End

# Просмотр SRv6 paths
sudo vtysh -c "show bgp ipv6 unicast"
```

### Сценарий 3: SRv6 на Cisco IOS-XR

```cisco
! Настройка SRv6 на Cisco IOS-XR
segment-routing
 traffic-eng
  ! SRv6 locator
  segment-list SL-TO-DC2
   index 10 mpls label 16001
   index 20 mpls label 16002

  ! Policy (Traffic Engineering)
  policy POLICY-TO-DC2
   color 101 end-point 10.0.0.2
   candidate-paths
    preference 100
     explicit segment-list SL-TO-DC2

! SRv6 locator
segment-routing
 srv6
  locators
   MAIN
    micro-segments
     prefix 2001:db8:1::/48
      behavior end
     !

! Verification
show segment-routing srv6 locator
show segment-routing srv6 sid
show segment-routing traffic-eng policy
show segment-routing traffic-eng policy POLICY-TO-DC2
```

### Сценарий 4: SRv6 в Kubernetes (Cilium)

```bash
# Включение SRv6 в Cilium
helm install cilium cilium/cilium --namespace kube-system \
    --set tunnel=vxlan \
    --set kubeProxyReplacement=strict \
    --set routingMode=native \
    --set ipv6.enabled=true

# Включение SRv6 через CiliumNetworkPolicy
cat <<EOF | kubectl apply -f -
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: sr6-routing
spec:
  endpointSelector:
    matchLabels:
      app: backend
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: frontend
    toPorts:
    - ports:
      - port: "80"
        protocol: TCP
  # SRv6 routing enabled via Cilium agent
EOF

# Проверка SRv6 routes на узле
ip -6 route show encap seg6 | grep cilium
# → 2001:db8:100::/120 via ... dev cilium_host
# →   encap seg6 segments 2001:db8:a::1,2001:db8:b::1
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **SRH not processed** | Packets dropped, no SRv6 forwarding | `tcpdump ip6 proto 43` - нет SRH | Включить SRv6 support на узле; проверить IPv6 forwarding |
| **SID not reachable** | Packets dropped at SID endpoint | `ip -6 route get <SID>` - unreachable | Добавить route для SID; проверить BGP advertisement |
| **Segments Left mismatch** | Premature decapsulation or infinite loop | `tcpdump` - Segments Left не decrement | Проверить SID function (End vs End.X) |
| **SRH overhead too large** | MTU exceeded, fragmentation | `ping -M do -s 1422 <SID>` fails | Уменьшить количество SID; увеличить MTU |
| **BGP SID not advertised** | SID not in routing table | `show bgp ipv6 unicast` - no SID route | Включить `advertise sr-v6-sids` в BGP config |
| **Encap mode mismatch** | Inline vs encap mode conflict | `ip -6 route show encap` - inconsistent modes | Ensure all nodes use same SRv6 mode (inline recommended) |

### Команды отладки

```bash
# SRv6 route information
ip -6 route show encap seg6
ip -6 route get 2001:db8:100::1

# SRv6 SID statistics
ip -6 sr show

# BGP SRv6 SIDs
sudo vtysh -c "show bgp ipv6 unicast"
sudo vtysh -c "show bgp ipv6 unicast 2001:db8:1::/48"

# TCPdump SRv6
sudo tcpdump -i eth0 -nn ip6 proto 43 -v
# → IP6 (hlim 64, next-header: Routing (43)):
# →   source: 2001:db8:1::1
# →   destination: 2001:db8:3::1
# →   Routing Header (type 4):
# →     segments left: 2
# →     segment list:
# →       [0] 2001:db8:2::1
# →       [1] 2001:db8:1::1
```

---

## Дополнительная информация

**Производственные рекомендации:**
- SRv6 рекомендуется для modern DC и 5G networks (замена MPLS + RSVP-TE).
- Используйте uSID (micro-SID) для снижения overhead SRH.
- SRv6 работает только в IPv6 сетях (нет dual-stack IPv4).
- Для overlay сетей SRv6 может заменить VXLAN (без encapsulation overhead).

**Связанные темы:**
- **[BGP EVPN](./bgp_evpn.md)** — control plane для VXLAN, complement SRv6.
- **[VXLAN/Geneve](./vxlan_geneve.md)** — data plane overlay (alternative to SRv6).
- **[SDN Overview (Segment Routing)](./sdn_overview.md#segment-routing-srv6-и-traffic-engineering)** — обзор SRv6 в контексте SDN.
- **[FRRouting](./network_automation.md)** — FRR для SRv6 automation.
- **[SR-MPLS](../../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md)** — SRv6 альтернатива в MPLS сетях.
