# Service Function Chaining (SFC) в DPDK

### Определения

- **SFC (Service Function Chaining)**: Архитектурный паттерн, при котором сетевой трафик направляется через последовательность сервисных функций (firewall → NAT → load balancer) в определённом порядке.
- **Service Function (SF)**: Отдельная сетевая функция, обрабатывающая трафик: firewall, NAT, IDS/IPS, load balancer, WAN optimizer, DPI.
- **NSH (Network Service Header, RFC 8300)**: Заголовок для Service Function Chaining. Содержит Service Path ID (SPI) и Service Index (SI), определяющие путь трафика через цепочку SF.
- **VXLAN-GPE (Generic Protocol Extension)**: Расширение VXLAN для поддержки протоколов, отличных от Ethernet (IP, NSH, MPLS). Используется для SFC транспорта.
- **SFF (Service Function Forwarder)**: Компонент, направляющий трафик к следующей SF в цепочке. Решение принимается на основе NSH SPI/SI илиvxlan VNI.
- **SF Descriptor**: Описание Service Function (тип, адрес, порт, метаданные). Используется для programmatic SFC.
- **Classifier**: Компонент, классифицирующий входящий трафик и определяющий Service Path (какую SF цепочку применить).
- **OAM (Operations, Administration, Maintenance)**: Протоколы для управления SFC (health check, statistics, path verification). NSH.includes OAM packets.
- **RRO (Reverse Route Overlay)**: Механизм для возврата трафика по обратному пути в SFC (для stateful SF).
- **DPDK SFC**: Библиотека DPDK для программирования Service Function Chaining. Поддерживает NSH, VxLAN-GPE, hardware offload через rte_flow.

---

### Теория

#### 1. Архитектура SFC

```
                        Service Function Chain
                        ========================

  Клиент                                                    Сервер
    │                                                           │
    ▼                                                           │
┌─────────┐                                                    │
│Classifi- │  1. Классификация трафика                     │
│er        │     → NSH: SPI=100, SI=3                       │
└────┬─────┘                                                    │
     │                                                           │
     ▼                                                           │
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    │
│ FW      │───►│ NAT     │───►│ LB      │───►│ DPI     │───►│
│ (SF 1)  │    │ (SF 2)  │    │ (SF 3)  │    │ (SF 4)  │    │
│ SI: 3→2 │    │ SI: 2→1 │    │ SI: 1→0 │    │ SI: 0→end│
└─────────┘    └─────────┘    └─────────┘    └─────────┘    │
     ▲                                                           │
     │                                                           │
     └──── NSH: SPI=100, SI decreasing ────────────────────────┘

SFF (Service Function Forwarder):
┌─────────────────────────────────────────────────────────────┐
│ SFF 1:_FW ──► NAT       SFF 2: NAT ──► LB                  │
│ SFF 3: LB ──► DPI       SFF 4: DPI ──► сервер               │
└─────────────────────────────────────────────────────────────┘
```

#### 2. NSH Header (RFC 8300)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|Ver|O|TTL|  U  |   Length      |   U   |   NSH Base Protocol  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Service Path ID (SPI)                   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Service Index (SI)                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
//                    Context Headers (optional)                //
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

Fields:
- Ver: Version (2 bits, currently 0)
- O: OAM bit (indicates OAM packet)
- TTL: Time To Live (3 bits)
- Length: Header length in 4-byte words
- SPI: Service Path ID (24 bits) - identifies the chain
- SI: Service Index (8 bits) - current position in chain
```

#### 3. SFC Transport Modes

| Mode | Транспорт | Когда использовать |
| :--- | :--- | :--- |
| **VXLAN-GPE + NSH** | VXLAN header + NSH header + payload | Most common, hardware support |
| **MPLS + NSH** | MPLS label + NSH header + payload | Telco environments |
| **GRE + NSH** | GRE header + NSH header + payload | Simple, no VXLAN overhead |
| **Ethernet + NSH** | Ethernet + NSH header + payload | Direct L2 SFC |

---

### Практическое руководство

#### 1. SFC через DPDK rte_flow

```c
// Классификатор: направить трафик с NSH SPI=100 в queue 0
struct rte_flow_item pattern[] = {
    { .type = RTE_FLOW_ITEM_TYPE_ETH },
    { .type = RTE_FLOW_ITEM_TYPE_IPV4 },
    { .type = RTE_FLOW_ITEM_TYPE_UDP,
      .spec = &(struct rte_flow_item_udp){
          .hdr.dst_port = rte_cpu_to_be_16(4790),  // VXLAN-GPE port
      },
      .mask = &(struct rte_flow_item_udp){
          .hdr.dst_port = RTE_BE16(0xFFFF),
      },
    },
    { .type = RTE_FLOW_ITEM_TYPE_END },
};

