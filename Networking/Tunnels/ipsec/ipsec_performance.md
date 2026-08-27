# IPsec: производительность и оптимизация

> **Основной документ:** [IPsec (основной документ)](./ipsec.md).

Данный файл описывает методы оптимизации производительности IPsec: hardware offload, sysctl-параметры, многопоточность и нагрузочные тесты.

---

## Определения

**Hardware Offload** — аппаратное ускорение криптографических операций (AES-GCM, ChaCha20) на специализированных чипах (Intel QAT, Mellanox IPsec, ARMv8 CE). Снижает нагрузку на CPU.

**AES-NI** — расширениеinstruction set Intel/AMD для аппаратного AES. Поддерживается всеми современными CPU. Ускоряет AES-GCM в 3-10 раз.

**XFRM offload** — аппаратное ускорение на уровне ядра Linux, при котором обработка ESP передаётся сетевой карте (NIC) с поддержкой IPsec offload.

**RSS (Receive Side Scaling)** — механизм распределения входящего трафика по ядрам CPU. Критичен для высокоскоростных IPsec-каналов (10Gbps+).

**GRO/GSO (Generic Receive Offload / Generic Segmentation Offload)** — аппаратное объединение/сегментация пакетов на уровне NIC. Снижает количество прерываний CPU.

---

## Основные концепции

### Источники overhead в IPsec

```
+-------------------+     +-------------------+     +-------------------+
|   Приложение      |     |   TCP/UDP         |     |   ESP             |
|   (payload)       |     |   (L4)            |     |   (L3.5)          |
+--------+----------+     +--------+----------+     +--------+----------+
         |                         |                         |
         v                         v                         v
+-------------------+     +-------------------+     +-------------------+
|   Полезная нагрузка|    |   Оверхед L4      |     |   Оверхед ESP:    |
|   N байт          |     |   20-8 байт       |     |   8-73 байт       |
+-------------------+     +-------------------+     +-------------------+
                                                       |
                                              +--------+----------+
                                              | ESP Header: 8 байт|
                                              | IV: 8-16 байт     |
                                              | Padding: 0-15     |
                                              | Trail: 1-2 байт   |
                                              | ICV: 12-16 байт   |
                                              +-------------------+
```

**Типичный overhead ESP:** 50-73 байт на пакет.

### Факторы производительности

| Фактор | Влияние | Оптимизация |
|--------|---------|-------------|
| **Размер пакета** | Маленькие пакеты = больше overhead/cpu на пакет | Увеличить MTU, GRO |
| **Криптография** | AES-GCM быстрее cipher+HMAC | Использовать AEAD |
| **Hardware offload** | Снижает CPU на 50-90% | Intel QAT, NIC offload |
| **Многопоточность** | charon обрабатывает IKE в одном потоке | charon-cmd, multiple instances |
| **Маршрутизация** | Каждый пакет проверяется в SPD | Оптимизировать правила |
| **Количество SA** | Много SA = много памяти ядра | Ограничить количество пиров |

---

## Практические сценарии

### Проверка hardware support

```bash
# 1. Проверка AES-NI
grep -o aes /proc/cpuinfo | head -1
# → aes (если поддерживается)

# Или более детально:
cpuid | grep -i "AES"
# → AES: supported

# 2. Проверка Intel QAT
lspci | grep -i "QuickAssist\|QAT\|Virtual Function"
# → Intel Corporation Device 37c9 (если установлен)

# 3. Проверка NIC IPsec offload
ethtool -i eth0 | grep driver
# → driver: mlx5_core (Mellanox поддерживает IPsec offload)

# ethtool -k eth0 | grep -i ipsec
# → tx-ipsec: on
# → rx-ipsec: on

# 4. Проверка ARMv8 CE (для ARM)
cat /proc/cpuinfo | grep -i "aes\|asimd\|pmull"
```

### Настройка XFRM offload (NIC)

```bash
# Для NIC с поддержкой IPsec offload (Mellanox, Intel)

# 1. Включение offload на интерфейсе
sudo ethtool -K eth0 rx-ipsec on tx-ipsec on

# 2. Проверка
ethtool -k eth0 | grep ipsec

# 3. Конфигурация strongSwan для offload
# /etc/swanctl/conf.d/offload.conf
connections {
    high-perf {
        version = 2
        local_addrs = 198.51.100.1
        remote_addrs = 203.0.113.2

        proposals = aes256gcm128-sha384-ecp384

        children {
            fast-tunnel {
                esp_proposals = aes256gcm128-ecp384
                # Включить offload в ядре
                # (требуется патч strongSwan или ручная настройка XFRM)
            }
        }
    }
}
```

### Sysctl-параметры для IPsec

