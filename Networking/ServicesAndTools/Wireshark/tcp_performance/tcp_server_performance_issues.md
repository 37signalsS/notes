# Диагностика проблем производительности сервера TCP

> **SSoT:** Определения базовых терминов (RTT, iRTT, Window Size, Expert Info) — в **[Определения](../definitions.md)**. Концепции захвата и offloading — в **[Основные концепции](../core_concepts.md)**. tshark-команды — в **[Использование tshark](../tshark_usage.md)**. Обзор диагностики — в **[Обзор диагностики](./tcp_performance_diagnostics.md)**. Клиентские проблемы — в **[Клиентские проблемы](./tcp_client_performance_issues.md)**. Потери и offloading — в **[Сетевые потери](./tcp_network_losses_and_offloading.md)**. Графики — в **[Инструменты анализа](./tcp_performance_analysis_tools.md)**. Алгоритм Нагла — в **[Nagle Algorithm](../../Protocols/TCP/tcp_nagle_algorithm.md)**. Тюнинг — в **[TCP Tuning](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)**.

## Определения

> Определения базовых терминов (RTT, iRTT, Window Size) — в **[Определения](../definitions.md)**. Ниже — специфичные для серверных проблем термины.

**Задержка на стороне сервера (Server-Side Latency)** — временные интервалы между отправкой последовательных порций данных сервером при условии, что клиент подтверждает получение практически мгновенно (низкий RTT).

**Троттлинг ресурсов (Resource Throttling)** — принудительное ограничение скорости обработки данных из-за достижения лимитов по CPU (CFS Quota) или квот ввода-вывода (IOPS/Bandwidth) в облачных и контейнеризованных средах.

**iRTT (Initial Round-Trip Time)** — базовое время кругового обхода, измеренное на этапе 3-way handshake. Используется как эталон для оценки последующих задержек в сессии.

**Хвостовая задержка (Tail Latency)** — аномально высокая задержка для небольшого процента пакетов (p99), часто вызванная сработкой тайм-аутов или блокировками IO.

**Sending Slow (Замедление отправки)** — паттерн, при котором сервер отправляет данные с задержками, значительно превышающими RTT, при условии что клиент активно подтверждает получение. Указывает на проблемы на стороне сервера (приложение, ОС или сеть).

**Auto-corking** — механизм ядра Linux (TCP automatic corking), который автоматически объединяет мелкие сегменты для повышения эффективности. Может вызывать задержки до 40 мс для интерактивных приложений.

## Quick-Start: Чек-лист диагностики серверных проблем

Быстрый старт при подозрении на проблемы на стороне сервера:

| Шаг | Действие | Как проверить | Норма |
| :--- | :--- | :--- | :--- |
| **1** | TTFB vs iRTT | `tcp.analysis.initial_rtt` | TTFB < 10 × iRTT |
| **2** | Ретрансмиссии | `tcp.analysis.retransmission` | < 0.1% от всех пакетов |
| **3** | Nagle + Delayed ACK | `tcp.analysis.delayed_ack` + `tcp.len < MSS` | 0 конфликтов |
| **4** | CFS Throttling | `frame.time_delta_displayed` ~ 0.1s | 0 паттернов |
| **5** | Конгестия | `tcp.analysis.bytes_in_flight` vs CWND | BBE, нет «столбов» |
| **6** | autotuning (send) | `ss -tin \| grep snd_space` | snd_space растет |
| **7** | Offloading | `frame.len > 1514` (не TSO) | 0 ложных |

## Основные концепции

### Признаки замедления работы сервера

Когда сервер становится «бутылочным горлышком», в трафике наблюдаются специфические паттерны:

1. **Delta Time > iRTT**: Интервал между запросом клиента и первым байтом ответа (TTFB) значительно превышает время установки соединения.
2. **Быстрые ACK**: Клиент отправляет подтверждения немедленно (микросекунды), что исключает сетевые задержки или проблемы на стороне клиента.
3. **Горизонтальные линии на Stevens Graph**: Длительные периоды отсутствия передачи данных (Silent periods) при наличии запросов.

