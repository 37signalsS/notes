# nftables — настройка производительности

## Определения

**Flowtable (Fastpath)** — механизм ядра Linux, позволяющий передавать пакеты установленных соединений напрямую между сетевыми интерфейсами, минуя классический стек Netfilter. Снижает нагрузку на CPU и задержки (latency), делая nftables пригодным для маршрутизаторов на скоростях 10Gbps+.

**XDP (eXpress Data Path)** — программируемый уровень обработки пакетов в ядре Linux, работающий на уровне драйвера сетевой карты до выделения `sk_buff`. Обеспечивает максимальную производительность фильтрации (10-100 Mpps), но ограничивается простыми действиями (drop, pass, redirect).

**conntrack** — подсистема ядра Linux для отслеживания состояний сетевых соединений. Основной bottleneck при высоких нагрузках из-за необходимости проверки каждого пакета.

**RSS (Receive Side Scaling)** — механизм распределения входящих пакетов между несколькими ядрами CPU на уровне NIC. Позволяет обойти ограничение single-core обработки.

**RPS (Receive Packet Steering)** — программный аналог RSS, реализованный в ядре. Распределяет пакеты между ядрами CPU после получения NIC, что полезно для NIC с одной очередью.

**XPS (Transmit Packet Steering)** — механизм привязки TX-очередей NIC к конкретным ядрам CPU для минимизации межядерного трафика.

**NUMA (Non-Uniform Memory Access)** — архитектура, при которой доступ к памяти через разные процессоры/сокеты имеет разную задержку. Критично для multi-socket серверов с 10G+ NIC.

**GRO (Generic Receive Offload)** — агрегация мелких пакетов в крупные перед обработкой в стеке ядра. Снижает количество прерываний и нагрузку на CPU.

**Multi-queue NIC** — сетевая карта с несколькими аппаратными очередями (Rx/Tx queues), позволяющими параллельную обработку пакетов на нескольких ядрах CPU.

## Основные концепции

### Место nftables в pipeline обработки пакета

```
NIC (hardware) → RSS → DMA → softirq (ksoftirqd) → Netfilter (nftables) → Application
       ↑                                              ↑
       XDP (driver-level)                    flowtable (bypass Netfilter)
```

**Ключевые точки:**
1. **XDP** — самая ранняя точка (до `sk_buff`), минимальная задержка.
2. **nftables** — стандартный уровень фильтрации (после выделения `sk_buff`).
3. **Flowtable** — bypass Netfilter для established-соединений (после `conntrack`).

### Факторы производительности

| Фактор | Влияние | Оптимизация |
|:---|:---|:---|
| **Количество правил** | Линейный поиск $O(n)$ | Sets/maps ($O(1)$), конкатенации |
| **Conntrack** | Проверка каждого пакета | `nf_conntrack_max`, `ct timeout`, `notrack` |
| **Flowtable** | Bypass Netfilter | `flow offload` для established |
| **XDP** | Driver-level фильтрация | XDP-pass/drop для DDoS |
| **RSS/RPS** | Распределение по ядрам | Настройка queues,irq affinity |
| **NUMA** | Межsocket latency | Привязка NIC к NUMA-node |
| **GRO/LRO** | Агрегация пакетов | `ethtool -K eth0 gro on` |

### Производительность vs гибкость

```
Максимальная производительность                    Максимальная гибкость
      │                                                    │
   XDP    →    flowtable    →    nftables (sets)    →    nftables (линейный)
  100 Mpps     10 Gbps            1 Gbps                  100 Mbps
```

## Предварительные требования

### Аппаратные требования

| Компонент | Минимум | Рекомендуется (10G+) |
|:---|:---|:---|
| **CPU** | 2 ядра | 8+ ядер, NUMA-aware |
| **RAM** | 2 GB | 16 GB+ (для conntrack) |
| **NIC** | 1x 1Gbps | Multi-queue 10G/25G/100G |
| **Ядро** | 5.3+ | 5.15+ (flowtable improvements) |

### Проверка окружения

```bash
# Версия ядра
uname -r

# NUMA-топология
lscpu | grep -E "NUMA|Socket|Core"
# → NUMA node(s):        2
# → Socket(s):           2
# → Core(s) per socket:  16

# Возможности NIC
ethtool -k eth0 | grep -E "gro|lro|rx-vlan|ntuple"
# → generic-receive-offload: on
# → large-receive-offload: off

# Multi-queue NIC
ethtool -l eth0
# → Combined:          8
# → RX:                8
# → TX:                8

# Текущие RSS queues
cat /proc/interrupts | grep eth0 | wc -l
# → 8 (по числу queues)
```

