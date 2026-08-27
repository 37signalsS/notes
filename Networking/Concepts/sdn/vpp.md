## Определения

- **VPP (Vector Packet Processing)**: Высокопроизводительный Userspace packet processing engine от FD.io (Cisco). Обрабатывает пакеты пакетами (vectors), а не по одному, что снижает overhead вызовов функций и увеличивает throughput (до 14.8Mpps на ядро CPU @ 3GHz).
- **Vector (Вектор)**: Набор пакетов (обычно 256), обрабатываемых одновременно. Вместо обработки каждого пакета отдельно, VPP загружает batch пакетов в CPU cache и обрабатывает их одним проходом через pipeline.
- **Graph Node**: Модуль VPP, обрабатывающий определённый тип задач (lookup, encap, decap, filter). Пакеты проходят через цепочку graph nodes,类似 Linux networking stack.
- **Plugins**: Модули VPP для расширения функциональности (ACL, VXLAN, IPsec, NAT, nat44). Аналог ядерных модулей Linux, но в Userspace.
- **DPDK (Data Plane Development Kit)**: Набор библиотек и драйверов для Userspace packet processing. VPP использует DPDK для высокоскоростного ввода/вывода (bypass kernel, hugepages, poll-mode drivers).
- **FD.io (Fast Data Project)**: Проект Linux Foundation, разрабатывающий VPP и связанные проекты (Honeycomb, GoVPP).
- **GoVPP**: Go-based client library для управления VPP через API (binapi). Позволяет программно управлять VPP из Go-приложений.
- **Honeycomb (fd.io)**: Web-based management plane для VPP (REST API, gNMI). Предоставляет конфигурацию и monitoring.
- **memif**: Shared memory interface для межпроцессного взаимодействия в VPP. Используется для подключения VPP к DPDK-приложениям, OVS, или другим VPP instances.
- **L2XC (L2 Cross-Connect)**: Простой L2 forwarding в VPP (аналог bridge в Linux). Два интерфейса связаны напрямую.
- **L2BD (L2 Bridge Domain)**: L2 bridge domain в VPP (аналог bridge в Linux). Несколько интерфейсов в одном L2-домене.

---

## Основные концепции

### VPP vs Linux kernel networking stack

| Критерий | Linux Kernel | VPP |
| :--- | :--- | :--- |
| **Обработка пакетов** | По одному (per-packet) | Пакетами (vector/batch, 256 packets) |
| **Context switch** | Kernel ↔ Userspace | Нет (Userspace only) |
| **Пропускная способность** | ~1-5Mpps (iptables/nftables) | ~14.8Mpps (per core @ 3GHz) |
| **CPU efficiency** | 30-40% cache hit ratio | 80-90% cache hit ratio |
| **Программируемость** | Ограничена (XDP, eBPF) | Полная (C, plugins) |
| **Features** | Полный networking stack (TCP/IP) | Ограниченная (L2/L3 forwarding, NAT) |
| **Назначение** | General-purpose networking | NFV, high-perf forwarding, router/switch |

### Архитектура VPP

```
┌─────────────────────────────────────────────────────────────┐
│  Приложение (GoVPP, CLI, REST API)                          │
├─────────────────────────────────────────────────────────────┤
│  VPP Graph Engine                                            │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│  │ Interface │→│  L2     │→│  IP     │→│  NAT   │→ Output   │
│  │ Input    │ │  BD/    │ │  Lookup │ │  NAPT  │          │
│  │          │ │  L2XC   │ │  (FIB)  │ │        │          │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘          │
├─────────────────────────────────────────────────────────────┤
│  Plugins (ACL, VXLAN, IPsec, NAT44, WireGuard, SRv6)      │
├─────────────────────────────────────────────────────────────┤
│  DPDK (poll-mode drivers, hugepages, mempool)              │
├─────────────────────────────────────────────────────────────┤
│  NIC (10G/25G/100G)                                         │
└─────────────────────────────────────────────────────────────┘
```

