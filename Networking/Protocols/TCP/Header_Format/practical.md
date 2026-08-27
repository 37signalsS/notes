# Практика анализа заголовка TCP

## Определения

**Практический анализ заголовка TCP** — процесс исследования управляющих полей сегмента в реальном времени или в сохраненных дампах (pcap). Целью анализа является диагностика сетевых задержек, проверка корректности работы алгоритмов управления потоком и выявление аномалий (например, некорректных контрольных сумм или флагов).

**Инструментарий:**

| Инструмент | Уровень | Назначение | Ограничения |
| :--- | :--- | :--- | :--- |
| **tcpdump** | CLI | Захват и разбор трафика в реальном времени | Нет визуализации, limited protocol decode |
| **tshark** | CLI | Полный разбор протоколов (Wireshark engine) | Требует Wireshark, сложный синтаксис фильтров |
| **Wireshark** | GUI | Графический анализ с экспертной системой | Требует GUI, высокое потребление памяти |
| **ss** | CLI | Доступ к внутренним счетчикам ядра (`tcp_info`) | Только для локальных соединений |
| **nstat** | CLI | Глобальные счетчики TCP (ошибки, ретрансмиссии) | Агрегированная статистика, без деталей per-connection |
| **eBPF (bcc-tools)** | CLI | Низкоуровневая трассировка событий стека TCP | Требует root, ядро ≥ 4.9, بعض инструменты требуют KPROBE |
| **bpftrace** | CLI | Скриптовый язык для eBPF-трассировки | Требует root, ядро ≥ 4.9 |

---

## Методология анализа

При диагностике TCP-соединений следуйте последовательности:

1. **Быстрый обзор** — `ss -ti` (rtt, retrans, cwnd, wscale, mss)
2. **Глобальная статистика** — `nstat -az` (счетчики ошибок, потерь, ECN)
3. **Захват трафика** — `tcpdump -w` (запись для глубокого анализа)
4. **Детальный разбор** — `tshark -r` или Wireshark (полная инспекция)
5. **Глубокая трассировка** — eBPF (если проблема на уровне ядра)

---

## Базовые концепции

### Полная таблица флагов TCP

8 флагов заголовка TCP (биты 0–7 в байте флагов, offset 13):

| Флаг | Бит | tcpdump | Wireshark | Описание | Когда устанавливается |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CWR** | 7 | `[W]` | `tcp.flags.cwr == 1` | Congestion Window Reduced | Отправитель снижает cwnd после ECE |
| **ECE** | 6 | `[E]` | `tcp.flags.ece == 1` | ECN-Echo | Получатель CE-пакета или запрашивает ECN |
| **URG** | 5 | `[U]` | `tcp.flags.urg == 1` | Urgent Pointer significant | Данные phải быть обработаны немедленно |
| **ACK** | 4 | `[.]` | `tcp.flags.ack == 1` | Acknowledgment field significant | Все сегменты кроме первого SYN |
| **PSH** | 3 | `[P]` | `tcp.flags.push == 1` | Push Function | Приложение запросило немедленную доставку |
| **RST** | 2 | `[R]` | `tcp.flags.reset == 1` | Reset connection | Сброс соединения (ошибка, отказ) |
| **SYN** | 1 | `[S]` | `tcp.flags.syn == 1` | Synchronize sequence numbers | Установление соединения |
| **FIN** | 0 | `[F]` | `tcp.flags.fin == 1` | No more data from sender | Корректное закрытие соединения |

**Комбинации флагов в реальном трафике:**

| Комбинация | Нотация tcpdump | Описание |
| :--- | :--- | :--- |
| SYN | `[S]` | Первый шаг handshake |
| SYN-ACK | `[S.]` | Второй шаг handshake |
| ACK | `[.]` | Третий шаг handshake или обычный ACK |
| PSH-ACK | `[P.]` | Данные с запросом на доставку |
| FIN-ACK | `[F.]` | Запрос закрытия соединения |
| RST | `[R]` | Сброс (отказ в подключении) |
| RST-ACK | `[R.]` | Подтверждение сброса |
| SYN-ECE-CWR | `[S.EW]` | SYN с запросом ECN |

### Интерпретация полей в выводе tcpdump -v

```bash
sudo tcpdump -i eth0 -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | head -3
# → IP 1.1.1.1.54321 > 2.2.2.2.80: Flags [S], seq 1234567890,
#   win 65535, length 0, options [mss 1460,sackOK,TS val 3094567890 ecr 0,
#   nop,wscale 7], cksum 0x1234 (correct)
```

**Разбор полей:**

| Поле | Пример | Описание |
| :--- | :--- | :--- |
| `seq` | 1234567890 | Начальный номер последовательности (ISN) |
| `ack` | 1025 | Номер подтверждения (только в ACK/SYN-ACK/FIN-ACK) |
| `win` | 65535 | Размер окна приема (без масштабирования) |
| `length` | 0 | Размер payload (0 для SYN/FIN/ACK) |
| `cksum` | 0x1234 | Контрольная сумма |
| `options` | mss 1460,... | Согласованные опции |
| `urg` | 0 | Указатель срочности (обычно 0) |

### Полная таблица полей ss -ti

Вывод `ss` предоставляет данные напрямую из структуры `tcp_info` ядра Linux:

```bash
ss -ti dst 8.8.8.8
# → cubic rto:204 rtt:15.2/0.5 ato:40 mss:1460 pmtu:1500 rcvmss:1460
# → advmss:1460 cwnd:10 ssthresh:7 bytes_sent:1234 bytes_acked:1234
# → bytes_received:5678 segs_out:100 segs_in:80 data_segs_out:50
# → data_segs_in:40 send 7.6Mbps pacing_rate 15.2Mbps delivery_rate 7.6Mbps
# → busy:200ms retrans:0/0 rcv_rtt:15.2 rcv_space:14600
# → minrtt:12.1
```

**Полный справочник полей:**

| Поле | Единицы | Описание | На что влияет |
| :--- | :--- | :--- | :--- |
| `rto` | мс | Таймаут ретрансмиссии (Retransmission Timeout) | При потерях — задержка восстановления |
| `rtt` | мс | Сглаженный RTT (Round-Trip Time) | Основа для расчёта RTO |
| `rttvar` | мс | Стандартное отклонение RTT | Влияет на jitter и RTO |
| `ato` | мс | Acknowledgment Timeout | Когда отправлять ACK (Nagle) |
| `mss` | байт | Согласованный MSS (отправитель) | Макс. размер сегмента |
| `rcvmss` | байт | MSS получателя | Ограничивает remote MSS |
| `advmss` | байт | Объявленный MSS (рекомендованный) | Клиент отправляет этот MSS |
| `pmtu` | байт | Discover Path MTU | Ограничивает MSS |
| `cwnd` | MSS | Текущее окно перегрузки | Основной ограничитель throughput |
| `ssthresh` | MSS | Порог slow start | Граница slow start → congestion avoidance |
| `bytes_sent` | байт | Отправлено байт данных | Мониторинг прогресса |
| `bytes_acked` | байт | Подтверждено байт | ACK прогресс |
| `bytes_received` | байт | Получено байт | Throughput получателя |
| `segs_out` | сегменты | Отправлено сегментов | Включая ACK |
| `segs_in` | сегменты | Получено сегментов | Включая ACK |
| `data_segs_out` | сегменты | Отправлено сегментов с данными | Без ACK |
| `data_segs_in` | сегменты | Получено сегментов с данными | Без ACK |
| `send` | Mbit/s | Текущая скорость отправки | throughput = cwnd × MSS / RTT |
| `pacing_rate` | Mbit/s | Скорость pacing (ограничение) | BBR/CUBIC pacing |
| `delivery_rate` | Mbit/s | Оценка delivery rate | Ядро оценивает пропускную способность |
| `busy` | мс | Время активности соединения | Для длинных сессий |
| `retrans` | N/M | Ретрансмиссии: текущие/всего | 0/0 = нет потерь |
| `rcv_rtt` | мс | RTT получателя | Для оценки задержки |
| `rcv_space` | байт | Оценка пространства приема | Влияет на Window Scale |
| `minrtt` | мс | Минимальный RTT | Baseline для оценки queue delay |
| `wscale` | N,N | Множители окна (send, recv) | Макс. окно = win × 2^wscale |
| `ecn` | — | ECN согласован | Если отсутствует → ECN не поддерживается |
| `tod` | — | Type of Service / DSCP | Маркировка трафика |
| `lp` | мс | Lost Packets (loss rate) | Процент потерянных пакетов |
| `dctcp` | — | DCTCP (Data Center TCP) | Если отсутствует → CUBIC/Reno |
| `snd_wnd` | байт | Размер окна отправителя | Текущий advertised window |

---

## Практические сценарии

### Сценарий 1: Анализ handshake и согласования опций

Проверка согласования опций (MSS, SACK, WS, Timestamps, ECN) позволяет выявить причины низкой производительности на этапе установки соединения.

```bash
# Захват SYN-пакетов с опциями
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null
# → IP 1.1.1.1.54321 > 2.2.2.2.80: Flags [S], seq 1024, win 65535,
#   options [mss 1460,sackOK,TS val 123 ecr 0,nop,wscale 7], length 0
# → IP 2.2.2.2.80 > 1.1.1.1.54321: Flags [S.], seq 4096, ack 1025,
#   win 28960, options [mss 1460,sackOK,TS val 456 ecr 123,nop,wscale 7],
#   length 0
```

**Интерпретация результатов:**

| Параметр | Клиент → Сервер | Сервер → Клиент | Примечание |
| :--- | :--- | :--- | :--- |
| MSS | 1460 | 1460 | Согласовано: min(1460, 1460) = 1460 |
| WS | 7 (×128) | 7 (×128) | Макс. окно: 65535 × 128 = 8 МБ |
| SACK | OK | OK | SACK разрешен |
| TS | val=123 ecr=0 | val=456 ecr=123 | Timestamps согласованы |
| ECN | — | — | ECN не запрошен (нет ECE/CWR) |

**Проблемы и их признаки:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| WS отсутствует у одной из сторон | Ядро ≤ 2.6.8 или `tcp_window_scaling=0` | Включить sysctl |
| MSS = 536 | Опция MSS не согласована | Проверить NAT/firewall |
| Timestamps отсутствует | `tcp_timestamps=0` или peer не поддерживает | Включить (теряется PAWS + RTTM) |
| ECN не согласован | `tcp_ecn=0` или маршрутизатор не поддерживает | Включить `tcp_ecn=1` |

