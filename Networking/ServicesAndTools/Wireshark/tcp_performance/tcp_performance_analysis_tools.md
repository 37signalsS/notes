# Графики Wireshark для анализа TCP

> **SSoT:** Определения базовых терминов (RTT, iRTT, Window Size, Expert Info) — в **[Определения](../definitions.md)**. Концепции захвата и offloading — в **[Основные концепции](../core_concepts.md)**. tshark-команды — в **[Использование tshark](../tshark_usage.md)**. Обзор диагностики — в **[Обзор диагностики](./tcp_performance_diagnostics.md)**. Клиентские проблемы — в **[Клиентские проблемы](./tcp_client_performance_issues.md)**. Серверные проблемы — в **[Серверные проблемы](./tcp_server_performance_issues.md)**. Потери и offloading — в **[Сетевые потери](./tcp_network_losses_and_offloading.md)**.

## Определения

> Определения базовых терминов (RTT, iRTT, Window Size) — в **[Определения](../definitions.md)**. Ниже — термины, специфичные для графиков и визуализации.

**Графики TCP-потока (TCP Stream Graphs)** — специализированный набор инструментов визуализации в Wireshark, позволяющий анализировать поведение конкретного сетевого соединения (последовательность сегментов, задержки, скорость и размер окна).

**Графики ввода-вывода (IO Graphs)** — универсальный инструмент для построения графиков интенсивности трафика по всему дампу или по конкретным фильтрам. Позволяет накладывать несколько метрик друг на друга для корреляционного анализа.

**tcptrace (Time-Sequence Graph)** — расширенный вид временной диаграммы, который отображает не только номера последовательности (Sequence Numbers), но и анонсированное окно получателя (Receive Window), а также SACK-блоки (выделяются серыми зонами).

**Stevens Graph** — упрощенная версия временной диаграммы, отображающая только Sequence Numbers без визуализации окна. Используется для базового анализа монотонности передачи.

**Path Ratio (Коэффициент маршрута)** — отношение `${ratio:0%.2r}` между Throughput и BDP. Если Ratio < 1.0, соединение не загружает канал (недогрузка). Если Ratio ≈ 1.0, канал загружен оптимально. Если Ratio > 1.0 с потерями — перегрузка. См. также: [Обзор диагностики](./tcp_performance_diagnostics.md).

**Micro-bursts (Микро-всплески)** — кратковременные (10-100 мкс) всплески трафика, которые переполняют буферы коммутаторов. При средней скорости ниже пропускной способности микро-всплески могут вызывать потери, которые не видны при усреднении в 1 секунду.

**Pacing Rate (Скорость отправки)** — целевая скорость, с которой ядро отправляет данные, определяемая алгоритмом конгестии (BBR/CUBIC). BBR использует стабильный pacing, CUBIC — пачками (bursty).

## Quick-Start: Какой график выбрать?

Быстрый выбор инструмента визуализации:

| Симптом | Инструмент | Фильтр | На что смотреть |
| :--- | :--- | :--- | :--- |
| Низкая скорость, нет потерь | tcptrace | `tcp.stream eq N` | Sequence упирается в Window |
| Много Retransmissions | IO Graphs | `tcp.analysis.retransmission` | Пики совпадают с падением Throughput |
| Задержки 40-200 мс | tcptrace | `tcp.analysis.delayed_ack` | Горизонтальные линии Seq |
| Zero Window | Window Scaling | `tcp.analysis.zero_window` | Окно падает до 0 |
| Высокий RTT | IO Graphs | `AVG(tcp.analysis.ack_rtt)` | RTT растет с нагрузкой (Bufferbloat) |
| Micro-bursts | IO Graphs (1 мкс) | `tcp` | Пики >> средней скорости |
| BBR vs CUBIC | IO Graphs | `AVG(tcp.time_delta)` | BBR: ровно, CUBIC: пила |

## Основные концепции

### Виды графиков TCP Stream Graphs

Доступны через меню: `Statistics → TCP Stream Graphs`. Требуют выбора пакета из целевого потока.

| График | Назначение | Особенности (Wireshark 4.x) |
| :--- | :--- | :--- |
| **Time-Sequence (tcptrace)** | Анализ Seq, ACK и Window. | Показывает «потолок» окна; идеален для поиска `Window Full` и SACK-эффективности. |
| **Throughput** | Мгновенная скорость. | Поддержка скользящего среднего (MA). Позволяет видеть «провалы» при потерях. |
| **Round Trip Time (RTT)** | Задержка подтверждений. | Визуализация джиттера. Важно: RTT считается только для пакетов с данными, а не для чистых ACK. |
| **Window Scaling** | Динамика буфера получателя. | Отображает анонсированное окно (`rwnd`). Падение графика к 0 означает `Zero Window`. |

### Продвинутые возможности IO Graphs

