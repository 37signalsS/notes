# Сетевая диагностика ВМ (KVM)

В данном файле описывается методология диагностики сетевых проблем виртуальных машин KVM/QEMU: от определения уровня проблемы до решения. Базовые сетевые архитектуры KVM описаны в [Сетевые основы KVM](./kvm_networking_fundamentals.md), а продвинутые топологии — в [Продвинутая сеть KVM](./kvm_networking_advanced.md).

## Определения

**macvtap** — виртуальный интерфейс, объединяющий bridge и прямой доступ к физическому NIC через MAC-адрес. В bridge-режиме имеет ограничение: трафик между ВМ на одном хосте не маршрутизируется через macvtap напрямую.

**vhost-net** — механизм переноса обработки сетевых пакетов VirtIO из userspace (QEMU) в ядро Linux. Снижает latency и CPU overhead по сравнению с пользовательским virtio-net.

**Multi-Queue VirtIO (MQ)** — многопоточная обработка сетевых очередей. Количество очередей должно соответствовать количеству vCPU для максимальной пропускной способности.

**SR-IOV (Single Root I/O Virtualization)** — аппаратная виртуализация NIC, создающая виртуальные функции (VF) с прямым DMA-доступом. Обеспечивает производительность, близкую к bare-metal.

**OVS (Open vSwitch)** — программный L2-коммутатор с поддержкой OpenFlow. Используется для сложных сетевых топологий в KVM-кластерах.

**conntrack** — подсистема ядра для отслеживания состояний TCP/UDP соединений. Частый bottleneck при большом количестве ВМ.

**MTU (Maximum Transmission Unit)** — максимальный размер кадра. MTU mismatch между хостом, ВМ и физическим оборудованием вызывает blackhole (пакеты теряются без ошибок).

## Базовые концепции

### Модель сетевого стека KVM

```
┌─────────────────────────────────────────────────┐
│  Гостевая ОС (ВМ)                               │
│  └── eth0 (virtio-net)                          │
│       ├── MQ: queues=4 ( virtio multiqueue)     │
│       └── Offloads: TSO, GSO, GRO               │
├─────────────────────────────────────────────────┤
│  QEMU (userspace)                               │
│  ├── virtio-net-pci (backend)                   │
│  └── vhost-net (kernel offload)                 │
├─────────────────────────────────────────────────┤
│  Ядро хоста                                     │
│  ├── vnet0 (tap device)                         │
│  ├── br0 (Linux Bridge) или OVS                 │
│  ├── conntrack                                  │
│  └── iptables/nftables (LIBVIRT_* chains)       │
├─────────────────────────────────────────────────┤
│  Физический NIC                                 │
│  └── eno1 / enp0s31f6                           │
└─────────────────────────────────────────────────┘
```

### Уровни диагностики

Диагностика строится по принципу Bottom-Up:

```
Уровень 5: Приложение (HTTP, SSH, DNS)
    ↓
Уровень 4: TCP/UDP (порты, соединения)
    ↓
Уровень 3: IP (маршрутизация, ARP)
    ↓
Уровень 2: Ethernet (bridge, VLAN, MTU)
    ↓
Уровень 1: Физический (cable, NIC, driver)
```

## Практические сценарии

### Сценарий 1: ВМ не получает IP-адрес

**Симптом:** `virsh domifaddr <vm>` пуст, DHCP не работает.

```bash
# 1. Проверка состояния ВМ
virsh domstate web-server-01
# → running

# 2. Проверка MAC-адреса в конфигурации
virsh dumpxml web-server-01 | grep -A5 "interface type"
# → <interface type='network'>
# →   <mac address='52:54:00:aa:bb:cc'/>
# →   <source network='default'/>

# 3. Проверка виртуальной сети
virsh net-list --all
# → Name      State    Autostart   Persistent
# → default   active   yes         yes

virsh net-info default
# → Active: yes
# → Bridge: virbr0

# 4. Проверка DHCP-аренд
cat /var/lib/libvirt/dnsmasq/default.leases
# → 1695481234 52:54:00:aa:bb:cc 192.168.122.10 web-server-01 *

# 5. Проверка dnsmasq
systemctl status libvirtd-dnsmasq
journalctl -u libvirtd-dnsmasq --since "10 minutes ago"

# 6. Проверка iptables (LIBVIRT_DHCP chain)
sudo iptables -L LIBVIRT_DHCP -n -v
# → ACCEPT  0  0  0.0.0.0/0  192.168.122.0/24  udp dpt:67

# 7. РЕШЕНИЕ: Принудительная выдача DHCP
virsh net-update default add ip-dhcp-host \
  "<host mac='52:54:00:aa:bb:cc' ip='192.168.122.10'/>" \
  --config
```

