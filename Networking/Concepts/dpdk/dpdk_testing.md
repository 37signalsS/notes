# Тестирование и бенчмаркинг DPDK-приложений

### Определения

- **RFC 2544**: Стандарт.testing methodology для network devices (IETF). Определяет тесты: throughput (zero-loss), latency (at load), frame loss rate, back-to-back. Используется для сертификации и бенчмаркинга.
- **Throughput (Пропускная способность)**: Максимальное количество пакетов/бит в секунду, которые устройство обрабатывает без потерь (zero packet loss).
- **PDR (Packet Drop Rate)**: Допустимый уровень потерь пакетов. Типичные значения: 0% (zero-loss), 0.01%, 0.1%.
- **Latency (Задержка)**: Время от момента передачи пакета генератором до момента его получения на выходе устройства. Замеряется при various load levels.
- **P50 / P99 / P99.9 Latency**: Перцентили задержки. P99 = 99% пакетов имеют задержку ниже этого значения. Критично для HFT и real-time.
- **Jitter**: Variance (изменчивость) задержки. Высокий jitter = нестабильная обработка пакетов.
- **TRex**: Высокопроизводительный трафик-генератор на базе DPDK. Поддерживает stateful (L7) и stateless (L2-L4) режимы, стерео-режим (two ports), API для автоматизации.
- **MoonGen**: Трафик-генератор на базе DPDK + Lua scripting. Более простой чем TRex, но менее функциональный.
- **pktgen-dpdk**: Минимальный трафик-генератор от DPDK project. Используется для быстрых тестов и sanity checks.
- **testpmd**: Стандартное DPDK-приложение для тестирования NIC. Поддерживает режимы: io, mac, simplex, chain, rxonly, txonly.
- **line-rate**: Полная скорость интерфейса (100Gbps = 100 Gbps = ~148.8 Mpps при 64B фреймах).
- **Mpps (Million packets per second)**: Основная метрика для оценки производительности packet processing.
- **Traffic generator**: Устройство/ПО для генерации и анализа трафика (TRex, MoonGen, Spirent, Ixia).
- **latency streams**: Потоки с замером latency (обычно 1% от общего трафика генератора).
- **Flow (поток)**: Уникальная комбинация 5-tuple (src_ip, dst_ip, src_port, dst_port, proto), определяющая один логический поток данных.

---

### Теория

#### 1. Типы тестов DPDK

| Тест | Цель | Что измеряется | RFC 2544 section |
| :--- | :--- | :--- | :--- |
| **Throughput (zero-loss)** | Максимальная скорость без потерь | Mpps, Gbps при 0% loss | 9.2 Throughput |
| **Latency (at load)** | Задержка при various load levels | P50, P99, max latency в мкс | 9.3 Latency |
| **Frame Loss Rate** | Потери при various load levels | %丢了 пакетов | 9.4 Frame Loss Rate |
| **Back-to-back** | Burst-обработка (连续 пакеты) | Количество丢失 после burst | 9.5 Back-to-Back |
| **Head-of-Line Blocking** | Блокировка đầu tiên pipeline | Latency spike при burst | - (non-RFC) |
| **Scalability** | Масштабирование по ядрам | Throughput при 1/2/4/8 lcores | - |

#### 2. Методология тестирования

**Бинарный поиск throughput (RFC 2544):**
```
1. Определить max rate: line-rate (100Gbps) или ~120% от ожидаемого throughput
2. Бинарный поиск:
   - Начать с midpoint (50% от max rate)
   - Если потерь нет → увеличить rate
   - Если есть потери → уменьшить rate
   - Продолжать до precision ±0.1% или 1Mpps
3. Результат: max throughput при 0% loss (Mpps)
```

**Измерение latency:**
```
1. Установить throughput rate (из шага 1)
2. Добавить latency streams (1% от общего трафика)
   - Каждый latency stream = один пакет каждые N мкс
   - Пакет содержит timestamp (от генератора)
3. На выходе: генератор сравнивает timestamp → вычисляет latency
4. Результат: P50, P99, P99.9, max latency (мкс)
```