### Типичные причины в современных средах

- **CFS Throttling (Kubernetes)**: Если лимит CPU установлен слишком жестко, ядро Linux приостанавливает выполнение потоков приложения внутри периода (обычно 100 мс). В Wireshark это выглядит как задержки кратностью 100 мс.
- **Garbage Collection (GC)**: Паузы «Stop-the-world» полностью останавливают сетевую активность приложения.
- **Ожидание внешних ресурсов**: Блокирующие вызовы к БД, кэшу или внешним API.
- **IO Wait**: Насыщение дисковой подсистемы или сетевого интерфейса хоста.

### Конфликт Nagle + Delayed ACK

Наиболее частая причина серверных задержек для интерактивных приложений. Конфликт возникает между отправителем (сервер) и получателем (клиент):

1. Сервер отправляет мелкий сегмент (< MSS). Алгоритм **Nagle** буферизует данные до получения ACK на предыдущий сегмент.
2. Клиент использует **Delayed ACK** — откладывает отправку ACK на 40-200 мс в надежде «приклеить» его к данным.
3. Результат: задержка ровно на время таймера Delayed ACK (обычно 40 мс).

**Как выглядит в Wireshark:**
- Пауза 40 мс между отправкой данных и следующим сегментом
- `tcp.analysis.delayed_ack` в Expert Info
- Маленькие сегменты (`tcp.len < MSS`) с задержкой кратной 40 мс

**Решение:** `TCP_NODELAY` на сервере:
```bash
# В коде приложения
setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
```

См. подробный разбор: [Алгоритм Нагла](../../Protocols/TCP/tcp_nagle_algorithm.md).

### Автотюнинг буфера отправки (send_buffer)

Ядро Linux автоматически управляет размером буфера отправки (`SO_SNDBUF`) на основе наблюдаемого BDP (Bandwidth-Delay Product). Механизм работает через `tcp_wmem`:

```bash
# Проверка автотюнинга
sysctl net.ipv4.tcp_wmem
# → net.ipv4.tcp_wmem = 4096 16384 4194304  (min, default, max)

# Проверка через ss для конкретного соединения
ss -tin dst 10.0.0.1 | grep snd_space
# → snd_space:16384 snd_ssthresh:4194304  ← текущий размер и порог
```

**Типичные проблемы:**
- `snd_space` не растет → автотюнинг отключен или `tcp_wmem` max слишком мал
- `SO_SNDBUF` зафиксирован в коде → ядро не может адаптировать размер
- `tcp_adv_win_scale` снижает доступный размер данных (аналогично приемному буферу)

**Решение:**
```bash
# Увеличение лимитов
sudo sysctl -w net.ipv4.tcp_wmem='4096 65536 67108864'
sudo sysctl -w net.core.wmem_max=67108864

# Включение автотюнинга (по умолчанию включен)
sudo sysctl -w net.ipv4.tcp_moderate_rcvbuf=1
```

### Pacing и Congestion Control (BBR/CUBIC)

Алгоритм конгестии определяет, как сервер контролирует скорость отправки:

| Алгоритм | Поведение | Задержка | Когда использовать |
| :--- | :--- | :--- | :--- |
| **CUBIC** (по умолчанию) | Агрессивный рост CWND, реагирует на потери | Выше при потерях | Общее назначение |
| **BBR** | ModelBased, игнорирует потери, оптимизирует BDP | Нижняя | LFN, CDN, video streaming |
| **RENO** | Линейный рост, реагирует на потери | Высокая | Только для совместимости |

**Как проверить текущий алгоритм:**
```bash
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr

# Доступные алгоритмы
sysctl net.ipv4.tcp_available_congestion_control
# → net.ipv4.tcp_available_congestion_control = reno cubic bbr

# Установка BBR
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr
```

