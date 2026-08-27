# QoS / Metering / Policing в DPDK

### Определения

- **QoS (Quality of Service)**: Совокупность механизмов для управления приоритетами, пропускной способностью и задержкой трафика. В DPDK реализуется через `rte_sched` (Hierarchical QoS) и `rte_mtr` (Metering and Policing).
- **rte_mtr (Metering and Policing)**: Библиотека DPDK для аппаратного/программного metering трафика по каждому flow. Поддерживает Two-Rate Three-Color Marker (trTCM, RFC 2697) и Single-Rate Three-Color Marker (srTCM, RFC 2698).
- **rte_sched (Hierarchical QoS Scheduler)**: Библиотека DPDK для многоуровневой очереди (hierarchy: Port → Subport → Pipe → Traffic Class → Queue). Поддерживает WRR (Weighted Round Robin), Strict Priority, и Wfq (Weighted Fair Queuing).
- **trTCM (Two-Rate Three-Color Marker)**: Алгоритм metering (RFC 2697). Два rates: CIR (Committed Information Rate) и PIR (Peak Information Rate). Три цвета: Green (≤ CIR), Yellow (CIR < rate ≤ PIR), Red (> PIR).
- **srTCM (Single-Rate Three-Color Marker)**: Алгоритм metering (RFC 2698). Один rate: CIR. Три цвета: Green (≤ CIR), Yellow (CIR < rate ≤ CIR + CBS), Red (> CIR + CBS).
- **CIR (Committed Information Rate)**: Гарантированная пропускная способность (Mpps или Mbps). Пакеты в пределах CIR помечаются как Green.
- **PIR (Peak Information Rate)**: Пиковая пропускная способность. Пакеты между CIR и PIR помечаются как Yellow. Пакеты выше PIR → Red.
- **CBS (Committed Burst Size)**: Максимальный burst для committed rate (в байтах). Определяет размер токен-бакета для CIR.
- **PBS (Peak Burst Size)**: Максимальный burst для peak rate (в байтах). Определяет размер токен-бакета для PIR.
- **DCB (Data Center Bridging)**: Набор стандартов IEEE для центров обработки данных. Включает PFC (Priority Flow Control), ETS (Enhanced Transmission Selection), DCBx (Discovery protocol).
- **PFC (Priority Flow Control, 802.1Qbb)**: Механизм back-pressure на уровне priority. При переполнении очереди NIC отправляет PAUSE frame с указанием priority. Предотвращает потери, но вызывает head-of-line blocking.
- **ETS (Enhanced Transmission Selection, 802.1Qaz)**: Механизм выделения полосы пропускания по priority groups. Каждая priority group получает свою часть полосы (напр., 70% для Storage, 30% для LAN).
- **DSCP (Differentiated Services Code Point)**: 6-битное поле в IP-заголовке (bits 2-7 of TOS byte). Определяет класс обслуживания пакета. DSCP values: BE (0), AF11 (10), AF21 (18), EF (46), CS6 (48).
- **WFQ (Weighted Fair Queuing)**: Алгоритм планирования, при котором каждая очередь получает пропорциональную часть пропускной способности на основе weight.
- **WRR (Weighted Round Robin)**: Упрощённый WFQ. Каждая очередь обслуживается последовательно с весом (weight). Простая реализация,不够 fine-grained.
- **Strict Priority**: Очередь с наивысшим приоритетом обслуживается первой. Низкоприоритетные очереди получают только остаток полосы.

---

### Теория

#### 1. Архитектура QoS в DPDK

```
Входящий трафик
    │
    ▼
┌──────────────────────────────────────────┐
│ rte_mtr (Metering)                       │
│ Каждый flow → trTCM/srTCM               │
│ Результат: Green / Yellow / Red          │
│ Действия: передать, drop, remark DSCP    │
└──────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────┐
│ rte_sched (Hierarchical Scheduler)       │
│                                          │
│ Port (eth port)                          │
│   └─ Subport (напр., VLAN)              │
│       └─ Pipe (напр., subscriber)        │
│           └─ Traffic Class (Storage/LAN) │
│               └─ Queue (per-flow queue)  │
│                                          │
│ Планирование: WRR + Strict Priority      │
└──────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────┐
│ DCB/PFC                                  │
│ Приоритетные queue → priority groups     │
│ PFC: PAUSE frame при переполнении        │
│ ETS: выделение полосы по priority        │
└──────────────────────────────────────────┘
    │
    ▼
  TX → NIC → Switch → Получатель
```

