# Сетевые потери и влияние offloading на анализ TCP

> **SSoT:** Определения базовых терминов (RTT, iRTT, Window Size, Expert Info) — в **[Определения](../definitions.md)**. Концепции захвата и offloading — в **[Основные концепции](../core_concepts.md)**. tshark-команды — в **[Использование tshark](../tshark_usage.md)**. Обзор диагностики — в **[Обзор диагностики](./tcp_performance_diagnostics.md)**. Клиентские проблемы — в **[Клиентские проблемы](./tcp_client_performance_issues.md)**. Серверные проблемы — в **[Серверные проблемы](./tcp_server_performance_issues.md)**. Графики — в **[Инструменты анализа](./tcp_performance_analysis_tools.md)**. Тюнинг — в **[TCP Tuning](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)**.

## Определения

> Определения базовых терминов (RTT, iRTT, Window Size) — в **[Определения](../definitions.md)**. Концепции захвата (Ring Buffer, AF_PACKET) — в **[Основные концепции](../core_concepts.md)**. Ниже — термины, специфичные для сетевых потерь и offloading.

**Сетевые потери (Packet Loss)** — состояние, при котором пакеты не достигают адресата. В TCP потери приводят к срабатыванию механизмов надежности (ретрансмиссий) и снижению скорости передачи.

**Нарушение порядка (Out-Of-Order, OOO)** — прибытие пакетов к получателю не в той последовательности, в которой они были отправлены. Часто вызвано многопутевой маршрутизацией (ECMP) или особенностями работы сетевых карт.

**Технологии разгрузки (Offloading)** — функции сетевой карты (NIC) или драйвера (TSO, GSO, GRO), переносящие ресурсоемкие сетевые задачи с CPU на аппаратный уровень. Создают «оптическую иллюзию» при анализе трафика, скрывая реальную сегментацию и состояние контрольных сумм.

**XDP Offloading** — перенос обработки пакетов на уровень драйвера или NIC через eBPF (eXpress Data Path). Пакеты, отброшенные или модифицированные на этом уровне, могут быть полностью невидимы для стандартных средств захвата (Wireshark/tcpdump), что создает «слепые зоны» в диагностике.

**Hardware Timestamping** — технология NIC для проставления временных меток в момент приема/передачи пакета на физическом уровне. Позволяет избежать джиттера, вносимого очередями ядра, что критично для точного расчета RTT и анализа микро-всплесков.

**PMTUD (Path MTU Discovery) Failure** — «невидимые» потери, возникающие, когда большие пакеты отбрасываются из-за ограничений MTU на промежуточных узлах, а ICMP-сообщения о необходимости фрагментации блокируются файрволами.

**ECMP (Equal-Cost Multi-Path)** — маршрутизация по нескольким равнозначным маршрутам. Пакеты одного потока могут идти по разным путям, что вызывает Out-of-Order прибытие и ложные ретрансмиссии в Wireshark.

**Jumbo Frames (Кадры jumbo)** — Ethernet-кадры с MTU > 1500 (обычно 9000). Требуют согласованной настройки на всех узлах пути. Несоответствие MTU вызывает Black Hole: крупные пакеты отбрасываются без ICMP-ответа.

**NIC Error Counters** — аппаратные счетчики ошибок сетевой карты (CRC errors, dropped, missed). Источник «невидимых» потерь, которые Wireshark не может зафиксировать, так как пакеты не доходят до стека ядра.

## Quick-Start: Диагностика потерь

Быстрый выбор инструмента в зависимости от типа потерь:

| Симптом | Инструмент | Команда / Фильтр | Что проверять |
| :--- | :--- | :--- | :--- |
| Retransmissions в Wireshark | Expert Info + IO Graphs | `tcp.analysis.retransmission` | Потери в сети или перегрузка |
| «Гигантские» пакеты (> 64 КБ) | `ethtool -k` | `ethtool -k eth0 \| grep tso` | TSO/GSO включены |
| `bad cksum` в tcpdump | `ethtool -k` | `ethtool -k eth0 \| grep checksum` | Checksum Offload включен |
| Пакеты «исчезают» | `pwru` / `xdp-dump` | `sudo pwru --filter 'tcp'` | XDP/eBPF отбрасывает |
| Ping мелкий работает, крупный нет | ICMP фильтр | `icmp.type == 3 and icmp.code == 4` | PMTUD Black Hole |
| Высокий Retrans Rate (>5%) | `ethtool -S` | `ethtool -S eth0 \| grep -i err` | Физические ошибки L1/L2 |
| OOO без потерь | `tcp.analysis.out_of_order` | `tshark -Y "tcp.analysis.out_of_order"` | ECMP или RSS |

