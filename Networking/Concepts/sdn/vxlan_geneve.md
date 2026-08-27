## Определения

- **VXLAN (Virtual eXtensible Local Area Network)**: Протокол инкапсуляции L2-кадров в UDP-пакеты (RFC 7348). Позволяет создавать виртуальные L2-сегменты (VNI, 24-битный идентификатор, до 16M сегментов) поверх L3-сети (underlay). Основной протокол для.overlay сетей в дата-центрах.
- **Geneve (Generic Network Virtualization Encapsulation)**: Современный протокол инкапсуляции (RFC 8926), разработанный как замена VXLAN и GRE. Поддерживает переменные метаданные (TLV options), что делает его более гибким для NFV и overlay сетей.
- **VTEP (VXLAN Tunnel Endpoint)**: Конечная точка туннеля VXLAN, выполняющая инкапсуляцию/деинкапсуляцию пакетов. Может быть.hardware (коммутатор), software (OVS, Linux kernel) или SmartNIC.
- **VNI (VXLAN Network Identifier)**: 24-битный идентификатор VXLAN-сегмента (аналог VLAN ID, но до 16M вместо 4K). Один VNI = один L2-домен.
- **Underlay Network**: Физическая сеть, транспортирующая инкапсулированные пакеты. Должна обеспечивать IP- маршрутизацию между VTEP.
- **Overlay Network**: Виртуальная L2-сеть, построенная поверх underlay через инкапсуляцию. Поды/ВМ "видят" L2-сегмент, не зная о физической топологии.
- **Head-End Replication (HER)**: Метод broadcast/unknown-unicast в VXLAN, где VTEP-источник отправляет копии пакета на каждый VTEP в VNI (в отличие от multicast). Используется в небольших кластерах.
- **ARP Suppression / Proxy**: Механизм кэширования ARP-ответов на VTEP, предотвращающий broadcast storms в overlay сетях. VTEP отвечает на ARP от своего кэша вместо forwarded broadcast.
- **Asymmetric IRB (Integrated Routing and Bridging)**: Модель, где routing между VNI выполняется на ingress VTEP (пакет инкапсулируется после маршрутизации). Проще, но требует knowledge о всех VNI на каждом VTEP.
- **Symmetric IRB**: Модель, где routing выполняется на каждом VTEP (пакет инкапсулируется с L3-заголовком, routing выполняется после деинкапсуляции). Более масштабируемая, используется в OVN/EVPN.

---

## Основные концепции

### Сравнение VXLAN и Geneve

| Критерий | VXLAN | Geneve |
| :--- | :--- | :--- |
| **RFC** | 7348 (2014) | 8926 (2020) |
| **Заголовок** | Фиксированный 8 байт + 24-бит VNI | Фиксированный 8 байт + TLV options (переменные) |
| **Транспорт** | UDP 4789 | UDP 6081 |
| **Идентификатор** | VNI (24 бит, 16M segmentов) | VNI (24 бит) + TLV для дополнительных данных |
| **Расширяемость** | Ограниченная (нет options) | Полная (TLV для metadata: tunnel ID, policy, telemetry) |
| **Поддержка вендорами** | Широкая (Cisco, Juniper, VMware, OVN, Cilium) | Растущая (OVN, Cilium, VMware NSX, Linux kernel 4.18+) |
| **Производительность** | Ядро Linux: ~3Mpps, DPDK: ~100Mpps | Аналогичная (чуть больше overhead из-за TLV) |
| **Когда использовать** | Простые overlay сети; совместимость с legacy | NFV, метаданные, telemetry, modern clouds |

### Структура пакета VXLAN

