# iSCSI: Оптимизация производительности

**Оптимизация iSCSI** — комплекс мер по настройке сетевого стека, параметров протокола и дисковой подсистемы для минимизации задержек (Latency) и максимизации пропускной способности (Throughput). Основная задача — снизить накладные расходы на инкапсуляцию SCSI в TCP/IP и уменьшить нагрузку на CPU.

## Определения и сокращения

| Термин | Описание |
| :--- | :--- |
| **MTU (Maximum Transmission Unit)** | Максимальный размер полезной нагрузки кадра канального уровня (L2). Стандарт Ethernet — 1500 байт. Для iSCSI рекомендуется 9000 (Jumbo Frames). |
| **BDP (Bandwidth-Delay Product)** | Объем данных "в пути", необходимый для заполнения канала. Определяет минимальный размер буферов TCP. Формула: `Bandwidth (bps) * RTT (sec)`. |
| **PFC (Priority-based Flow Control)** | Механизм управления потоком (802.1Qbb), предотвращающий потери пакетов в определённых классах трафика. Критичен для RoCE и iSCSI в совмещённых сетях. |
| **IRQ Affinity** | Привязка обработки прерываний сетевой карты к конкретным ядрам CPU через `/proc/irq/<IRQ>/smp_affinity`. Снижает переключения контекста и улучшает кэширование. |
| **NUMA (Non-Uniform Memory Access)** | Архитектура памяти, где задержка доступа зависит от физического расположения DIMM-слотов относительно CPU-сокета. В dual-socket системах разница может достигать 30-50%. |
| **Offloading** | Аппаратная разгрузка CPU (расчет контрольных сумм TCP/UDP, сегментация, сборка пакетов) на сетевой адаптер (NIC). Типы: TSO, GRO, LRO, UFO, GSO. |
| **RSS (Receive Side Scaling)** | Механизм распределения входящих пакетов по очередям NIC на несколько ядер CPU. Позволяет обрабатывать высокий Throughput параллельно. |
| **RPS (Receive Packet Steering)** | Программная реализация RSS на уровне ядра. Используется, если NIC не поддерживает аппаратный RSS или его очередей недостаточно. |
| **Interrupt Coalescing** | Объединение нескольких прерываний NIC в одно. Снижает количество прерываний (interrupts per second), но увеличивает latency. Требует баланса. |
| **TCP Congestion Control** | Алгоритм управления перегрузкой. Типичные: **CUBIC** (по умолчанию в Linux, стабильный) и **BBR** (основан на модели, лучше для lossy/long-RTT сетей). |
| **SCSI Queue Depth** | Максимальное количество одновременных SCSI-команд (CDB) в одной iSCSI-сессии. Определяется параметрами `node.session.cmds_max` и `node.session.queue_depth`. |
| **Header Digest** | Проверка целостности заголовка iSCSI PDU (CRC32c). Защищает от повреждения заголовков. Опция: `CRC32c` или `None`. |
| **Data Digest** | Проверка целостности данных (payload) iSCSI PDU (CRC32c). Дополнительная защита от битовых сбоев. Влияет на производительность из-за вычисления CRC. |
| **Zero-Copy** | Передача данных из памяти приложения в сетевой стек без промежуточного копирования. Реализуется через `sendfile()`, `splice()`, RDMA. Снижает нагрузку на CPU. |

## Основные концепции

### Влияние сети на блочный трафик

iSCSI транспортирует блочные SCSI-команды поверх TCP/IP. Каждый SCSI-команд оборачивается в iSCSI PDU, который инкапсулируется в TCP-сегмент, затем в IP-пакет и Ethernet-кадр. Это создаёт многоуровневый overhead:

```text
┌─────────────────────────────────────────────────────────────────┐
│ Ethernet (L2)   │  14 байт + 4 (FCS) + 4 (802.1Q VLAN)       │
├─────────────────┤                                              │
│ IP (L3)         │  20 байт                                    │
├─────────────────┤                                              │
│ TCP (L4)        │  20-60 байт (обязательный + опции)          │
├─────────────────┤                                              │
│ iSCSI           │  48 байт (Basic Header) + опции             │
├─────────────────┤                                              │
│ SCSI CDB        │  6-32 байт (команда)                        │
├─────────────────┤                                              │
│ Данные          │  0 - MaxRecvDataSegmentLength (до 1МБ)      │
└─────────────────┴──────────────────────────────────────────────┘
```

**Суммарный overhead на один запрос:** 62-162 байта заголовков + данные. При маленьких блоках (4-8 КБ) overhead составляет 2-4%, при больших (256 КБ) — менее 0.1%.

iSCSI крайне чувствителен к потерям пакетов. Потеря одного TCP-сегмента приводит к срабатыванию механизмов Retransmission, что вызывает:
- **Всплеск задержек (Latency Spikes):** один потерянный пакет блокирует доставку всех последующих (Head-of-Line Blocking)
- **Потерю пропускной способности:** таймаут RTO (Retransmission Timeout) минимум 200 мс, при losses > 0.1% Throughput падает на 50-80%
- **Сталкивание в очередях:** при потере данных на целевом устройстве формируются ошибки SCSI Check Condition