**Как выглядит в Wireshark:**
- **CUBIC:** CWND растет экспоненциально, затем полиномиально. При потерях — резкое снижение.
- **BBR:** CWND стабилен, pacing rate меняется плавно. Меньше jitter, меньше потерь.

### SO_BUSY_POLL — снижение задержки за счет активного опроса NIC

По умолчанию ядро обрабатывает входящие пакеты по прерыванию (IRQ). Это добавляет задержку 50-200 мкс из-за времени пробуждения CPU. `SO_BUSY_POLL` позволяет приложению активно опрашивать NIC:

```bash
# Включение busy polling (в микросекундах)
sudo sysctl -w net.core.busy_poll=50
sudo sysctl -w net.core.busy_read=50

# В коде приложения
setsockopt(fd, SOL_SOCKET, SO_BUSY_POLL, &timeout, sizeof(timeout));
```

**Когда использовать:** Latency-критичные сервисы (trading, gaming, real-time). Не рекомендуется для bulk-передач — увеличивает потребление CPU.

## Практические сценарии

### Сценарий 1: Анализ TTFB и iRTT

TTFB (Time To First Byte) — ключевая метрика серверной производительности.

```bash
# tshark: iRTT (время SYN → SYN-ACK)
tshark -r capture.pcap -Y "tcp.flags.syn == 1 && tcp.flags.ack == 1" \
  -T fields -e tcp.stream -e tcp.analysis.initial_rtt

# tshark: все соединения с TTFB > 1с
tshark -r capture.pcap -Y "tcp.analysis.initial_rtt > 1.0" \
  -T fields -e tcp.stream -e tcp.analysis.initial_rtt -e ip.dst

# tshark: TTFB vs iRTT для конкретного потока
tshark -r capture.pcap -Y "tcp.stream eq 0" -T fields \
  -e frame.number -e tcp.analysis.initial_rtt -e tcp.time_delta | head -20
```

**Интерпретация:**
- `TTFB < 5 × iRTT` → норма
- `TTFB > 10 × iRTT` → проблема на сервере (приложение или ОС)
- `TTFB > 100 × iRTT` → критическая проблема (GC, deadlock, зависание)

### Сценарий 2: Поиск паттернов троттлинга (CFS)

CFS Throttling в Kubernetes выглядит как задержки кратные 100 мс:

```bash
# tshark: задержки кратные 100 мс (CFS) от сервера
tshark -r capture.pcap -Y "ip.src == <SERVER_IP> && tcp.len > 0" \
  -T fields -e frame.time_relative -e tcp.time_delta | \
  awk '$2 > 0.09 && $2 < 0.11 {print "CFS:", $0}'

# tshark: все задержки > 50 мс от сервера
tshark -r capture.pcap -Y "ip.src == <SERVER_IP> && tcp.time_delta > 0.05" \
  -T fields -e frame.number -e tcp.time_delta -e tcp.stream

# tshark: статистика задержек от сервера
tshark -r capture.pcap -Y "ip.src == <SERVER_IP> && tcp.len > 0" -q \
  -z "io,stat,1,AVG(tcp.time_delta),MAX(tcp.time_delta),STDEV(tcp.time_delta)"
```

**Интерпретация:**
- Задержки ровно ~0.1 с → CFS Throttling
- Задержки кратные 0.1 с (0.2, 0.3) → несколько периодов CFS
- Задержки без паттерна → другая причина (GC, IO Wait)

### Сценарий 3: Идентификация пауз GC

```bash
# tshark: провалы трафика (GC pauses)
tshark -r capture.pcap -Y "ip.src == <SERVER_IP>" -q \
  -z "io,stat,0.01,COUNT(frame)frame" | head -30
# → Интервалы с COUNT=0 указывают на паузу

# tshark: I/O Graphs для визуализации
tshark -r capture.pcap -Y "ip.src == <SERVER_IP>" -q \
  -z "io,stat,0.01,SUM(tcp.len)tcp.len"

# В Wireshark: Statistics → I/O Graphs
# Интервал: 10 мс, Y-axis: SUM(tcp.len)
# Провалы до 0 при стабильной нагрузке = GC pause
```

