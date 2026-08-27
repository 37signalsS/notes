# DPDK Bonding — LACP, failover, балансировка

### Определения

- **librte_bond**: Библиотека DPDK для аппаратного/программного объединения нескольких NIC в один логический интерфейс (bonding). Работает в userspace, без участия kernel bonding driver.
- **LACP (Link Aggregation Control Protocol)**: Протокол (IEEE 802.3ad) для автоматического объединения физических link-ов в логический канал. Два NIC обмениваются LACPDU пакетами и协商 aggregation group.
- **802.3ad (LACP)**: Режим bonding, при котором NIC обмениваются LACPDU с коммутатором. Требует поддержки LACP на switch. Балансировка по XOR-хэшу (src_mac XOR dst_mac XOR src_port XOR dst_port).
- **balance-rr (Round Robin)**: Режим bonding с round-robin передачей пакетов по slave-интерфейсам. Балансировка: поочерёдная отправка по slave 0, 1, 0, 1...
- **balance-xor (XOR)**: Режим bonding с балансировкой по XOR hash: `hash(src_mac, dst_mac, src_port, dst_port) % nb_slaves`. Один поток всегда идёт через один slave.
- **balance-tlb (Adaptive Transmit Load Balancing)**: Режим bonding с балансировкой TX только (RX через slave, к которому пришёл пакет). Не требует поддержки switch.
- **balance-alb (Adaptive Load Balancing)**: Режим bonding с балансировкой и RX, и TX. Использует ARP-промиску для перенаправления RX. Не требует switch.
- **active-backup (Active-Standby)**: Режим bonding с одним активным slave и одним/несколькими standby. При отказе active → failover на standby. Не требует switch. Нет балансировки.
- **Slave (подчинённый интерфейс)**: Физический NIC, входящий в bond. Типичная конфигурация: 2-4 slave.
- **Primary slave**: Основной slave в режиме active-backup. При восстановлении возвращается в active.
- **xmit_hash_policy**: Политика хэширования для балансировки: L2, L3, L4, or custom. Влияет на распределение потоков по slave.
- **miimon (Monitor interval)**: Интервал проверки link status slave в миллисекундах. При обнаружении link down → failover.
- **downdelay**: Задержка перед переключением на другой slave после обнаружения link down (для избежания flapping).
- **updelay**: Задержка перед возвратом slave в active после link up (для стабилизации).

---

### Теория

#### 1. Режимы bonding в DPDK

| Режим | Балансировка | Требование к switch | Failover | Throughput | Сценарий |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **balance-rr** | Round-robin TX, RX по轮询 | LACP | Да | line-rate × N | Не используется в продакшене (проблемы с reordering) |
| **balance-xor** | XOR hash | LACP или static trunk | Да | line-rate × N | Фиксированные потоки, stateless балансировка |
| **balance-tlb** | TX только | Не нужен | Да | ~line-rate × N | Простая балансировка TX, RX не балансируется |
| **balance-alb** | TX + RX | Не нужен | Да | ~line-rate × N | ARP-based RX балансировка, simplest setup |
| **802.3ad (LACP)** | L3/L4 XOR hash | LACP | Да | line-rate × N | **Стандарт в продакшене** — автоматическое объединение |
| **active-backup** | Нет | Не нужен | Да | line-rate × 1 | Redundancy, HA, простейший failover |

#### 2. Как работает LACP

```
 Host A                                            Switch
┌─────────┐                                      ┌─────────┐
│ Bond    │                                      │ Port 1  │
│ slave 0 ├──── LACPDU (Actor: mac0, port 0) ───►│         │
│ slave 1 ├──── LACPDU (Actor: mac1, port 1) ───►│ Port 2  │
└─────────┘                                      └─────────┘
                                                     │
    1. Host отправляет LACPDU с Actor MAC и port    │
    2. Switch получает LACPDU, определяет伙伴     │
    3. Switch формирует Aggregation Group           │
    4. Host и Switch начинают балансировку          │
```

**LACPDU содержит:**
- Actor MAC address + port priority + port number
- Partner MAC address + port priority + port number
- System priority + system MAC
- Key (aggregation key)
- State flags (activity, timeout, aggregation, sync, collecting, distributing)

**Агрегация на switch:**
```bash
# Cisco IOS
interface Port-channel1
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30

interface GigabitEthernet0/1
 channel-group 1 mode active  # LACP active
interface GigabitEthernet0/2
 channel-group 1 mode active

# Juniper
ae0 {
    aggregated-ether-options {
        lacp {
            active;
            periodic fast;  # 1 сек instead of 30
        }
    }
    unit 0 {
        family inet {
            address 10.0.0.1/24;
        }
    }
}
```