### Режимы работы VPP

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| **L2 Switch** | VPP работает как L2 bridge (L2XC/L2BD). Замена OVS. | Virtual switching, overlay |
| **L3 Router** | VPP маршрутизирует пакеты (IP lookup, FIB). | High-perf routing, NFV |
| **NAT** | VPP выполняет NAT44/NAT66 (Stateful NAT). | CG-NAT, firewall, proxy |
| **IPsec Gateway** | VPP шифрует/дешифрует IPsec tunnel. | VPN gateway, overlay encryption |
| **Service Chaining** | VPP направляет трафик через цепочку функций (FW → IDS → NAT). | NFV, service insertion |
| **DPDK acceleration** | VPP с DPDK для максимальной производительности. | 100G+ links, telco/DC |

### Пакетный pipeline в VPP

```
NIC → DPDK RX → Interface Input → L2/L3 Classification →
  → [L2BD/L2XC] → [IP Lookup (FIB)] → [NAT] → [IPsec] →
  → [ACL] → [QoS] → Interface Output → DPDK TX → NIC

Каждый шаг — это graph node, который обрабатывает batch (vector) пакетов.
```

---

## Практические сценарии

### Сценарий 1: Установка VPP

```bash
# Ubuntu 22.04/Debian 12
# Добавление репозитория FD.io
curl -fsSL https://packagecloud.io/install/repositories/fdio/release/script.deb.sh | sudo bash

sudo apt update && sudo apt install -y \
    vpp vpp-plugin-core vpp-plugin-dpdk \
    vpp-api-python vpp-dev

# Проверка
vpp --version
# → vpp 24.02 ...

# Запуск VPP
sudo systemctl start vpp
sudo systemctl status vpp

# CLI доступ
sudo vppctl
# vpp# show interface
#              Name               Idx    State  IP4 Address      ...
# host-vpp0                        1     up     10.0.0.1/24
# GigabitEthernet0/0/0             2     up     10.0.1.1/24
```

### Сценарий 2: L2 Bridge Domain (замена OVS)

```bash
# Создание L2 bridge domain с 2 интерфейсами
sudo vppctl create bridge-domain 100 learn enable unicast-flood enable

# Добавление интерфейсов в bridge
sudo vppctl set interface l2 bridge GigabitEthernet0/0/0 100 enable
sudo vppctl set interface l2 bridge GigabitEthernet0/0/1 100 enable

# Проверка
sudo vppctl show bridge-domain 100
# → Bridge-Domain 100 learning=1 unicast-flood=1
# →   Index    Name           ...

# Просмотр MAC table
sudo vppctl show bridge-domain 100 detail
# → Bridge-Domain 100:
# →   learn=1 unicast-flood=1 ...
# →   3 learn+forward 1 flood=1 bvi=0
```

### Сценарий 3: VXLAN в VPP

```bash
# Создание VXLAN tunnel (VTEP)
sudo vppctl create vxlan tunnel \
    local-ip 10.0.0.1 \
    remote-ip 10.0.0.2 \
    vni 100

# Просмотр VXLAN tunnels
sudo vppctl show vxlan tunnel
# → [0] local 10.0.0.1 remote 10.0.0.2 vni 100 ...

# Добавление VXLAN interface в L2 bridge
sudo vppctl set interface l2 bridge vxlan_tunnel0 100 enable

# Проверка MAC learning
sudo vppctl show bridge-domain 100
# → MAC addresses learned on vxlan_tunnel0
```

### Сценарий 4: NAT44 в VPP

```bash
# Настройка NAT44 (Stateful NAT)
sudo vppctl nat44 add addresses 203.0.113.10

# Включение NAT на интерфейсах
sudo vppctl set interface nat44 in GigabitEthernet0/0/0 out GigabitEthernet0/0/1

# Добавление static mapping (port forwarding)
sudo vppctl nat44 add static mapping local 10.0.0.80:80 external 203.0.113.10:8080

# Проверка NAT translations
sudo vppctl show nat44 translations
# → NAT44 translations:
# →   udp 10.0.0.50:12345 203.0.113.10:20001 -> 8.8.8.8:53

# Проверка NAT statistics
sudo vppctl show nat44 statistics
```