#### 2. Metering: trTCM vs srTCM

**trTCM (Two-Rate Three-Color):**
```
Два токен-бакета:
1. CIR bucket (Committed Information Rate):
   - Пополняется CIR tokens/сек
   - Максимум CBS tokens
   - Пакет ≤ CIR bucket → Green

2. PIR bucket (Peak Information Rate):
   - Пополняется PIR tokens/сек
   - Максимум PBS tokens
   - Пакет ≤ PIR bucket → Yellow
   - Пакет > PIR bucket → Red
```

**srTCM (Single-Rate Three-Color):**
```
Один токен-бакет CIR + EBS (Excess Burst Size):
- Пакет ≤ CIR bucket → Green
- Пакет ≤ CIR + EBS bucket → Yellow
- Пакет > CIR + EBS bucket → Red
```

**Пример настройки trTCM:**
```
Flow: 10 Gbps гарантировано (CIR), 20 Gbps пик (PIR)
CBS = 1500 байт (1 MTU)
PBS = 1500 байт (1 MTU)

Сценарий 1: 8 Gbps → Green (≤ 10 Gbps CIR)
Сценарий 2: 15 Gbps → Yellow (10 Gbps < 15 Gbps ≤ 20 Gbps PIR)
Сценарий 3: 25 Gbps → Red (> 20 Gbps PIR)
```

#### 3. Hierarchical QoS (rte_sched)

**Иерархия:**
```
Port (1 порт NIC)
  │
  ├── Subport 0 (VLAN 10)
  │     ├── Pipe 0 (Subscriber A)
  │     │     ├── TC 0 (Storage): Queue 0, 1, 2, 3
  │     │     └── TC 1 (LAN):    Queue 0, 1, 2, 3
  │     └── Pipe 1 (Subscriber B)
  │           ├── TC 0 (Storage): Queue 0, 1, 2, 3
  │           └── TC 1 (LAN):    Queue 0, 1, 2, 3
  │
  ├── Subport 1 (VLAN 20)
  │     ├── Pipe 0 (Subscriber C)
  │     └── Pipe 1 (Subscriber D)
  │
  └── ... (до 64 subports)
```

**Параметры планирования:**
```c
struct rte_sched_port_params port_params = {
    .name = "port0",
    .socket = 0,                // NUMA socket
    .rate = 100000,             // Port rate (Mbps) = 100 Gbps
    .txq_burstsz = 32,         // TX burst size
    .nb_txqs = 4,              // Количество TX queues
    .nb_subports_per_port = 2, // Количество subports
    .nb_pipes_per_subport = 16, // Количество pipes на subport
    .qsize = 1024,             // Размер queue (в пакетах)
    . Sheduler: {
        .nb_tc_per_pipe = 2,    // Traffic classes на pipe
        .tc_period = 10,       // Period для токен-бакета (мс)
        .tc_cra_rate = 100,     // CRA rate (Mbps)
    },
    .wrr = {
        .weights = { 1, 2, 4, 8 }, // WRR weights для 4 queue в TC
    },
};
```

**Настройка подсетей:**
```c
// Subport parameters
struct rte_sched_subport_params subport_params = {
    .cir = 10000,     // CIR для subport (Mbps) = 10 Gbps
    .pir = 20000,     // PIR для subport (Mbps) = 20 Gbps
    .cbs = 1500,      // CBS (bytes)
    .pbs = 1500,      // PBS (bytes)
};

// Pipe parameters
struct rte_sched_pipe_params pipe_params = {
    .cir = 1000,      // CIR для pipe (Mbps) = 1 Gbps
    .pir = 5000,      // PIR для pipe (Mbps) = 5 Gbps
    .cbs = 1500,
    .pbs = 1500,
    .worst_case_latency = 100, // Worst-case latency (мкс)
    .avg_pkt_size = 256,
};
```

