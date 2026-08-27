## Определения

- **eBPF (extended Berkeley Packet Filter)**: Технология ядра Linux, позволяющая загружать пользовательские программы в безопасном виртуальном машине (eBPF VM) внутри ядра. Программы прикрепляются к хукам (hooks) сетевого стека и выполняются при прохождении пакетов, без необходимости перекомпиляции или перезагрузки модуля ядра.
- **XDP (eXpress Data Path)**: Самый ранний хук в сетевом стеке Linux — выполняется сразу после получения пакета NIC (Network Interface Card), до выделения `sk_buff`. Это делает XDP самым быстрым механизмом обработки пакетов в Userspace- и Kernel-based решениях (до 24Mpps на ядро).
- **TC (Traffic Control) BPF**: Хук в сетевом стеке, работающий на уровне `qdisc`. Позволяет модифицировать, маршрутизировать или дропать пакеты после классификации, но до передачи в приложение. Более гибкий чем XDP, но медленнее (имеет access к `sk_buff`).
- **XDP Actions**: Тип обработки пакета в XDP:
    - `XDP_PASS` — передать пакет в обычный сетевой стек.
    - `XDP_DROP` — дропать пакет на уровне NIC (в 10-100 раз быстрее `iptables -j DROP`).
    - `XDP_TX` — вернуть пакет на тот же порт NIC (пример: bridge, reflector).
    - `XDP_REDIRECT` — перенаправить пакет на другой интерфейс или CPU (пример: load balancer, tunnel encap).
    - `XDP_ABORTED` — ошибка обработки (для отладки).
- **BPF Map**: Хранилище данных в ядре, доступное из eBPF-программ и Userspace-приложений. Типы: `hash`, `array`, `per-cpu array`, `LRU hash`, `ring buffer` (для вывода данных). Используются для хранения state (connection tables, counters, forwarding rules).
- **Cilium**: CNCF-продукт, использующий eBPF как основу для сетевого стека Kubernetes. Заменяет iptables, kube-proxy, OpenFlow через eBPF-программы, работающие на уровне ядра.
- **TC (Traffic Control) flower**: Механизм ядра Linux для hardware offload eBPF-программ на SmartNIC через `tc filter add ... flower ... action bpf`.

---

## Основные концепции

### Место eBPF в сетевом стеке Linux

```
┌─────────────────────────────────────────────────────────────────┐
│  Приложение (nginx, grpc)                                       │
│       ↕  socket()                                               │
├─────────────────────────────────────────────────────────────────┤
│  TCP/IP стек (ядро)                                            │
│       ↕                                                         │
│  TC qdisc  ←── TC BPF хук (modifies/sprays packets)            │
│       ↕                                                         │
│  Netfilter (iptables/nftables) ← eBPF может заменить           │
│       ↕                                                         │
│  XDP хук  ←── Самый ранний хук (before sk_buff allocation)    │
│       ↕                                                         │
│  NIC driver (igb, mlx5, virtio_net)                            │
│       ↕                                                         │
│  Hardware (SmartNIC для offload)                                │
└─────────────────────────────────────────────────────────────────┘
```

### XDP Modes

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Generic XDP** | Программа запускается в ядре (после `sk_buff`). Не требует поддержки NIC. | Тестирование, development (медленнее в 3-5 раз). |
| **Driver-native XDP** | Программа запускается в NIC driver, до `sk_buff`. | Production (высокая производительность). Требует `ethtool -L eth0 xdpgeneric off` и поддержку driver. |
| **Offloaded XDP** | Программа загружается на SmartNIC (NIC executing). | Максимальная производительность (200G+). Требует NIC с поддержкой (Mellanox, Netronome). |

**Рекомендация 2026:** Для production используйте **driver-native XDP** на серверах с 10G+ NIC. Generic XDP — только для dev/test. Offloaded XDP — только для SmartNIC (BlueField, Netronome Agilio).

### Proactive vs Reactive в eBPF

В отличие от OpenFlow, eBPF-программы устанавливаются **proactive** (загружаются один раз при attach к хуку) и выполняются на каждом пакете без запросов к контроллеру.

| Критерий | OpenFlow (Reactive) | eBPF (Proactive) |
| :--- | :--- | :--- |
| **Решение о маршруте** | Контроллер (Packet-In/Packet-Out) | Ядро Linux (BPF-программа) |
| **Латентность** | 1-5 мс (network round-trip) | < 1 мкс (kernel execution) |
| **Пропускная способность** | ~1Mpps (OVS, CPU) | ~24Mpps (XDP, per-core) |
| **Динамическое управление** | Flow-Mod через OpenFlow | Обновление BPF Map через Userspace |
| **State** | На контроллере | В BPF Map (connection tracking) |