Ключевые зоны оптимизации:
1. **Минимизация прерываний:** Jumbo Frames (уменьшение количества пакетов в 6 раз при MTU 9000) и Interrupt Coalescing
2. **Эффективность CPU:** Привязка IRQ к ядрам того же NUMA-узла, на котором находится NIC; аппаратные разгрузки (TSO, GRO)
3. **Тюнинг TCP:** Алгоритмы перегрузки (CUBIC/BBR) и размеры буферов, соответствующие BDP канала

### Bandwidth-Delay Product (BDP)

BDP определяет минимальный размер буферов TCP для полного использования пропускной способности канала. Если буфер меньше BDP, канал не будет загружен на 100%.

```text
BDP = Bandwidth (bps) × RTT (sec)
```

**Примеры расчета:**

| Скорость | RTT | BDP | Минимальный буфер TCP |
| :--- | :--- | :--- | :--- |
| 1 Гбит/с | 0.1 мс (localhost) | 12.5 КБ | 12.5 КБ |
| 10 Гбит/с | 0.1 мс (DC) | 125 КБ | 125 КБ |
| 10 Гбит/с | 0.5 мс (same-rack) | 625 КБ | 625 КБ |
| 10 Гбит/с | 1 мс (cross-rack) | 1.25 МБ | 1.25 МБ |
| 25 Гбит/с | 0.5 мс (DC) | 1.56 МБ | 1.56 МБ |
| 100 Гбит/с | 0.5 мс (DC) | 6.25 МБ | 6.25 МБ |

**Важно:** Буферы TCP настраиваются в два раза больше BDP (для bidirectional traffic) и должны учитывать `tcp_rmem` и `tcp_wmem` + лимиты `rmem_max`/`wmem_max`.

### TCP Congestion Control: CUBIC vs BBR

Алгоритм управления перегрузкой определяет, как TCP реагирует на потерю пакетов и перегрузку сети:

| Параметр | CUBIC | BBR |
| :--- | :--- | :--- |
| **Алгоритм** | Based on丢弃 loss (congestion window растет cubically) | Based on delay model (bandwidth + RTT) |
| **Реакция на потерю** | Агрессивное снижение CWND (÷2) | Мягкое снижение, ищет alternative path |
| **Лучшая среда** | Стабильные сети с низким loss | Сети с jitter, bufferbloat, long RTT |
| **CPU overhead** | Низкий | Сlightly higher (mesaurement phase) |
| **Совместимость** | По умолчанию в Linux 2.6.19+ | Доступен с Linux 4.9+ |

**Рекомендация для iSCSI:**
- **CUBIC** — по умолчанию, хорош для стабильных серверных сетей (data center, короткий RTT < 1 мс)
- **BBR** — рассматривать для сетей с потерями, bufferbloat или длинным RTT (> 5 мс)

```bash
# Проверка текущего алгоритма
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = cubic

# Список доступных алгоритмов
sysctl net.ipv4.tcp_available_congestion_control
# → net.ipv4.tcp_available_congestion_control = reno cubic

# Включение BBR
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr

# Постоянное сохранение
echo "net.ipv4.tcp_congestion_control = bbr" | sudo tee /etc/sysctl.d/99-iscsi-tcp-cc.conf
```

### Queue Depth: взаимосвязь уровней

Queue Depth определяет максимальное количество одновременных запросов. Существует несколько уровней Queue Depth, которые должны согласовываться:

```text
┌─────────────────────────────────────────────────────────────────┐
│ Уровень                │ Параметр                │ Значение     │
├────────────────────────┤─────────────────────────┤──────────────┤
│ iSCSI session (initiator) │ node.session.cmds_max  │ 32-256      │
│ iSCSI queue (initiator) │ node.session.queue_depth │ 32-256      │
│ SCSI mid-level (ядро)  │ /sys/block/sdX/queue/nr_requests │ 128-1024 │
│ Device (диск)          │ /sys/block/sdX/queue/queue_depth │ 32-256    │
└────────────────────────┴─────────────────────────┴──────────────┘
```

**Правило:** `node.session.queue_depth` ≤ `nr_requests` ≤ device queue depth. Если инициатор отправит больше команд, чем device может обработать, возникнут ошибки `TASK SET FULL`.

**Влияние Queue Depth на производительность:**
- **Маленький QD (1-4):** Низкая latency, но низкий Throughput (mal загружен диск)
- **Средний QD (8-32):** Баланс latency и throughput
- **Большой QD (64-256):** Максимальный Throughput, но latency растёт (очередь)

### Data Integrity в iSCSI

iSCSI предоставляет механизмы проверки целостности данных:

| Механизм | Уровень | Защита | Overhead |
| :--- | :--- | :--- | :--- |
| **TCP Checksum** | TCP (L4) | Заголовок + payload | Минимальный (аппаратный) |
| **Header Digest** | iSCSI | Заголовок iSCSI PDU (CRC32c) | 8 байт на PDU, +1-2% CPU |
| **Data Digest** | iSCSI | Payload iSCSI PDU (CRC32c) | 8 байт на PDU, +3-5% CPU |
| **Guard Tag (T10-PI)** | SCSI | Data + Protection Information | 8 байт на 512B сектор, аппаратный |