#### 4. DCB (Data Center Bridging)

**DCB компоненты:**
```
┌─────────────────────────────────────────────────────┐
│ NIC (Intel E810 / NVIDIA ConnectX-7)                │
│                                                     │
│ Priority Groups (8 priority levels: 0-7):           │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│ │ PG 0    │ │ PG 1    │ │ PG 2    │ │ PG 3    │   │
│ │ (LAN)   │ │ (Storage)│ │ (vMotion)│ │ (NFV)   │   │
│ │ 50%     │ │ 30%     │ │ 10%     │ │ 10%     │   │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘   │
│                                                     │
│ PFC: При переполнении PG → PAUSE frame              │
│ ETS: Каждый PG получает свою часть полосы           │
└─────────────────────────────────────────────────────┘
```

**Настройка DCB:**
```bash
# Проверка DCB support
ethtool --show-features enp1s0 | grep dcb
# → dcb-pfc: on
# → dcb-pfc-auto: off

# Включение DCBx (auto-negotiation с switch)
lldptool -T -i enp1s0 -V DCBX EE
# → Enable DCBx: willing

# Настройка PFC (Priority Flow Control)
# PG 0: priority 0-3, 50% bandwidth, PFC enabled
# PG 1: priority 4-5, 30% bandwidth, PFC enabled
# PG 2: priority 6, 10% bandwidth, PFC disabled
# PG 3: priority 7, 10% bandwidth, PFC disabled

# Через dcbtool (Intel)
dcbtool setenp1s0 pfc pfcwilling+ pfcen0+ pfcen1+ pfcen2- pfcen3-
dcbtool setenp1s0 pgid pgid0=0 pgid1=0 pgid2=0 pgid3=1 pgid4=1 pgid5=2 pgid6=3 pgid7=3
dcbtool setenp1s0 pg pgenable0=on pgenable1=on pgenable2=on pgenable3=on

# Проверка
dcbtool getenp1s0 pfc
dcbtool getenp1s0 pg
```

---

### Практическое руководство

#### 1. Metering через rte_mtr (пример)

```c
#include <rte_mtr.h>

// Создание meter profile
struct rte_mtr_meter_profile profile = {
    .algo = RTE_MTR_TRTCM,      // Two-Rate Three-Color
    .trtcms.cir = 10000000000,  // 10 Gbps CIR (bps)
    .trtcms.pir = 20000000000,  // 20 Gbps PIR (bps)
    .trtcms.cbs = 1500,         // 1500 bytes
    .trtcms.pbs = 1500,         // 1500 bytes
};

uint32_t profile_id = 0;
rte_mtr_meter_profile_add(port_id, profile_id, &profile, &error);

// Создание meter
uint32_t meter_id = 0;
struct rte_mtr_params params = {
    .meter_profile_id = profile_id,
    .tc[0] = {  // Traffic Color 0 (Green)
        .drop = 0,           // Don't drop Green
        .dscp_table = NULL,
    },
    .tc[1] = {  // Traffic Color 1 (Yellow)
        .drop = 0,           // Don't drop Yellow
    },
    .tc[2] = {  // Traffic Color 2 (Red)
        .drop = 1,           // Drop Red
    },
};

rte_mtr_create(port_id, meter_id, &params, &error);

// Привязка meter к queue
rte_mtr_meter_dscp_table_update(port_id, meter_id, dscp_table, &error);

// Запрос статистики
struct rte_mtr_stats stats;
rte_mtr_stats_read(port_id, meter_id, &stats, &error);
printf("Green: %lu pkts\n", stats.n_pkts[0]);
printf("Yellow: %lu pkts\n", stats.n_pkts[1]);
printf("Red (dropped): %lu pkts\n", stats.n_pkts[2]);
```

#### 2. QoS через rte_sched (пример)