## Практические сценарии

### 1. Оптимизация conntrack

Conntrack — основной bottleneck при высоких нагрузках. Каждый пакет проходит проверку в таблице состояний.

**Настройка sysctl:**
```bash
# /etc/sysctl.d/99-conntrack-tuning.conf

# Максимальное количество записей conntrack
# Веб-сервис: 512K-1M, Маршрутизатор: 2M-4M
net.netfilter.nf_conntrack_max = 1048576

# Размер хэш-таблицы (рекомендуется = max / 4)
net.netfilter.nf_conntrack_buckets = 262144

# Таймауты TCP (по умолчанию 5 дней — слишком долго для серверов)
net.netfilter.nf_conntrack_tcp_timeout_established = 86400
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 30

# Таймауты UDP (.stream = ответ на DNS-запрос)
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 60

# Общие
net.netfilter.nf_conntrack_generic_timeout = 120
net.netfilter.nf_conntrack_icmp_timeout = 10

# Логирование переполнения
net.netfilter.nf_log_all_netns = 0
```

**Применение:**
```bash
sudo sysctl -p /etc/sysctl.d/99-conntrack-tuning.conf
```

**Отключение conntrack для конкретного трафика (notrack):**
```bash
table inet raw {
    chain prerouting {
        type filter hook prerouting priority -300; policy accept;

        # DNS-запросы к кэширующему серверу — не отслеживать
        udp dport 53 ip daddr 10.0.0.53 notrack

        # HTTP к CDN — не отслеживать (высокий трафик)
        tcp dport { 80, 443 } ip daddr @cdn_servers notrack
    }
}
```

### 2. Flowtable для маршрутизаторов (10G+)

Flowtable позволяет established-соединения обходить Netfilter, что критично для маршрутизаторов.

```bash
table ip filter {
    flowtable ft_main {
        hook ingress priority 0
        devices = { eth0, eth1 }
    }

    chain forward {
        type filter hook forward priority 0; policy drop;

        # Established — в fastpath
        ct state established flow add @ft_main

        # Остальные — классическая обработка
        ct state established,related accept
        ct state invalid drop

        # Остальные правила...
    }
}
```

**Валидация:**
```bash
# Проверка flowtable
sudo nft list flowtable ip filter ft_main

# Мониторинг: сколько пакетов идет через fastpath
watch -n 1 'sudo nft list chain ip filter forward'
# → ct state established flow add @ft_main # packets 1542000 bytes 987200000
```

**Ограничения flowtable:**
- Работает только для established-соединений (не для new)
- Не поддерживает NAT (для маршрутизаторов с NAT используйте классические цепочки)
- Не поддерживает `log`, `quota`, `counter` внутри flowtable

### 3. XDP для DDoS-защиты

XDP работает на уровне драйвера NIC, до выделения `sk_buff`. Подходит для простых правил drop/pass.

```bash
# Загрузка XDP-программы (пример: drop на порт 80)
ip link set dev eth0 xdpgeneric obj xdp_drop.o sec xdp

# Проверка
ip link show dev eth0 | grep xdp
# → xdpgeneric id 42

# Отключение
ip link set dev eth0 xdpgeneric off
```

**XDP vs nftables:**
| Критерий | XDP | nftables |
|:---|:---|:---|
| **Уровень** | Driver (до sk_buff) | Netfilter (после sk_buff) |
| **Производительность** | 10-100 Mpps | 1-10 Mpps |
| **Гибкость** | Ограничена (drop, pass, redirect) | Полная (sets, maps, conntrack) |
| **Conntrack** | Недоступен | Доступен |
| **Диагностика** | Сложная (perf, bpftool) | Простая (nft list, nftrace) |
| **Применение** | DDoS-защита, простая фильтрация | Сложная логика, stateful |

**Рекомендация:** Используйте XDP для простых правил drop (DDoS), а nftables — для сложной логики (stateful, sets, maps).

### 4. RSS и multi-queue NIC

**Настройка RSS queues:**
```bash
# Просмотр текущего количества queues
ethtool -l eth0
# → Combined: 8

# Установка количества queues (равно числу ядер на NUMA-node)
sudo ethtool -L eth0 combined 8

# Проверка распределения IRQ
cat /proc/interrupts | grep eth0
# → 128:  12345  12345  12345  12345  12345  12345  12345  12345   PCI-MSI-edge   eth0-TxRx-0
# → 129:  12345  12345  12345  12345  12345  12345  12345  12345   PCI-MSI-edge   eth0-TxRx-1
```