## Основные концепции

### Влияние Offloading на достоверность анализа

Инструменты захвата (Wireshark, tcpdump) перехватывают пакеты на уровне ядра, что создает визуальные «оптические иллюзии»:

| Артефакт в Wireshark | Технология | Суть явления |
| :--- | :--- | :--- |
| **Гигантские пакеты (> 60 Кбайт)** | TSO / GSO | Ядро еще не разделило данные на стандартные сегменты MSS. |
| **Ошибки контрольных сумм** | Checksum Offloading | NIC вычислит сумму в момент физической отправки; Wireshark видит мусор или нули на стороне отправителя. |
| **Ложные ретрансмиссии** | GRO / LRO | На приемной стороне пакеты склеиваются NIC, что сбивает счетчик Seq-номеров в анализаторе. |
| **Слепая зона (Missing packets)** | XDP / eBPF | Пакеты отбрасываются драйвером до того, как попадут в стек ядра и будут замечены Wireshark. |

### Диагностика реальных потерь (Expert Info)

В 2026 году Wireshark стал «умнее» в распознавании современных механизмов ядра:

- **RACK-awareness:** Wireshark 4.4+ корректно отображает ретрансмиссии, вызванные алгоритмом **RACK (Recent ACK)**, который ориентируется на время, а не на количество DupACK.
- **Previous segment(s) not captured:** Признак потери данных до точки захвата или переполнения кольцевого буфера NIC.
- **Fast Retransmission:** Реакция на 3 Duplicate ACK (классический метод).
- **Spurious Retransmission:** Повторная отправка данных, которые уже подтверждены. Часто возникает при некорректной настройке **RSS (Receive Side Scaling)**, когда пакеты одного потока попадают на разные ядра CPU и перемешиваются (Out-of-Order).
- **DupACK Analysis:** Каждый Duplicate ACK указывает на пропущенный сегмент. Массовые DupACK — признак проблем с конкретным сегментом.

### Стек сетевых потерь (Network Stack Packet Loss)

Потери могут происходить на разных уровнях, и каждый уровень требует своего инструмента диагностики:

```
[ Приложение ] → [ TCP ] → [ IP ] → [ qdisc (qdisc) ] → [ NIC Driver ] → [ Физика (L1/L2) ]
        ↓             ↓        ↓              ↓                    ↓                ↓
   App drops     Retrans   Routing       Shaping            XDP/GRO          CRC errors
   (backlog)     (RACK)    (ECMP)        (HTB/fq)           (eBPF)           (cable)
```

| Уровень | Типичные потери | Инструмент диагностики |
| :--- | :--- | :--- |
| **Приложение** | Backlog overflow, slow read | `ss -ltn`, `netstat -an` |
| **TCP** | RTO, Fast Retransmit, RACK | `nstat -az TcpExtTCPTimeouts` |
| **IP** | Routing blackhole | `ip route get <dst>`, `mtr` |
| **qdisc** | Shaping drops, HTB overlimit | `tc -s qdisc show`, `tc -s class show` |
| **NIC Driver** | XDP drop, ring buffer overflow | `pwru`, `ethtool -S eth0` |
| **Физика (L1/L2)** | CRC errors, runts, giants | `ethtool -S eth0 \| grep -i error` |

### Диагностика через ethtool

`ethtool` показывает аппаратные счетчики ошибок NIC — единственный способ увидеть потери, которые не доходят до Wireshark:

```bash
# Полная статистика ошибок NIC
ethtool -S eth0 | grep -E 'error|drop|miss|crc|collision|fifo'
# Пример вывода:
# → rx_crc_errors: 15        ← Проблема с кабелем или NIC
# → rx_missed_errors: 8      ← Переполнение RX-очереди
# → tx_dropped: 120           ← Переполнение TX-очереди (qdisc drops)
# → rx_fifo_errors: 3         ← NIC не успевает обрабатывать

# Счетчики丢失 пакетов на уровне NIC
ethtool -S eth0 | grep -i drop
# → rx_dropped: 45            ← пакеты отброшены NIC (XDP, ring buffer)
# → tx_dropped: 10            ← пакеты отброшены при передаче

# Проверка состояния ring buffer
ethtool -g eth0
# → Pre-set:
#   RX:  256,  RX Mini: 0,  RX Jumbo: 0,  TX:  256
# → Current:
#   RX:  256,  RX Mini: 0,  RX Jumbo: 0,  TX:  256
```