#### 3. Трафик-генераторы: сравнение

| Параметр | TRex | MoonGen | pktgen-dpdk |
| :--- | :--- | :--- | :--- |
| **Архитектура** | DPDK + stateful L7引擎 | DPDK + Lua скрипты | DPDK (minimal) |
| **Режимы** | Stateless, Stateful, SmartNIC | Stateless, Flowgen | Stateless |
| **L7 поддержка** | HTTP, DNS, NAT-T, Custom | HTTP (ограниченно) | Нет |
| **Количество потоков** | Миллионы (flow tables) | До 256K | До 256 |
| **API** | Python/REST, JSON-RPC | Lua scripting | CLI |
| **Стерео** | Да (2 NIC → 1 генератор) | Да | Нет |
| **Сложность** | Высокая (много опций) | Средняя | Низкая |
| **Где используется** | Телеком, cloud, HFT testing | Lab testing | Quick sanity checks |
| **Поддержка RSS** | Да (распределение по queue) | Да | Да |
| **Стоимость** | Free (open source) | Free (open source) | Free (DPDK project) |

#### 4. Ключевые метрики

**Какие метрики смотреть:**
```
- Throughput: Mpps (миллионов пакетов/сек), Gbps (гигабит/сек)
- Zero-loss throughput: max Mpps при 0%丢了
- Latency: P50 (медиана), P99 (99-й перцентиль), max (worst-case)
- Jitter: std deviation latency (или P99 - P50)
- Frame Loss Rate:丢了 при various load levels
- CPU utilization: сколько CPU используется (должно быть ~100% на busy-polling lcores)
- Memory: HugePages usage, mempool availability
```

**Как интерпретировать результаты:**
```
- Throughput接近 line-rate = NIC + DPDK работают оптимально
- P99 latency > 10 мкс = проблемы с ISR/NUMA/cache misses
- Jitter > 50% от P50 = фоновые процессы мешают (isolcpus не работает)
-丢了 > 0% при < line-rate = bottleneck в NIC, driver, или приложении
```

---

### Практическое руководство

#### 1. Тестирование на testpmd (baseline)

**Запуск testpmd в режиме io (loopback через кабель):**
```bash
# Запуск testpmd с 4 ядрами, 4 RX/TX queues
./build/app/testpmd -l 2-5 -n 4 -w 0000:01:00.0 --socket-mem 2048,0 -- \
  --forward-mode=io \
  --rxq=4 --txq=4 \
  --rxd=1024 --txd=1024 \
  --burst=32 \
  --stats-period=1 \
  --forward-stats
```

**Ключевые команды testpmd:**
```bash
# Информация о порте
testpmd> show port info 0
# → Link status: up
# → Link speed: 100 Gbps
# → RSS: on, Toeplitz
# → RX queues: 4, TX queues: 4
# → RX offloads: CHECKSUM RSS_HASH SCATTER

# Статистика (обновляется каждую секунду)
testpmd> show port stats 0
# → *RX Good Packets: 14880952
# → *TX Good Packets: 14880952
# → *RX Good Bytes: 10019248640
# → *TX Good Bytes: 10019248640
# → RX Errors: 0
# → TX Errors: 0
# → RX Missed: 0

# Расширенная статистика (NIC-specific)
testpmd> show port xstats 0
# → rx_q0_packets: 3720238
# → rx_q1_packets: 3720238
# → rx_q2_packets: 3720238
# → rx_q3_packets: 3720238
# → tx_q0_packets: 3720238

# Настройка forwarding mode
testpmd> set fwd io
testpmd> set fwd mac
testpmd> set fwd rxonly
testpmd> set fwd txonly

# Запуск/остановка
testpmd> start
testpmd> stop

# Очистка статистики
testpmd> clear port stats all

# Просмотр конфигурации
testpmd> show config fwd
# → Forwarding mode: io
# → RX queues: 4
# → TX queues: 4
# → Burst size: 32

# Остановка и выход
testpmd> quit
```