**Рекомендация:** Включайте `HeaderDigest = CRC32c` для защиты от повреждения заголовков (особенно на длине > 10 м). `DataDigest` рекомендуется для критичных данных, но снижает производительность на 3-5%.

## Практические сценарии

### 1. Сетевое ускорение (Offloading)

Используйте `ethtool` для управления аппаратными функциями разгрузки.

```bash
# Проверка текущих настроек
sudo ethtool -k eth1
# → tcp-segmentation-offload: on
# → generic-receive-offload: on

# Оптимальная конфигурация для iSCSI
sudo ethtool -K eth1 tso on gro on lro off
```

| Функция | Описание | Рекомендация |
| :--- | :--- | :--- |
| **TSO (TCP Segmentation Offload)** | NIC разбивает большой TCP-сегмент на MTU-пакеты. Снижает нагрузку CPU на сегментацию. | **on** — всегда для iSCSI |
| **GRO (Generic Receive Offload)** | Ядро агрегирует входящие пакеты перед обработкой. Снижает количество прерываний. | **on** — всегда для iSCSI |
| **LRO (Large Receive Offload)** | Аппаратная агрегация на NIC. Конфликтует с iSCSI: может агрегировать PDU разных сессий, вызывая CRC-ошибки. | **off** — обязательно для iSCSI |
| **UFO (UDP Fragmentation Offload)** | Фрагментация UDP-датаграмм на NIC. Не используется iSCSI. | **off** |
| **GSO (Generic Segmentation Offload)** | Программная сегментация, если TSO недоступен. | **on** как fallback |

*Примечание*: **LRO** рекомендуется отключать, так как он может конфликтовать с iSCSI-пакетами, вызывая ошибки CRC на уровне инициатора.

```bash
# Проверка поддержки аппаратного offloading
sudo ethtool -k eth1 | grep -E "segmentation-offload|receive-offload"
# → tcp-segmentation-offload: on
# → generic-receive-offload: on
# → large-receive-offload: on   ← это LRO, должен быть off

# Проверка NIC Multi-Queue (для RSS)
sudo ethtool -l eth1
# → Combined:      8
# → Other:         0
# → RX:            0
# → TX:            0
```

### 2. Настройка Jumbo Frames (MTU 9000)

Снижает нагрузку на CPU на 20-30% за счет уменьшения количества обрабатываемых заголовков. Увеличивает полезную нагрузку кадра с 1500 до 9000 байт (в 6 раз).

```bash
# Установка MTU
sudo ip link set dev eth1 mtu 9000

# Сохранение при перезагрузке (systemd-networkd)
sudo mkdir -p /etc/systemd/network/
cat << 'EOF' | sudo tee /etc/systemd/network/70-iscsi-jumbo.network
[Match]
Name=eth1

[Link]
MTUBytes=9000
EOF

# Сохранение при перезагрузке (NetworkManager)
sudo nmcli connection modify eth1 802-3-ethernet.mtu 9000
```

**Верификация:**

```bash
# Проверка MTU
ip link show eth1
# → mtu 9000

# Тест прохождения Jumbo Frame (без фрагментации)
ping -M do -s 8972 <TARGET_IP>
# → 8980 bytes from <TARGET_IP>: icmp_seq=1 ttl=64 time=0.123 ms

# Если не проходит — проблема на одном из звеньев:
# 1. Физический интерфейс NIC (проверить ethtool -i)
# 2. Коммутатор (проверить MTU на порту)
# 3. Target-сервер (проверить MTU на интерфейсе)
```

**Требования:**
- MTU должен быть одинаков на **всех** участниках пути: Initiator NIC → Коммутатор → Target NIC
- Если хотя бы одно звено не поддерживает Jumbo Frames, кадры отбрасываются без ICMP-ответа (Black Hole)
- На коммутаторе необходимо включить поддержку Jumbo Frames на порту

### 3. Тюнинг сетевого стека (sysctl)

Для высокоскоростных SAN (10GbE+) необходимо увеличить лимиты буферов. Расчет BDP: `Bandwidth * RTT`. Буферы должны быть ≥ 2× BDP для bidirectional traffic.

```bash
# /etc/sysctl.d/99-iscsi-performance.conf

# === TCP Buffers ===
# Максимальные размеры буферов (128MB для 40/100G)
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728

# Автотюнинг TCP: min (4KB), default (автовыбор), max (128MB)
net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728

# Страницы памяти для TCP (для больших буферов)
net.ipv4.tcp_moderate_rcvbuf = 1
net.ipv4.tcp_adv_win_scale = 1

# === Конгестия и управление потоком ===
# Алгоритм перегрузки (cubic для стабильных сетей, bbr для lossy/long-RTT)
net.ipv4.tcp_congestion_control = cubic

# Дисциплина очереди qdisc (fq для fairness, fq_codel для bufferbloat)
net.core.default_qdisc = fq

# === Таймауты и keepalive ===
# Отключение Delayed ACK (ускоряет подтверждение мелких блоков)
net.ipv4.tcp_low_latency = 1

# Keepalive для обнаружения мертвых пиров (15 сек интервал, 5 попыток)
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 15
net.ipv4.tcp_keepalive_probes = 5

# === Backlog и соединения ===
# Увеличение=backlog для входящих соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# === Защита от SYN flood (важно для iSCSI target) ===
net.ipv4.tcp_syncookies = 1

# === Memory pressure ===
# Минимальное количество памяти для TCP (в страницах)
net.ipv4.tcp_mem = 131072 131072 262144

# Применение
sudo sysctl --system
```