```c
#include <rte_sched.h>

// Создание QoS scheduler
struct rte_sched_port *sched = rte_sched_port_config(&port_params);
if (!sched) {
    rte_exit(EXIT_FAILURE, "Cannot create scheduler\n");
}

// Настройка subport
rte_sched_subport_config(sched, subport_id, &subport_params);

// Настройка pipe
rte_sched_pipe_config(sched, subport_id, pipe_id, &pipe_params);

// Классификация пакета → queue
// (предполагается, что приложение уже определило subport/pipe/tc/queue)
uint32_t subport = 0;
uint32_t pipe = 0;
uint32_t tc = 0;
uint32_t queue = 0;

// Добавление пакета в scheduler
rte_sched_port_pkt_write(sched, m, subport, pipe, tc, queue);

// Извлечение пакетов для передачи
struct rte_mbuf *pkts[32];
uint16_t nb_pkts = rte_sched_port_pkts_dequeue(sched, pkts, 32);

// Передача через NIC
rte_eth_tx_burst(port_id, tx_queue_id, pkts, nb_pkts);
```

#### 3. Мониторинг QoS

```c
// Статистика scheduler
struct rte_sched_port_queues_stats stats;
rte_sched_port_stats_read(sched, &stats);

// Просмотр по subport/pipe/tc/queue
for (int s = 0; s < nb_subports; s++) {
    for (int p = 0; p < nb_pipes; p++) {
        for (int t = 0; t < nb_tc; t++) {
            printf("Subport %d, Pipe %d, TC %d: drop=%lu, tx=%lu\n",
                   s, p, t,
                   stats.subport[s].pipe[p].tc[t].n_pkts_dropped,
                   stats.subport[s].pipe[p].tc[t].n_pkts_tc);
        }
    }
}
```

#### 4. Тестирование QoS

```bash
# Тест: ограничение 1 Gbps на конкретном flow
# 1. Настроить meter: CIR=1Gbps, PIR=2Gbps
# 2. Отправить 3 Gbps трафика через TRex
# 3. На DUT (DPDK с rte_mtr):
#    - 1 Gbps → Green (passed)
#    - 1 Gbps → Yellow (passed, но remark DSCP)
#    - 1 Gbps → Red (dropped)

# Проверка на testpmd:
# show port stats 0
# → tx_good_packets уменьшается (Red пакеты dropped)

# Проверка на TRex:
# → Lost: ~33% (1/3 трафика = Red)
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `rte_mtr_create` fails | Meter не создан | NIC не поддерживает rte_mtr | Проверьте `rte_mtr_capabilities_get()` |
| Все пакеты Red | Нет Green/Yellow | CBS/PBS слишком малы | Увеличьте CBS/PBS до size ≥ MTU |
| QoS scheduler не работает | Все пакеты drop | Параметры rate неправильные | Проверьте `cir`, `pir`, `cbs`, `pbs` |
| PFC не работает | Пакеты丢在 switch | DCB не включён или LLDP не работает | Включите DCBx, проверьте LLDP邻居 |
| Head-of-line blocking | Задержки на других priority | PFC включён на всех priority | Включите PFC только на critical traffic |

---

### Дополнительная информация

- **[DPDK: RSS](dpdk_rss.md)** — распределение трафика по ядрам (до QoS).
- **[DPDK: Тестирование](dpdk_testing.md)** — как протестировать QoS ограничения.
- **[DPDK: Bonding](dpdk_bonding.md)** — failover для redundant links.
- **[DPDK: Архитектура PMD](dpdk_overview.md)** — как PMD работает с QoS.
- **[RFC 2697](https://tools.ietf.org/html/rfc2697)** — trTCM (Two-Rate Three-Color Marker).
- **[RFC 2698](https://tools.ietf.org/html/rfc2698)** — srTCM (Single-Rate Three-Color Marker).
- **[IEEE 802.1Qbb PFC](https://standards.ieee.org/standard/802_1Qbb-2011.html)** — Priority Flow Control.
- **[IEEE 802.1Qaz ETS](https://standards.ieee.org/standard/802_1Qaz-2011.html)** — Enhanced Transmission Selection.
