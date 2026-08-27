# Wireshark: диагностика производительности TCP — обзор

> **SSoT:** Определения базовых терминов (RTT, iRTT, Window Size, Expert Info) — в **[Определения](../definitions.md)**. Концепции захвата и offloading — в **[Основные концепции](../core_concepts.md)**. tshark-команды — в **[Использование tshark](../tshark_usage.md)**. Графики и визуализация — в **[Инструменты анализа](./tcp_performance_analysis_tools.md)**. Проблемы сервера — в **[Серверные проблемы](./tcp_server_performance_issues.md)**. Проблемы клиента — в **[Клиентские проблемы](./tcp_client_performance_issues.md)**. Потери и offloading — в **[Сетевые потери](./tcp_network_losses_and_offloading.md)**.

## Определения

**Диагностика производительности TCP** — комплексный метод анализа сетевого трафика в Wireshark, направленный на выявление причин замедления передачи данных на стороне сервера, клиента или в сетевой инфраструктуре.

**Ключевые метрики:**
- **RTT (Round-Trip Time)** — время кругового обхода; интервал от отправки сегмента до получения подтверждения (ACK) на него.
- **iRTT (Initial RTT)** — RTT, измеренный во время 3-way handshake (SYN → SYN-ACK). Является базовой задержкой канала без учета очередей.
- **Delta Time** — интервал между пакетами. Различают `frame.time_delta` (от предыдущего пакета в захвате) и `tcp.time_delta` (от предыдущего пакета в этом же TCP-потоке).
- **Throughput (Пропускная способность)** — фактическая скорость передачи полезных данных.
- **Window Size (RWND)** — объем данных, которые приемник готов принять без подтверждения (размер буфера сокета).
- **Bytes in Flight** — объем данных, отправленных, но еще не подтвержденных. В идеале должен быть близок к BDP.
- **BDP (Bandwidth-Delay Product)** — «емкость» сетевого пути; максимальный объем данных, который может находиться в «трубе» одновременно. Рассчитывается как `Bandwidth * RTT`.

## Quick-Start: Чек-лист диагностики TCP

Быстрый старт при подозрении на проблемы с производительностью TCP:

| Шаг | Действие | Как проверить |
| :--- | :--- | :--- |
| **1** | Посмотреть Expert Info | `Analyze → Expert Information` — количество Warning/Error |
| **2** | Проверить RTT | `tcp.analysis.initial_rtt` — должен быть < 50 мс для локальной сети |
| **3** | Посмотреть Bytes in Flight | `tcp.analysis.bytes_in_flight` — должен быть близок к BDP |
| **4** | Проверить Zero Window | `tcp.analysis.zero_window` — должен быть 0 пакетов |
| **5** | Проверить Window Full | `tcp.analysis.window_full` — должен быть 0 пакетов |
| **6** | Проверить ретрансмиссии | `tcp.analysis.retransmission` — должен быть < 0.1% от всех пакетов |
| **7** | Проверить Offloading | `frame.len > 1500` — большие пакеты = LRO/GRO включен |
| **8** | Проверить Window Scale | SYN/SYN-ACK → `Options: Window Scale` — должен быть согласован |

## Основные концепты

### Ограничители скорости TCP

Скорость передачи данных в TCP всегда ограничена минимальным из трех окон:
1. **RWND (Receiver Window):** Ограничение со стороны приложения-получателя (буферы сокета).
2. **CWND (Congestion Window):** Ограничение со стороны сети (алгоритмы CUBIC, BBR).
3. **SND_BUF:** Ограничение со стороны буферов отправителя.

В Wireshark событие `TCP Window Full` означает, что мы уперлись в **RWND**, а отсутствие таких сообщений при низкой скорости часто указывает на ограничение **CWND** или потери.

### Поведение алгоритмов (CUBIC vs BBR v3)

В 2026 году важно различать паттерны работы алгоритмов контроля перегрузки:
- **CUBIC:** Характеризуется «пилообразным» графиком пропускной способности. При потере пакета резко снижает окно и постепенно восстанавливает его. В Wireshark часто видны всплески (bursts) пакетов сразу после получения ACK.
- **BBR (Bottleneck Bandwidth and RTT):** Использует **Pacing** (равномерную отправку). В Wireshark это выглядит как стабильный интервал между сегментами (`tcp.time_delta` почти константна). BBR не реагирует на единичные потери, стараясь удерживать объем данных на уровне BDP.

**Как отличить в Wireshark:**
```
CUBIC:  [пакет][пакет][пакет]...[пауза]...[пакет][пакет][пакет]
BBR:    [пакет]..[пакет]..[пакет]..[пакет]..[пакет]..[пакет]
```