```bash
# Быстрая проверка через ss
ss -ti dst 8.8.8.8 | grep -E 'mss|wscale|ecn|ts'
# → mss:1460 wscale:7,7 ecn
```

### Сценарий 2: Диагностика ECN и микро-перегрузок

ECN (Explicit Congestion Notification) позволяет обнаруживать перегрузку без потерь пакетов.

```bash
# Проверка ECN в SYN-пакете
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | \
  head -5
# → Flags [S.EW], ...  ← ECE + CWR → ECN запрошен

# Проверка ECN через ss
ss -ti dst 8.8.8.8 | grep ecn
# → ecn (ECN согласован)

# Проверка ECN через nstat
nstat -az | grep -i ecn
# → TcpExtTCPAECEPktRcvd  5  ← CE-события (маршрутизатор пометил)
# → TcpExtTCPAECEReducedCwnd  3  ← CWR отправлен (cwnd снижен)

# Включение ECN
sudo sysctl -w net.ipv4.tcp_ecn=1

# Включение L4S (ECT(1) для микро-сигналов)
sudo sysctl -w net.ipv4.tcp_ecn=1
# L4S требует поддержки маршрутизатора (dualQ)
```

**Анализ CE-событий:**
```bash
# Мониторинг CE-событий в реальном времени
watch -n 1 'nstat -az | grep -i ecn'

# Поиск CE-помеченных пакетов через tcpdump
sudo tcpdump -i eth0 'ip[1] & 3 == 3' -nn
# → IP ... flags [E], ... ← ECT(1) с CE marking

# Проверка dualQ на маршрутизаторе
# Если CE-события частые → маршрутизатор поддерживает ECN
# Если CE нет → проверить настройки маршрутизатора
```

### Сценарий 3: Диагностика TSO/GRO и искажения размеров пакетов

При захвате трафика на отправляющем хосте пакеты могут выглядеть больше 64 КБ — это артефакт аппаратного оффлоадинга.

```bash
# Проверка состояния offloading
ethtool -k eth0 | grep -E 'segmentation|receive|generic-segmentation'
# → tcp-segmentation-offload: on
# → tcp-generic-segmentation-offload: on
# → tcp-generic-receive-offload: on

# Влияние на захват:
# TSO: ядро передает NIC блок до 64 КБ → NIC нарезает на MSS
# GRO: NIC объединяет сегменты → в дампе пакет > MSS
# Результат: tcpdump видит пакеты с length > 1460

# Временное отключение для «чистого» захвата
sudo ethtool -K eth0 tso off gro off gso off
# → Actual changes:
# → tso: off
# → gro: off
# → gso: off

# ... анализ ...

# Восстановление offloading
sudo ethtool -K eth0 tso on gro on gso on
```

**Таблица offloading-механизмов:**

| Механизм | Направление | Описание | Влияние на tcpdump |
| :--- | :--- | :--- | :--- |
| **TSO** | TX | NIC нарезает large segment на MSS | Пакеты > MSS в дампе |
| **GSO** | TX | Ядро нарезает до передачи NIC | Аналог TSO, программный |
| **GRO** | RX | NIC объединяет сегменты | Пакеты > MSS в дампе |
| **LRO** | RX | Устаревший GRO | Не использовать |
| **CSUM** | TX/RX | NIC вычисляет checksum | `bad cksum` в tcpdump (ложная тревога) |

```bash
# Проверка checksum offloading
sudo ethtool -k eth0 | grep checksum
# → rx-checksumming: on
# → tx-checksumming: on
# → tx-checksum-ipv4: on
# → rx-checksum-ipv4: on

# Если checksum offloading включен → bad cksum в tcpdump нормально
# Причина: tcpdump видит пакет ДО вычисления checksum NIC

# Для «чистого» захвата checksum
sudo ethtool -K eth0 tx off rx off
# ... анализ ...
sudo ethtool -K eth0 tx on rx on
```

### Сценарий 4: Диагностика Zero Window и проблем с приемом

Zero Window означает, что получатель не может принять данные — его buffer заполнен.

```bash
# Поиск Zero Window в дампе
sudo tcpdump -i any -nn 'tcp[14:2] = 0'
# → 12:10:05 IP 10.0.0.1.80 > 10.0.0.2.54321: Flags [.], ack 100, win 0

# Более детально —_Window Probe
sudo tcpdump -i any -nn -v 'tcp[14:2] = 0' | head -10

# Через tshark (pcap)
tshark -r capture.pcap -Y "tcp.analysis.zero_window" 2>/dev/null | head -5

# Wireshark-фильтры:
# tcp.window_size == 0                    — Zero Window
# tcp.analysis.zero_window                — обнаружен Zero Window
# tcp.analysis.zero_window_probe          — Persist Probe
# tcp.analysis.zero_window_probe_ack      — ответ на Persist Probe
# tcp.analysis.window_update              — обновление окна

# Проверка через nstat
nstat -az | grep -i "ZeroWindow\|win "
# → TcpExtTCPReceiveQueueFull  5  ← Zero Window situations
```

**Причины Zero Window:**

