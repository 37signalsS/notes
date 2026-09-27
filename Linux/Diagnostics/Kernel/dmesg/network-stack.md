# Диагностика сетевого стека через dmesg

## Определения

**Сетевой стек Linux** — многоуровневая подсистема ядра, реализующая обработку сетевых пакетов от получения с сетевого интерфейса (NIC) до передачи в сокет приложения. Ключевые компоненты: NIC driver, NAPI (New API), softirq (NET_RX/NET_TX), TCP/IP stack, netfilter/conntrack, socket layer.

**Сообщения сетевого стека в dmesg** — выводы ядра, отражающие события обработки сетевых пакетов: переполнение очередей, ошибки драйверов, переполнение таблиц соединений, аппаратные сбои NIC, проблемы с IRQ-балансировкой. Эти сообщения критичны для диагностики проблем с сетевой производительностью и доступностью сервисов.

---

## Базовые концепции

### Архитектура сетевой обработки

```
NIC (аппаратура)
  ↓ Hard IRQ (прерывание)
  ↓ NAPI (polling mode)
  ↓ SoftIRQ (NET_RX)
  ↓ ksoftirqd (ядерный поток)
  ↓ Netfilter (iptables/nftables)
  ↓ TCP/IP stack
  ↓ Socket (приложение)
```

Ключевые компоненты в dmesg:
*   **NIC driver** — `e1000e`, `ixgbe`, `mlx5`, `vmxnet3`, `virtio_net`
*   **NAPI** — механизм снижения нагрузки IRQ через поллинг
*   **Softirq** — программные прерывания для обработки пакетов (NET_RX, NET_TX)
*   **Conntrack** — таблица состояния соединений netfilter
*   **TCP stack** — SYN cookies, backlog, retransmits

---

## Практические сценарии

### Поиск сетевых событий в dmesg

```bash
# Все сетевые события
dmesg -T | grep -iE "net|eth|link|carrier|nic|network|tcp|udp|syn|conntrack|softirq|irq.*eth"

# Только ошибки
dmesg -T | grep -iE "net.*error|link.*down|carrier.*lost|rx_missed|tx_timeout"

# Проблемы с IRQ и softirq
dmesg -T | grep -iE "irq.*eth|softirq|ksoftirqd|NET_RX|NET_TX|budget"
```

### Переполнение таблицы conntrack

Сообщение: `nf_conntrack: table full, dropping packet`

```bash
# 1. Подтвердить наличие проблемы
dmesg -T | grep -i "conntrack.*table full"

# 2. Проверить текущее использование
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max

# 3. Мониторинг в реальном времени
watch -d "cat /proc/sys/net/netfilter/nf_conntrack_count /proc/sys/net/netfilter/nf_conntrack_max | paste - -"

# 4. Решение: увеличить лимит
sudo sysctl -w net.netfilter.nf_conntrack_max=1048576
sudo sysctl -w net.netfilter.nf_conntrack_buckets=262144

# 5. Постоянное применение
cat <<EOF | sudo tee /etc/sysctl.d/90-conntrack.conf
net.netfilter.nf_conntrack_max=1048576
net.netfilter.nf_conntrack_buckets=262144
net.netfilter.nf_conntrack_tcp_timeout_established=3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
EOF
```

### SYN Flood и SYN Cookies

Сообщение: `TCP: Possible SYN flooding on port 80. Sending cookies.`

```bash
# 1. Подтвердить
dmesg -T | grep -i "syn.*flood\|syn.*cookie"

# 2. Проверить состояние TCP-соединений
ss -s
# → TCP:   12345 (estab 8000, closed 1000, orphaned 200, timewait 300)

# 3. Проверить SYN-очередь
nstat -az | grep -i "syn"
# → TcpExtSYNsToListenBacklog
# → TcpExtListenOverflows
# → TcpExtListenDrops

# 4. Решение
sudo sysctl -w net.ipv4.tcp_syncookies=1
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=65535
sudo sysctl -w net.ipv4.tcp_synack_retries=2
```

### Проблемы с NIC и link