### Сценарий 2: ВМ не имеет сети после миграции

**Симптом:** После live migration ВМ теряет сетевую связность.

```bash
# 1. Проверка на целевом хосте
virsh domifaddr web-server-01
# →ifa 2    bridge    52:54:00:aa:bb:cc    ipv4    192.168.122.10/24

# 2. Проверка bridge
bridge link show
# → 3: vnet0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master br0 state forwarding

# 3. Проверка ARP-таблицы хоста
arp -n | grep 192.168.122.10
# → 192.168.122.10  ether  52:54:00:aa:bb:cc  C  virbr0

# 4. Проверка macvtap (если используется)
ip link show vnet0
# → vnet0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...

# 5. Проверка filter (если включен nwfilter)
virsh nwfilter-binding-list
# → UUID                  Portdev   Filter
# → xxxxxxxx-...          vnet0     clean-traffic

# 6. РЕШЕНИЕ: Перезапуск сети внутри гостя
virsh qemu-agent-command web-server-01 \
  '{"execute":"guest-network-get-interfaces"}' 2>/dev/null

# Или через SSH (если доступен):
ssh root@192.168.122.10 "systemctl restart networking"
```

### Сценарий 3: Низкая пропускная способность (1 Gbps вместо 10 Gbps)

**Симптом:** `iperf3` показывает ~940 Мбит/с вместо ожидаемых 10 Гбит/с.

```bash
# 1. Проверка MTU на всех уровнях
# На хосте:
ip link show eno1 | grep mtu
# → mtu 1500

# Внутри гостя:
ssh root@192.168.122.10 "ip link show eth0 | grep mtu"
# → mtu 1500

# Проверка что MTU согласован: ping с DF bit
ping -M do -s 1472 192.168.122.1
# Если: "message too long" → MTU mismatch

# 2. Проверка multi-queue
# Внутри гостя:
ssh root@192.168.122.10 "ethtool -l eth0"
# → Pre-set maximums:
# → Combined:   4        ← max queues
# → Current:
# → Combined:   1        ← только 1 очередь!

# 3. РЕШЕНИЕ: Включение multi-queue
# В XML ВМ:
# <interface type='network'>
#   <model type='virtio'/>
#   <driver name='vhost' queues='4'/>
# </interface>

virsh edit web-server-01
# → (добавить queues='4' в секцию driver)

# Проверка внутри гостя:
ssh root@192.168.122.10 "ethtool -l eth0"
# → Combined:   4

# 4. Проверка offload
# Внутри гостя:
ssh root@192.168.122.10 "ethtool -k eth0 | grep -E 'tcp-segmentation|generic-segmentation|generic-receive-offload'"
# → tcp-segmentation-offload: on
# → generic-segmentation-offload: on
# → generic-receive-offload: on

# 5. Бенчмарк после исправлений
# На хосте (сервер):
iperf3 -s

# Внутри гостя (клиент):
iperf3 -c 192.168.122.1 -P 4 -t 30
# → [ ID] Interval       Transfer     Bitrate
# → [  5] 0.00-30.00  sec  33.5 GBytes  9.59 Gbits/sec  ← OK
```

### Сценарий 4: Высокий latency между ВМ

**Симптом:** `ping` между ВМ на одном хосте показывает задержки > 0.5ms.

