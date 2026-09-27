# Аппаратная диагностика сетевых адаптеров (NIC)

## Определения

**Аппаратная диагностика NIC** — процесс выявления и устранения проблем на физическом (L1) и канальном (L2) уровнях сетевой карты, включая ошибки передачи, переполнение буферов, несоответствие скорости/дуплекса, проблемы с оптикой (SFP/QSFP) и прерывания CPU.

**Использование (USE) метод** — методология мониторинга ресурсов: **U**tilization (загрузка), **S**aturation (переполнение), **E**rrors (ошибки). Применяется к NIC через `ethtool -S`, `ip -s link`, `dmesg`.

**ksoftirqd** — поток ядра, обрабатывающий SoftIRQ (мягкие прерывания) для обработки сетевых пакетов. Высокая загрузка `ksoftirqd` указывает на перегрузку сетевого стека или NIC.

## Основные концепции

### Точки потерь пакетов в стеке Linux

Пакет проходит несколько этапов от NIC до приложения, и на каждом возможны потери:

```
NIC Hardware (DMA → Ring Buffer)
    │  rx_missed_errors, rx_fifo_errors
    ▼
NAPI / SoftIRQ (irqbalance → ksoftirqd)
    │  netdev_budget, netdev_max_backlog
    ▼
Сетевой стек (ip → tcp/udp)
    │  socket buffer (rmem), conntrack
    ▼
Приложение (read/recv)
```

### Ключевые счётчики NIC (`ethtool -S`)

| Счётчик | Уровень | Описание | Типичная причина |
|:---|:---|:---|:---|
| `rx_missed_errors` | L1/L2 | Пакеты, отброшенные из-за переполнения Ring Buffer | Малый Ring Buffer, высокий NPS |
| `rx_fifo_errors` | L1/L2 | Пакеты, отброшенные из-за переполнения FIFO | NIC не справляется с потоком |
| `rx_crc_errors` | L1 | Ошибки контрольной суммы Ethernet | Плохой кабель, SFP, разъем |
| `rx_frame_errors` | L2 | Ошибки размера кадра (< 64 или > 1518 байт) | Коллизии, duplex mismatch |
| `rx_length_errors` | L2 | Неверная длина пакета | MTU mismatch, фрагментация |
| `tx_dropped` | L2 | Пакеты, отброшенные при передаче | Переполнение TX FIFO, TC qdisc |
| `tx_timeout` | L2 | Таймауты передачи ( watchdog ) | Проблемы с драйвером, IRQ |
| `fec_uncorrectable_errors` | L1 | Неисправимые FEC-ошибки | Оптика, кабель, SFP |
| `link_down` | L1 | Количество падений линка | Кабель, SFP, коммутатор |

### Мониторинг через `ip -s link`

```bash
# Базовая статистика интерфейса
ip -s link show eth0
# → RX:  bytes packets errors dropped overrun mcast
# → TX:  bytes packets errors dropped carrier collsns

# Ключевые поля:
# errors  — ошибки на уровне драйвера (аналог ethtool -S)
# dropped — пакеты отброшенные ядром (нехватка буферов)
# overrun — переполнение Ring Buffer NIC (hardware drop)
```

### Проверка состояния линка

```bash
# Скорость, дуплекс, ссылка
ethtool eth0
# → Speed: 10000Mb/s
# → Duplex: Full
# → Auto-negotiation: on
# → Link detected: yes

# Состояние операционного интерфейса
ip -br link show eth0
# → eth0  UP  aa:bb:cc:dd:ee:ff  MTU 1500  state UP

# Проверка через sysfs
cat /sys/class/net/eth0/speed       # текущая скорость (Мбит/с)
cat /sys/class/net/eth0/duplex      # full/half
cat /sys/class/net/eth0/operstate   # up/down/unknown
```

### Проблема Duplex Mismatch

Одно устройство работает в Full Duplex, другое в Half — классическая причина коллизий и CRC-ошибок.

| Признак | Счётчик |
|:---|:---|
| Высокие коллизии | `collisions` в `ip -s link` |
| CRC-ошибки | `rx_crc_errors` в `ethtool -S` |
| Низкая пропускная способность | `speed` = 100M вместо 1G |