| Причина | Симптом | Решение |
| :--- | :--- | :--- |
| Медленное чтение приложением | Persistent Zero Window | Оптимизировать приложение |
| Малый buffer приложения | Частые Zero Window | Увеличить `SO_RCVBUF` |
| TCP window full | `tcp.analysis.window_full` | Увеличить `tcp_rmem` |
| Проблемы с disk I/O | Zero Window + high iowait | Диагностика I/O |
| Memory pressure | Частый Zero Window на сервере | Увеличить `net.ipv4.tcp_mem` |

```bash
# Проверка буферов
sysctl net.ipv4.tcp_rmem net.ipv4.tcp_wmem net.core.rmem_max net.core.wmem_max
# → net.ipv4.tcp_rmem = 4096 131072 6291456
# → net.ipv4.tcp_wmem = 4096 65536 4194304
# → net.core.rmem_max = 212992
# → net.core.wmem_max = 212992

# Увеличение буферов
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216
sudo sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"
sudo sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"
```

### Сценарий 5: Анализ через tshark (извлечение полей заголовка)

`tshark` — консольный аналог Wireshark, позволяет извлекать任意 поля заголовка.

```bash
# Извлечение всех ключевых полей заголовка
tshark -r capture.pcap -T fields \
  -e frame.number \
  -e ip.src -e ip.dst \
  -e tcp.srcport -e tcp.dstport \
  -e tcp.seq -e tcp.ack \
  -e tcp.len -e tcp.window_size_value \
  -e tcp.flags -e tcp.flags.str \
  -e tcp.options.mss -e tcp.options.wscale \
  -e tcp.options.sack -e tcp.options.ts_val \
  -e tcp.checksum -e tcp.urgent_pointer \
  2>/dev/null | head -20

# Анализ handshake (SYN + SYN-ACK + ACK)
tshark -r capture.pcap -Y "tcp.flags.syn==1" \
  -T fields -e ip.src -e ip.dst \
  -e tcp.srcport -e tcp.dstport \
  -e tcp.seq -e tcp.ack \
  -e tcp.options.mss -e tcp.options.wscale \
  -e tcp.options.sack -e tcp.options.ts_val \
  2>/dev/null

# Извлечение опций SYN через tshark
tshark -r capture.pcap -Y "tcp.flags.syn==1" \
  -T fields -e tcp.options.mss \
  -e tcp.options.wscale -e tcp.options.sack \
  -e tcp.options.ts_val 2>/dev/null | head -5

# Фильтрация по флагам
tshark -r capture.pcap -Y "tcp.flags.reset==1" 2>/dev/null   # RST
tshark -r capture.pcap -Y "tcp.flags.fin==1" 2>/dev/null     # FIN
tshark -r capture.pcap -Y "tcp.flags.push==1" 2>/dev/null    # PSH

# Анализ только данных (не ACK)
tshark -r capture.pcap -Y "tcp.len > 0" \
  -T fields -e frame.number -e tcp.seq -e tcp.len \
  2>/dev/null | head -20
```

**Полезные tshark-фильтры:**

| Фильтр | Описание |
| :--- | :--- |
| `tcp.flags.syn==1 && tcp.flags.ack==0` | Только SYN (не SYN-ACK) |
| `tcp.flags.syn==1 && tcp.flags.ack==1` | SYN-ACK |
| `tcp.flags.reset==1` | RST |
| `tcp.analysis.retransmission` | Ретрансмиссии |
| `tcp.analysis.duplicate_ack` | DupACK (3+ → Fast Retransmit) |
| `tcp.analysis.zero_window` | Zero Window |
| `tcp.analysis.out_of_order` | Out-of-Order пакеты |
| `tcp.analysis.window_full` | Окно заполнено |
| `tcp.options.mss` | Пакеты с MSS опцией |
| `tcp.options.ts_val > 0` | Пакеты с Timestamps |

### Сценарий 6: Анализ SACK и ретрансмиссий

SACK (Selective Acknowledgment) позволяет точно определить, какие блоки данных потеряны.

```bash
# Поиск пакетов с SACK Data (Kind=5, Data Offset > 8*4=32)
sudo tcpdump -i eth0 -nn 'tcp[12] & 0xf0 > 80' 2>/dev/null | head -5
# → 12:15:01 IP 10.0.0.1.80 > 10.0.0.2.54321: Flags [.],
#   ack 5000, win 65535, options [nop,nop,sack 1 {4500:5000}]

# Анализ SACK блоков через tshark
tshark -r capture.pcap -Y "tcp.analysis.sack" \
  -T fields -e tcp.sack.left_edge -e tcp.sack.right_edge \
  2>/dev/null | head -10
# → 4500 5000
# → 6000 7500

# Проверка D-SACK (Duplicate SACK)
nstat -az | grep -i dsack
# → TcpExtTCPSACKDSackRecv  3  ← D-SACK получены (подтверждает до-получение)
# → TcpExtTCPSACKDSackOld   1  ← D-SACK для старых данных

# Поиск ретрансмиссий
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-syn == 0' 2>/dev/null | \
  grep -E 'retransmit|Retransmission'

# Через tshark
tshark -r capture.pcap -Y "tcp.analysis.retransmission" 2>/dev/null | head -5

# Через nstat
nstat -az | grep -E 'TcpRetrans|TCPFastRetrans|TCPSlowStart'
# → TcpRetransSegs  50  ← всего ретрансмиссий
# → TcpExtTCPFastRetrans  30  ← Fast Retransmit (по DupACK)
# → TcpExtTCPSlowStartRetrans  20  ← после timeout
```