**Характерные признаки GC:**
- Паузы 10-50 мс (Java GC) или 100-500 мс (Go GC, старые версии)
- Паттерн: стабильный трафик → провал → всплеск (компенсация) → стабильный трафик
- Частота: каждые несколько секунд (incremental GC) или реже (full GC)

### Сценарий 4: Диагностика Nagle + Delayed ACK

```bash
# tshark: Delayed ACK
tshark -r capture.pcap -Y "tcp.analysis.delayed_ack" -T fields \
  -e frame.number -e tcp.stream -e ip.src -e tcp.srcport -e tcp.time_delta

# tshark: конфликт Nagle + Delayed ACK (задержка 40-200 мс для мелких данных)
tshark -r capture.pcap -Y "tcp.analysis.delayed_ack && tcp.len < 1460" \
  -T fields -e frame.number -e tcp.stream -e tcp.len -e tcp.time_delta

# tshark: статистика по задержкам Delayed ACK
tshark -r capture.pcap -Y "tcp.analysis.delayed_ack" -q \
  -z "io,stat,1,AVG(tcp.time_delta),MAX(tcp.time_delta),COUNT(tcp.analysis.delayed_ack)"

# tshark: поиск соединений с largest Delayed ACK задержками
tshark -r capture.pcap -Y "tcp.analysis.delayed_ack" -T fields \
  -e tcp.stream -e tcp.time_delta | sort -k2 -rn | head -10
```

**Интерпретация:**
- `tcp.time_delta` около 0.04 с → Delayed ACK таймер (40 мс)
- `tcp.time_delta` около 0.2 с → максимальный Delayed ACK (200 мс)
- Много `delayed_ack` + маленькие сегменты → конфликт Nagle

### Сценарий 5: Анализ ретрансмиссий на стороне сервера

```bash
# tshark: ретрансмиссии от сервера
tshark -r capture.pcap -Y "tcp.analysis.retransmission && ip.src == <SERVER_IP>" \
  -T fields -e frame.number -e tcp.stream -e tcp.seq -e tcp.len

# tshark: fast retransmissions от сервера
tshark -r capture.pcap -Y "tcp.analysis.fast_retransmission && ip.src == <SERVER_IP>" \
  -T fields -e frame.number -e tcp.stream -e tcp.seq

# tshark: потоки с наибольшим количеством ретрансмиссий
tshark -r capture.pcap -Y "tcp.analysis.retransmission && ip.src == <SERVER_IP>" \
  -T fields -e tcp.stream | sort | uniq -c | sort -rn | head -10

# tshark: время от первого пакета до ретрансмиссии
tshark -r capture.pcap -Y "tcp.analysis.retransmission && ip.src == <SERVER_IP>" \
  -T fields -e frame.number -e frame.time_relative -e tcp.stream -e tcp.analysis.rto
```

**Интерпретация:**
- Ретрансмиссии с `tcp.analysis.rto` > 1 с → высокий RTO (проблема с RTT)
- Fast retransmission → 3 DupACK, потеря в сети
- Много ретрансмиссий с одного потока → проблема с конкретным соединением

### Сценарий 6: Автотюнинг буферов отправки

```bash
# Проверка autotuning (ядро)
sysctl net.ipv4.tcp_wmem
# → net.ipv4.tcp_wmem = 4096 16384 4194304

# Проверка через ss для конкретного соединения
ss -tin dst 10.0.0.1 | grep snd_space
# → snd_space:16384 snd_ssthresh:4194304

# Если snd_space не растет — проблема с autotuning
ss -tin | awk '/snd_space/ {print $0}' | sort -k2 -n | tail -5

# Проверка SO_SNDBUF в коде
strace -e setsockopt -p <PID> 2>&1 | grep SO_SNDBUF
```

**Нормальные значения для разных сетей:**