**Настройка IRQ affinity (привязка к NUMA-node):**
```bash
# Определение NUMA-node NIC
cat /sys/class/net/eth0/device/numa_node
# → 0

# Привязка IRQ к ядрам NUMA-node 0
for irq in $(grep eth0 /proc/interrupts | awk -F: '{print $1}' | tr -d ' '); do
    echo 1 > /proc/irq/$irq/smp_affinity  # CPU 0
done

# Или через irqbalance (автоматически)
sudo systemctl enable --now irqbalance
```

### 5. RPS и XPS

**RPS (Receive Packet Steering):**
```bash
# Включение RPS для eth0 (распределение на 8 ядер)
echo "ff" > /sys/class/net/eth0/queues/rx-0/rps_cpus
echo "ff" > /sys/class/net/eth0/queues/rx-1/rps_cpus

# Для всех queues
for queue in /sys/class/net/eth0/queues/rx-*/rps_cpus; do
    echo "ff" > "$queue"
done
```

**XPS (Transmit Packet Steering):**
```bash
# Привязка TX-queues к ядрам
echo "1" > /sys/class/net/eth0/queues/tx-0/xps_cpus  # CPU 0
echo "2" > /sys/class/net/eth0/queues/tx-1/xps_cpus  # CPU 1
echo "4" > /sys/class/net/eth0/queues/tx-2/xps_cpus  # CPU 2
echo "8" > /sys/class/net/eth0/queues/tx-3/xps_cpus  # CPU 3
```

### 6. GRO и offloading

```bash
# Включение GRO (агрегация пакетов)
sudo ethtool -K eth0 gro on

# Включение TSO (TCP Segmentation Offload)
sudo ethtool -K eth0 tso on

# Включение LRO (Large Receive Offload) — только для серверов
sudo ethtool -K eth0 lro on

# Проверка
ethtool -k eth0 | grep -E "gro|tso|lro"
# → generic-receive-offload: on
# → tcp-segmentation-offload: on
# → large-receive-offload: on
```

### 7. Оптимизация sets для больших списков

При работе с наборами (sets), содержащими тысячи элементов, утилита `nft list set` может потреблять значительные ресурсы или завершаться паникой (OOM) из-за попытки вывести все элементы. Для диагностики и администрирования используйте флаг `-s`/`--stateless`, который выводит только определение набора без перечисления элементов.

```bash
 # Полный вывод (опасно для больших sets)
nft list set inet filter blacklist

 # Только определение набора (безопасно)
nft list set inet filter blacklist -s
# → table inet filter {
# →     set blacklist {
# →         type ipv4_addr
# →         flags interval, timeout
# →         timeout 1h
# →     }
# → }
```

**Рекомендация:** Добавьте alias или функцию-обёртку для ежедневного использования:

```bash
alias nft-sets='nft list set'
alias nft-ruleset='nft list ruleset'
```

```bash
table inet filter {
    # Использование interval для CIDR-блоков
    set blacklist {
        type ipv4_addr
        flags interval, timeout
        timeout 1h
        # Автоматическое удаление устаревших записей
    }

    # Конкатенация для контекстных проверок
    set allowed_pairs {
        type ipv4_addr . inet_service
        flags interval
        elements = {
            10.0.0.0/8 . 22,
            10.0.0.0/8 . 80,
            10.0.0.0/8 . 443
        }
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # O(1) проверка вместо линейного перебора
        ip saddr @blacklist drop
        ip saddr . tcp dport @allowed_pairs accept
    }
}
```

### 8. NUMA-aware размещение

```bash
# Определение NUMA-топологии
numactl --hardware
# → node 0 cpus: 0 1 2 3 4 5 6 7
# → node 1 cpus: 8 9 10 11 12 13 14 15
# → node 0 size: 32768 MB
# → node 1 size: 32768 MB

# Привязка nftables к NUMA-node 0 (вместе с NIC)
numactl --cpunodebind=0 --membind=0 nft -f /etc/nftables.conf

# Или через systemd
# /etc/systemd/system/nftables.service.d/numa.conf
[Service]
ExecStart=
ExecStart=/usr/bin/numactl --cpunodebind=0 --membind=0 /usr/sbin/nft -f /etc/nftables.conf
```