**Измерение throughput на testpmd:**
```bash
# 1. Запустить testpmd на одном сервере (DUT)
./build/app/testpmd -l 2-5 -n 4 -w 0000:01:00.0 --socket-mem 2048,0 -- \
  --forward-mode=io --rxq=4 --txq=4 --burst=32 --stats-period=1

# 2. Подключить трафик-генератор к NIC (через кабель/switch)

# 3. На testpmd:
testpmd> set fwd io
testpmd> start

# 4. На генераторе: отправлять 100Gbps line-rate (64B фреймы)
# 5. На testpmd: смотреть show port stats 0

# Ожидаемый результат для 100G NIC:
# RX Good Packets: ~14880952 pps (line-rate при 64B)
# TX Good Packets: ~14880952 pps
# RX Missed: 0
# RX Errors: 0
```

#### 2. Тестирование на TRex (полноценный генератор)

**Установка TRex:**
```bash
# Скачивание TRex
wget https://trex-tgn.cisco.com/trex/release/v3.04.tar.gz
tar xzf v3.04.tar.gz
cd v3.04

# Конфигурация (trex_cfg.yaml)
cat > /etc/trex_cfg.yaml << 'EOF'
- port_limit: 2
  version: 2
  interfaces: ["PCI_0000:01:00.0", "PCI_0000:01:00.1"]
  port_info:
    - ip: 10.0.0.1
      default_gw: 10.0.0.2
    - ip: 10.0.0.2
      default_gw: 10.0.0.1
EOF

# Запуск TRex
./t-rex-64 -i --astf
```

**Базовый тест на TRex (Python API):**
```python
from trex.stl.api import *

# Подключение к TRex
client = STLClient(server='127.0.0.1')

try:
    client.connect()

    # Создание потока: 64B UDP, 10Mpps
    pkt = Ether()/IP(src="10.0.0.1", dst="10.0.0.2")/UDP(sport=1234, dport=5678)
    stream = STLStream(
        packet=STLPktBuilder(pkt=pkt),
        mode=STLStreamMode_CONTINUOUS_BURST,
        rate=PPS(10000000)  # 10Mpps
    )

    # Добавление потока на порт 0
    client.add_streams(stream, ports=[0])

    # Запуск передачи на 10 секунд
    client.start(ports=[0], duration=10)

    # Сбор статистики
    stats = client.get_stats()

    print(f"TX: {stats[0]['opackets']} packets")
    print(f"TX Rate: {stats[0]['opps']} pps")
    print(f"TX Bytes: {stats[0]['obytes']} bytes")

    # Проверка потерь на порту 1 (получатель)
    print(f"RX: {stats[1]['ipackets']} packets")
    print(f"Loss: {stats[0]['opackets'] - stats[1]['ipackets']} packets")

finally:
    client.stop(ports=[0])
    client.disconnect()
```

**RFC 2544 throughput test на TRex:**
```python
from trex.stl.api import *

client = STLClient(server='127.0.0.1')

try:
    client.connect()

    # Создание потока
    pkt = Ether()/IP(src="10.0.0.1", dst="10.0.0.2")/UDP(sport=1234, dport=5678)
    stream = STLStream(
        packet=STLPktBuilder(pkt=pkt),
        mode=STLStreamMode_CONTINUOUS_BURST,
        rate=PPS(14880952)  # 100G line-rate при 64B
    )

    client.add_streams(stream, ports=[0])

    # Binary search throughput (RFC 2544)
    # TRex автоматически выполняет binary search
    result = client.ports_stats

    # Или ручной binary search:
    test_rates = [14880952, 12000000, 10000000, 8000000]  # pps
    for rate in test_rates:
        client.reset(ports=[0, 1])
        stream.rate = PPS(rate)
        client.add_streams(stream, ports=[0])
        client.start(ports=[0], duration=10)
        stats = client.get_stats()
        loss = stats[0]['opackets'] - stats[1]['ipackets']
        loss_pct = (loss / stats[0]['opackets']) * 100
        print(f"Rate: {rate} pps, Loss: {loss_pct:.2f}%")
        if loss_pct == 0:
            print(f"Zero-loss throughput: {rate} pps")
            break

finally:
    client.stop(ports=[0])
    client.disconnect()
```