| Тип сети | Рекомендуемый `tcp_wmem` max | Ожидаемый `snd_space` |
| :--- | :--- | :--- |
| 100 Мбит/с, RTT 10 мс | 4 МБ | 2-4 МБ |
| 1 Гбит/с, RTT 10 мс | 16 МБ | 8-16 МБ |
| 10 Гбит/с, RTT 1 мс | 64 МБ | 32-64 МБ |
| LFN (1 Гбит/с, RTT 100 мс) | 64 МБ | 32-64 МБ |

### Сценарий 7: Выбор Congestion Control

```bash
# Текущий алгоритм
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr

# Доступные алгоритмы
sysctl net.ipv4.tcp_available_congestion_control
# → net.ipv4.tcp_available_congestion_control = reno cubic bbr

# Установка BBR
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr

# Проверка через ss
ss -tin | grep -o "cubic\|bbr\|reno" | sort | uniq -c
# →  15 bbr
# →   3 cubic

# Сравнение поведения в Wireshark
# CUBIC: CWND растет экспоненциально → полиномиально
# BBR: CWND стабилен, pacing rate меняется плавно
```

### Сценарий 8: Клиентские проблемы в Docker/Kubernetes

```bash
# Проверка CPU throttling
docker stats --no-stream
# → %CPU > limits = throttling

# Проверка cgroup
cat /sys/fs/cgroup/cpu/cpu.stat
# → nr_throttled: 0  ← норма
# → nr_throttled: 42  ← проблема

# Kubernetes: увеличение CPU limits
# resources:
#   limits:
#     cpu: "2"    ← увеличить
#   requests:
#     cpu: "1"

# Sidecar proxy: проверка задержек
tshark -r capture.pcap -Y "ip.dst == <SIDECAR_IP> && tcp.len > 0" \
  -T fields -e frame.time_relative -e tcp.time_delta | head -10

# Проверка буферов внутри контейнера
docker exec <container> sysctl net.ipv4.tcp_wmem
# → net.ipv4.tcp_wmem = 4096 16384 4194304  ← стандартные значения

# Увеличение буферов для контейнера
docker run --sysctl net.ipv4.tcp_wmem="4096 65536 67108864" ...
```

**Типичные проблемы в Kubernetes:**
- **Sidecar-proxy (Envoy/Istio):** Proxy может стать bottleneck если его буферы меньше, чем у приложения
- **Network Policy:** Файрволы могут замедлять ACK, вызывая ложные Retransmission
- **Service Mesh:** Дополнительный hop увеличивает RTT, что требует больших буферов

## Таблица проблем

| Проблема | Симптом в Wireshark | Фильтр | Решение |
| :--- | :--- | :--- | :--- |
| **TTFB >> iRTT** | Долгая пауза перед первым ответом | `frame.time_delta > iRTT * 10` | Оптимизировать приложение |
| **CFS Throttling** | Задержки кратные 100 мс | `frame.time_delta_displayed ~ 0.1` | Увеличить CPU limits |
| **GC Pause** | Провалы до 0 на I/O Graphs | `Statistics → I/O Graphs` | Уменьшить паузы GC |
| **Nagle + Delayed ACK** | Задержка 40-200 мс для мелких данных | `tcp.analysis.delayed_ack` | `TCP_NODELAY` |
| **Retransmission** | `TCP Retransmission` в Expert Info | `tcp.analysis.retransmission` | Проверить сеть |
| **Buffer underrun** | Пустые ACK без данных | `tcp.len == 0 && tcp.flags.ack == 1` | Увеличить `SO_SNDBUF` |
| **SO_BUSY_POLL off** | Высокий jitter на I/O Graphs | `AVG(tcp.analysis.ack_rtt)` | `SO_BUSY_POLL` |

## Проверка на уровне ОС

### Linux