#### 3. Выбор режима bonding

```
Нужна redundancy?
  ├─ Да → active-backup (простой failover)
  ├─ Да + балансировка → 802.3ad (LACP)
  └─ Нет → balance-xor (если switch поддерживает)

Switch поддерживает LACP?
  ├─ Да → 802.3ad (LACP) — рекомендуется
  └─ Нет → balance-tlb или balance-alb

Нужен line-rate на всех slave?
  ├─ Да → 802.3ad (LACP) или balance-rr
  └─ Нет → balance-tlb (обычно достаточно)
```

#### 4. Балансировка: xmit_hash_policy

**L2 hash (по MAC):**
```
hash = src_mac XOR dst_mac
queue = hash % nb_slaves
Проблема: если src_mac и dst_mac фиксированы ( trickle), все пакеты идут в один slave
```

**L3 hash (по IP):**
```
hash = src_ip XOR dst_ip
queue = hash % nb_slaves
Плюс: распределение по IP-адресам
Минус: не учитывает порты (4+ потока одного клиента → один slave)
```

**L3+L4 hash (по IP + ports):**
```
hash = src_ip XOR dst_ip XOR src_port XOR dst_port
queue = hash % nb_slaves
Плюс: максимальное распределение (каждый поток → разный slave)
Рекомендуется для大多数 сценариев
```

**Encap2+3 (для туннелей):**
```
hash = inner_src_ip XOR inner_dst_ip XOR outer_src_ip XOR outer_dst_ip
Используется для VXLAN/GRE/Geneve туннелей
```

---

### Практическое руководство

#### 1. Создание bond device

```c
#include <rte_eth_bond.h>

// Создание bond device (LACP mode)
uint16_t bond_port = rte_eth_bond_create(
    "bond0",                      // Имя
    RTE_BOND_MODE_8023AD,         // Режим (LACP)
    RTE_BOND_XMIT_POLICY_L3L4,   // xmit_hash_policy (L3+L4)
    rte_socket_id()               // NUMA socket
);

// Добавление slave (NIC)
rte_eth_bond_slave_add(bond_port, slave_port_0);
rte_eth_bond_slave_add(bond_port, slave_port_1);

// Настройка primary slave (для active-backup)
rte_eth_bond_primary_set(bond_port, slave_port_0);

// Конфигурация LACP
struct rte_eth_bond_8023ad_conf lacp_conf = {
    .fast_period = 1,    // Fast LACPDU (1 сек)
    .slow_period = 30,   // Slow LACPDU (30 сек)
    .short_timeout = 3,  // Short timeout = 3 × fast_period
    .long_timeout = 90,  // Long timeout = 3 × slow_period
    .aggregate_timeout = 2, // Aggregate timeout
    .selection_logic = RTE_BOND_8023AD_SELECTION_LOGIC_STABLE,
};
rte_eth_bond_8023ad_setup(bond_port, &lacp_conf);

// Настройка miimon (health check)
rte_eth_bond_mode_set(bond_port, RTE_BOND_MODE_8023AD);
rte_eth_bond_link_monitoring_set(bond_port, 100); // 100ms interval
rte_eth_bond_link_down_prop_delay_set(bond_port, 5000); // 5 sec
rte_eth_bond_link_up_prop_delay_set(bond_port, 5000);  // 5 sec

// Конфигурация bond порта (как обычный DPDK порт)
struct rte_eth_conf bond_conf = {
    .rxmode = {
        .mq_mode = RTE_ETH_MQ_RX_RSS,
        .offloads = RTE_ETH_RX_OFFLOAD_CHECKSUM,
    },
    .rx_adv_conf = {
        .rss_conf = {
            .rss_hf = RTE_ETH_RSS_IP | RTE_ETH_RSS_TCP | RTE_ETH_RSS_UDP,
        },
    },
};

rte_eth_dev_configure(bond_port, nb_rx_queues, nb_tx_queues, &bond_conf);

// Запуск
rte_eth_dev_start(bond_port);
```

#### 2. Мониторинг bond

```c
// Проверка статуса bond
struct rte_eth_bond_slave_stats stats;
rte_eth_bond_stats_get(bond_port, &stats);

// Проверка link status bond
struct rte_eth_link link;
rte_eth_link_get_nowait(bond_port, &link);
printf("Bond link: %s, speed: %u Mbps\n",
       link.link_status ? "UP" : "DOWN",
       link.link_speed);

// Просмотр слaves
uint16_t slaves[4];
int nb_slaves = rte_eth_bond_slaves_get(bond_port, slaves, 4);
for (int i = 0; i < nb_slaves; i++) {
    struct rte_eth_link slave_link;
    rte_eth_link_get_nowait(slaves[i], &slave_link);
    printf("Slave %d: %s, %u Mbps\n",
           slaves[i],
           slave_link.link_status ? "UP" : "DOWN",
           slave_link.link_speed);
}
```