**Типы ретрансмиссий:**

| Тип | Механизм | Причина | Признак |
| :--- | :--- | :--- | :--- |
| **Fast Retransmit** | 3 DupACK | Потеря пакета (не перегрузка) | `tcp.analysis.duplicate_ack >= 3` |
| **Timeout Retransmit** | RTO истёк | Серьёзная потеря или задержка | `retrans: N/0` |
| **RACK-TLP** | Time-based | Современный алгоритм (RFC 8985) | `tcp.analysis.rack` |
| **Spurious Retransmit** | Ложная тревога | Задержка, а не потеря | `tcp.analysis.spurious_retransmission` |

### Сценарий 7: Анализ RST и аномалий соединения

RST (Reset) указывает на некорректное завершение соединения.

```bash
# Поиск RST-пакетов
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-rst != 0' 2>/dev/null | head -5
# → 12:20:01 IP 10.0.0.1.80 > 10.0.0.2.54321: Flags [R], seq 5000, win 0

# Анализ RST через tshark
tshark -r capture.pcap -Y "tcp.flags.reset==1" \
  -T fields -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport \
  -e tcp.seq -e tcp.ack 2>/dev/null | head -10

# Проверка RST-счетчиков
nstat -az | grep -i "Abort\|Reset"
# → TcpExtTCPAbortOnClose  5  ← active close (данные в queue)
# → TcpExtTCPAbortOnTimeout  3  ← RST из-за timeout
# → TcpExtTCPAbortOnLinger  2  ← linger timeout
# → TcpExtTCPAbortOnMemory  1  ← нехватка памяти
# → TcpExtTCPAbortOnlingerDelete  1  ← linger + delete
```

**Причины RST:**

| Причина | Описание | Как диагностировать |
| :--- | :--- | :--- |
| **Порт закрыт** | Сервис не слушает порт | `ss -tlnp | grep :PORT` |
| **Сервис упал** | Процесс завершился с данными в queue | `TcpExtTCPAbortOnClose` |
| **Timeout** | RTO истёк, нет ответа | `TcpExtTCPAbortOnTimeout` |
| **Память** | Нехватка socket/memory | `TcpExtTCPAbortOnMemory` |
| **Linger** | Close с linger timeout | `TcpExtTCPAbortOnLinger` |
| **Middlebox** | Firewall/NAT сбросил соединение | Проверить трассировку |
| **Simultaneous close** | Обе стороны отправили FIN | Редкий случай |
| **SYN to closed port** | Ответ на SYN к закрытому порту | `TcpExtTCPAbortOnTimeout` |

### Сценарий 8: Трассировка через eBPF (bcc-tools / bpftrace)

Инструменты eBPF позволяют увидеть *почему* ядро отбросило пакет или отправило RST — это невозможно с помощью `tcpdump`.

```bash
# === Трассировка состояний TCP ===
sudo tcpstates -tw
# → TIME     PID    COMM       IP SADDR:SPORT    > DADDR:DPORT    STATE
# → 12:15:01 1234   curl       4  10.0.0.1:54321 > 8.8.8.8:443    SYN_SENT
# → 12:15:01 1234   curl       4  10.0.0.1:54321 > 8.8.8.8:443    ESTABLISHED
# → 12:15:05 1234   curl       4  10.0.0.1:54321 > 8.8.8.8:443    CLOSE_WAIT

# === Трассировка ретрансмиссий ===
sudo tcpretrans
# → TIME     LADDR:LPORT          RADDR:RPORT          STATE
# → 12:15:01 192.168.1.10:54321   8.8.8.8:443          ESTABLISHED
# → 12:15:02 192.168.1.10:54321   8.8.8.8:443          ESTABLISHED

# === Трассировка падений пакетов ===
sudo tcpdrop
# → TIME     PID    COMM       IP SADDR:SPORT       > DADDR:DPORT   STATE
# → 12:15:03 0      swapper    4  10.0.0.2:80        > 10.0.0.1:54321 ESTABLISHED

# === Трассировка подключений ===
sudo tcpconnect -t
# → TIME     PID    COMM       IP SADDR:SPORT    > DADDR:DPORT
# → 12:15:04 1234   curl       4  10.0.0.1:54321 > 8.8.8.8:443

# === Трассировка accept ===
sudo tcpaccept -t
# → TIME     PID    COMM       IP LADDR:LPORT    > RADDR:RPORT
# → 12:15:05 5678   nginx      4  10.0.0.2:80    > 10.0.0.1:54321

# === Жизненный цикл соединения ===
sudo tcplife -t
# → TIME     PID    COMM       IP LADDR:LPORT    > RADDR:PORT  TX_KB  RX_KB  MS
# → 12:15:06 1234   curl       4  10.0.0.1:54321 > 8.8.8.8:443   12     45    2000

# === Убийство соединения ===
sudo tcpkill host 10.0.0.1 and port 80
# → Отправляет RST для новых соединений к 10.0.0.1:80
```

**Сравнение инструментов eBPF:**