### Диагностика PMTUD (Path MTU Discovery)

Когда large segments отбрасываются, а ICMP «не работает»:

```bash
# Поиск PMTUD Black Hole в Wireshark
# 1. Ищите пакеты с DF флагом
tshark -r capture.pcap -Y "ip.flags.df == 1 && tcp.len > 1400" \
  -T fields -e frame.number -e ip.src -e ip.dst -e tcp.len

# 2. Ищите ICMP "Fragmentation Needed"
tshark -r capture.pcap -Y "icmp.type == 3 && icmp.code == 4" \
  -T fields -e frame.number -e ip.src -e ip.dst -e icmp.mtu

# 3. Поиск "замерших" TCP-сессий
tshark -r capture.pcap -Y "tcp.len > 1400 && tcp.analysis.retransmission" \
  -T fields -e tcp.stream | sort -u

# Решение:
# 1. MSS Clamping на файрволе:
#    iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
#             -j TCPMSS --clamp-mss-to-pmtu
# 2. Или увеличение MTU на всем пути до 9000 (jumbo frames)
```

## Практические сценарии

### Сценарий 1: Отличие потерь от троттлинга (Shaping)

Для доказательства того, что скорость ограничена именно потерями:
1. Используйте **IO Graphs** (`Statistics → IO Graphs`).
2. В Wireshark 4.4+ установите **Tick interval** в **1 microsecond** для выявления микро-всплесков.
3. Настройте два графика: `all packets` (Bits/s) и `tcp.analysis.retransmission` (Packets).
4. **Анализ:** Если графики «зеркальны» (всплеск ошибок = провал скорости) — в сети есть реальные потери. Если пропускная способность ограничена ровной линией («полкой») без всплесков ошибок — это работа **Shaper** (ограничителя) на стороне провайдера.

**tshark-эквивалент:**
```bash
# Статистика по секундам: Throughput vs Retransmissions
tshark -r capture.pcap -q -z "io,stat,1,SUM(tcp.len)*8,COUNT(tcp.analysis.retransmission)tcp.analysis.retransmission"
```

### Сценарий 2: Диагностика проблем MTU (PMTUD)