**Решение:** всегда использовать Auto-Negotiation на обоих концах линка.

## Практические сценарии

### 1. Сбор всех аппаратных метрик NIC

```bash
#!/bin/bash
# nic_audit.sh — полный аудит NIC для SRE
IFACE=${1:-eth0}

echo "=== Link State ==="
ethtool $IFACE 2>/dev/null | grep -E "Speed|Duplex|Auto|Link|PHY"

echo -e "\n=== Offloading ==="
ethtool -k $IFACE 2>/dev/null | grep -E "tcp-segmentation|generic-receive|large-receive|generic-segmentation|rx-checksumming|tx-checksumming|scatter-gather"

echo -e "\n=== Ring Buffers ==="
ethtool -g $IFACE 2>/dev/null

echo -e "\n=== Interrupt Coalescing ==="
ethtool -c $IFACE 2>/dev/null

echo -e "\n=== Multi-Queue ==="
ethtool -l $IFACE 2>/dev/null

echo -e "\n=== Error Counters ==="
ethtool -S $IFACE 2>/dev/null | grep -iE "error|drop|miss|fifo|crc|collision|timeout|fec|reset"

echo -e "\n=== IP Statistics ==="
ip -s link show $IFACE

echo -e "\n=== dmesg NIC messages ==="
dmesg -T 2>/dev/null | grep -i "$IFACE" | tail -10
```

### 2. Диагностика переполнения Ring Buffer

**Симптом:** `rx_missed_errors` растёт при высокой нагрузке.

```bash
# Шаг 1: Проверка текущего размера
ethtool -g eth0
# → Pre-set:  RX: 256  TX: 256
# → Current:  RX: 256  TX: 256

# Шаг 2: Увеличение до максимума
sudo ethtool -G eth0 rx 4096 tx 4096

# Шаг 3: Проверка через 5 минут
watch -n 30 'ethtool -S eth0 | grep -E "rx_missed|rx_fifo"'
```

**Постоянная настройка (systemd-networkd):**
```ini
# /etc/systemd/network/10-eth0.link
[Link]
RxBufferSize=4096
TxBufferSize=4096
GenericReceiveOffload=true
TCPSegmentationOffload=true
```

### 3. Диагностика ошибок кабеля/SFP

**Симптом:** CRC-ошибки, link flapping, рост `rx_crc_errors`.

```bash
# Шаг 1: Проверка ошибок NIC
ethtool -S eth0 | grep -E "crc|frame|length|error"
# → rx_crc_errors: 1523
# → rx_frame_errors: 47

# Шаг 2: Проверка состояния линка (включая ошибки L1)
ethtool -S eth0 | grep -E "link|reset|timeout"
# → link_down: 15    ← 15 падений линка!
# → nic_reset: 3     ← аппаратные сбросы

# Шаг 3: Проверка FEC (для 25G/100G)
ethtool -S eth0 | grep fec
# → fec_uncorrectable_errors: 0    ← если > 0, проблема с оптикой
# → fec_correctable_errors: 1234   ← нормально (FEC исправляет)

# Шаг 4: Проверка SFP/DOM (если поддерживается)
ethtool -m eth0
# → Optical TX Power: -3.2 dBm
# → Optical RX Power: -8.5 dBm
# → Temperature: 45°C

# Шаг 5: Замена кабеля/SFP (исключить аппаратуру)
```

### 4. Диагностика высокой нагрузки ksoftirqd

**Симптом:** `top` показывает высокий %CPU у `ksoftirqd/N`.

```bash
# Шаг 1: Определение ядра с высокой нагрузкой
ps -eo pid,psr,comm | grep ksoftirqd
# → 12  3 ksoftirqd/3    ← ядро 3

# Шаг 2: Проверка распределения прерываний
cat /proc/interrupts | grep eth0
# → eth0: 12345678  ← все прерывания на одном ядре!

# Шаг 3: Включение multi-queue (если поддерживается)
sudo ethtool -L eth0 combined 8

# Шаг 4: Проверка RSS
ethtool -x eth0
# → RX flow hash indirection table for eth0 with 8 RSS groups

# Шаг 5: Настройка irqbalance
sudo systemctl enable --now irqbalance
```

### 5. Диагностика через dmesg