```bash
# 1. Базовый замер latency
ping -c 100 192.168.122.10
# → rtt min/avg/max/mdev = 0.123/0.456/1.234/0.234 ms

# 2. Проверка conntrack (частый bottleneck)
cat /proc/sys/net/netfilter/nf_conntrack_count
# → 384567

cat /proc/sys/net/netfilter/nf_conntrack_max
# → 524288

# Процент использования:
echo "scale=1; $(cat /proc/sys/net/netfilter/nf_conntrack_count) * 100 / $(cat /proc/sys/net/netfilter/nf_conntrack_max)" | bc
# → 73.3%  ← high!

# 3. Проверка iptables правил
sudo iptables -L -n -v | head -20
# → Если много DROP/REJECT → проверить nwfilter

# 4. Проверка CPU на обработку пакетов
mpstat -P ALL 1 5 | grep -E "CPU|idle"
# → Если %soft или %irq высокие → увеличить RPS/XPS

# 5. РЕШЕНИЕ: Отключение conntrack для internal traffic
# Если ВМ общаются только между собой через bridge:
sudo sysctl -w net.bridge.bridge-nf-call-iptables=0
sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0

# Или через iptables (netfilter bypass):
sudo iptables -t raw -A PREROUTING -i virbr0 -j NOTRACK
sudo iptables -t raw -A OUTPUT -o virbr0 -j NOTRACK

# 6. РЕШЕНИЕ: Увеличение conntrack max
sudo sysctl -w net.netfilter.nf_conntrack_max=1048576
sudo sysctl -w net.netfilter.nf_conntrack_buckets=262144
```

### Сценарий 5: Потеря пакетов (packet loss)

**Симптом:** `ping` показывает 5-20% packet loss, `iperf3` обрывается.

```bash
# 1. Проверка на уровне NIC
ethtool -S eno1 | grep -iE "drop|error|miss"
# → rx_missed_errors: 0
# → rx_dropped: 0
# → tx_dropped: 0

# 2. Проверка ring buffer
ethtool -g eno1
# → Pre-set maximums:
# → RX:  4096
# → TX:  4096
# → Current hardware settings:
# → RX:  256    ← слишком мало!
# → TX:  256

# 3. РЕШЕНИЕ: Увеличение ring buffer
sudo ethtool -G eno1 rx 4096 tx 4096

# 4. Проверка IRQ balance
cat /proc/interrupts | grep eno1
# → Если все IRQ на одном CPU → IRQ balance проблема

# РЕШЕНИЕ: Включение irqbalance
sudo systemctl enable --now irqbalance

# 5. Проверка RPS (Receive Packet Steering)
cat /sys/class/net/eno1/queues/rx-0/rps_cpus
# → 00000000  ← отключено

# РЕШЕНИЕ: Включение RPS для распределения по CPU
echo "ff" | sudo tee /sys/class/net/eno1/queues/rx-0/rps_cpus

# 6. Проверка QoS/TC
tc -s qdisc show dev eno1
# → Если планировщик не настроен → добавить:
tc qdisc add dev eno1 root pfifo_fast
```

### Сценарий 6: ВМ не видна из внешней сети

**Симптом:** ВМ работает, имеет IP в NAT-сети, но недоступна извне.

```bash
# 1. Проверка port forwarding (NAT)
virsh net-dumpxml default | grep -A5 forward
# → <forward mode='nat'>
# →   <nat>
# →     <port start='1024' end='65535'/>
# →   </nat>
# → </forward>

# 2. Настройка port forwarding
# Добавление DNAT для порта 80:
virsh net-update default add port-forward \
  "<port proto='tcp' hostip='' start='8080' end='8080'/>" \
  --config

# Или через iptables напрямую:
sudo iptables -t nat -A LIBVIRT_FWI -p tcp -d 192.168.122.10 --dport 80 \
  -j DNAT --to-destination 192.168.122.10:80

# 3. Проверка файрвола
sudo iptables -L LIBVIRT_FWI -n -v
# → Если DROP все → добавить правило:

sudo iptables -I LIBVIRT_FWI -p tcp -d 192.168.122.10 --dport 80 -j ACCEPT

# 4. Проверка внутри ВМ
ssh root@192.168.122.10 "iptables -L INPUT -n -v"
# → Если есть DROP → настроить внутри гостя:

ssh root@192.168.122.10 "iptables -I INPUT -p tcp --dport 80 -j ACCEPT"

# 5. Альтернатива: macvtap (прямой доступ без NAT)
# В XML ВМ:
# <interface type='direct'>
#   <mac address='52:54:00:aa:bb:cc'/>
#   <source dev='eno1' mode='bridge'/>
#   <model type='virtio'/>
# </interface>
# Ограничение: трафик между ВМ на одном хосте не работает
```