| Инструмент | Что показывает | Когда использовать |
| :--- | :--- | :--- |
| `tcpstates` | Переходы состояний TCP | Поиск причин RST/FIN |
| `tcpretrans` | Ретрансмиссии с Seq/Ack | Диагностика потерь |
| `tcpdrop` | Причины отбрасывания пакетов | Поиск багов в стеке |
| `tcpconnect` | Исходящие подключения | Мониторинг клиентов |
| `tcpaccept` | Входящие подключения | Мониторинг серверов |
| `tcplife` | Жизненный цикл соединения | Статистика по соединениям |
| `tcpkill` | Принудительный сброс | Отладка, тестирование |

```bash
# bpftrace: кастомная трассировка
# Трассировка всех событий TCP для конкретного порта
sudo bpftrace -e 'kprobe:tcp_rcv_establishished {
  printf("%-16s %-6d %-16s %s\n",
    comm, pid, func, probe);
}'

# Трассировка времени в state SYN_SENT
sudo bpftrace -e '
kprobe:tcp_set_state /arg1 == 4/ {
  @start[tid] = nsecs;
}
kretprobe:tcp_set_state /@start[tid]/ {
  printf("SYN_SENT duration: %d ms\n", (nsecs - @start[tid]) / 1000000);
  delete(@start[tid]);
}'

# Мониторинг частоты retransmits
sudo bpftrace -e 'kprobe:tcp_retransmit_skb { @retransmits = count(); }'
```

### Сценарий 9: Визуальный анализ в Wireshark

Wireshark предоставляет графические инструменты для анализа, которые недоступны в CLI.

**Expert Information:**
- Меню `Analyze → Expert Information`
- **Warnings:** Bad TCP checksum, Zero Window, Retransmission
- **Errors:** Malformed packet, Invalid flags, Checksum error
- **Notes:** Window update, ACKed unseen segment

**TCP Stream Graphs:**
- Меню `Statistics → TCP Stream Graphs`
- **Time-Sequence (Stevens):** Визуализация Seq/Time — показывает ретрансмиссии, gaps, window updates
- **Time-Sequence (tcptrace):** Аналогичный, но с window size overlay
- **Throughput:** График throughput по времени
- **Window Scaling:** График window size по времени

**Conversation Statistics:**
- Меню `Statistics → Conversations → TCP`
- Показывает все TCP-сессии:_SRC → DST, packets, bytes, duration
- Позволяет быстро найти «тяжелые» соединения

**IO Graphs:**
- Меню `Statistics → I/O Graphs`
- Построение throughput, retransmissions, round-trip time по времени

**Фильтры Wireshark для анализа заголовка:**

| Фильтр | Описание |
| :--- | :--- |
| `tcp.analysis.checksum_status` | Статус проверки checksum |
| `tcp.analysis.flags` | Все аномалии флагов |
| `tcp.analysis.retransmission` | Ретрансмиссии |
| `tcp.analysis.duplicate_ack` | Дублирующие ACK |
| `tcp.analysis.out_of_order` | Пакеты не по порядку |
| `tcp.analysis.window_full` | Окно заполнено |
| `tcp.analysis.zero_window` | Zero Window |
| `tcp.analysis.fast_retransmission` | Fast Retransmit |
| `tcp.analysis.spurious_retransmission` | Ложная ретрансмиссия |
| `tcp.window_size == 0` | Zero Window |
| `tcp.options.mss` | Пакеты с MSS |
| `tcp.options.sack` | Пакеты с SACK |

### Сценарий 10: Анализ Throughput и производительности

```bash
# Расчет theoretical throughput
# throughput = min(cwnd, rwnd) × MSS / RTT
# При cwnd=10, MSS=1460, RTT=100ms:
# throughput = 10 × 1460 / 0.1 = 146000 B/s = 1.17 Mbps

# Мониторинг throughput через ss
watch -n 1 'ss -ti dst 8.8.8.8 | grep -E "send|delivery_rate|cwnd|rtt"'
# → send 7.6Mbps pacing_rate 15.2Mbps delivery_rate 7.6Mbps cwnd:10

# Мониторинг через nstat
nstat -az | grep -E 'TcpOutSegs|TcpRetransSegs|TcpExtTCPLoss'
# → TcpOutSegs  10000  ← всего отправлено сегментов
# → TcpRetransSegs  50  ← ретрансмиссии
# → loss_rate = 50/10000 = 0.5%

# Анализ throughput через iperf3
iperf3 -c 8.8.8.8 -t 10 -i 1
# → [ ID] Interval       Transfer     Bitrate
# → [  5] 0.00-1.00   sec  110 MBytes  924 Mbits/sec
```

**Факторы, ограничивающие throughput:**

| Фактор | Механизм | Как проверить |
| :--- | :--- | :--- |
| **cwnd** | Окно перегрузки | `ss -ti \| grep cwnd` |
| **rwnd** | Окно приема (receiver) | `ss -ti \| grep rcv_space` |
| **RTT** | ЗадержкаRound-Trip | `ss -ti \| grep rtt` |
| **Loss** | Потери пакетов | `nstat \| grep Retrans` |
| **MTU** | Ограничивает MSS | `ip link show \| grep mtu` |
| ** NIC** | Ограничение NIC | `ethtool eth0 \| grep Speed` |
| **CPU** | CPU bottleneck | `mpstat -P ALL 1` |
| **Memory** | Буферы сокетов | `sysctl net.ipv4.tcp_rmem` |

### Сценарий 11: Обнаружение Middlebox (NAT/Firewall)