**Проверка текущих значений:**

```bash
# Все параметры TCP
sysctl -a | grep -E "tcp_rmem|tcp_wmem|rmem_max|wmem_max|congestion|qdisc"

# Текущий алгоритм перегрузки
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = cubic

# Текущий qdisc
tc qdisc show dev eth1
# → qdisc fq 0: root refcnt 2 limit 10000p
```

### 4. Тюнинг сессии iSCSI (`iscsid.conf`)

Параметры, определяющие размер iSCSI PDU и глубину очередей.

```ini
# /etc/iscsi/iscsid.conf (профиль производительности)

# === Размер PDU ===
# Максимальный размер сегмента данных (должен быть кратен MTU и размеру страницы 4KB)
# Оптимально 256KB для современных систем (262144 = 256 × 1024)
node.session.iscsi.MaxRecvDataSegmentLength = 262144
node.session.iscsi.MaxXmitDataSegmentLength = 262144

# Максимальный размер данных в одном SCSI ответе (для чтения)
# Должен быть ≥ MaxRecvDataSegmentLength
node.session.iscsi.MaxBurstLength = 16776192

# Первый запрос без R2T (для записи)
# Ускоряет начальную фазу записи (снижает latency для малых блоков)
node.session.iscsi.FirstBurstLength = 262144

# === Queue Depth ===
# Максимальное количество одновременных SCSI-команд (CDB) в сессии
# HDD: 32-64 (ограничены механикой)
# SSD: 128-256
# NVMe: 256-1024
node.session.cmds_max = 128
node.session.queue_depth = 128

# === TCP ===
# Отключение Nagle (минимизация латентности)
# Для iSCSI отправка малых PDU без задержки критична
node.conn[0].tcp.nodelay = 1

# Keepalive (обнаружение мертвых соединений)
node.conn[0].timeo.noop_out_interval = 15
node.conn[0].timeo.noop_out_timeout = 15

# === Дайджесты ===
# Проверка целостности заголовков (рекомендуется)
node.conn[0].iscsi.HeaderDigest = CRC32c

# Проверка целостности данных (опционально, снижает throughput на 3-5%)
node.conn[0].iscsi.DataDigest = None
```

**Применение изменений:**

```bash
# После изменения iscsid.conf необходимо перезапустить iscsid
sudo systemctl restart iscsid

# Переподключение к target для применения новых параметров
sudo iscsiadm -m node -T <IQN> -p <IP> --logout
sudo iscsiadm -m node -T <IQN> -p <IP> --login

# Проверка применённых параметров
sudo iscsiadm -m session -P 3 | grep -E "MaxRecv|MaxXmit|queue_depth|HeaderDigest"
```

### 5. Управление прерываниями и NUMA

Для минимизации задержек памяти (Memory Latency) привяжите прерывания к "родному" CPU-сокету.

**Шаг 1: Определение NUMA-узла сетевой карты**

```bash
cat /sys/class/net/eth1/device/numa_node
# → 0 (означает первый сокет)
```

**Шаг 2: Определение списка ядер этого узла**

```bash
lscpu | grep "NUMA node0"
# → NUMA node0 CPU(s): 0-15,32-47
```

**Шаг 3: Найти IRQ номер сетевой карты**

```bash
grep eth1 /proc/interrupts | awk '{print $1}' | tr -d ':'
# → 32

# Или более детально:
cat /proc/interrupts | grep eth1
# → 32: ... PCI-MSI-edge ... eth1-TxRx-0
# → 33: ... PCI-MSI-edge ... eth1-TxRx-1
# → ... (для Multi-queue NIC каждая queue — отдельный IRQ)
```

**Шаг 4: Установить маску привязки**

```bash
# Привязка к одному ядру (ядро 0 — hex маска)
echo 1 | sudo tee /proc/irq/32/smp_affinity

# Или через список ядер (ядро 0)
echo 0 | sudo tee /proc/irq/32/smp_affinity_list

# Для Multi-queue NIC: привязать каждую queue к отдельному ядру
echo 1 | sudo tee /proc/irq/32/smp_affinity  # Queue 0 → ядро 0
echo 2 | sudo tee /proc/irq/33/smp_affinity  # Queue 1 → ядро 1
echo 4 | sudo tee /proc/irq/34/smp_affinity  # Queue 2 → ядро 2
echo 8 | sudo tee /proc/irq/35/smp_affinity  # Queue 3 → ядро 3
```

**Шаг 5: Проверка**

```bash
cat /proc/irq/32/smp_affinity
# → 00000001

# Проверка, что прерывания обрабатываются на нужном ядре
mpstat -P ALL 1 3 | head -20
```

**Автоматизация (systemd unit):**

```bash
cat << 'EOF' | sudo tee /etc/systemd/system/iscsi-irq-affinity.service
[Unit]
Description=iSCSI IRQ Affinity for eth1
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'echo 1 > /proc/irq/$(grep eth1 /proc/interrupts | head -1 | awk "{print \$1}" | tr -d ":")/smp_affinity'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable iscsi-irq-affinity.service
```