```bash
# Сообщения NIC-драйвера в kernel ring buffer
dmesg -T | grep -iE "eth0|link|nic|driver|firmware"
# → [Tue Sep 16 10:23:45 2025] ixgbe eth0: NIC Link is Up 10 Gbps
# → [Tue Sep 16 10:25:12 2025] ixgbe eth0: NIC Link is Down
# → [Tue Sep 16 10:25:13 2025] ixgbe eth0: NIC Link is Up 10 Gbps

# Ошибки памяти/буферов
dmesg -T | grep -iE "drop|miss|overflow|budget"
# → [Tue Sep 16 10:23:45 2025] NETDEV WATCHDOG: eth0 (ixgbe): transmit queue 0 timed out

# Ring buffer overflow
dmesg -T | grep -iE "ring buffer|rx_missed"
```

### 6. Отключение offloading для точной диагностики

При захвате пакетов через `tcpdump` или `tshark` аппаратная разгрузка искажает картину:

```bash
# Отключить TSO/GSO/GRO/LRO/VLAN offload
sudo ethtool -K eth0 tso off gso off gro off lro off rx-vlan-offload off tx-vlan-offload off

# ... диагностика ...

# Вернуть стандартные настройки
sudo ethtool -K eth0 tso on gso on gro on lro off rx-vlan-offload on tx-vlan-offload on
```

**Влияние offloading на захват:**

| Offloading | Эффект на tcpdump |
|:---|:---|
| TSO/GSO | Исходящие пакеты 60 КБ+ вместо 1500 Б |
| GRO/LRO | Входящие пакеты "склеиваются" |
| Checksum | `bad cksum` для исходящих (NIC считает позже) |
| VLAN | Теги скрыты на физическом интерфейсе |

### 7. Мониторинг NIC в реальном времени

```bash
# Автоматический мониторинг ошибок каждые 10 секунд
watch -n 10 'echo "=== $(date) ===" && \
  ethtool -S eth0 | grep -iE "error|drop|miss|crc" && \
  echo "---" && \
  ip -s link show eth0 | grep -A1 RX'

# Аллерт на рост ошибок (скрипт для cron)
#!/bin/bash
ERRORS=$(ethtool -S eth0 2>/dev/null | grep -c "error\|drop\|miss\|crc")
if [ "$ERRORS" -gt 10 ]; then
  echo "ALERT: NIC errors detected on eth0: $ERRORS counters non-zero" | \
    logger -t nic_monitor
fi
```

## Дополнительная информация

### Интеграция с Prometheus (node_exporter)

node_exporter собирает NIC-метрики через `/sys/class/net/`:

| Метрика | Описание | Пороговое значение |
|:---|:---|:---|
| `node_network_transmit_errs_total` | TX ошибки | > 0 (constant) |
| `node_network_receive_errs_total` | RX ошибки | > 0 (constant) |
| `node_network_transmit_drop_total` | TX дропы | Рост > baseline |
| `node_network_receive_drop_total` | RX дропы | Рост > baseline |
| `node_network_speed_bytes` | Скорость линка | != ожидаемой |
| `node_network_up` | Состояние линка | != 1 |

**Alert rules:**
```yaml
groups:
  - name: nic_alerts
    rules:
      - alert: NICErrorsDetected
        expr: rate(node_network_receive_errs_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "NIC errors on {{ $labels.device }}"

      - alert: NICLinkDown
        expr: node_network_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "NIC link down on {{ $labels.device }}"
```

### Связанные инструменты

- **[ethtool](../../Networking/Tools/ethtool.md)** — полная справка по ethtool (SSoT).
- **[Offloading](../../Networking/Concepts/offloading.md)** — описание TSO/GRO/LRO/GSO.
- **[RSS, RPS, RFS](../../Networking/Concepts/rss_rps_rfs.md)** — распределение нагрузки по ядрам.
- **[NAPI](../../Networking/Concepts/napi_optimization.md)** — оптимизация обработки пакетов.
- **[Packet Loss Diagnostics](../../Networking/network_stack_packet_loss.md)** — диагностика потерь на всех уровнях стека.
- **[dmesg network-stack](../../Diagnostics/Kernel/dmesg/network-stack.md)** — сетевые сообщения ядра.