### 9. Профилирование производительности nftables

```bash
# Замер времени обработки пакета через perf
sudo perf record -e 'nf_tables:*' -a -- sleep 5
sudo perf report

# Проверка softirq
watch -n 1 'cat /proc/softirqs | grep NET_RX'
# → NET_RX: 1234567 1234567 1234567 1234567 ...

# Проверка времени обработки в softirq
cat /proc/net/softnet_stat
# → Столбец 2: time_us (микросекунды на пакет)

# Профилирование через bpftrace
sudo bpftrace -e 'kprobe:nf_hook_slow { @[comm] = count(); }'
```

## Валидация результатов

### Проверка throughput

```bash
# Тестирование через iperf3
iperf3 -s -p 5201  # Сервер
iperf3 -c <server_ip> -t 30 -P 8  # Клиент (8 потоков)
# → [ ID] Interval       Transfer     Bitrate
# → [  5] 0.00-30.00  sec  34.5 GBytes  9.89 Gbits/sec

# С включенным flowtable
# → [  5] 0.00-30.00  sec  34.5 GBytes  9.91 Gbits/sec (немного быстрее)
```

### Проверка conntrack

```bash
# Текущее использование
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → nf_conntrack_count = 45000
# → nf_conntrack_max = 1048576

# Статистика drop
conntrack -S | grep drop
# → cpu=0   found=12850 invalid=120 ... drop=0
```

### Проверка RSS

```bash
# Распределение пакетов по queues
cat /proc/net/dev | grep eth0
# → eth0: 1234567890 12345 ... (RX bytes)

# Распределение по ядрам
mpstat -P ALL 1
# → Все ядра должны загружаться равномерно
```

## Диагностика и устранение неполадок

| Проблема | Признак | Диагностика | Решение |
|:---|:---|:---|:---|
| **Одно ядро загружено на 100%** | `top` показывает 100% на одном CPU | `cat /proc/interrupts \| grep eth0` | Настройте RSS, RPS, IRQ affinity |
| **Conntrack переполнен** | `dmesg` показывает `table full` | `conntrack -S \| grep drop` | Увеличьте `nf_conntrack_max`, настройте `ct timeout` |
| **Flowtable не работает** | Нет ускорения | `nft list flowtable` | Убедитесь, что `ct state established flow add` присутствует |
| **XDP не загружается** | `ip link show` нет xdp | `dmesg \| grep xdp` | Проверьте поддержку driver NIC |
| **Высокий softirq** | `top` показывает high si | `cat /proc/softirqs \| grep NET_RX` | Включите RSS, GRO, увеличьте queues |
| **Асимметричная загрузка ядер** | `mpstat` показывает неравномерность | `cat /proc/net/softnet_stat` | Настройте RPS, XPS |

## Best Practices

1. **Conntrack tuning** — настраивайте `nf_conntrack_max` и таймауты под конкретный workload. Для веб-сервера: 512K-1M записей, таймаут established = 86400s.

2. **Flowtable** — используйте для маршрутизаторов и балансировщиков с >1Gbps. Не используйте для NAT или сложной логики.

3. **XDP** — начинайте с `xdpgeneric` для тестирования, переходите на `xdp` (native) для production. Используйте только для простых правил drop.

4. **RSS** — устанавливайте количество queues равным числу ядер на NUMA-node. Привязывайте IRQ к ядрам NIC.

5. **GRO** — включайте на всех серверах. Снижает количество прерываний и нагрузку на CPU.

6. **Sets** — используйте именованные наборы вместо анонимных для >10 элементов. Включайте `interval` для CIDR-блоков.

7. **Профилирование** — перед оптимизацией замерьте `mpstat`, `conntrack -S`, `/proc/softnet_stat`. Оптимизируйте узкое место.

8. **NUMA** — на multi-socket серверах привязывайте nftables и NIC к одному NUMA-node.

## См. также

- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — flowtable, sets, maps.
- **[nftables — практические сценарии](./practical_scenarios.md)** — flowtable, rate limiting.
- **[eBPF/XDP](../../../../../../Networking/Concepts/sdn/ebpf_xdp.md)** — архитектура XDP.
- **[Настройка сети (sysctl)](../../../../../../Linux/Networking/Settings/sysctl_network.md)** — RSS, GRO, offloading.
- **[NUMA-осведомленность](../../../../../../Linux/Core/processes/numa_awareness.md)** — NUMA-topology и привязка процессов.