Инструмент `Statistics → IO Graphs` позволяет анализировать не только объем, но и статистические параметры полей.

- **Интервалы (Tick interval):** В Wireshark 4.4+ поддерживаются интервалы до **1 микросекунды**, что критично для выявления микро-всплесков (Micro-bursts), вызывающих переполнение буферов на ASIC коммутаторов.
- **Расширенные функции (Y-axis):**
  - `AVG(tcp.analysis.ack_rtt)` — среднее время подтверждения в динамике.
  - `MAX(tcp.time_delta)` — поиск максимальных пауз между пакетами.
  - `SUM(tcp.len)` — суммарный объем полезной нагрузки (Goodput).
  - `COUNT(frame.number)` — интенсивность пакетов (для поиска burst-паттернов).
- **Сглаживание (SMA/EMA):** Использование простых и экспоненциальных скользящих средних для подавления шума в высокочастотном трафике.

### Выбор правильного графика

Методология выбора инструмента:

1. **Быстрый обзор потока** — Откройте `Statistics → Conversations → TCP`. Найдите соединение с проблемой. Кликните правой кнопкой → `Follow → TCP Stream`.
2. **Определите симптом:**
   - **Низкая скорость** → `Throughput` или `tcptrace` (проверьте, не ограничен ли Window)
   - **Задержки** → `RTT` (проверьте, не растет ли RTT)
   - **Потери** → `IO Graphs` с фильтром `tcp.analysis.retransmission`
3. **Корреляция** → Наложите два графика в `IO Graphs` (например, Throughput + Retransmissions)

### Эквиваленты GUI-графиков в tshark

Для удаленного анализа или автоматизации используйте CLI-аналоги:

| GUI-инструмент | tshark-аналог | Команда |
| :--- | :--- | :--- |
| IO Graphs (Bits/s) | `io,stat` | `tshark -r cap.pcap -q -z io,stat,1,SUM(tcp.len)*8` |
| TCP Stream Graphs | tshark не поддерживает | Только через GUI Wireshark |
| Conversations | `conv,tcp` | `tshark -r cap.pcap -q -z conv,tcp` |
| Endpoints | `endpoints,tcp` | `tshark -r cap.pcap -q -z endpoints,tcp` |
| Expert Info | `expert` | `tshark -r cap.pcap -q -z expert` |
| Protocol Hierarchy | `io,phs` | `tshark -r cap.pcap -q -z io,phs` |

**Важно:** tshark не имеет прямого аналога TCP Stream Graphs. Для визуализации Sequence Numbers, Window Scaling и SACK-блоков используйте GUI Wireshark или сторонние инструменты ( chẳng hạn как `tcpflow`, `tcptrace`).

## Практические сценарии

### Сценарий 1: Диагностика ограничения скоростью окна (Window Limited)

Если скорость низкая, а потерь нет:
1.  Откройте `Statistics → TCP Stream Graphs → Time-Sequence (tcptrace)`.
2.  **Анализ:** Если линия Sequence Numbers (отправленные данные) постоянно упирается в верхнюю линию Advertised Window — отправитель ограничен буфером получателя (`RWND`).
3.  **Решение:** Увеличение `tcp_rmem` в Linux или переход на асинхронное чтение (io_uring) в приложении-клиенте.

**tshark-команда для быстрой проверки:**
```bash
# Проверка Window Full и Zero Window
tshark -r capture.pcap -Y "tcp.analysis.window_full || tcp.analysis.zero_window" \
  -T fields -e frame.number -e tcp.stream -e ip.src -e tcp.srcport \
  -e tcp.analysis.window_full -e tcp.analysis.zero_window
```

### Сценарий 2: Корреляция потерь и скорости через IO Graphs

Для доказательства того, что «сеть тормозит»:
1.  Откройте `Statistics → IO Graphs`.
2.  Настройте два графика:
    - График 1 (черный): `all packets`, Y-axis: `Bits/s`.
    - График 2 (красный): `tcp.analysis.retransmission`, Y-axis: `Packets`.
3.  **Анализ:** Если каждый всплеск красного графика (потери) сопровождается резким падением черного (Throughput) — причина в работе алгоритмов Congestion Control (CUBIC/Reno), которые снижают окно при потерях.

**CLI-эквивалент:**
```bash
# Статистика по секундам: Throughput vs Retransmissions
tshark -r capture.pcap -q -z "io,stat,1,SUM(tcp.len)*8,COUNT(tcp.analysis.retransmission)tcp.analysis.retransmission"
```

### Сценарий 3: Анализ микро-всплесков (Micro-bursts)