### Сравнение eBPF с традиционными механизмами

| Механизм | Уровень | Пропускная способность | Программируемость | Использование |
| :--- | :--- | :--- | :--- | :--- |
| **iptables** | Kernel (Netfilter) | ~1Mpps (單规则) | Ограничена (CLI) | Legacy firewalling |
| **nftables** | Kernel (Netfilter) | ~5Mpps | Улучшенная (sets, maps) | Modern替代 iptables |
| **OpenFlow (OVS)** | Kernel + Userspace | ~5-10Mpps (DPDK: 100M+) | Высокая (match+action) | SDN overlay |
| **eBPF/XDP** | Kernel (earliest hook) | ~24Mpps (per core) | Полная (C, Rust) | Cloud-native networking |
| **DPDK** | Userspace | ~100Mpps+ | Полная (Userspace app) | NFV, high-perf forwarding |

### Механизмы offload eBPF на SmartNIC

```
eBPF-программа (BPF bytecode)
    ↓ Clang/LLVM compilation
eBPF object file (.o)
    ↓ ip link set dev eth0 xdpgeneric obj prog.o sec xdp
Kernel JIT compiler → Machine code (x86_64, ARM64)
    ↓ tc flower ... action bpf obj prog.o
SmartNIC (Mellanox, BlueField) → Hardware execution
```