Middlebox (NAT, firewall, load balancer) могут модифицировать или отбрасывать TCP-пакеты.

```bash
# Поиск аномалий checksum
nstat -az | grep -i csum
# → TcpExtTCPInCsumErrors  5  ← checksum ошибки

# Поиск неожиданных RST
sudo tcpdump -i any -nn 'tcp[tcpflags] & tcp-rst != 0' 2>/dev/null | head -10
# Если RST приходит от IP, отличного от целевого → middlebox

# Поиск сегментов с修改_seq
tshark -r capture.pcap -Y "tcp.analysis.invalid_ack" 2>/dev/null | head -5

# Проверка MSS clamping
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | \
  grep -o 'mss [0-9]*' | sort | uniq -c | sort -rn
# → 50 mss 1460
# → 10 mss 1380  ← MSS clamping на NAT

# Проверка TCP window scaling
ss -ti | grep wscale
# → wscale:7,7  ← если 0,0 → middlebox strip window scale
```

**Признаки middlebox:**

| Признак | Симптом | Диагностика |
| :--- | :--- | :--- |
| MSS clamping | MSS < MTU-40 | `tcpdump \| grep mss` |
| Window Scale stripped | wscale=0,0 | `ss -ti \| grep wscale` |
| Timestamps stripped | TS отсутствует | `tcpdump \| grep "TS val"` |
| SACK stripped | SACK не согласован | `tcpdump \| grep sackOK` |
| ECN stripped | ECE/CWR не в SYN | `tcpdump \| grep flags` |
| Checksum errors | `bad cksum` | `nstat \| grep csum` |
| Invalid RST | RST от чужого IP | `tcpdump \| grep R` |

### Сценарий 12: Работа с PCAP-файлами

```bash
# Запись дампа
sudo tcpdump -i eth0 -w /tmp/tcp.pcap tcp and host 10.0.0.1
# → Запись до Ctrl+C

# Запись с ограничением по размеру и времени
sudo tcpdump -i eth0 -w /tmp/tcp.pcap -C 100 -W 10 tcp and host 10.0.0.1
# → Файлы: tcp.pcap00, tcp.pcap01, ... tcp.pcap09
# → Макс. 10 файлов по 100 МБ (ротация)

# Чтение дампа
tcpdump -r /tmp/tcp.pcap -nn
tcpdump -r /tmp/tcp.pcap -nn 'tcp port 443'
tcpdump -r /tmp/tcp.pcap -nn -v 'tcp[tcpflags] & tcp-syn != 0'

# Извлечение опций через tshark
tshark -r /tmp/tcp.pcap -Y "tcp.flags.syn==1" \
  -T fields -e tcp.options.mss -e tcp.options.wscale 2>/dev/null

# Конвертация форматов
tshark -r input.pcap -w output.pcapng
editcap -F pcapng input.pcap output.pcapng

# Разбиение по соединениям
tcpdump -r input.pcap -w 'connection_%d.pcap' -C 10

# Статистика по дампу
capinfos /tmp/tcp.pcap
# → File name: /tmp/tcp.pcap
# → Number of packets: 1000
# → File size: 524288 bytes
# → First packet time: 2026-08-26 12:00:00
# → Last packet time: 2026-08-26 12:01:00

# Статистика по протоколам
tshark -r /tmp/tcp.pcap -q -z io,phs 2>/dev/null
# → Protocol Hierarchy Statistics
# → TCP  100.00%
```

---

## Диагностические команды (агрегированная секция)

### Быстрый обзор

```bash
# Краткая сводка по всем TCP-соединениям
ss -s
# → TCP:   150 (estab 120, closed 10, orphaned 5, timewait 10)

# Все established соединения с опциями
ss -tinH state established | head -20

# Конкретный хост
ss -ti dst 8.8.8.8
```

### Мониторинг заголовков

```bash
# Просмотр всех параметров TCP для соединения
ss -tin dst 10.0.0.1

# Просмотр Recv-Q / Send-Q (данные в буфере)
ss -tnp state established | awk '{print $1, $2, $3, $6}'

# Быстрая сводка по 연결ям
ss -s
```

### Глобальная статистика

```bash
# Счетчики ошибок (checksum, abnormal flags)
nstat -az | grep -E 'TcpExt(TCPAbortOn|TcpInCsumErrors|ListenOverflows|ListenDrops)'

# Счетчики ретрансмиссий
nstat -az | grep -E 'TcpRetransSegs|TcpExtTCPFastRetrans|TcpExtTCPTimeouts'

# SACK статистика
nstat -az | grep -i sack

# Timestamps статистика
nstat -az | grep -i timestamp

# ECN статистика
nstat -az | grep -i ecn

# PAWS статистика
nstat -az | grep -i paws
```

### Захват пакетов

```bash
# Весь TCP-трафик с деталями
sudo tcpdump -i any -nn -v tcp

# Конкретный хост/порт
sudo tcpdump -i eth0 -nn 'host 10.0.0.1 and port 443'

# Сохранение в pcap
sudo tcpdump -i eth0 -w /tmp/tcp.pcap tcp and host 10.0.0.1

# Извлечение опций через tshark
tshark -r /tmp/tcp.pcap -Y "tcp.flags.syn==1" \
  -T fields -e tcp.options.mss -e tcp.options.wscale
```

---