**Проверка эффективности:**

```bash
# До привязки IRQ (высокий context switch)
vmstat 1 5 | awk '{print "cs:", $16}'

# После привязки IRQ (context switch снижаются)
vmstat 1 5 | awk '{print "cs:", $16}'
```

### NUMA Topology и влияние на производительность

В системах с несколькими CPU-сокетами (dual-socket) задержка доступа к памяти зависит от расположения процессора относительно DIMM-слотов:

```bash
# Просмотр NUMA-топологии
numactl --hardware
# → available: 2 nodes (0-1)
# node 0 cpus: 0-15 32-47
# node 0 size: 32768 MB
# node 1 cpus: 16-31 48-63
# node 1 size: 32768 MB

# Привязка процесса iscsid к NUMA-узлу сетевой карты
numactl --cpunodebind=0 --membind=0 /usr/sbin/iscsid
```

**Эффект NUMA:** Если сетевая карта подключена к PCI-E слоту на NUMA-узле 0, а процесс обработки iSCSI выполняется на ядрах NUMA-узла 1, задержка доступа к кэшу увеличивается на 30-50%.

**Проверка текущей привязки:**

```bash
# Проверка NUMA-узла процесса iscsid
pid=$(pgrep iscsid)
numactl --show --pid=$pid
# → policy: default
# → preferred node: current
# → membind: 0

# Проверка распределения памяти
numastat -p $pid
```

### 6. iSER (iSCSI Extensions for RDMA)

iSER исключает TCP-стек и копирование данных в памяти (Zero-Copy), используя RDMA (Remote Direct Memory Access). Данные передаются напрямую из памяти инициатора в память target без участия CPU.

**Преимущества:**
- Снижение Latency в 3-5 раз (отсутствие TCP/IP overhead)
- Практически нулевая загрузка CPU при передаче данных ( RDMA-адаптер выполняет передачу аппаратно)
- Zero-Copy: данные не копируются между буферами ядра и приложения

**Требования:**
- NIC с поддержкой RDMA (RoCE или iWARP)
- Загруженный модуль ядра `ib_iser`
- Target, поддерживающий iSER (LIO с RDMA-адаптером)

**Настройка инициатора:**

```bash
# Загрузка модуля
sudo modprobe ib_iser

# Проверка RDMA-устройств
ibv_devinfo
# → hca_id: mlx5_0
#     transport: InfiniBand
#     fw_ver: 20.31.1012

# Подключение через iSER
sudo iscsiadm -m discovery -t sendtargets -p <IP_TARGET>
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.conn[0].iscsi.HeaderDigest -v None
sudo iscsiadm -m node -T <IQN> -p <IP> --login

# Проверка транспорта
iscsiadm -m session -P 3 | grep "Transport"
# → iSCSI Session = 1
#     Transport = iSER (iSCSI Extensions for RDMA)
```

**sysctl для iSER:**

```bash
# /etc/sysctl.d/99-iser-performance.conf
# Для iSER/RoCE рекомендуется fq (Fair Queue)
net.core.default_qdisc = fq

# Увеличение RQ/RQO буферов для RDMA
net.core.rmem_max = 268435456
net.core.wmem_max = 268435456
```

### 7. Валидация MTU пути (End-to-End)

Несоответствие MTU на любом звене пути вызывает Black Hole — крупные пакеты отбрасываются без ICMP-ответа.

```bash
# 1. Проверка MTU на интерфейсе
ip link show eth1 | grep mtu
# → mtu 9000

# 2. Проверка MTU на target
ssh <TARGET_IP> "ip link show eth1 | grep mtu"
# → mtu 9000

# 3. Тест прохождения Jumbo Frame
ping -M do -s 8972 <TARGET_IP>
# → successful

# 4. Проверка MTU на коммутаторе (Cisco IOS)
# show interface eth1/1 | include MTU
# → MTU is 9000 bytes

# 5. Тест с увеличением размера пакета
for size in 1472 4000 8000 8972; do
    result=$(ping -M do -c 1 -s $size <TARGET_IP> 2>&1 | tail -1)
    echo "Size $size: $result"
done

# 6. Проверка.fragmentation на target
ssh <TARGET_IP> "ping -M do -c 1 -s 8972 <INITIATOR_IP>"
```

### 8. Выбор алгоритма TCP Congestion Control

```bash
# Проверка текущего алгоритма
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = cubic

# Список доступных
sysctl net.ipv4.tcp_available_congestion_control
# → net.ipv4.tcp_available_congestion_control = reno cubic bbr

# === Включение BBR ===
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr

# Постоянное сохранение
cat << 'EOF' | sudo tee /etc/sysctl.d/99-iscsi-tcp-cc.conf
net.ipv4.tcp_congestion_control = bbr
EOF

# Проверка через tc
tc -s qdisc show dev eth1
# → qdisc fq 0: root ... Sent 1234567 bytes 8765 pkt
```

**Когда использовать BBR:**
- Сеть с потерями (loss > 0.1%)
- Long RTT (> 5 мс)
- Bufferbloat (высокая latency под нагрузкой)
- Сети с переменным jitter

**Когда CUBIC предпочтительнее:**
- Стабильные DC-сети с RTT < 1 мс
- Низкие потери (< 0.01%)
- Необходимость максимальной совместимости