### Сценарий 7: DNS-резолвинг не работает

**Симптом:** Внутри ВМ `ping 8.8.8.8` работает, но `ping google.com` — нет.

```bash
# 1. Проверка DNS внутри ВМ
ssh root@192.168.122.10 "cat /etc/resolv.conf"
# → nameserver 192.168.122.1

# 2. Проверка DNS на хосте
cat /var/lib/libvirt/dnsmasq/default.conf | grep server
# → server=8.8.8.8
# → server=8.8.4.4

# 3. Тест DNS через dnsmasq
dig @192.168.122.1 google.com
# → ;; ANSWER SECTION:
# → google.com.  300  IN  A  142.250.74.78

# 4. Проверка /etc/resolv.conf внутри ВМ
ssh root@192.168.122.10 "nslookup google.com 192.168.122.1"
# → Server:   192.168.122.1
# → Address:  192.168.122.1#53
# → Non-authoritative answer:
# → Name:     google.com
# → Address:  142.250.74.78

# 5. РЕШЕНИЕ: Если dnsmasq не отвечает
sudo systemctl restart libvirtd-dnsmasq
# Или добавить внешний DNS в конфигурацию сети:
virsh net-edit default
# → <dns>
# →   <forwarder addr='8.8.8.8'/>
# →   <forwarder addr='1.1.1.1'/>
# → </dns>
```

### Сценарий 8: macvtap — ограничение и обход

**Проблема:** macvtap в bridge-режиме не позволяет трафику между ВМ на одном хосте.

```bash
# 1. Проверка используется ли macvtap
virsh dumpxml web-server-01 | grep "interface type"
# → <interface type='direct'>
# →   <source dev='eno1' mode='bridge'/>

# 2. Симптом: ВМ-1 (macvtap) НЕ может ping ВМ-2 (macvtap) на том же хосте
# Но обе ВМ доступны из внешней сети

# 3. РЕШЕНИЕ: Использование дополнительного bridge-интерфейса
# Создание моста для inter-VM traffic:
sudo ip link add br-internal type bridge
sudo ip link set br-internal up

# Добавление macvtap к bridge (внутренний интерфейс):
# В XML каждой ВМ добавить второй интерфейс:
# <interface type='bridge'>
#   <source bridge='br-internal'/>
#   <model type='virtio'/>
# </interface>

# 4. Альтернатива: полный bridge без macvtap
# Замена direct на bridge в XML:
virsh edit web-server-01
# → <interface type='bridge'>
# →   <source bridge='br0'/>
# →   <model type='virtio'/>
# → </interface>
```

### Сценарий 9: SR-IOV — диагностика VF

**Симптом:** VF не видна в ВМ или работает медленно.

```bash
# 1. Проверка VF на хосте
lspci | grep -i "virtual function"
# → 01:00.2 Ethernet controller: Intel Corporation Ethernet Controller X710 for 10GbE SFP+ (VF)

# 2. Проверка IOMMU
dmesg | grep -i iommu
# → DMAR: IOMMU enabled
# → vfio-pci 0000:01:00.2: enabling device (0000 -> 0002)

# 3. Проверка привязки к vfio-pci
dpdk-devbind.py --status | grep 01:00.2
# → 0000:01:00.2 'Device 1592' if= drv=vfio-pci unused=i40e

# 4. Проверка в ВМ
ssh root@192.168.122.10 "lspci | grep -i ethernet"
# → 00:03.0 Ethernet controller: Intel Corporation Ethernet Virtual Function 700 Series

# 5. Проверка driver внутри ВМ
ssh root@192.168.122.10 "ethtool -i ens3"
# → driver: i40evf
# → version: 2.7.2-k

# 6. РЕШЕНИЕ: Если VF не видна
# Проверка XML ВМ:
virsh dumpxml web-server-01 | grep -A10 hostdev
# → <hostdev mode='subsystem' type='pci' managed='yes'>
# →   <source>
# →     <address domain='0x0000' bus='0x01' slot='0x00' function='0x2'/>
# →   </source>
# → </hostdev>

# Если managed='no' → установить managed='yes'
virsh edit web-server-01
```