При «загадочных» потерях на высокоскоростных интерфейсах (10G/40G/100G):
1.  В IO Graphs установите `Tick interval` в `100 us` или `10 us`.
2.  **Анализ:** Ищите резкие пики (Spikes), превышающие среднюю скорость в 5-10 раз.
3.  **Причина:** Такие всплески мгновенно переполняют микро-буферы коммутаторов (Buffer exhaustion), вызывая дропы, которые не видны при усреднении в 1 секунду.

**CLI-эквивалент:**
```bash
# Статистика с микроинтервалом (100 мкс)
tshark -r capture.pcap -q -z "io,stat,0.0001,SUM(tcp.len)*8"

# Поиск пиков > 10 Мбит/с в интервале 1 мс
tshark -r capture.pcap -q -z "io,stat,0.001,SUM(tcp.len)*8" | awk '$3 > 10000000'
```

### Сценарий 4: Дифференциация BBR Pacing и CUBIC Bursts

Для понимания работы алгоритмов перегрузки в 2026 году:
1.  В IO Graphs создайте график с функцией `AVG(tcp.time_delta)`.
2.  **BBR:** График будет стабильным и ровным, так как BBR использует **Pacing** (равномерную отправку).
3.  **CUBIC:** Вы увидите «пилу» — резкие провалы `delta` (пачка пакетов уходит мгновенно) и последующие паузы до прихода ACK.
4.  **Зачем это нужно:** Pacing снижает вероятность микро-всплесков и переполнения очередей в сети.

**CLI-эквивалент:**
```bash
# Среднее время между пакетами (pacing)
tshark -r capture.pcap -Y "tcp.len > 0 && tcp.stream eq 0" -T fields \
  -e tcp.time_delta | awk '{sum+=$1; count++} END {print "AVG delta:", sum/count, "sec"}'

# Сравнение через ss (в реальном времени)
ss -tin dst 10.0.0.1 | grep -E "cwnd|pacing_rate|rtt"
```

### Сценарий 5: Анализ эффективности SACK

При потерях на каналах с высоким BDP:
1.  Откройте `tcptrace`. Изучите серые прямоугольные области (SACK-блоки).
2.  **Анализ:** Если внутри серой зоны видны белые пятна (пропущенные сегменты) и при этом отправитель шлет новые данные вместо переотправки потерянных — SACK работает неэффективно или игнорируется.
3.  **Решение:** Проверка настроек `net.ipv4.tcp_sack` и `net.ipv4.tcp_dsack` на обоих концах.

**CLI-эквивалент:**
```bash
# Проверка SACK блоков
tshark -r capture.pcap -Y "tcp.options.sack" -T fields \
  -e frame.number -e tcp.stream -e tcp.options.sack

# Проверка настроек SACK в Linux
sysctl net.ipv4.tcp_sack net.ipv4.tcp_dsack
# → net.ipv4.tcp_sack = 1
# → net.ipv4.tcp_dsack = 1
```

### Сценарий 6: Анализ Path Ratio (BDP vs Throughput)

Path Ratio показывает, насколько эффективно соединение загружает канал:

```bash
# 1. Найдите средний Throughput
tshark -r capture.pcap -q -z "io,stat,1,AVG(tcp.len)*8"
# → Средний Throughput: X бит/с

# 2. Найдите средний RTT
tshark -r capture.pcap -Y "tcp.analysis.initial_rtt" -T fields \
  -e tcp.analysis.initial_rtt | head -1
# → iRTT: Y сек

# 3. Рассчитайте BDP
# BDP = Throughput × RTT
# Если BDP = 1 Гбит/с × 10 мс = 1.25 МБ
# Throughput = 500 Мбит/с → Path Ratio = 0.5 (недогрузка)
```

**Интерпретация:**
- Ratio < 0.5 → Критическая недогрузка (проблема с приложением)
- Ratio 0.5-0.8 → Частичная недогрузка (окно слишком мало)
- Ratio 0.8-1.0 → Оптимальная загрузка
- Ratio > 1.0 → Перегрузка (потери в сети)

### Сценарий 7: Диагностика Zero Window через Window Scaling

```bash
# tshark: Zero Window events
tshark -r capture.pcap -Y "tcp.analysis.zero_window" -T fields \
  -e frame.number -e tcp.stream -e ip.src -e tcp.srcport \
  -e frame.time_relative

# tshark: Window Full (окно заполнено, но не закрыто)
tshark -r capture.pcap -Y "tcp.analysis.window_full" -T fields \
  -e frame.number -e tcp.stream -e ip.src -e tcp.srcport \
  -e tcp.window_size_value

# В Wireshark: Statistics → TCP Stream Graphs → Window Scaling
# → Линия окна падает до 0 = Zero Window
# → Линия окна приближается к Bytes in Flight = Window Full
```

### Сценарий 8: RTT vs Throughput (поиск Bufferbloat)

Bufferbloat — раздувание задержек при высокой нагрузке:

```bash
# IO Graphs: RTT и Throughput одновременно
# График 1: tcp, Y-axis: Bits/s
# График 2: tcp.analysis.ack_rtt, Y-axis: AVG (нормализовать)

# tshark: RTT в динамике
tshark -r capture.pcap -Y "tcp.len > 0" -T fields \
  -e frame.time_relative -e tcp.analysis.ack_rtt | head -50

# При Bufferbloat:
# → Throughput растет → RTT пропорционально растет
# → Причина: oversized buffers в промежуточном оборудовании
# → Решение: SQM (Smart Queue Management), fq_codel, CAKE
```

### Сценарий 9: Экспорт данных для отчетов

```bash
# Экспорт IO Graphs данных в CSV
tshark -r capture.pcap -q -z "io,stat,1,SUM(tcp.len)*8,COUNT(frame)frame" \
  -T fields -e frame.time_relative -e tcp.len > io_graph_data.csv

# Экспорт Conversation Statistics
tshark -r capture.pcap -q -z "conv,tcp" -T fields \
  -e conv.tcp.addr_a -e conv.tcp.addr_b -e conv.tcp.bytes_a2b > conversations.csv

# Генерация графика через gnuplot (пример)
# set terminal png; set output 'throughput.png';
# plot 'io_graph_data.csv' using 1:2 with lines title 'Throughput'
```

## Таблица проблем

| Проблема | Симптом на графике | Инструмент | Фильтр | Решение |
| :--- | :--- | :--- | :--- | :--- |
| **Window Limited** | Seq упирается в Window | tcptrace | `tcp.stream eq N` | Увеличить `tcp_rmem` |
| **Window Full/Zero** | Окно падает к 0 | Window Scaling | `tcp.analysis.zero_window` | Оптимизировать приложение |
| **Retransmissions** | Пики на IO Graphs | IO Graphs | `tcp.analysis.retransmission` | Проверить сеть |
| **Bufferbloat** | RTT растет с Throughput | RTT Graph | `AVG(tcp.analysis.ack_rtt)` | SQM/fq_codel |
| **Micro-bursts** | Пики в 5-10× среднего | IO Graphs (1 мкс) | `tcp` | Буферы коммутатора |
| **Nagle + Delayed ACK** | Горизонтальные линии Seq | tcptrace | `tcp.analysis.delayed_ack` | `TCP_NODELAY` |
| **CFS Throttling** | Задержки ~100 мс | IO Graphs | `tcp.time_delta > 0.09` | Увеличить CPU limits |
| **GC Pause** | Провалы до 0 | IO Graphs (10 мс) | `SUM(tcp.len)tcp.len` | Оптимизировать GC |
| **Path Ratio < 0.5** | Throughput << BDP | IO Graphs | `SUM(tcp.len)*8` | Увеличить окно |

## Дополнительная информация

### Настройка осей и экспорт данных

- **Y-axis (Calculated):** Используйте `COUNT(frame.number)` для анализа интенсивности запросов или `SUM(tcp.len)` для Goodput.
- **Инструмент "Zoom":** В TCP Stream Graphs используйте левую кнопку мыши для выделения области и правую для сброса масштаба.
- **Экспорт для отчетов:**
  - `File → Export` сохраняет график как PNG/PDF.
  - `Copy` позволяет вставить данные в Excel/Google Sheets для дальнейшего мат-анализа.

### Диагностические команды ОС

| Команда | Что проверяет | Норма |
| :--- | :--- | :--- |
| `ss -tin \| grep rwnd` | Receive Window | > 64 КБ |
| `ss -tin \| grep snd_space` | Send Window | Растет |
| `sysctl net.ipv4.tcp_rmem` | Receive buffer limits | max > 4 МБ |
| `sysctl net.ipv4.tcp_wmem` | Send buffer limits | max > 4 МБ |
| `sysctl net.ipv4.tcp_congestion_control` | Алгоритм конгестии | bbr |
| `nstat -az TcpExtTCPWindowFull` | Window Full events | 0 |
| `nstat -az TcpExtTCPTimeouts` | RTO таймауты | < 1% |

### См. также

- **[Определения Wireshark](../definitions.md)** — базовые термины (RTT, iRTT, Window Size).
- **[Основные концепции захвата](../core_concepts.md)** — offloading, ring buffer, AF_PACKET.
- **[Использование tshark](../tshark_usage.md)** — CLI-команды для анализа TCP.
- **[Обзор диагностики производительности](./tcp_performance_diagnostics.md)** — методология и ключевые метрики.
- **[Проблемы клиента](./tcp_client_performance_issues.md)** — Zero Window, Window Full, backpressure.
- **[Проблемы сервера](./tcp_server_performance_issues.md)** — TTFB, CFS, GC, Nagle.
- **[Сетевые потери и offloading](./tcp_network_losses_and_offloading.md)** — влияние инфраструктуры.