### 9. Тюнинг файловой системы на iSCSI-устройствах

Файловая система на iSCSI-устройстве требует специальной настройки для производительности и целостности.

**ext4:**

```bash
# Оптимальные опции монтирования
sudo mount -o noatime,nodiratime,discard,barrier=0 /dev/sda1 /mnt/iscsi

# Для SSD/NVMe: отключение barriers (если target гарантирует порядок записи)
# Для HDD: barrier=1 (по умолчанию, безопасно)

# Проверка опций
mount | grep sda
# → /dev/sda1 on /mnt/iscsi type ext4 (rw,noatime,nodiratime,discard,barrier=0)

# Параметры tune2fs
sudo tune2fs -m 1 /dev/sda1  # Резерв 1% (по умолчанию 5%)
sudo tune2fs -o journal_data_writeback /dev/sda1  # Режим журнала
```

**XFS (рекомендуется для iSCSI):**

```bash
# Оптимальные опции
sudo mount -o noatime,nodiratime,logbufs=8,logbsize=256k /dev/sda1 /mnt/iscsi

# Проверка опций
mount | grep sda
# → /dev/sda1 on /mnt/iscsi type xfs (rw,noatime,nodiratime,logbufs=8,logbsize=256k)

# Увеличение размера журнала (для high-throughput workload)
sudo mkfs.xfs -f -l logbufs=8,logbsize=256k /dev/sda1
```

**Постоянное сохранение (/etc/fstab):**

```bash
# /etc/fstab
/dev/sda1  /mnt/iscsi  ext4  defaults,noatime,nodiratime,discard,_netdev  0  2
# _netdev — ждать монтирования сети перед mount (критично для iSCSI)
```

### 10. Write Caching и Barriers

Кэширование записи критично для производительности, но влияет на целостность данных.

**Типы кэширования:**

| Тип | Описание | Throughput | Безопасность |
| :--- | :--- | :--- | :--- |
| **Write-Back (кэш target)** | Записи буферизуются в RAM target, подтверждаются до записи на диск | Максимальный | Низкая (потеря питания) |
| **Write-Through** | Записи сразу на диск + в кэш | Средний | Высокая |
| **Direct I/O** | Без кэширования, прямая запись на диск | Низкий | Максимальная |

**Настройка write cache на target (LIO):**

```bash
# Просмотр текущего режима
sudo targetcli /backstores/block/disk0 get attribute
# → block_status=online
# → emulated=0

# Включение write-back (если target поддерживает)
sudo targetcli /backstores/block/disk0 set attribute emulated=1

# Отключение write-back (безопасный режим)
sudo targetcli /backstores/block/disk0 set attribute emulated=0
```

**Настройка barriers на инициаторе:**

```bash
# Для ext4: barriers защищают journal от повреждения при аварийном отключении
# barrier=1 (по умолчанию) — безопасно, barrier=0 — быстрее
sudo mount -o barrier=1 /dev/sda1 /mnt/iscsi

# Для XFS: barriers включены по умолчанию, отключаются через noumbbarrier
sudo mount -o noumbbarrier /dev/sda1 /mnt/iscsi
```

**Проверка кэша на устройстве:**

```bash
# Проверка write cache на target
hdparm -W /dev/sda
# → write-caching = 1 (включено)

# Проверка через sysfs
cat /sys/block/sda/queue/write_cache
# → write back

# Включение write cache
echo write back | sudo tee /sys/block/sda/queue/write_cache
```

### 11. Бенчмаркинг iSCSI (fio, dd)

**fio — рекомендуемый инструмент:**

```bash
# Sequential Read (проверка Throughput)
fio --name=seqread --ioengine=libaio --direct=1 --bs=128k --iodepth=32 \
    --rw=read --size=10G --runtime=60 --filename=/mnt/iscsi/testfile

# Sequential Write
fio --name=seqwrite --ioengine=libaio --direct=1 --bs=128k --iodepth=32 \
    --rw=write --size=10G --runtime=60 --filename=/mnt/iscsi/testfile

# Random Read (проверка IOPS и Latency)
fio --name=randread --ioengine=libaio --direct=1 --bs=4k --iodepth=64 \
    --rw=randread --size=10G --runtime=60 --filename=/mnt/iscsi/testfile

# Random Write
fio --name=randwrite --ioengine=libaio --direct=1 --bs=4k --iodepth=64 \
    --rw=randwrite --size=10G --runtime=60 --filename=/mnt/iscsi/testfile

# Mixed Random R/W (70% read / 30% write — typical workload)
fio --name=mixed --ioengine=libaio --direct=1 --bs=4k --iodepth=64 \
    --rw=randrw --rwmixread=70 --size=10G --runtime=60 \
    --filename=/mnt/iscsi/testfile
```

**dd — быстрый тест Throughput:**

```bash
# Sequential Write (128K blocks, direct I/O)
dd if=/dev/zero of=/mnt/iscsi/testfile bs=128k count=10000 oflag=direct
# → 1.31 GB in 3.2 sec → 409 MB/s

# Sequential Read
dd if=/mnt/iscsi/testfile of=/dev/null bs=128k iflag=direct
# → 1.31 GB in 2.8 sec → 467 MB/s

# Без direct I/O (через page cache — не показательно для iSCSI)
dd if=/dev/zero of=/mnt/iscsi/testfile bs=128k count=10000
```