## Быстрый чек-лист диагностики

```bash
#!/bin/bash
# vm-network-diagnose.sh — быстрая диагностика сети ВМ
set -euo pipefail

VM_NAME="${1:?Usage: $0 <vm-name>}"

echo "=== VM Network Diagnostics: $VM_NAME ==="

# 1. Состояние ВМ
echo "--- VM State ---"
virsh domstate "$VM_NAME"

# 2. Сетевые интерфейсы
echo "--- Network Interfaces ---"
virsh domifaddr "$VM_NAME"

# 3. XML конфигурация сети
echo "--- Network Config ---"
virsh dumpxml "$VM_NAME" | grep -A8 "interface type"

# 4. Bridge status
echo "--- Bridge Status ---"
bridge link show | head -10

# 5. Conntrack usage
echo "--- Conntrack ---"
COUNT=$(cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null || echo "N/A")
MAX=$(cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null || echo "N/A")
echo "conntrack: $COUNT / $MAX"

# 6. DHCP leases
echo "--- DHCP Leases ---"
cat /var/lib/libvirt/dnsmasq/*.leases 2>/dev/null | head -5

# 7. Проверка DNS
echo "--- DNS Test ---"
GUEST_IP=$(virsh domifaddr "$VM_NAME" 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
if [ -n "$GUEST_IP" ]; then
  echo "Guest IP: $GUEST_IP"
  ping -c 1 -W 2 "$GUEST_IP" && echo "Ping: OK" || echo "Ping: FAIL"
fi
```

## Типичные ошибки и их решения

| Симптом | Причина | Команда диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **ВМ не получает IP** | dnsmasq не работает | `systemctl status libvirtd-dnsmasq` | Перезапустить `systemctl restart libvirtd-dnsmasq` |
| **Низкая пропускная способность** | MTU mismatch | `ip link show` + `ping -M do -s 1472` | Согласовать MTU на всех уровнях |
| **Packet loss** | conntrack满了 | `cat /proc/sys/net/netfilter/nf_conntrack_count` | Увеличить `nf_conntrack_max` |
| **Высокий latency** | conntrack + iptables | `iptables -L -n -v \| wc -l` | Отключить conntrack для internal traffic |
| **DNS не резолвится** | dnsmasq DNS forwarder | `dig @192.168.122.1 google.com` | Добавить `forwarder` в net XML |
| **VF не видна в ВМ** | Некорректный hostdev XML | `virsh dumpxml \| grep hostdev` | Исправить bus/slot/function |
| **После миграции нет сети** | ARP cache устарел | `arp -n \| grep <ip>` | `arp -d <ip>` или перезапуск сети в госте |
| **inter-VM traffic не работает** | macvtap bridge restriction | `virsh dumpxml \| grep "type='direct'"` | Использовать bridge или добавить br-internal |

## Мониторинг

```yaml
# Prometheus alert rules для сети ВМ
groups:
  - name: vm_network_alerts
    rules:
      - alert: VMLostNetwork
        expr: libvirt_domain_info_status{status="running"} == 1 and on(instance) absent(node_network_up{device=~"vnet.*"})
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "ВМ {{ $labels.domain }} потеряла сеть"

      - alert: ConntrackNearFull
        expr: (node_netfilter_conntrack_entries / node_netfilter_conntrack_entries_limit) > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "conntrack > 85% на хосте {{ $labels.instance }}"

      - alert: HighPacketLoss
        expr: rate(node_network_receive_drop_total{device=~"vnet.*"}[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий packet loss на {{ $labels.device }}"
```

## Дополнительная информация

- [Сетевые основы KVM](./kvm_networking_fundamentals.md) — libvirt networks, dnsmasq, nwfilter.
- [Продвинутая сеть KVM](./kvm_networking_advanced.md) — OVS, VXLAN, GRE.
- [Sysctl чек-лист для KVM-хостов](./kvm_host_sysctl_checklist.md) — network sysctl params.
- [Диагностика и решение проблем](./troubleshooting.md) — kvm_stat, логи.
- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — Multi-Queue VirtIO, vhost-net.