```
┌────────────────────────────────────────────────────────────┐
│ Underlay Ethernet Header (14 bytes)                        │
│  dst MAC: VTEP-destination MAC                            │
│  src MAC: VTEP-source MAC                                 │
│  EtherType: 0x0800 (IPv4)                                │
├────────────────────────────────────────────────────────────┤
│ Underlay IP Header (20 bytes)                              │
│  src IP: VTEP-source IP                                   │
│  dst IP: VTEP-destination IP                              │
│  Protocol: 17 (UDP)                                       │
├────────────────────────────────────────────────────────────┤
│ UDP Header (8 bytes)                                       │
│  dst port: 4789 (VXLAN)                                  │
│  src port: random (hash для ECMP)                         │
├────────────────────────────────────────────────────────────┤
│ VXLAN Header (8 bytes)                                     │
│  Flags: 0x08 (I flag set)                                │
│  VNI: 24 bits (например, 10000)                          │
├────────────────────────────────────────────────────────────┤
│ Original L2 Frame (MTU dependent)                          │
│  Ethernet Header + IP Packet + Payload                    │
│  ⚠️ Total overhead: 50-62 bytes                          │
└────────────────────────────────────────────────────────────┘
```

### MTU в overlay сетях

| Underlay MTU | VXLAN overhead | Максимальный MTU пода | Рекомендация |
| :--- | :--- | :--- | :--- |
| 1500 | 50 байт (без VLAN) | 1450 | По умолчанию (без jumbo frames) |
| 1500 | 54 байта (с VLAN) | 1446 | Если underlay использует VLAN |
| 9000 (jumbo) | 50 байт | 8950 | Для high-perf storage/overlay |
| 9216 (jumbo+) | 50 байт | 9166 | Максимальная производительность |

**Критично:** Если MTU пода > 1450 (при underlay MTU 1500), возникает фрагментация или drop. Всегда проверяйте:
```bash
# Проверка MTU на поде
kubectl exec -it <pod> -- ip link show eth0
# → eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 ...

# Проверка path MTU
kubectl exec -it <pod> -- ping -M do -s 1422 <remote-ip>
# → 1422 + 28 (IP+ICMP headers) = 1450 = MTU
```

### Механизмы learning в VXLAN

| Метод | Описание | Масштабируемость | Использование |
| :--- | :--- | :--- | :--- |
| **Flood-and-learn** | Broadcast/unknown-unicast на все VTEP. VTEP учит MAC-адреса из входящих пакетов. | Ограниченная (broadcast storm) | Legacy, небольшие сети |
| **Multicast** | VXLAN encapsulated multicast через IP multicast в underlay. VTEP подписываются на multicast group. | Средняя | Cisco Nexus, OVN (multicast mode) |
| **BGP EVPN** | Control-plane learning через BGP. VTEP анонсируют MAC/IP через BGP Route Type 2/5. | Высокая | Production DC (EVPN-VXLAN) |
| **Static (HER)** | Head-End Replication: VTEP отправляет копии на все VTEP в VNI. | Низкая (<50 VTEP) | OVN default, Kubernetes |
| **OVN southbound DB** | OVN контроллер programs forwarding rules в OVS. Нет flooding (всё через control plane). | Высокая | OVN-Kubernetes |

### Routing между VNI (IRB)

**Asymmetric IRB (простая модель):**
```
Под A (VNI 100, 10.0.1.10) → VTEP1:
  1. L2 lookup: VNI 100 → routing table
  2. L3 routing: 10.0.1.10 → 10.0.2.20 (VNI 200)
  3. Encap: VXLAN (VNI 200) → VTEP2
  4. VTEP2: Decap → L2 lookup VNI 200 → delivery to Pod B

⚠️ VTEP1 должен знать все VNI (100 и 200) для routing.
```

**Symmetric IRB (масштабируемая модель):**
```
Под A (VNI 100, 10.0.1.10) → VTEP1:
  1. L2 lookup: VNI 100 → L3 interface (10.0.1.1/24)
  2. L3 routing: 10.0.1.10 → 10.0.2.20, next-hop VTEP2
  3. Encap: VXLAN (VNI 200 - transit VNI, не destination VNI)
  4. VTEP2: Decap → L3 routing → deliver to Pod B (VNI 200)

✅ Каждый VTEP знает только свои VNI + transit VNI.
```