### TCP Expert Info — «Быстрая скрининг-диагностика»

Wireshark автоматически помечает аномалии через флаги `tcp.analysis.flags`:
- **Retransmission:** Повторная отправка сегмента (потеря в сети).
- **Fast Retransmission:** Сработка механизма быстрой переотправки через DupACK.
- **Out-of-Order:** Нарушение порядка следования (часто из-за параллельных путей в сети).
- **Spurious Retransmission:** Ложная ретрансмиссия (когда ACK пришел позже, чем сработал таймер).
- **Window Full:** Отправитель заполнил объявленное окно получателя.
- **Zero Window:** Получатель объявил `rwnd=0` — переполнение буфера.
- **Window Probe:** Отправитель проверяет, освободилось ли окно получателя.

### Опции TCP и производительность

Для высокоскоростных каналов (Long Fat Networks) критичны следующие опции:
- **Window Scaling (wscale):** Позволяет расширить окно RWND за пределы 64 Кбайт. В Wireshark ищите значение в пакете SYN. Если `wscale` не согласован, скорость будет ограничена ~50 Мбит/с даже на 10G-канале.
- **SACK (Selective ACK):** Позволяет подтверждать только успешно дошедшие сегменты при потерях, избегая ретрансмиссии всего окна. Без SACK производительность на «грязных» каналах падает катастрофически.
- **Timestamps:** Необходимы для точного измерения RTT и защиты от PAWS (Protection Against Wrapped Sequence numbers) на скоростях > 10 Гбит/с.

### Современные механизмы обнаружения потерь

В современных ядрах Linux (5.x+) и Wireshark 4.x важно учитывать:
- **RACK (Recent Acknowledgment):** Заменяет классический подсчет DupACK (3 шт.) на анализ времени. Позволяет быстрее восстанавливаться при переупорядочивании пакетов.
- **TLP (Tail Loss Probe):** Механизм зондирования «хвоста» очереди для предотвращения длительных таймаутов RTO при потере последних сегментов транзакции.

### Анализ задержек (Latency)

| Тип задержки | Проявление в Wireshark | Причина | Фильтр |
| :--- | :--- | :--- | :--- |
| **Сетевая (RTT)** | Высокое время между SYN и SYN-ACK. | Большая дистанция, перегрузка узлов, Bufferbloat. | `tcp.analysis.initial_rtt > 0.1` |
| **Серверная (iRTT)** | Низкий RTT, но большое Delta Time перед ответом сервера. | Медленная БД, высокая нагрузка на CPU, блокировки IO. | `tcp.time_delta > 0.5` |
| **Клиентская** | Пакеты `TCP Zero Window`. | Клиент не успевает вычитывать данные из сокета. | `tcp.analysis.zero_window` |
| **Хвостовая (Tail)** | Ретрансмиссия после долгой паузы без DupACK. | Сработка RTO — потеря последних сегментов. | `tcp.analysis.retransmission` |

## Практические сценарии

### Настройка столбцов для SRE

Для быстрой диагностики добавьте поля как столбцы (`Правый клик на поле → Apply as Column`):
- `tcp.analysis.initial_rtt` — базовый RTT соединения.
- `tcp.analysis.ack_rtt` — время подтверждения конкретного сегмента.
- `tcp.analysis.bytes_in_flight` — текущая нагрузка на канал.
- `tcp.window_size_value` — размер окна приемника (raw).
- `tcp.time_delta` — время с предыдущего пакета потока (помогает видеть Pacing).
- `tcp.analysis.flags` — все экспертные флаги в одном столбце.

```bash
# tshark: настройка столбцов через профиль
tshark -r capture.pcap -T fields -e frame.number -e tcp.analysis.initial_rtt -e tcp.analysis.bytes_in_flight -e tcp.analysis.ack_rtt -e tcp.window_size_value -e tcp.time_delta
```

### Сценарий 1: Расчет BDP и диагностика недогрузки

1. Найдите средний RTT (через `Statistics → TCP Stream Graphs → Round Trip Time`).
2. Определите целевую скорость (например, 1 Гбит/с).
3. Рассчитайте BDP: `(1000 Мбит/с * 0.1 сек) / 8 = 12.5 Мбайт`.
4. Сравните с `tcp.analysis.bytes_in_flight`. Если значение значительно ниже 12.5 Мбайт и нет потерь — отправитель или сеть искусственно ограничивают скорость (малый CWND).