**Метрики для мониторинга во время тестирования:**

```bash
# В отдельном терминале
iostat -xy 1       # Дисковая подсистема
nstat -az 1        # TCP-статистика (retransmits)
sar -n DEV 1       # Сетевая активность
```

### 12. Multi-queue NICs и RSS

Receive Side Scaling (RSS) распределяет входящий трафик по нескольким очередям NIC, позволяя обрабатывать high Throughput параллельно на нескольких ядрах CPU.

**Проверка Multi-Queue:**

```bash
# Количество очередей NIC
sudo ethtool -l eth1
# → Combined:      8
# → Other:         0
# → RX:            0
# → TX:            0

# Установка количества очередей
sudo ethtool -L eth1 combined 8
```

**Настройка RPS (Receive Packet Steering) — программный RSS:**

```bash
# Включение RPS для eth1 (для NIC без аппаратного RSS или для увеличения масштаба)
echo "ff" | sudo tee /sys/class/net/eth1/queues/rx-0/rps_cpus
# → ff = 8 ядер (битовая маска)

# Для Multi-queue NIC: каждая queue обрабатывается своим ядром
echo "01" | sudo tee /sys/class/net/eth1/queues/rx-0/rps_cpus
echo "02" | sudo tee /sys/class/net/eth1/queues/rx-1/rps_cpus
echo "04" | sudo tee /sys/class/net/eth1/queues/rx-2/rps_cpus
echo "08" | sudo tee /sys/class/net/eth1/queues/rx-3/rps_cpus
```

**Настройка XPS (Transmit Packet Steering):**

```bash
# Привязка TX-очереди к ядрам
echo "01" | sudo tee /sys/class/net/eth1/queues/tx-0/xps_cpus
echo "02" | sudo tee /sys/class/net/eth1/queues/tx-1/xps_cpus
echo "04" | sudo tee /sys/class/net/eth1/queues/tx-2/xps_cpus
echo "08" | sudo tee /sys/class/net/eth1/queues/tx-3/xps_cpus
```

**Проверка распределения:**

```bash
# Проверка RSS-хэша
ethtool -x eth1
# → RX flow hash indirection table for eth1 with 8 RX ring(s):
# → 0:  0  1  2  3  4  5  6  7
# → ...

# Проверка распределения пакетов по ядрам
mpstat -P ALL 1 3
```

### 13. Interrupt Coalescing

Объединение прерываний снижает количество interrupt/s, но увеличивает latency.

```bash
# Проверка текущих настроек
sudo ethtool -c eth1
# → rx-usecs: 8
# → tx-usecs: 8
# → rx-frames: 0
# → tx-frames: 0

# Настройка для iSCSI (минимальная latency)
sudo ethtool -C eth1 rx-usecs 0 tx-usecs 0 rx-frames 1 tx-frames 1

# Или для снижения interrupt rate (если высокая нагрузка)
sudo ethtool -C eth1 rx-usecs 16 tx-usecs 16

# Проверка效果
cat /proc/interrupts | grep eth1
# → 32: ... PCI-MSI-edge ... eth1-TxRx-0
```

**Рекомендация:**
- **Минимальная latency** (interactive workloads): `rx-usecs=0, tx-usecs=0`
- **Сбалансированный режим** (iSCSI): `rx-usecs=4-8, tx-usecs=4-8`
- **Снижение interrupt/s** (high throughput): `rx-usecs=16-32, tx-usecs=16-32`

## Дополнительная информация

### Ожидаемые результаты оптимизации

| Параметр | До оптимизации | После оптимизации | Метод достижения |
| :--- | :--- | :--- | :--- |
| Latency (read) | 200-500 мкс | 50-100 мкс | Jumbo Frames + TCP buffers |
| Latency (write) | 150-400 мкс | 30-80 мкс | Write-Back + TSO + NUMA |
| Throughput (10GbE) | 400-600 MB/s | 900-1100 MB/s | Offloading + NUMA |
| Throughput (25GbE) | 1000-1500 MB/s | 2500-2800 MB/s | Jumbo Frames + RSS + BDP |
| Throughput (100GbE) | 4000-6000 MB/s | 9000-11000 MB/s | iSER + NUMA + 256 queue depth |
| CPU utilization (10GbE) | 40-60% | 5-15% | TSO/GRO + IRQ affinity |
| IOPS (4K random read, SSD) | 10,000-30,000 | 100,000-200,000 | Queue depth 64-128 + RSS |
| Retransmissions | 100-500/мин | 0-5/мин | Network stability + BDP |

**Важно:** Точные значения зависят от аппаратного обеспечения, нагрузки и конфигурации сети. Приведенные цифры актуальны для 10GbE с NVMe-массивами.

### Бенчмарки по типам хранилища