---

## Практические сценарии

### Сценарий 1: Настройка VXLAN в Linux (ручная)

```bash
# Создание VXLAN интерфейса (VTEP)
# VNI=100, remote VTEP: 10.0.0.2, local VTEP: 10.0.0.1
ip link add vxlan100 type vxlan \
    id 100 \
    local 10.0.0.1 \
    dstport 4789 \
    nolearning    # Для OVN/BGP EVPN (без flood-and-learn)

ip link set vxlan100 up

# Добавление в bridge (для L2 connectivity)
ip link add br100 type bridge
ip link set vxlan100 master br100
ip link set br100 up

# Добавление интерфейсов подов в bridge
ip link set veth0 master br100  # veth0 - интерфейс пода
ip link set veth0 up

# Просмотр
bridge fdb show dev vxlan100
# → 00:00:00:00:00:00 dst 10.0.0.2 via vxlan100 self permanent
# → aa:bb:cc:dd:ee:ff dst 10.0.0.2 self

# Проверка MTU
ip link show vxlan100
# → vxlan100: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 ...
```

### Сценарий 2: VXLAN через OVN (Kubernetes)

```bash
# OVN автоматически создает VXLAN туннели между VTEP
# Ключевые команды:

# Просмотр VTEP (local endpoints)
ovn-sbctl show
# → datapath: <UUID>
# →   tunnel key: 1
# →   mac: "00:00:00:00:00:01"
# →   ip: 10.0.0.1
# →   ...
# →   tunnel key: 2
# →   ip: 10.0.0.2

# Просмотр логических коммутаторов
ovn-nbctl show
# → switch <ls-web>
# →   port sw0-port1, addresses: [00:11:22:33:44:55 10.0.1.10]
# →   port sw0-port2, addresses: [00:11:22:33:44:66 10.0.1.11]

# Трассировка пакета через VXLAN
ovn-trace sw0 'inport == "pod1" && ip.dst == 10.0.2.10 && tcp.dst_port == 80'
# → table=0 (ls_in_port_sec_l2): inport == "pod1" => accept;
# → table=8 (ls_in_acl): ip => verdict=allow;
# → table=10 (ls_in_l2_lkup): eth.dst == 00:11:22:33:44:55 => output;
# → → Encap: VXLAN VNI=200 → tunnel to 10.0.0.2

# Проверка OpenFlow rules для VXLAN
ovs-ofctl dump-flows br-int | grep "tunnel_id"
# → cookie=0x0, table=0, priority=100,tun_id=0x64,... actions=load:0x1->NXM_NX_REG14[0..15],resubmit(...)
```

### Сценарий 3: Трассировка и отладка VXLAN

```bash
# 1. Tcpdump на VTEP интерфейсе (ловим инкапсулированные пакеты)
sudo tcpdump -i eth0 -nn port 4789
# → 10:30:01.123456 IP 10.0.0.1.12345 > 10.0.0.2.4789: UDP, length 1450
# →   VXLAN vni=100
# →   IP 10.0.1.10.80 > 10.0.2.20.45678: Flags [S.], ...

# 2. Tcpdump на поде (ловим деинкапсулированные пакеты)
kubectl exec -it <pod> -- tcpdump -i eth0 -nn
# → 10:30:01.123456 IP 10.0.2.20.45678 > 10.0.1.10.80: Flags [S], ...

# 3. Проверка VXLAN FDB (forwarding database)
bridge fdb show dev vxlan100
# → aa:bb:cc:dd:ee:ff dst 10.0.0.2 self
# → aa:bb:cc:dd:ee:00 dst 10.0.0.3 self
# → 00:00:00:00:00:00 dst 10.0.0.2 self permanent  ← Head-End Replication

# 4. Проверка VXLAN statistics
ip -s link show vxlan100
# → RX: bytes=... packets=... errors=... dropped=...
# → TX: bytes=... packets=... errors=... dropped=...

# 5. Проверка ARP table на VTEP
ip neigh show dev vxlan100
# → 10.0.2.20 lladdr aa:bb:cc:dd:ee:ff REACHABLE
```