| Команда | Что проверяет | Норма |
| :--- | :--- | :--- |
| `kubectl top pod` | CPU/RAM контейнера | < limits |
| `cat /sys/fs/cgroup/cpu/cpu.stat` | `nr_throttled` | 0 |
| `iostat -xz 1` | Очереди к дискам | %util < 80% |
| `strace -T -p <PID>` | Длительные syscall | Нет > 10 мс |
| `nstat -az TcpExtTCPAutoCork` | Auto-corking | Стабильно |
| `ss -tin \| grep snd_space` | snd_space | Растет |
| `sysctl net.ipv4.tcp_congestion_control` | Алгоритм конгестии | bbr |
| `ethtool -k eth0 \| grep tso` | TSO | on |
| `ss -s` | Общая статистика | SYN_RECV < 100 |

**Диагностика через nstat:**
```bash
# Счетчики ядра для серверных проблем
nstat -az TcpExtTCPAutoCork TcpExtTCPSlowStartRetransmits TcpExtTCPRetransFail
# → TcpExtTCPAutoCork        128 0.0  ← auto-corking сработал
# → TcpExtTCPSlowStartRetransmits  5 0.0  ← ретрансмиссии в slow start
# → TcpExtTCPRetransFail     0 0.0   ←.failed retransmissions (норма: 0)
```

### Docker/Kubernetes

```bash
# Проверка CPU throttling
docker stats --no-stream
# → %CPU > limits = throttling

# Проверка cgroup
cat /sys/fs/cgroup/cpu/cpu.stat
# → nr_throttled: 0  ← норма
# → nr_throttled: 42  ← проблема

# Kubernetes: увеличение CPU limits
# resources:
#   limits:
#     cpu: "2"    ← увеличить
#   requests:
#     cpu: "1"

# Sidecar proxy: проверка задержек
tshark -r capture.pcap -Y "ip.dst == <SIDECAR_IP> && tcp.len > 0" \
  -T fields -e frame.time_relative -e tcp.time_delta | head -10

# Проверка буферов внутри контейнера
docker exec <container> sysctl net.ipv4.tcp_wmem
# → net.ipv4.tcp_wmem = 4096 16384 4194304  ← стандартные значения

# Увеличение буферов для контейнера
docker run --sysctl net.ipv4.tcp_wmem="4096 65536 67108864" ...
```

**Типичные проблемы в Kubernetes:**
- **Sidecar-proxy (Envoy/Istio):** Proxy может стать bottleneck если его буферы меньше, чем у приложения
- **Network Policy:** Файрволы могут замедлять ACK, вызывая ложные Retransmission
- **Service Mesh:** Дополнительный hop увеличивает RTT, что требует больших буферов

### Валидация после настройки

```bash
# После изменения tcp_wmem
sysctl net.ipv4.tcp_wmem net.core.wmem_max

# После включения BBR
sysctl net.ipv4.tcp_congestion_control net.ipv4.tcp_available_congestion_control

# После включения SO_BUSY_POLL
sysctl net.core.busy_poll net.core.busy_read

# Проверка через ss для конкретного соединения
ss -tin dst 10.0.0.1
# → snd_space:4194304  ← подтвердился max из tcp_wmem
# → bbr  ← алгоритм активен
```

## Дополнительная информация

### См. также

- **[Определения Wireshark](../definitions.md)** — базовые термины (RTT, iRTT, Window Size).
- **[Основные концепции захвата](../core_concepts.md)** — offloading, ring buffer, AF_PACKET.
- **[Использование tshark](../tshark_usage.md)** — CLI-команды для анализа TCP.
- **[Обзор диагностики производительности](./tcp_performance_diagnostics.md)** — методология и ключевые метрики.
- **[Проблемы клиента](./tcp_client_performance_issues.md)** — Zero Window, Window Full, backpressure.
- **[Сетевые потери и offloading](./tcp_network_losses_and_offloading.md)** — влияние инфраструктуры.
- **[Инструменты анализа: графики TCP](./tcp_performance_analysis_tools.md)** — визуализация потоков.
- **[Алгоритм Нагла](../../Protocols/TCP/tcp_nagle_algorithm.md)** — Nagle, TCP_NODELAY, конфликт с Delayed ACK.
- **[Оптимизация TCP в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — тюнинг буферов и алгоритмов.