#### 3. Тестирование failover

```bash
# 1. Создать bond device
./build/app/testpmd -l 2-3 -n 4 -w 0000:01:00.0 -w 0000:01:00.1 --socket-mem 1024,0 -- \
  --forward-mode=io --bond-slave0=0000:01:00.0 --bond-slave1=0000:01:00.1 \
  --bond-mode=4 --bond-xmit-policy=l3l4

# 2. В testpmd:
# show port info 0
# → Bond mode: 802.3ad (LACP)
# → Active slaves: 2
# → Link status: UP

# 3. Эмулирование отказа slave (отключить кабель)
# На testpmd: show port stats 0
# → Через 5 секунд: active slaves = 1, link status仍然 UP

# 4. Восстановление (подключить кабель обратно)
# → Через updelay (5 сек): active slaves = 2
```

#### 4. Конфигурация active-backup

```c
// Простейший failover без LACP
uint16_t bond_port = rte_eth_bond_create(
    "bond0",
    RTE_BOND_MODE_ACTIVE_BACKUP,  // Active-backup mode
    0,                             // xmit_hash_policy (не используется)
    rte_socket_id()
);

// Добавление slaves
rte_eth_bond_slave_add(bond_port, slave_port_0);
rte_eth_bond_slave_add(bond_port, slave_port_1);

// Настройка primary
rte_eth_bond_primary_set(bond_port, slave_port_0);

// Health check (miimon)
rte_eth_bond_link_monitoring_set(bond_port, 100);  // 100ms

// Failover при link down
rte_eth_bond_link_down_prop_delay_set(bond_port, 5000);  // 5 sec delay
```

#### 5. Конфигурация balance-xor

```c
// Балансировка по XOR hash (требует trunk на switch)
uint16_t bond_port = rte_eth_bond_create(
    "bond0",
    RTE_BOND_MODE_XOR,              // XOR mode
    RTE_BOND_XMIT_POLICY_L3L4,      // L3+L4 hash
    rte_socket_id()
);

rte_eth_bond_slave_add(bond_port, slave_port_0);
rte_eth_bond_slave_add(bond_port, slave_port_1);

// Аналогичная конфигурация bond_conf и запуск
```

#### 6. Проверка LACP на switch

```bash
# Cisco IOS
show lacp neighbor
# → Flags:  S - Device is requesting Slow LACP timers
# →           F - Device is requesting Fast LACP timers
# →           A - Device is in Active mode
# →           P - Device is in Passive mode
# → ------------------------------------------------------
# → Port      Flags   Dev       Actor  Partner  Priority
# → Gi0/1     SA      Po1       1/1    1/1      32768
# → Gi0/2     SA      Po1       1/2    1/2      32768

show etherchannel summary
# → Group  Port-channel  Protocol   Ports
# → 1      Po1(SD)       LACP       Gi0/1(D) Gi0/2(D)

# Juniper
show lacp interfaces
show lacp statistics
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| LACP не поднимается | Bond: active slaves = 0 | Switch не настроен на LACP | Настройте `channel-group mode active` на switch |
| Failover не работает | Bond не переключается при link down | miimon не настроен или downdelay слишком большой | Проверьте `miimon` (рекомендуется 100ms) |
| Низкий throughput | 50Gbps вместо 200Gbps (4 slave) | xmit_hash_policy не поддерживается NIC | Используйте L3+L4 hash; проверьте RSS на NIC |
| Reordering пакетов | P50 latency в порядке, P99 spike | balance-rr режим (round-robin) | Используйте LACP или balance-xor |
| LACP flap | Slave постоянно переключается | Нестабильный link или неправильный timeout | Увеличьте downdelay/updelay; проверьте кабели |

---

### Дополнительная информация

- **[DPDK: Тестирование](dpdk_testing.md)** — как протестировать bonding (failover, throughput).
- **[DPDK: RSS](dpdk_rss.md)** — распределение трафика по ядрам (внутри bond).
- **[DPDK: Архитектура PMD](dpdk_overview.md)** — как PMD работает с bond.
- **[DPDK: Низкая задержка (HFT)](scenarios.md#сценарий-5-hft)** — bonding для HA в HFT.
- **[IEEE 802.3ad LACP](https://standards.ieee.org/standard/802_3ad-2000.html)** — официальный стандарт.
- **[Linux bonding driver](https://www.kernel.org/doc/Documentation/networking/bonding.rst)** — сравнение DPDK bonding с kernel bonding.