### Сценарий 4: Настройка Geneve в Linux

```bash
# Создание Geneve интерфейса
ip link add geneve100 type geneve \
    id 100 \
    remote 10.0.0.2 \
    dstport 6081

ip link set geneve100 up

# Добавление в bridge
ip link add br100 type bridge
ip link set geneve100 master br100

# Geneve с метаданными (TLV options)
# Пример: добавление tunnel metadata через ip link
ip link add geneve200 type geneve \
    id 200 \
    remote 10.0.0.2 \
    dstport 6081

# Просмотр Geneve interfaces
ip -d link show type geneve
# → geneve100: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 ...
# →     geneve id 100 remote 10.0.0.2 dstport 6081 ...

# Проверка Geneve трафика
sudo tcpdump -i eth0 -nn port 6081
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **MTU fragmentation** | TCP retransmits, slow performance, large ICMP dropped | `ping -M do -s 1472 <remote-ip>` fails | Установить MTU=1450 на подах; включить jumbo frames в underlay |
| **VTEP unreachable** | VXLAN packets dropped, ARP timeout | `tcpdump -i eth0 port 4789` - нет трафика; `ip neigh show` incomplete | Проверить IP-маршрутизацию между VTEP; проверить firewall (UDP 4789) |
| **ARP storm** | Broadcast flooding, high CPU, packet loss | `tcpdump -i vxlan100 arp` - множество ARP request | Включить ARP suppression (OVN, Cilium); уменьшить количество VNI |
| **MAC flapping** | MAC address moves between ports, switching loop | `bridge fdb show` - MAC on multiple VTEPs | Проверить duplicate VNI; исключить loop в underlay |
| **FDB table overflow** | Количество MAC > hardware limit, drops | `bridge fdb show | wc -l` > platform limit | Использовать BGP EVPN (control-plane learning) вместо flood-and-learn |
| **ecn bits incorrect** | Marking ECN bits incorrectly, packet drops | `tcpdump -vv` - ECN bits mismatch | Проверить конфигурацию ECN на VTEP (ECN support required) |

### Производительность overlay

| Underlay | Overhead | Max Throughput (per core) | Latency |
| :--- | :--- | :--- | :--- |
| Kernel VXLAN | 50 bytes | ~3Mpps | 10-30 мкс |
| Geneve (kernel) | 50-62 bytes | ~3Mpps | 10-30 мкс |
| OVS + DPDK VXLAN | 50 bytes | ~100Mpps+ | 5-10 мкс |
| SmartNIC VXLAN | 50 bytes | ~200Gbps (line rate) | < 1 мкс |

---

## Дополнительная информация

**Рекомендации:**
- Всегда устанавливайте MTU=1450 на подах в overlay сетях (при underlay MTU 1500).
- Для production DC используйте BGP EVPN вместо flood-and-learn для масштабируемости.
- Geneve предпочтительнее VXLAN для modern overlay (NFV, telemetry).
- Мониторьте VXLAN FDB через `bridge fdb show` и `ip -s link show type vxlan`.

**Связанные темы:**
- **[OpenFlow (VXLAN encap)](./openflow.md)** — VXLAN через OpenFlow.
- **[OVN (Kubernetes)](./sdn_overview.md#деплой-ovn-для-виртуальных-сетей)** — VXLAN в OVN.
- **[BGP EVPN](./bgp_evpn.md)** — control-plane learning для VXLAN.
- **[MTU (Net块)](./sdn_overview.md#edge-cases)** — MTU mismatch troubleshooting.
- **[Proxmox SDN](./sdn_overview.md#интеграция-proxmox-sdn-с-ovn)** — VXLAN zones в Proxmox.
- **[Cilium](./kubernetes_cni.md)** — VXLAN/Geneve в Kubernetes CNI.