#### 3. Тестирование latency

**Тестирование latency через TRex:**
```python
from trex.stl.api import *

client = STLClient(server='127.0.0.1')

try:
    client.connect()

    # Latency stream (1 пакет каждые 10 мкс = 100Kpps)
    latency_pkt = Ether()/IP(src="10.0.0.1", dst="10.0.0.2")/UDP(sport=1234, dport=5678)
    latency_stream = STLStream(
        packet=STLPktBuilder(pkt=latency_pkt),
        mode=STLStreamMode_CONTINUOUS_BURST,
        rate=PPS(100000),  # 100Kpps latency stream
    )

    # Background stream (99% трафика)
    bg_pkt = Ether()/IP(src="10.0.0.1", dst="10.0.0.2")/UDP(sport=1234, dport=5678)
    bg_stream = STLStream(
        packet=STLPktBuilder(pkt=bg_pkt),
        mode=STLStreamMode_CONTINUOUS_BURST,
        rate=PPS(14000000),  # 14Mpps background
    )

    client.add_streams([latency_stream, bg_stream], ports=[0])

    client.start(ports=[0], duration=30)
    stats = client.get_stats()

    # Latency statistics
    latency = stats[0]['latency']
    print(f"P50: {latency['average']:.2f} мкс")
    print(f"P99: {latency['total_max']:.2f} мкс")
    print(f"Jitter: {latency['jitter']:.2f} мкс")

finally:
    client.stop(ports=[0])
    client.disconnect()
```

**Тестирование latency через testpmd:**
```bash
# testpmd не имеет built-in latency measurement
# Используйте TRex или MoonGen для latency тестов

# Или через hardware timestamping:
# testpmd> set fwd mac
# testpmd> set port 0 timestamp on
# testpmd> start
```

#### 4. Тестирование с pktgen-dpdk (быстрый sanity check)

```bash
# Запуск pktgen
./build/app/pktgen -l 2-3 -n 4 -w 0000:01:00.0 --socket-mem 1024,0

# В pktgen:
#> set 0 rate 100%         # Line-rate
#> set 0 size 64           # 64B фреймы
#> set 0 count 10000000    # 10M пакетов
#> start 0                 # Начать передачу
#> stop 0                  # Остановить

#> stat 0                  # Статистика
#> port 0                  # Информация о порте

#> quit                    # Выход
```

#### 5. Проверка распределения по ядрам (RSS test)

```bash
# 1. Запустить testpmd с 4 RX queues
./build/app/testpmd -l 2-5 -n 4 -w 0000:01:00.0 --socket-mem 2048,0 -- \
  --forward-mode=io --rxq=4 --txq=4 --stats-period=1

# 2. На генераторе: отправить 4 потока с разными src_ip
# Поток 1: src=10.0.0.1, dst=10.0.0.2, dport=80
# Поток 2: src=10.0.0.2, dst=10.0.0.2, dport=80
# Поток 3: src=10.0.0.3, dst=10.0.0.2, dport=80
# Поток 4: src=10.0.0.4, dst=10.0.0.2, dport=80

# 3. На testpmd: show port stats 0
# Ожидаемый результат: rx-0 ~ rx-3 получают примерно равное количество пакетов
# rx-0.packets: ~25% от общего
# rx-1.packets: ~25% от общего
# rx-2.packets: ~25% от общего
# rx-3.packets: ~25% от общего
```

#### 6. Проверка аппаратных ошибок NIC