```bash
# tshark: расчет BDP для потока
tshark -r capture.pcap -q -z "io,stat,1,AVG(tcp.analysis.initial_rtt)" -Y "tcp.stream eq 0"

# tshark: текущий Bytes in Flight для потока
tshark -r capture.pcap -Y "tcp.stream eq 0 && tcp.analysis.bytes_in_flight" -T fields -e frame.time_relative -e tcp.analysis.bytes_in_flight
```

### Сценарий 2: Дифференциация CUBIC и BBR v3

1. Посмотрите на `tcp.time_delta` для исходящих данных от сервера.
2. **BBR:** Значения `delta` будут равномерными (например, ~0.1 мс для многих пакетов подряд). Это результат работы **Pacing**.
3. **CUBIC:** Вы увидите всплески — пачка пакетов с `delta` близкой к 0, затем пауза до прихода следующего ACK.
4. **Зачем это нужно:** BBR гораздо эффективнее на «грязных» каналах (Wi-Fi, LTE) с потерями, где CUBIC ошибочно снижает скорость.

```bash
# tshark: анализ Pacing (BBR)
tshark -r capture.pcap -Y "tcp.stream eq 0 && tcp.len > 0" -T fields -e frame.time_delta -e tcp.seq | head -30

# Если все delta ~константны → BBR
# Если delta = 0 для группы пакетов → CUBIC
```

### Сценарий 3: Диагностика «ложных» потерь (Offloading)

Если вы видите огромные пакеты (например, 20-30 Кбайт) и сообщения `TCP Spurious Retransmission`:
1. Скорее всего, на сетевой карте включен **LRO (Large Receive Offload)** или **GRO**.
2. Сетевая карта склеивает пакеты до того, как их увидит Wireshark, что ломает логику анализа TCP-опций.
3. **Решение:** Для точной диагностики отключите offloading: `ethtool -K eth0 gro off lro off`. Подробнее: **[Влияние offloading на анализ](./tcp_network_losses_and_offloading.md)**.

```bash
# tshark: поиск крупных пакетов (признак LRO/GRO)
tshark -r capture.pcap -Y "frame.len > 1514" -T fields -e frame.number -e frame.len -e tcp.stream

# Отключение offloading на Linux
sudo ethtool -K eth0 gro off lro off tso off gso off

# Проверка
ethtool -k eth0 | grep -E "generic-receive-offload|large-receive-offload"
```

### Сценарий 4: Поиск Bufferbloat

Bufferbloat — это раздувание задержек при высокой нагрузке.
1. Откройте `Statistics → TCP Stream Graphs → Round Trip Time`.
2. Если при росте Throughput (график пропускной способности) пропорционально растет RTT — промежуточное оборудование имеет слишком большие буферы, что убивает интерактивность.

```bash
# tshark: мониторинг RTT в динамике
tshark -r capture.pcap -q -z "io,stat,1,AVG(tcp.analysis.ack_rtt),MAX(tcp.analysis.ack_rtt)"

# График RTT vs Throughput
tshark -r capture.pcap -q -z "io,stat,1,AVG(tcp.analysis.ack_rtt),SUM(tcp.len)*8/1"
```

### Сценарий 5: Диагностика хвостовых задержек (Tail Latency)

1. Примените фильтр: `tcp.analysis.retransmission`.
2. Используйте поле `frame.time_delta` для поиска пакетов с задержкой > 1 сек.
3. Если ретрансмиссия происходит через большой интервал без DupACK — это сработка **RTO**, что критично для производительности API.

```bash
# tshark: поиск ретрансмиссий с высоким time_delta
tshark -r capture.pcap -Y "tcp.analysis.retransmission && frame.time_delta > 1.0" -T fields -e frame.number -e frame.time_delta -e tcp.stream -e ip.src -e tcp.srcport

# tshark: статистика ретрансмиссий по потокам
tshark -r capture.pcap -Y "tcp.analysis.retransmission" -T fields -e tcp.stream | sort | uniq -c | sort -rn | head -10
```

### Сценарий 6: Диагностика SYN-ретрансмиссий

SYN-ретрансмиссии указывают на проблему с установлением соединения:
```bash
# tshark: поиск SYN-ретрансмиссий
tshark -r capture.pcap -Y "tcp.flags.syn == 1 && tcp.analysis.retransmission" -T fields -e frame.number -e ip.src -e tcp.dstport -e tcp.analysis.initial_rtt

# Wireshark: Expert Info → Warning → SYN Retransmission
# Причина: файрвол блокирует, сервер перегружен, DNS разрешается медленно
```

### Сценарий 7: Диагностика высокого RTT