| Тип хранилища | Sequential Read | Sequential Write | Random Read IOPS | Random Write IOPS | Latency (read) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **HDD 7.2K SAS** | 150-200 MB/s | 150-200 MB/s | 100-200 | 100-200 | 2-5 мс |
| **HDD 10K SAS** | 200-250 MB/s | 180-220 MB/s | 200-400 | 200-400 | 1-3 мс |
| **HDD 15K SAS** | 250-300 MB/s | 220-280 MB/s | 300-500 | 300-500 | 0.5-2 мс |
| **SSD SATA** | 500-550 MB/s | 450-520 MB/s | 50,000-80,000 | 40,000-70,000 | 50-100 мкс |
| **SSD NVMe (Gen3)** | 2000-3500 MB/s | 1200-3000 MB/s | 200,000-500,000 | 150,000-400,000 | 10-30 мкс |
| **SSD NVMe (Gen4)** | 5000-7000 MB/s | 4000-5500 MB/s | 500,000-1,000,000 | 400,000-800,000 | 5-15 мкс |
| **NVMe-oF (RDMA)** | 6000-8000 MB/s | 5000-7000 MB/s | 600,000-1,200,000 | 500,000-1,000,000 | 5-20 мкс |

### Управление потоком (Flow Control)

1. **IEEE 802.3x (Global Flow Control)**: При переполнении буфера коммутатор посылает PAUSE-кадр, останавливая весь трафик на порту. Может вызвать "разлив" заторов (Congestion Spreading).
2. **IEEE 802.1Qbb (PFC — Priority-based Flow Control)**: Позволяет останавливать только трафик определенного приоритета (Class of Service). **Рекомендуется** для совмещенных сетей (LAN + iSCSI) и RoCE.

```bash
# Проверка PFC на интерфейсе
sudo ethtool -a eth1
# → preceiver-pause: on (если поддерживается)

# Включение PFC (требует поддержки коммутатором и DCBX)
# На коммутаторе (пример Cisco):
# mls qos
# mls qos map dscp-output-queue
# priority-queue out
# interface GigabitEthernet0/1
#   mls qos trust dscp
```

**PFC и iSCSI:**
- В совмещенных сетях (LAN + SAN) PFC предотвращает потерю iSCSI-пакетов при перегрузке LAN
- Для выделенных SAN-сетей PFC не обязателен (нет конкуренции за пропускную способность)
- Всегда согласовывайте PFC на коммутаторе и инициаторе — неправильная настройка ухудшает производительность

### Выбор планировщика I/O

Для сетевых блочных устройств на современных ядрах (6.x+):

| Планировщик | Описание | Рекомендация |
| :--- | :--- | :--- |
| **none** | Без переупорядочивания. Минимальный overhead. | NVMe-oF, SSD SAN, высокопроизводительные таргеты |
| **mq-deadline** | Приоритизация чтения перед записью. Минимальная latency. | HDD-массивы, общего назначения |
| **bfq** | Budget Fair Queueing. Баланс throughput между процессами. | Десктопы, multi-tenant среда |
| **kyber** | Latency-ориентированный. Автоматическое управление очередями. | Быстрые SSD (NVMe) |

```bash
# Просмотр текущего планировщика
cat /sys/block/mapper/mpatha/queue/scheduler
# → [none] mq-deadline kyber bfq

# Установка (временно)
echo none | sudo tee /sys/block/mapper/mpatha/queue/scheduler

# Постоянная настройка (udev rule)
cat << 'EOF' | sudo tee /etc/udev/rules.d/60-iscsi-scheduler.rules
ACTION=="add|change", KERNEL=="mapper/mpath*", ATTR{queue/scheduler}="none"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Влияние IPsec на производительность

Если используется IPsec для шифрования iSCSI-трафика:

| Алгоритм | Throughput loss | Latency overhead | Рекомендация |
| :--- | :--- | :--- | :--- |
| AES-256-CBC + HMAC-SHA256 | 20-30% | +50-100 мкс | Использовать AES-NI |
| AES-256-GCM (AEAD) | 10-15% | +20-50 мкс | **Рекомендуется** |
| ChaCha20-Poly1305 | 15-20% | +30-70 мкс | Для систем без AES-NI |

Для минимизации влияния IPsec:
- Включите AES-NI в BIOS/EFI (`aes` модуль загружен: `lsmod | grep aes`)
- Используйте `aes-gcm` (AEAD) вместо `aes-cbc` + `hmac-sha256`
- Рассмотрите iSER (RDMA) как альтернативу: шифрование на уровне адаптера

### Диагностика производительности

```bash
# Быстрая оценка текущего состояния
echo "=== TCP Retransmissions ===" && nstat -az TcpExtTcpRetransSegs | tail -1
echo "=== Network Throughput ===" && sar -n DEV 1 1 | grep eth1
echo "=== Disk I/O ===" && iostat -xy 1 1 | grep -A 20 "Device"
echo "=== CPU on iSCSI IRQs ===" && mpstat -P ALL 1 1 | grep -E "CPU|eth1"
```

### См. также

- **[Настройка Multipath I/O](./iscsi_multipath.md)** — балансировка и агрегация путей.
- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — мониторинг ретрансмиссий и таймаутов.
- **[Безопасность iSCSI](./iscsi_security.md)** — влияние IPsec на производительность.
- **[Мониторинг iSCSI](./iscsi_monitoring.md)** — сбор метрик latency и throughput.
- **[Тюнинг TCP в Linux](../Concepts/tcp_tuning/tcp_tuning_overview.md)** — базовые принципы BDP.