**Ограничения offload:**
- Взаимодействие с BPF Map ограничено (некоторые типы не offload'ятся).
- Программы с циклами (bounded loops) могут не компилироваться для SmartNIC.
- Рекомендуется: максимальный размер программы ~4K инструкций.

---

## Практические сценарии

### Сценарий 1: Установка и запуск XDP-программы

```bash
# 1. Установка инструментов (Ubuntu/Debian)
sudo apt update && sudo apt install -y clang llvm libelf-dev \
    libbpf-dev bpfcc-tools linux-headers-$(uname -r) iproute2

# 2. Написание простой XDP-программы (drop фейковых IP)
cat > xdp_drop_fake.c << 'EOF'
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>

SEC("xdp")
int xdp_drop_fake(struct xdp_md *ctx) {
    void *data_end = (void *)(long)ctx->data_end;
    void *data = (void *)(long)ctx->data;

    struct ethhdr *eth = data;
    if (eth + 1 > data_end)
        return XDP_PASS;

    if (eth->h_proto != __constant_htons(ETH_P_IP))
        return XDP_PASS;

    struct iphdr *iph = data + sizeof(*eth);
    if (iph + 1 > data_end)
        return XDP_PASS;

    // Drop пакеты от 192.168.66.0/24 (test prefix)
    if ((iph->saddr & 0x00FFFFFF) == 0x42A8C0A0) // 192.168.66.0 в network order
        return XDP_DROP;

    return XDP_PASS;
}

char _license[] SEC("license") = "GPL";
EOF

# 3. Компиляция
clang -O2 -g -target bpf -c xdp_drop_fake.c -o xdp_drop_fake.o

# 4. Загрузка на интерфейс
sudo ip link set dev eth0 xdpgeneric obj xdp_drop_fake.o sec xdp

# 5. Проверка
ip link show eth0
# → ... xdpgeneric id <prog_id> ...

# 6. Просмотр статистики
ip -s link show eth0
# → RX: bytes=... packets=... errors=... dropped=...

# 7. Отладка через bpftool
sudo bpftool prog list
# → 12: xdp  name xdp_drop_fake  tag ...
# →   loaded_at Aug 25 2026  uid=0  xlated=128B  jited=96B  memlock=4096B

sudo bpftool prog show id 12
# → xlated=128B  jited=96B  run_time_ns=456  run_cnt=12345

# 8. Удаление
sudo ip link set dev eth0 xdpgeneric off
```

### Сценарий 2: XDP Load Balancer (LRB hash)

```bash
# Пример: XDP-based load balancer с round-robin через BPF Map
cat > xdp_lb.c << 'EOF'
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/tcp.h>

#define MAX_BACKENDS 16

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, MAX_BACKENDS);
    __type(key, __u32);      // backend index
    __type(value, __u32);    // backend IP
} backends SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u32);    // current backend index (round-robin)
} rr_index SEC(".maps");

SEC("xdp")
int xdp_load_balancer(struct xdp_md *ctx) {
    void *data_end = (void *)(long)ctx->data_end;
    void *data = (void *)(long)ctx->data;

    struct ethhdr *eth = data;
    if (eth + 1 > data_end) return XDP_PASS;
    if (eth->h_proto != __constant_htons(ETH_P_IP)) return XDP_PASS;

    struct iphdr *iph = data + sizeof(*eth);
    if (iph + 1 > data_end) return XDP_PASS;

    // Найти текущий backend index
    __u32 key = 0;
    __u32 *idx = bpf_map_lookup_elem(&rr_index, &key);
    if (!idx) return XDP_PASS;

    // Найти backend IP
    __u32 *backend_ip = bpf_map_lookup_elem(&backups, idx);
    if (!backend_ip) return XDP_PASS;

    // DNAT: перезаписать destination IP
    iph->daddr = *backend_ip;

    // Переключить на следующий backend (round-robin)
    __u32 next_idx = (*idx + 1) % MAX_BACKENDS;
    bpf_map_update_elem(&rr_index, &key, &next_idx, BPF_ANY);

    return XDP_TX; // Вернуть пакет на тот же интерфейс
}

char _license[] SEC("license") = "GPL";
EOF

# Компиляция и загрузка
clang -O2 -g -target bpf -c xdp_lb.c -o xdp_lb.o
sudo ip link set dev eth0 xdpgeneric obj xdp_lb.o sec xdp

# Пример BPF Map manipulation через bpftool
sudo bpftool map update id 3 key 0 0 0 0 value 10 0 168 192  # backend[0] = 192.168.0.10
sudo bpftool map update id 3 key 1 0 0 0 value 11 0 168 192  # backend[1] = 192.168.0.11
```

### Сценарий 3: TC BPF для модификации пакетов

```bash
# TC BPF позволяет модифицировать пакеты (в отличие от XDP, который работает до sk_buff)
# Пример: добавление VLAN tag на основе IP-адреса источника

cat > tc_bpf_vlan.c << 'EOF'
#include <linux/bpf.h>
#include <linux/pkt_cls.h>
#include <linux/if_ether.h>
#include <linux/if_vlan.h>
#include <linux/ip.h>

SEC("classifier")
int add_vlan(struct __sk_buff *skb) {
    void *data_end = (void *)(long)skb->data_end;
    void *data = (void *)(long)skb->data;

    struct ethhdr *eth = data;
    if (eth + 1 > data_end) return TC_ACT_OK;

    // Если пакет уже имеет VLAN tag — пропустить
    if (eth->h_proto == __constant_htons(ETH_P_8021Q))
        return TC_ACT_OK;

    struct iphdr *iph = data + sizeof(*eth);
    if (iph + 1 > data_end) return TC_ACT_OK;

    // VLAN 100 для 10.0.0.0/8, VLAN 200 для остальных
    __u16 vlan_id = (iph->saddr & 0xFF000000) == 0x0A000000 ? 100 : 200;

    bpf_skb_vlan_push(skb, __constant_htons(ETH_P_8021Q), vlan_id);
    return TC_ACT_OK;
}

char _license[] SEC("license") = "GPL";
EOF

# Компиляция и применение через tc
clang -O2 -g -target bpf -c tc_bpf_vlan.c -o tc_bpf_vlan.o
sudo tc qdisc add dev eth0 clsact
sudo tc filter add dev eth0 egress bpf obj tc_bpf_vlan.o sec classifier

# Просмотр
sudo tc filter show dev eth0 egress
```

### Сценарий 4: Cilium eBPF в Kubernetes

```bash
# 1. Установка Cilium с включением eBPF datapath
helm repo add cilium https://helm.cilium.io/
helm install cilium cilium/cilium --namespace kube-system \
    --set bpf.masquerade=true \
    --set kubeProxyReplacement=strict \
    --set tunnel=vxlan

# 2. Просмотр eBPF-программ на узле
kubectl -n kube-system exec -it <cilium-pod> -- \
    cilium bpf prog list
# → ID   TYPE      UID  NAME              LOAD TIME  SIZE     MAPS
# → 123  cgroup/sa 0    cilium_sock4_connect  12.5μs   5.2KB    3
# → 124  xdp       0    cilium_xdp            8.3μs    3.1KB    2
# → 125  tc/ingress 0   cilium_from_network    15.7μs   8.4KB    5

# 3. Просмотр eBPF maps (connection tracking)
kubectl -n kube-system exec -it <cilium-pod> -- \
    cilium bpf ct list global
# → IPv4: 10.0.0.5:80 <> 10.0.1.10:45678  policy=1 rx_packets=123 rx_bytes=18450 ...

# 4. Просмотр eBPF programs на конкретном узле
kubectl -n kube-system exec -it <cilium-pod> -- \
    cilium bpf policy list --endpoint 123456
# → Ingress:
# →   Label verdict: allow
# →     +-from-endpoint: 10.0.1.0/24 => 80/TCP ALLOW
# → Egress:
# →   Label verdict: allow
# →     +to-cidr: 10.0.2.0/24 => 443/TCP ALLOW

# 5. Мониторинг eBPF events
kubectl -n kube-system exec -it <cilium-pod> -- \
    cilium monitor --type drop
# → xx drop (Policy denied) flow 0x... to endpoint 123456, identity 5678 -> ...
```

### Сценарий 5: Отладка eBPF через bpftool

```bash
# Просмотр всех eBPF-программ в системе
sudo bpftool prog list
# → ID   TYPE      UID  NAME              LOAD TIME  SIZE     MAPS
# → 123  cgroup/sa 0    cilium_sock4_...  12.5μs     5.2KB    3
# → 124  xdp       0    xdp_drop_fake     8.3μs      3.1KB    2

# Просмотр всех BPF maps
sudo bpftool map list
# → ID   TYPE       KEY  VALUE  MAX_ENTRIES  NAME
# → 3    hash       4    4      16384        cilium_ct4
# → 4    lru_hash   4    12     524288       cilium_nat4

# Дамп содержимого map
sudo bpftool map dump id 3
# → key: 0a 00 00 05  → value: ...

# Отладка программы (tracing)
sudo bpftool prog tracelog
# → (после generate traffic)
# → bpf_trace_printk: packet from 10.0.0.5 to 10.0.1.10
```

---

## Безопасность и ограничения

### Риски

| Риск | Описание | Митигация |
| :--- | :--- | :--- |
| **Yama ptrace_scope** | Загрузка eBPF-программ может быть заблокирована SELinux/Yama | `sysctl kernel.yama.ptrace_scope=0` (не рекомендуется в production) |
| **eBPF verifier bypass** | Попытки обойти валидатор для загрузки вредоносных программ | Только root/sudo; в современных ядрах (5.10+) —硬化ненный verifier |
| **Map exhaustion** | Большинство map фиксированного размера | Мониторинг через `bpftool map list`, правильное планирование `max_entries` |
| **Program complexity** | Слишком сложные eBPF-программы могут не пройти верификацию | Ограничить 4K инструкций; использовать tail calls для модульности |
| **Hardware offload limitations** | Не все SmartNIC поддерживают все типы map и инструкций | Проверять `bpftool feature probe` перед offload |

### Производительность

| Сценарий | Пакетов/сек (per core) | Задержка |
| :--- | :--- | :--- |
| **XDP (driver-native)** | 24M+ pps | < 1 мкс |
| **TC BPF** | 3-5M pps | 2-5 мкс |
| **OVS + DPDK** | 100M+ pps | 5-10 мкс |
| **iptables** | 1M pps | 10-50 мкс |
| **Userspace (DPDK app)** | 100M+ pps | 5-10 мкс |

---

## Дополнительная информация

**Полезные инструменты:**
- **bpftool**: CLI для управления eBPF programs и maps (`iproute2` package).
- **bpftrace**: Язык для написания eBPF-программ (аналог awk для tracing).
- **Cilium CLI**: Управление Cilium в Kubernetes (`cilium status`, `cilium bpf`).
- **xdp-tools**: Утилиты для загрузки/тестирования XDP-программ (https://github.com/xdp-project/xdp-tools).

**Связанные темы:**
- **[OpenFlow (Сравнение)](./openflow.md)** — eBPF как альтернатива OpenFlow для Data Plane.
- **[SDN Overview (eBPF)](./sdn_overview.md#программируемость-и-наблюдаемость)** — eBPF в контексте SDN.
- **[Kubernetes CNI](./kubernetes_cni.md)** — Cilium, Antrea и другие CNI на базе eBPF.
- **[NetFlow/Hubble](./netflow.md#наблюдаемость-в-cloud-native-ebpf-и-hubble)** — Hubble для eBPF-based flow monitoring.
- **[DPDK](../dpdk/dpdk_overview.md)** — альтернативный high-perf datapath (Userspace).
- **[Cilium (K8s)](../../Kubernetes/Networking/Network/CNI/cilium.md)** — полная документация Cilium.