```bash
# tshark: все соединения с RTT > 100 мс
tshark -r capture.pcap -Y "tcp.analysis.initial_rtt > 0.1" -T fields -e tcp.stream -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport -e tcp.analysis.initial_rtt

# tshark: топ-10 соединений по RTT
tshark -r capture.pcap -q -z "conv,tcp" | sort -k8 -rn | head -10

# tshark: джиттер RTT (разброс задержек)
tshark -r capture.pcap -q -z "io,stat,1,AVG(tcp.analysis.ack_rtt),STDEV(tcp.analysis.ack_rtt)" -Y "tcp.stream eq 0"
```

### Сценарий 8: Диагностика Window Probe

Window Probe возникает, когда отправитель проверяет, освободилось ли окно получателя после Zero Window:
```bash
# tshark: поиск Window Probe
tshark -r capture.pcap -Y "tcp.analysis.zero_window_probe" -T fields -e frame.number -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport

# tshark: Window Probe Ack (получатель подтверждает освобождение окна)
tshark -r capture.pcap -Y "tcp.analysis.zero_window_probe_ack" -T fields -e frame.number -e tcp.window_size_value

# Если Window Probe持续 возникает → приложение не успевает вычитывать данные
```

### Сценарий 9: Анализ TIME-WAIT и коротких соединений

```bash
# tshark: поиск соединений в TIME-WAIT
tshark -r capture.pcap -Y "tcp.flags.fin == 1 && tcp.analysis.flags" -T fields -e tcp.stream -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport

# tshark: количество соединений с одного IP
tshark -r capture.pcap -Y "tcp.flags.syn == 1" -T fields -e ip.src | sort | uniq -c | sort -rn | head -10
```

## Дополнительная информация

### Математические зависимости

**Максимальная скорость (формула Матиса):**
`Throughput ≤ (MSS / RTT) * (1 / sqrt(p))`, где `p` — вероятность потери пакетов.
Даже 1% потерь при RTT 50 мс ограничивает скорость до нескольких мегабит, независимо от ширины канала.

**Практические примеры:**
| Канал | RTT | Потери | Макс. Throughput |
| :--- | :--- | :--- | :--- |
| 100 Мбит/с | 10 мс | 0% | 100 Мбит/с |
| 100 Мбит/с | 10 мс | 0.1% | ~10 Мбит/с |
| 100 Мбит/с | 100 мс | 1% | ~1 Мбит/с |
| 1 Гбит/с | 50 мс | 0.01% | ~100 Мбит/с |

### Типичные проблемы и их симптомы

| Проблема | Симптом в Wireshark | Фильтр | Решение |
| :--- | :--- | :--- | :--- |
| **Нет Window Scale** | Окно не растет выше 64 КБ | `tcp.options.wscale == 0` | Включить Window Scaling на сервере |
| **Нет SACK** | Полная ретрансмиссия при потерях | `tcp.options.sack == 0` | Включить SACK на сервере |
| **CWND limited** | Низкий throughput, нет потерь | `tcp.analysis.bytes_in_flight < BDP` | Увеличить CWND или перейти на BBR |
| **Bufferbloat** | RTT растет пропорционально нагрузке | `tcp.analysis.ack_rtt > initial_rtt * 10` | Уменьшить буферы на маршрутизаторе |
| **LRO/GRO** | Крупные пакеты, Spurious Retransmission | `frame.len > 1514` | `ethtool -K eth0 gro off lro off` |
| **Zero Window** | Получатель не справляется | `tcp.analysis.zero_window` | Увеличить SO_RCVBUF или оптимизировать приложение |
| **SYN Retransmission** | Задержка установления соединения | `tcp.flags.syn==1 && tcp.analysis.retransmission` | Проверить файрвол, DNS, доступность сервера |

### См. также

- **[Определения Wireshark](../definitions.md)** — RTT, iRTT, Expert Info и др.
- **[Основные концепции захвата](../core_concepts.md)** — offloading, ring buffer, multi-iface.
- **[Использование tshark](../tshark_usage.md)** — CLI-команды для анализа TCP.
- **[Проблемы сервера](./tcp_server_performance_issues.md)** — внутренние задержки ОС и приложений.
- **[Клиентские проблемы](./tcp_client_performance_issues.md)** — Zero Window, Window Full.
- **[Сетевые потери и offloading](./tcp_network_losses_and_offloading.md)** — влияние инфраструктуры.
- **[Инструменты анализа: графики TCP](./tcp_performance_analysis_tools.md)** — визуализация потоков.
- **[Оптимизация TCP в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — тюнинг буферов и алгоритмов.