```bash
# Link flapping (повторяющиеся Up/Down)
dmesg -T | grep -iE "link.*(up|down)|carrier.*(lost|found)"

# Пример вывода:
# → [Sep 10 14:23:01] ixgbe 0000:03:00.0: NIC Link is Down
# → [Sep 10 14:23:04] ixgbe 0000:03:00.0: NIC Link is Up 10 Gbps

# Ошибки RX/TX
dmesg -T | grep -iE "rx_missed|tx_timeout|rx_crc|rx_missed_errors"

# Ключевые паттерны:
# → rx_missed_errors: нехватка ring buffer NIC (увеличьте: ethtool -G eth0 rx 4096)
# → tx_timeout: таймаут передачи (проверьте link, кабель, switch port)
```

### Ошибки драйверов NIC

```bash
# Поиск ошибок драйверов
dmesg -T | grep -iE "e1000|ixgbe|mlx5|i40e|bnxt|vmxnet3|virtio_net|igb|tg3"

# Типичные паттерны:
# → ixgbe: Hardware Error: forcing link reset
# → mlx5_core: FW error, initiating reset
# → vmxnet3 0000:0b:00.0: eth0: ring ring0 is full (dropped X packets)
```

### Проблемы с IRQ и softirq

```bash
# Проверка распределения IRQ по ядрам
cat /proc/interrupts | grep -i "eth\|eth0\|ens\|enp"

# Проверка softirq
cat /proc/softirqs | grep -i "NET_RX\|NET_TX"

# Если NET_RX неравномерно распределён:
# 1. Проверить irqbalance
systemctl status irqbalance

# 2. Отключить irqbalance и настроить вручную (для production)
sudo systemctl stop irqbalance

# 3. Привязать IRQ NIC к NUMA-локальному ядру
# Определить NUMA node NIC
cat /sys/class/net/eth0/device/numa_node

# Найти IRQ NIC
grep "eth0" /proc/interrupts | awk '{print $1}' | tr -d ':'

# Установить affinity
echo "1" | sudo tee /proc/irq/<IRQ>/smp_affinity  # CPU 1
```

### TCP-события в dmesg

```bash
# TCP drops и rejects
dmesg -T | grep -iE "tcp.*drop|tcp.*reject|tcp.*abort|reset.*connection"

# TCP retransmit (если включён netconsole или journald)
dmesg -T | grep -iE "retransmit|timeout|retry"

# Связь с ss
ss -ti | head -20
# → retrans 0/0 → норма
# → retrans 3/10 → проблема, проверьте dmesg на packet loss
```

### Диагностика проблемы «сервер не отвечает на ping»

```bash
# 1. Проверить link state
dmesg -T | grep -iE "link.*(up|down)|carrier"
ip link show

# 2. Проверить ARP
dmesg -T | grep -i "arp"
cat /proc/net/arp

# 3. Проверить netfilter (блокировка ICMP)
dmesg -T | grep -iE "DROP.*icmp|REJECT.*icmp"

# 4. Проверить conntrack (если ICMP tracked)
conntrack -L -p icmp 2>/dev/null | head

# 5. Проверить network namespace (для контейнеров)
ls /var/run/docker/netns/
nsenter --net=/var/run/docker/netns/<id> -- ip link show
```

---

## Дополнительная информация

### Связанные темы

*   [**NAPI-оптимизация**](../../../Networking/Concepts/napi_optimization.md) — архитектура NAPI, softirq budget, ksoftirqd.
*   [**RSS/RPS/RFS**](../../../Networking/Concepts/rss_rps_rfs.md) — распределение сетевой нагрузки по ядрам.
*   [**Conntrack production tuning**](../../../Networking/Concepts/conntrack_production_tuning.md) — тюнинг таблицы соединений.
*   [**Network packet loss**](../../../Networking/network_stack_packet_loss.md) — полный путь потери пакетов.
*   [**Обзор dmesg**](./index.md) — общая архитектура kmsg.
*   [**Поиск и устранение неисправностей**](./troubleshooting.md) — Call Trace, Oops, Panic.
*   [**Эфиры dmesg**](./usage.md) — фильтрация и форматирование.