```bash
# /etc/sysctl.d/99-ipsec-performance.conf

# === XFRM параметры ===
# Максимальное количество SA в ядре
net.core.xfrm_acq_expires = 30
# Максимальное количество SA в шаблонах
net.ipv4.xfrm4_gc_thresh = 262144

# === Маршрутизация ===
# Включение IP forwarding
net.ipv4.ip_forward = 1
# Увеличение размера таблицы маршрутизации
net.ipv4.route.max_size = 524288

# === Сетевые буферы ===
# Увеличение размера RX/TX буферов
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576

# TCP buffer auto-tuning
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# === Conntrack ===
# Увеличение лимита conntrack (для NAT)
net.netfilter.nf_conntrack_max = 262144
net.netfilter.nf_conntrack_udp_timeout = 60
net.netfilter.nf_conntrack_udp_timeout_stream = 180

# === Прерывания ===
# Распределение прерываний по ядрам (RSS)
# Настройка через irqbalance или вручную:
# echo <cpu_mask> > /proc/irq/<irq_num>/smp_affinity
```

```bash
# Применение
sudo sysctl -p /etc/sysctl.d/99-ipsec-performance.conf
```

### Многопоточность charon

```bash
# strongSwan charon поддерживает многопоточность

# /etc/strongswan.conf.d/99-performance.conf
charon {
    # Количество рабочих потоков (по умолчанию = количество CPU)
    threads = 8

    # Приоритет планировщика (снижение нагрузки на систему)
    cpu_nice = -5

    # Включить параллельную обработку IKE
    processor_prio = -5

    # Лимит памяти на SA (MB)
    # block_threshold = 0

    # Таймауты для производительности
    # retransmit_timeout = 4.0
    # retransmit_tries = 5
}

# Для LibreSwan (pluto)
# /etc/ipsec.conf (внутри config setup)
# plutodebug=-1  # Отключить отладку для производительности
```

### Нагрузочное тестирование

#### iperf3 через IPsec

```bash
# Сервер (на удалённом шлюзе)
iperf3 -s

# Клиент (через IPsec-туннель)
iperf3 -c 192.168.2.1 -t 60 -P 4

# Результаты для Gigabit Ethernet:
# Без IPsec: ~940 Mbps
# С IPsec (AES-GCM-256, AES-NI): ~850-900 Mbps (5-10% overhead)
# С IPsec (AES-CBC, без AES-NI): ~400-500 Mbps
```

#### iperf3 с разными размерами пакетов

```bash
# Тест с разными MTU
for mtu in 1500 1400 1300 1200; do
    ip link set xfrm0 mtu $mtu
    echo "MTU $mtu:"
    iperf3 -c 192.168.2.1 -t 10 -M $((mtu - 73))
done
```

#### ping с разными размерами

```bash
# Определение максимального MTU через пинг
ping -M do -s 1372 -c 10 192.168.2.1
# 1372 + 28 (IP+ICMP) + 73 (ESP overhead) = 1473 байт

# Пошаговое определение
for size in $(seq 1300 10 1400); do
    result=$(ping -M do -s $size -c 1 -W 1 192.168.2.1 2>&1)
    if echo "$result" | grep -q "bytes from"; then
        echo "OK: size=$size"
    else
        echo "FAIL: size=$size"
        break
    fi
done
```

### Мониторинг производительности

```bash
# 1. Статистика CPU для charon
pidstat -p $(pgrep charon) 1

# 2. Статистика XFRM
watch -n 1 'ip -s xfrm state | grep -E "proto esp|packets|bytes"'

# 3. Мониторинг сетевых интерфейсов
sar -n DEV 1

# 4. Проверка аппаратного offload
ethtool -S eth0 | grep -i ipsec

# 5. Статистика прерываний
cat /proc/interrupts | grep -i eth0
```

---

## Типовые проблемы производительности

| Проблема | Симптом | Причина | Решение |
|----------|---------|---------|---------|
| Низкая пропускная способность | iperf < 500 Mbps | Нет AES-NI, cipher+HMAC | Включить AES-NI, перейти на AEAD |
| Высокая задержка | ping > 10ms через туннель | Фрагментация, маршрутизация | Увеличить MTU, MSS Clamping |
| CPU 100% на шлюзе | charon/pluto грузит CPU | Однопоточность, много SA | Увеличить threads, hash size |
| Пакеты дропаются | `ip -s xfrm state` errors растут | Overflow conntrack, хеш-таблица | Увеличить conntrack_max, xfrm GC |
| Туннель не поднимается при нагрузке | Timeout при согласовании | Маленький `retransmit_timeout` | Увеличить таймауты |

---

## Дополнительная информация

### Ожидаемая производительность

| Сценарий | Ожидаемый Throughput | CPU Load |
|----------|---------------------|----------|
| AES-GCM-256 + AES-NI, 10G NIC | 9-9.5 Gbps | 10-15% |
| AES-GCM-256 без AES-NI, 1G NIC | 400-500 Mbps | 60-80% |
| ChaCha20-Poly1305, 1G NIC | 500-700 Mbps | 30-50% |
| AES-CBC + HMAC-SHA256, 1G NIC | 300-400 Mbps | 70-90% |

### Связанные документы

- **[IPsec (основной документ)](./ipsec.md)** — архитектура IKEv2, рекомендации по алгоритмам.
- **[Мониторинг IPsec](./ipsec_monitoring.md)** — метрики производительности.
- **[Высокая доступность IPsec](./ipsec_ha.md)** — failover и кластеризация.
- **[MTU и VPN](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — детальный разбор overhead.