// Action: decrement SI, forward to next SF
struct rte_flow_action actions[] = {
    { .type = RTE_FLOW_ACTION_TYPE_QUEUE,
      .conf = &(struct rte_flow_action_queue){ .index = 0 } },
    { .type = RTE_FLOW_ACTION_TYPE_END },
};

struct rte_flow *flow = rte_flow_create(port_id, &attr, pattern, actions, &error);
```

#### 2. SFC с VPP (Vector Packet Processing)

```bash
# VPP поддерживает SFC через NSH plugin
# Установка VPP с NSH support
sudo apt install vpp vpp-plugin-core vpp-plugin-dpdk

# Конфигурация SFC в VPP
vppctl nsh map add-del add \
  spi 100 \
  si 3 \
  nsh-type 1 \
  transport VXLAN-GPE \
  mapper0 GigabitEthernet0/0/0 \
  mapper1 GigabitEthernet0/0/1

# Просмотр SFC mappings
vppctl nsh map dump
```

#### 3. Простейшая SFC через DPDK (pipeline)

```c
// Pipeline: FW → NAT → LB
// Каждый этап = отдельный lcore с rte_ring

struct rte_ring *fw_to_nat = rte_ring_create("fw_nat", 1024, socket_id, 0);
struct rte_ring *nat_to_lb = rte_ring_create("nat_lb", 1024, socket_id, 0);

// FW lcore
void fw_lcore(void) {
    struct rte_mbuf *pkts[32];
    while (1) {
        unsigned nb = rte_ring_sc_dequeue_burst(rx_ring, (void **)pkts, 32, NULL);
        for (unsigned i = 0; i < nb; i++) {
            if (firewall_check(pkts[i]) == PASS) {
                rte_ring_sp_enqueue(fw_to_nat, pkts[i]);
            } else {
                rte_pktmbuf_free(pkts[i]);  // Drop
            }
        }
    }
}

// NAT lcore
void nat_lcore(void) {
    struct rte_mbuf *pkts[32];
    while (1) {
        unsigned nb = rte_ring_sc_dequeue_burst(fw_to_nat, (void **)pkts, 32, NULL);
        for (unsigned i = 0; i < nb; i++) {
            nat_translate(pkts[i]);
            rte_ring_sp_enqueue(nat_to_lb, pkts[i]);
        }
    }
}

// LB lcore
void lb_lcore(void) {
    struct rte_mbuf *pkts[32];
    while (1) {
        unsigned nb = rte_ring_sc_dequeue_burst(nat_to_lb, (void **)pkts, 32, NULL);
        for (unsigned i = 0; i < nb; i++) {
            uint16_t backend = load_balance(pkts[i]);
            rte_eth_tx_burst(port_id, backend_queue[backend], &pkts[i], 1);
        }
    }
}
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| NSH не распознаётся | SFC не работает | NIC не поддерживает NSH offload | Проверьте rte_flow capabilities; используйте VPP |
| SI не decrement | Трафик зацикливается | SFF не уменьшает SI | Проверьте SFF logic; убедитесь что SF обновляет NSH |
| Throughput падает в chain | 100G → 50G через 3 SF | CPU bottleneck на каждом SF | Используйте hardware offload; распределите SF по ядрам |

---

### Дополнительная информация

- **[DPDK: rte_flow API](dpdk_rte_flow.md)** — программирование SFC через flow rules.
- **[DPDK: VPP Scenario](scenarios.md#сценарий-3-vpp)** — VPP для edge routing.
- **[RFC 8300 NSH](https://tools.ietf.org/html/rfc8300)** — Network Service Header standard.
- **[RFC 7665 SFC Architecture](https://tools.ietf.org/html/rfc7665)** — SFC architecture.
- **[FD.io VPP SFC](https://docs.fd.io/vpp/)** — VPP SFC plugin documentation.