```bash
# Аппаратные счётчики ошибок
ethtool -S enp1s0 | grep -iE "error|drop|miss|crc|collision"
# → rx_crc_errors: 0
# → rx_missed: 0
# → rx_dropped: 0
# → tx_dropped: 0
# → tx_collision_errors: 0

# Если errors > 0:
# - rx_crc_errors → проблема с кабелем/PHY
# - rx_missed → NIC не успевает обработать (overload)
# - rx_dropped → mempool exhaustion или virtio queue full
# - tx_dropped → TX ring full (overload)

# Мониторинг в реальном времени
watch -n 1 'ethtool -S enp1s0 | grep -E "rx_packets|tx_packets|rx_errors|tx_errors"'
```

#### 7. Benchmarking methodology (полный цикл)

```bash
# === Phase 1: Sanity check ===
# 1. Проверка HugePages
cat /proc/meminfo | grep -i huge
# 2. Проверка IOMMU
dmesg | grep -i iommu
# 3. Проверка NIC binding
./usertools/dpdk-devbind.py --status
# 4. Запуск testpmd (loopback)
./build/app/testpmd -l 2-3 -n 4 -w 0000:01:00.0 --socket-mem 1024,0 -- \
  --forward-mode=io --stats-period=1
# 5. Проверка: show port stats 0 → RX/TX > 0

# === Phase 2: Throughput test ===
# 1. Подключить трафик-генератор
# 2. Отправить 100Gbps line-rate (64B фреймы)
# 3. На testpmd: show port stats 0 → все пакеты приняты, 0 errors
# 4. Результат: max Mpps при 0丢了

# === Phase 3: Latency test ===
# 1. Установить throughput rate (из Phase 2)
# 2. Добавить latency stream (TRex)
# 3. Запустить на 60 секунд
# 4. Результат: P50, P99, max latency (мкс)

# === Phase 4: Scalability test ===
# 1. Повторить Phase 2 с 1/2/4/8 lcores
# 2. Построить график: throughput vs lcores
# 3. Ожидаемый: линейное масштабирование до NUMA boundary

# === Phase 5: Stress test ===
# 1. Запустить тест на 24+ часов
# 2. Мониторить: throughput, latency, errors, mempool exhaustion
# 3. Проверить стабильность
```

---

### Типичные ошибки тестирования

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| 0 Mpps на testpmd | TX-pps = 0, RX-pps = 0 | Кабель не подключён или NIC не bind к vfio-pci | Проверьте `ip link show`, `ethtool`, физическое подключение |
| Throughput < line-rate | 80Gbps вместо 100Gbps | Wrong burst size, NUMA mismatch, NIC offload disabled | Увеличьте burst; проверьте NUMA; включите offloads |
| P99 latency > 100 мкс | Спайки задержки | IRQ, NUMA, cache miss, фоновые задачи | isolcpus, nohz_full, rcu_nocbs; NUMA-local HugePages |
| TRex не запускается | `Cannot connect to TRex server` | TRex не запущен или порт 4501 заблокирован | `./t-rex-64 -i`; `ufw allow 4501` |
| Потери при < line-rate |丢了 > 0% при 50Gbps | NIC queue overflow, mempool exhaustion | Увеличьте mempool size; уменьшите burst; добавьте RX queues |

---

### Дополнительная информация

- **[DPDK: RSS](dpdk_rss.md)** — как настроить распределение трафика по ядрам.
- **[DPDK: rte_flow API](dpdk_rte_flow.md)** — программирование фильтрации в железе.
- **[DPDK: Технические детали](dpdk_technical.md)** — HugePages, mempool, rte_ring, burst size.
- **[DPDK: Практические сценарии](scenarios.md)** — HFT, NFV, 5GUPF — где нужны benchmarking.
- **[TRex Documentation](https://trex-tgn.cisco.com/trex/doc/trex_manual.html)** — официальный мануал TRex.
- **[RFC 2544](https://tools.ietf.org/html/rfc2544)** — стандарт testing methodology.
- **[MoonGen Documentation](https://github.com/emmericp/MoonGen)** — документация MoonGen.