### Сценарий 5: ACL в VPP

```bash
# Создание ACL с правилами
sudo vppctl acl add ip4 deny \
    proto 1 src 10.0.0.0/8 dst 10.0.0.0/8

sudo vppctl acl add ip4 permit \
    proto 6 src 0.0.0.0/0 dst 10.0.1.80/32 dst-port 80

sudo vppctl acl add ip4 permit \
    proto 6 src 0.0.0.0/0 dst 10.0.1.80/32 dst-port 443

# Применение ACL к интерфейсу (ingress)
sudo vppctl set interface acl GigabitEthernet0/0/0 input

# Просмотр ACL
sudo vppctl show acl
# → ACLs:
# → [0] ...
# → [1] ...
# → [2] ...

# Просмотр ACL на интерфейсе
sudo vppctl show interface acl GigabitEthernet0/0/0
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **VPP crash** | VPP process terminated, core dump | `journalctl -u vpp`; `/var/crash/` | Проверить compatibility plugin'ов; увеличить hugepages |
| **NIC not detected** | DPDK driver not binding | `dpdk-devbind.py --status` | Bind NIC к DPDK: `dpdk-devbind.py -b igb_uio <PCI>` |
| **Hugepages insufficient** | VPP fails to start, "no memory" | `cat /proc/meminfo \| grep HugePages` | Настроить hugepages: `echo 1024 > /proc/sys/vm/nr_hugepages` |
| **ACL drops** | Legitimate traffic dropped | `vppctl show interface stats`; `vppctl trace add ..." | Проверить ACL rules; добавить permit rule |
| **NAT table full** | New translations not created | `vppctl show nat44 translations`; `vppctl show nat44 statistics` | Увеличить `nat44 max translations`; настроить session timeout |
| **Performance degradation** | Low throughput, high CPU | `vppctl show runtime`; `perf top -g` | Optimize pipeline; use appropriate NUMA node |

### Команды отладки

```bash
# Общая информация
sudo vppctl show version
sudo vppctl show interface
sudo vppctl show interface address
sudo vppctl show runtime

# Трафик и статистика
sudo vppctl show interface stats
sudo vppctl show ip fib
sudo vppctl show ip arp
sudo vppctl show bridge-domain 100 detail

# Tracing (отладка пакетов)
sudo vppctl trace add interface-input 10
# → Generate traffic
sudo vppctl trace dump

# Packet capture (в VPP)
sudo vppctl packet-tracer max 100
# → Generate traffic
sudo vppctl packet-tracer show

# Runtime profiling
sudo vppctl show runtime
# → Name                   Calls   Suspends  ...
# → ip4-lookup             123456  0         ...
# → ip4-nat44-out2in       123456  0         ...

# Per-CPU statistics
sudo vppctl show runtime per-node
```

---

## Дополнительная информация

**Производственные рекомендации:**
- VPP best suited для NFV и high-perf forwarding (10G-100G).
- Используйте hugepages (1G hugepages для production).
- Привязывайте NIC к正确的 NUMA node (CPU near NIC).
- VPP не заменяет полностью Linux networking stack (нет TCP/IP в Userspace).
- Для overlay сетей используйте VPP + DPDK + VXLAN plugins.

**Связанные темы:**
- **[DPDK](../dpdk/dpdk_overview.md)** — основа для VPP.
- **[eBPF/XDP](./ebpf_xdp.md)** — альтернативный high-perf datapath (kernel-based).
- **[OpenFlow/OVS](./openflow.md)** — VPP как замена OVS для NFV.
- **[SRv6](./srv6.md)** — VPP поддерживает SRv6 tunneling.
- **[NFV](./sdn_overview.md#key-преимущества-sdn)** — VPP как NFV datapath.