Если мелкие пакеты (ping, SSH) проходят, а крупные данные (HTTP, gRPC) «виснут»:
1. Ищите пакеты с флагом **DF (Don't Fragment)**.
2. В Wireshark примените фильтр: `icmp.type == 3 and icmp.code == 4` (Fragmentation Needed).
3. Если ответов ICMP нет, а TCP-сессия замирает после отправки крупного сегмента — вы столкнулись с «ICMP Black Hole».
4. **Решение:** Настройка **TCP MSS Clamping** на пограничном оборудовании или увеличение MTU на всем пути.

**tshark-команды:**
```bash
# Поиск крупных пакетов с DF (потенциальные жертвы PMTUD)
tshark -r capture.pcap -Y "ip.flags.df == 1 && tcp.len > 1400" \
  -T fields -e frame.number -e ip.src -e ip.dst -e tcp.len | head -20

# Проверка ICMP "Fragmentation Needed"
tshark -r capture.pcap -Y "icmp.type == 3 && icmp.code == 4" \
  -T fields -e frame.number -e ip.src -e ip.dst -e icmp.mtu
```

### Сценарий 3: Устранение искажений Offloading

При сомнениях в корректности дампа (например, гигантские пакеты или ошибки CRC):
1. Отключите аппаратные оптимизации на интерфейсе:
   ```bash
   sudo ethtool -K eth0 tso off gso off gro off lro off rx-checksum off tx-checksum off
   ```
2. Повторите захват. Если артефакты исчезли — дамп стал достоверным.
3. Не забудьте включить их обратно после диагностики, так как это повышает нагрузку на CPU.

**Проверка до и после:**
```bash
# Проверка состояния offloading
ethtool -k eth0 | grep -E 'segmentation|receive|generic|checksum'
# → tcp-segmentation-offload: on
# → tcp-generic-segmentation-offload: on
# → tcp-generic-receive-offload: on
# → rx-checksumming: on

# После отключения:
# → tcp-segmentation-offload: off
# → tcp-generic-segmentation-offload: off
```

### Сценарий 4: Поиск «невидимых» потерь (XDP/eBPF)

Если Wireshark не видит ожидаемых пакетов даже на входящем интерфейсе:
1. Используйте eBPF-инструменты для трассировки внутри драйвера.
2. **pwru:** Позволяет отследить путь пакета в ядре и увидеть, на какой функции он был сброшен.
3. **xdp-dump:** Если пакеты перехватываются XDP-программой, стандартный `tcpdump` их не увидит. Используйте `xdp-dump` для захвата на уровне драйвера.
4. Это критично для отладки современных Cloud-Native сетей и высокопроизводительных балансировщиков.

**pwru-команды:**
```bash
# Трассировка всех TCP-пакетов в ядре
sudo pwru --filter 'tcp' --output /tmp/pwru.log

# Поиск конкретного потока
sudo pwru --filter 'tcp.port == 8080 && ip.dst == 10.0.0.1'

# Анализ XDP-счетчиков
sudo bpftool prog show | grep xdp
sudo bpftool map dump name xdp_stats_map
```

### Сценарий 5: Диагностика ложных ошибок Checksum (Offload)

При анализе трафика через `tcpdump` на локальном хосте часто видны пометки `bad cksum` для **исходящих** пакетов:

```bash
# 1. Проверка: bad cksum — это нормально или нет?
# На стороне ОТПРАВИТЕЛЯ: bad cksum = НОРМА (NIC еще не вычислил)
# На стороне ПОЛУЧАТЕЛЯ: bad cksum = ПРОБЛЕМА (данные повреждены)

# 2. Проверка offloading
ethtool -k eth0 | grep checksum
# → rx-checksumming: on
# → tx-checksumming: on
# Если включено → bad cksum в tcpdump — это артефакт offload

# 3. Поиск реальных ошибок checksum
nstat -az | grep -i csum
# → TcpInCsumErrors    5    0.0
# Если TcpInCsumErrors > 0 → реальная проблема (кабель, память NIC)

# 4. Временное отключение для чистого захвата
sudo ethtool -K eth0 rx-checksum off tx-checksum off
# → Теперь bad cksum в tcpdump = реальная проблема
```

### Сценарий 6: Анализ ECMP-вызывающих Out-of-Order

ECMP (Equal-Cost Multi-Path) маршрутизация по нескольким равнозначным путям:

```bash
# 1. Поиск OOO в Wireshark
tshark -r capture.pcap -Y "tcp.analysis.out_of_order" -T fields \
  -e frame.number -e tcp.stream -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport

# 2. Статистика OOO по потокам
tshark -r capture.pcap -Y "tcp.analysis.out_of_order" -T fields \
  -e tcp.stream | sort | uniq -c | sort -rn | head -10
# → Поток с наибольшим количеством OOO = подозрительный

# 3. Проверка маршрутов в Linux
ip route get 10.0.0.1
# → 10.0.0.1 via 192.168.1.1 dev eth0 src 192.168.1.100 uid 0
# → cache

# Множественные маршруты (ECMP):
ip route get 10.0.0.1 fibmatch
# → 10.0.0.0/24 via 192.168.1.1 dev eth0 proto static
# → 10.0.0.0/24 via 192.168.2.1 dev eth1 proto static

# 4. Проверка hashing
ethtool -k eth0 | grep receive-hashing
# → receive-hashing: on
```

### Сценарий 7: Анализ NIC Error Counters

Аппаратные ошибки NIC — источник «невидимых» для Wireshark потерь:

```bash
# 1. Полная статистика ошибок
ethtool -S eth0 | grep -E 'error|drop|miss|crc|collision|fifo|overflow'
# → rx_crc_errors: 15        ← Проблема с кабелем или PHY
# → rx_missed_errors: 8      ← NIC не успевает обрабатывать
# → tx_fifo_errors: 120       ← Переполнение TX-очереди
# → rx_frame_errors: 3        ← Ошибка фрейма Ethernet

# 2. Мониторинг в реальном времени
watch -n 1 'ethtool -S eth0 | grep -E "error|drop|miss"'

# 3. Корреляция с потерями в Wireshark
# Если rx_missed_errors растет同期енно с retransmissions → проблема на NIC

# 4. Диагностика физики (L1/L2)
ethtool eth0 | grep -E 'Speed|Duplex|Link detected|Auto-negotiation'
# → Speed: 10000Mb/s
# → Duplex: Full
# → Link detected: yes
# → Auto-negotiation: on

# 5. Проверка кабеля
ethtool -S eth0 | grep -i cable
# → rx_length_errors: 0       ← все корректно
# → If cable issues, check physical layer
```

### Сценарий 8: Диагностика через nstat (агрегированные счетчики)

```bash
# 1. Ретрансмиссии и таймауты
nstat -az | grep -E 'TcpRetransSegs|TcpOutSegs|TcpExtTCPTimeouts|TcpExtTCPFastRetrans|TcpExtTCPTailLossProbe'
# → TcpRetransSegs    100   0.0
# → TcpOutSegs        50000 0.0
# → Retrans Rate = 100/50000 = 0.2% (норма)

# 2. Ошибки контрольных сумм
nstat -az | grep -i csum
# → TcpInCsumErrors    5    0.0   ← проблема (кабель, NIC)
# → TcpOutCsumErrors   0    0.0   ← норма

# 3. Window-related ошибки
nstat -az | grep -iE 'Window|Zero|Full'
# → TcpExtTCPWindowFull    0    0.0   ← норма
# → TcpExtTCPZeroWindow    0    0.0   ← норма

# 4. Offload-related ошибки
nstat -az | grep -iE 'Offload|TSO|GRO|LRO'
# → TcpExtTCPOrigDataSent  50000  0.0
```

## Таблица проблем

| Проблема | Симптом в Wireshark | Инструмент проверки | Диагностическая команда | Решение |
| :--- | :--- | :--- | :--- | :--- |
| **Retransmissions** | `tcp.analysis.retransmission` | Expert Info | `nstat -az TcpRetransSegs` | Проверить сеть (mtr, ping) |
| **TSO/GSO Artifact** | Пакеты > 64 КБ | `ethtool -k` | `ethtool -k eth0 \| grep tso` | Отключить для захвата |
| **Checksum Offload** | `bad cksum` в tcpdump | `ethtool -k` | `ethtool -k eth0 \| grep checksum` | Это нормально на TX |
| **XDP/eBPF Drop** | Пакеты исчезают | `pwru` | `sudo pwru --filter 'tcp'` | Проверить XDP-программы |
| **PMTUD Black Hole** | Крупные TCP зависают | ICMP фильтр | `icmp.type == 3 && icmp.code == 4` | MSS Clamping |
| **NIC CRC Errors** | «Невидимые» потери | `ethtool -S` | `ethtool -S eth0 \| grep crc` | Заменить кабель |
| **ECMP OOO** | `tcp.analysis.out_of_order` | `tshark` + `ip route` | `tshark -Y "tcp.analysis.out_of_order"` | Настроить хеш-функцию |
| **LRO/GRO Artifact** | Ложные Spurious Retrans | `ethtool -k` | `ethtool -k eth0 \| grep gro` | Отключить LRO |
| **Ring Buffer Overflow** | `rx_missed_errors` | `ethtool -S` | `ethtool -S eth0 \| grep missed` | Увеличить ring buffer |

## Дополнительная информация

### Уровни потерь и их влияние

- **< 0.1%:** Допустимый уровень для большинства интернет-каналов.
- **0.1% – 1%:** Ощутимое замедление передачи файлов, деградация качества VoIP/Video.
- **> 1%:** Критическая нестабильность; требуется проверка физики (L1) или ошибок на портах (L2).

### Диагностические команды ОС

| Команда | Что проверяет | Норма |
| :--- | :--- | :--- |
| `nstat -az TcpRetransSegs` | Глобальные ретрансмиссии | < 1% от TcpOutSegs |
| `nstat -az TcpExtTCPTimeouts` | RTO таймауты | 0 |
| `nstat -az TcpInCsumErrors` | Ошибки checksum | 0 |
| `ethtool -S eth0 \| grep crc` | CRC ошибки NIC | 0 |
| `ethtool -S eth0 \| grep drop` | Дропы на NIC | 0 |
| `ethtool -g eth0` | Ring buffer | Current = Pre-set |
| `ss -ti \| grep retrans` | Retrans per connection | Стабильное значение |

### См. также

- **[Определения Wireshark](../definitions.md)** — базовые термины (RTT, iRTT, Window Size).
- **[Основные концепции захвата](../core_concepts.md)** — Ring Buffer, AF_PACKET, offloading.
- **[Использование tshark](../tshark_usage.md)** — CLI-команды для анализа.
- **[Обзор диагностики производительности](./tcp_performance_diagnostics.md)** — методология.
- **[Проблемы клиента](./tcp_client_performance_issues.md)** — Zero Window, backpressure.
- **[Проблемы сервера](./tcp_server_performance_issues.md)** — TTFB, CFS, GC.
- **[Инструменты анализа: графики TCP](./tcp_performance_analysis_tools.md)** — визуализация потоков.
- **[Network Offloading в Linux](../../../../Linux/Networking/Concepts/offloading.md)** — глубокий разбор GRO/LRO/TSO/GSO.
- **[ethtool: диагностика железа](../../../../Linux/Networking/Tools/ethtool.md)** — работа с NIC.