## Docker и Kubernetes

### Docker

```bash
# Проверка параметров в контейнере
docker exec <container> sysctl net.ipv4.tcp_congestion_control
docker exec <container> ss -ti dst 8.8.8.8

# Отключение TSO/GRO (если нужен «чистый» захват в контейнере)
docker exec <container> ethtool -K eth0 tso off gro off

# Просмотр offloading в контейнере
docker exec <container> ethtool -k eth0 | grep -E 'segmentation|checksum'

# Захват трафика из контейнера
docker exec <container> tcpdump -i eth0 -w /tmp/capture.pcap &
docker exec <container> curl http://example.com
docker cp <container>:/tmp/capture.pcap ./capture.pcap
```

### Kubernetes

```bash
# Захват трафика из пода
kubectl exec -it <pod> -- tcpdump -i eth0 -w /tmp/pod.pcap

# Просмотр tcp_info в поде
kubectl exec -it <pod> -- ss -ti dst 8.8.8.8

# DaemonSet для мониторинга TCP
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: tcp-header-diagnostics
  namespace: kube-system
spec:
  selector:
    matchLabels:
      name: tcp-header-diagnostics
  template:
    metadata:
      labels:
        name: tcp-header-diagnostics
    spec:
      hostPID: true
      containers:
      - name: diagnostics
        image: busybox
        command:
        - sh
        - -c
        - |
          echo "=== TCP Header Parameters ==="
          ss -tinH state established | head -20
          echo ""
          echo "=== Checksum Errors ==="
          nstat -az | grep -i csum
          echo ""
          echo "=== Window Scale Check ==="
          sysctl net.ipv4.tcp_window_scaling
          echo ""
          echo "=== ECN Status ==="
          sysctl net.ipv4.tcp_ecn
          echo ""
          echo "=== Retransmissions ==="
          nstat -az | grep -E 'TcpRetrans|TCPFastRetrans'
          sleep infinity
        securityContext:
          privileged: true
EOF
```

---

## Траблшутинг: типичные проблемы

### Проблема 1: Низкая скорость передачи

```bash
# Быстрая диагностика
ss -ti dst $HOST | grep -E 'cwnd|rtt|retrans|wscale|send'
# → send 1.2Mbps cwnd:2 rtt:150.0 retrans:0/5

# Анализ:
# - send 1.2Mbps → очень мало
# - cwnd:2 → окно перегрузки мало (slow start или loss)
# - rtt:150ms → высокая задержка
# - retrans:0/5 → было 5 потерь

# Решения:
# 1. Увеличить буферы: sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"
# 2. Включить ECN: sysctl -w net.ipv4.tcp_ecn=1
# 3. Сменить алгоритм: sysctl -w net.ipv4.tcp_congestion_control=bbr
```

### Проблема 2: Разрывы соединений

```bash
# Поиск RST
nstat -az | grep -i abort
# → TcpExtTCPAbortOnTimeout  10  ← timeout-based RST

# Проверка через tcpdump
sudo tcpdump -i any -nn 'tcp[tcpflags] & tcp-rst != 0' -c 10

# Проверка таймаутов
ss -ti | grep rto
# → rto:3000  ← очень высокий RTO (3 сек)
```

### Проблема 3: Высокий RTT

```bash
# Проверка RTT
ss -ti dst $HOST | grep rtt
# → rtt:200.0/50.0  ← RTT 200ms, отклонение 50ms

# Анализ: задержка может быть в:
# 1. Сети (physically far)
# 2. Маршрутизаторе (queue)
# 3. Приложении (slow processing)
# 4. TCP stack (delayed ACK)

# Проверка через ping
ping -c 10 $HOST
# → rtt min/avg/max/mdev = 150.0/200.0/300.0/50.0 ms

# Проверка через mtr
mtr -r -c 10 $HOST
```

### Проблема 4: Потери пакетов

```bash
# Проверка потерь
nstat -az | grep -E 'TcpRetrans|Loss'
# → TcpRetransSegs  100  ← ретрансмиссии
# → TcpExtTCPLostRetransmit  20  ← потеря ретрансмиссий

# Проверка через ss
ss -ti | grep retrans
# → retrans:5/100  ← 5 текущих, 100 всего

# Анализ через tcpretrans
sudo tcpretrans
# → Показывает конкретные соединения с потерями
```

---

## Дополнительная информация

### См. также

- **[Формат заголовка TCP](./index.md)** — описание структуры полей.
- **[Опции TCP](./options.md)** — детали работы MSS, SACK и Timestamps.
- **[tcpdump в Linux](../../../../Linux/Diagnostics/Networking/tcpdump.md)** — полный справочник по утилите.
- **[Надежность TCP](../reliability_mechanisms/concepts.md)** — Seq/Ack, Checksum.
- **[Управление потоком](../Flow_Control/index.md)** — Window Size, Flow Control.

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (2022).
- **RFC 7323:** TCP Extensions for High Performance (Window Scale, Timestamps, PAWS).
- **RFC 3168:** The Addition of Explicit Congestion Notification (ECN) to IP.
- **RFC 2018/6675:** TCP Selective Acknowledgment Options.
- **RFC 2883:** D-SACK Extension.
- **RFC 8985:** RACK-TLP — time-based loss detection.
- **RFC 7413:** TCP Fast Open (TFO).
