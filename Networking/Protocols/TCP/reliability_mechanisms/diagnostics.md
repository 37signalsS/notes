# Диагностика надежности TCP

## Определения

**Диагностика надежности TCP** — процесс мониторинга и анализа механизмов восстановления данных (ретрансмиссий, подтверждений, тайм-аутов) для выявления деградации сетевого канала, аппаратных сбоев или ошибок конфигурации сетевого стека ОС.

**Ключевые метрики:**
- **Retransmission Rate (Коэффициент ретрансмиссий):** Процент повторно отправленных сегментов от общего объема исходящего трафика. Значение выше 1% в локальной сети или выше 5% в интернет-канале обычно указывает на проблемы.
- **RTO Retransmits:** Повторные передачи, вызванные истечением таймера ожидания (признак полной потери пакетов или серьезных заторов).
- **Fast Retransmits:** Повторные передачи, инициированные механизмом 3-DupACK (нормальное поведение при кратковременных заторах).
- **TLP (Tail Loss Probe):** Механизм зондирования «хвоста» очереди, позволяющий обнаружить потерю последнего сегмента транзакции, когда получение дублирующих ACK невозможно.
- **Spurious Retransmission:** Ложная ретрансмиссия — повторная отправка данных, которые не были потеряны, а лишь задержались в сети. Расточительна и может ухудшать производительность.

---

## Систематический подход к диагностике

Диагностика надежности TCP следует алгоритму из 4 шагов:

```text
Шаг 1: Обнаружение   →  Шаг 2: Классификация  →  Шаг 3: Локализация  →  Шаг 4: Исправление
   ↓                        ↓                       ↓                      ↓
nstat, ss -ti          Тип потерь              Причина               sysctl, tcpdump,
Prometheus, Grafana    RTO/Fast/TLP/Spurious   Сеть/Сервер/NIC       ethtool, приложение
```

### Шаг 1: Обнаружение аномалий
```bash
# 1.1 Глобальная проверка (секундный снимок)
nstat -az | grep -E 'TcpRetransSegs|TcpOutSegs|TcpExtTCPTimeouts|TcpExtTCPFastRetrans|TcpExtTCPTailLossProbe'
# → Формула: Retransmission Rate = (TcpRetransSegs / TcpOutSegs) * 100

# 1.2 Непрерывный мониторинг (обновление каждую секунду)
watch -n 1 'nstat -az | grep -E "TcpRetransSegs|TcpOutSegs|TcpExtTCPTimeouts"'

# 1.3 Состояние конкретного соединения
ss -ti dst 8.8.8.8
# → cubic rto:204 rtt:15.2/0.5 cwnd:10 retrans:0/12 backoff:0
```

### Шаг 2: Классификация типа потерь
| Тип | Признак в `ss` | Признак в `nstat` | Вероятная причина |
| :--- | :--- | :--- | :--- |
| **RTO (по таймеру)** | `backoff > 0`, `retrans` растет | `TcpExtTCPTimeouts` растет | Полная потеря пакета или серьезная перегрузка. |
| **Fast Retransmit** | `retrans` растет, `rtt` стабильно | `TcpExtTCPFastRetrans` растет | Единичный пропуск (кратковременный затор). |
| **TLP** | `retrans` растет, `rtt` стабильно | `TcpExtTCPTailLossProbe` растет | Потеря «хвоста» на коротких транзакциях. |
| **Spurious** | `retrans` растет, но `rtt` аномально низкое | `TcpExtTCPSpuriousRtxHostQueues` растет | Ложная ретрансмиссия (пакет задержался, не потерялся). |

### Шаг 3: Локализация источника
```bash
# Проверка физического уровня (NIC, кабель)
ethtool -S eth0 | grep -iE 'error|drop|crc|miss|fifo'
# → rx_crc_errors: 42  ← ошибки на L2
# → rx_missed_errors: 15  ← пропущено из-за переполнения FIFO
# → tx_dropped: 3  ← отброшено при отправке

# Проверка очередей ядра
nstat -az | grep -iE 'Queue|Overflow|Drop'
# → TcpExtTCPRecvQueueFull  5  0.0  ← приложение не успевает читать
# → TcpExtTCPWindowFull  42  0.0  ← отправитель заблокирован (zero window)

# Захват трафика для детального анализа
sudo tcpdump -i eth0 -w /tmp/reliability_debug.pcap 'host 8.8.8.8' &
# ... воспроизвести проблему ...
sudo kill %1
```

### Шаг 4: Исправление
См. раздел «Типы инцидентов и исправления» ниже.

---

## Основные инструменты

### 1. Глобальная статистика (nstat)
Утилита `nstat` (современная замена `netstat -s`) предоставляет агрегированные счетчики SNMP стека TCP с момента последней загрузки системы.

```bash
# Мониторинг критических счетчиков надежности в реальном времени
nstat -az | grep -E 'TcpRetransSegs|TcpOutSegs|TcpExtTCPTimeouts|TcpExtTCPTailLossProbe'
# → TcpRetransSegs                   50                 0.0
# → TcpOutSegs                      5000                0.0
# → TcpExtTCPTimeouts                5                  0.0
# → TcpExtTCPTailLossProbe           12                 0.0
```
**Формула расчета Retransmission Rate:** `(TcpRetransSegs / TcpOutSegs) * 100`.

### 2. Детальный анализ сессий (ss)
Инструмент `ss -ti` позволяет увидеть состояние конкретного соединения «глазами ядра», включая текущие таймеры и статистику потерь.

```bash
ss -ti dst 1.2.3.4
# → cubic rto:204 rtt:15.2/0.5 cwnd:10 retrans:0/12 backoff:2
```
- **retrans:текущие/всего:** Первый параметр — количество сегментов, ожидающих подтверждения прямо сейчас; второй — общее количество ретрансмиссий за время жизни сокета.
- **backoff:** Счетчик экспоненциального увеличения интервала RTO. Если значение выше 0 — соединение испытывает тяжелые потери и "зависло" в ожидании.

### 3. Трассировка через eBPF (2026)
Методы eBPF позволяют проводить глубокую диагностику без накладных расходов на копирование пакетов в пользовательское пространство (в отличие от `tcpdump`).

- **tcpretrans:** Выводит информацию о каждой ретрансмиссии с указанием типа (RTO/Fast) и состояния соединения.
- **tcpdrop:** Фиксирует моменты, когда ядро отбрасывает пакет (например, из-за переполнения очередей или неверной контрольной суммы).
- **tcpstates:** Отслеживает переходы состояний TCP (ESTABLISHED, TIME_WAIT, CLOSE_WAIT и т.д.).
- **tcprtt:** Измеряет распределение RTT для каждого соединения.

```bash
# Пример вывода tcpretrans
sudo tcpretrans
# → TIME     PID    LADDR:LPORT          DADDR:DPORT          STATE       TYPE
# → 12:00:01 123    1.1.1.1:443       >  2.2.2.2:54321        ESTABLISHED RTO

# Включение фильтра по IP-адресу (только интересующее соединение)
sudo tcpretrans -L 1.1.1.1 -D 2.2.2.2

# tcpdrop — отслеживание моментов отбрасывания
sudo tcpdrop
# → TIME     PID    LADDR:LPORT          DADDR:DPORT          STATE    REASON
# → 12:00:05 -      0.0.0.0:80        <-  3.3.3.3:12345        LISTEN   tcp_v4_rcv()
```

---

## Полный референс счетчиков nstat для надежности

### Группа 1: Ретрансмиссии
| Счетчик | Описание | Норма |
| :--- | :--- | :--- |
| `TcpRetransSegs` | Общее количество ретрансмитированных сегментов. | < 1% от `TcpOutSegs`. |
| `TcpExtTCPTimeouts` | Количество срабатываний таймера RTO. | 0 для стабильных соединений. |
| `TcpExtTCPFastRetrans` | Количество быстрых ретрансмиссий (по 3 DupACK). | Зависит от нагрузки; < 1%. |
| `TcpExtTCPTailLossProbe` | Количество TLP-событий. | Низкое; рост = потери «хвоста». |
| `TcpExtTCPSlowStartRetrans` | Ретрансмиссии во время фазы Slow Start. | 0 для стабильных соединений. |
| `TcpExtTCPSACKRecovery` | Восстановления с использованием SACK. | Нормально при потерях; < 1%. |
| `TcpExtTCPRenoRecovery` | Восстановления без SACK (Reno). | Должно быть 0; если растет → SACK отключен. |
| `TcpExtTCPLostRetransmit` | Сегменты, потерянные повторно после ретрансмиссии. | 0; рост = проблема с NIC или памятью. |

### Группа 2: Spurious Retransmissions
| Счетчик | Описание | Диагностика |
| :--- | :--- | :--- |
| `TcpExtTCPSpuriousRtxHostQueues` | Ложные ретрансмиссии из-за(reordered packets). | Высокий → включить RACK (`net.ipv4.tcp_recovery=1`). |
| `TcpExtTCPSpuriousRto` | Ложные RTO (таймаут сработал зря). | Высокий → проверить сетевую стабильность или увеличить `tcp_rto_min`. |
| `TcpExtTCPTimeouts` | Событий RTO (включая ложные). | Сравнить с `TCPSpuriousRto` для вычисления доли ложных. |

### Группа 3: Ошибки и отбрасывания
| Счетчик | Описание | Диагностика |
| :--- | :--- | :--- |
| `TcpInCsumErrors` | Пакеты с неверной контрольной суммой (Silent Drop). | > 0 → проверить NIC, кабель, память (ECC). |
| `TcpExtListenOverflows` | Переполнение очереди backlog (приложение не вызывает `accept()`). | > 0 → увеличить `net.core.somaxconn` или оптимизировать приложение. |
| `TcpExtListenDrops` | Отброшенные соединения в состоянии LISTEN. | > 0 → проверить `syncookies` и `tcp_max_syn_backlog`. |
| `TcpExtTCPReqQFullDrop` | Переполнение очереди запросов. | > 0 → приложение перегружено. |

### Группа 4: Flow Control
| Счетчик | Описание | Диагностика |
| :--- | :--- | :--- |
| `TcpExtTCPWindowFull` | Отправка заблокирована из-за zero window. | > 0 → приложение медленно читает из сокета. |
| `TcpExtTCPRecvQueueFull` | Приемный буфер переполнен. | > 0 → увеличить `net.core.rmem_max` или оптимизировать приложение. |
| `TcpExtTCPPureAcks` | Количество «пустых» ACK (без данных). | Высокий → Delayed ACK отключен или приложение отправляет мало данных. |

### Группа 5: Соединения
| Счетчик | Описание | Диагностика |
| :--- | :--- | :--- |
| `TcpAttemptFails` | Неудачные попытки установки соединения. | > 0 → проверить доступность сервера, фаервол. |
| `TcpEstabResets` | Принудительное закрытие соединения (RST). | > 0 → проверить таймауты приложения или сетевые блокировки. |
| `TcpExtTCPAbortOnTimeout` | Закрытие из-за таймаута. | > 0 → проблема с доступностью партнера. |
| `TcpExtTCPAbortOnClose` | Закрытие с непрочитанными данными в буфере. | > 0 → приложение закрыло сокет без `recv()`. |
| `TcpExtTCPAbortOnMemory` | Закрытие из-за нехватки памяти. | > 0 → увеличить `net.ipv4.tcp_mem`. |

---

## Интерпретация полей ss -ti

Полный справочник полей `ss -ti` для диагностики надежности:

| Поле | Описание | На что смотреть |
| :--- | :--- | :--- |
| `rto` | Текущий Retransmission Timeout (мс). | > 200 в локальной сети → проблема; 200–1000 → норма для WAN. |
| `rtt` | Сглаженное значение RTT (мс). | Рост под нагрузкой → bufferbloat; стабильно → потери случайные. |
| `mdev` (jitter) | Отклонение RTT (мс). | > 50% от RTT → нестабильная сеть (Wi-Fi, мобильные). |
| `cwnd` | Текущее окно перегрузки (в MSS). | 1 → только что была потеря; растет → восстановление. |
| `ssthresh` | Порог slow start (в MSS). | 10 → недавняя потеря; > 100 → стабильное соединение. |
| `retrans` | Ретрансмиссии: текущие/всего. | Первое число > 0 → активная потеря; второе растет → хроническая. |
| `backoff` | Множитель RTO (2^backoff × RTO). | > 0 → экспоненциальный backoff (серьезные потери). |
| `ato` | Acknowledgment Timeout (мс). | 40 → QuickACK; 200 → Delayed ACK; > 200 → проблема. |
| `rcv_space` | Оценка доступного пространства приема. | < MSS → получатель заблокирован (zero window). |
| `snd_wnd` | Размер отправительского окна (байты). | Сравнивать с BDP; если мало → ограничено `rwnd` или `cwnd`. |

```bash
# Пример: сравнение полей для двух соединений
ss -ti dst 8.8.8.8
# → cubic rto:204 rtt:15.2/0.5 cwnd:10 ssthresh:14 retrans:0/12 backoff:0

ss -ti dst 1.1.1.1
# → cubic rto:520 rtt:85.3/42.1 cwnd:4 ssthresh:2 retrans:3/45 backoff:3
# → Проблема: высокий rtt, большой jitter, low cwnd, активные ретрансмиссии
```

---

## tcpdump и tshark: фильтры для анализа надежности

### Базовые фильтры
```bash
# Все ретрансмиссии в дампе
sudo tcpdump -r capture.pcap 'tcp[tcpflags] & (tcp-syn|tcp-fin) == 0' -nn | \
  awk '{print $1, $2, $3, $4, $5, $NF}' | sort | uniq -d

# Ретрансмиссии через tshark (быстрее и точнее)
tshark -r capture.pcap -Y "tcp.analysis.retransmission" -T fields \
  -e frame.time -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport -e tcp.len

# Только Fast Retransmit
tshark -r capture.pcap -Y "tcp.analysis.fast_retransmission"

# Только Timeout-based retransmission (RTO)
tshark -r capture.pcap -Y "tcp.analysis.retransmission and !tcp.analysis.fast_retransmission"

# Spurious retransmission (ложные)
tshark -r capture.pcap -Y "tcp.analysis.spurious_retransmission"
```

### Диагностика конкретных проблем
```bash
# 1. Поиск дублирующих ACK (DupACK)
tshark -r capture.pcap -Y "tcp.analysis.duplicate_ack" -T fields \
  -e frame.time -e ip.src -e tcp.ack

# 2. Поиск Zero Window
tshark -r capture.pcap -Y "tcp.analysis.zero_window" -T fields \
  -e frame.time -e ip.src -e tcp.srcport

# 3. ПоискWindowState (окно уменьшилось)
tshark -r capture.pcap -Y "tcp.analysis.window_full" -T fields \
  -e frame.time -e ip.src -e tcp.srcport

# 4. Поиск Out-of-Order сегментов
tshark -r capture.pcap -Y "tcp.analysis.out_of_order"

# 5. Анализ RTT через TCP Timestamps
tshark -r capture.pcap -Y "tcp.options.timestamp" -T fields \
  -e frame.time -e ip.src -e tcp.srcport -e tcp.options.tsval -e tcp.options.tsecr \
  | awk '{rtt = ($5 - $6) / 1000; print $0, "RTT=" rtt "ms"}'

# 6. Анализ SACK-блоков
tshark -r capture.pcap -Y "tcp.options.sack" -T fields \
  -e frame.time -e ip.src -e tcp.srcport -e tcp.options.sack
```

### Wireshark IO Graphs (визуализация)
```text
В Wireshark: Statistics → IO Graphs

Фильтр 1 (Весь трафик):   tcp
Фильтр 2 (Ретрансмиссии):  tcp.analysis.retransmission
Фильтр 3 (DupACK):         tcp.analysis.duplicate_ack
Фильтр 4 (Zero Window):    tcp.analysis.zero_window

Настройка:_Display Interval = 1 сек, Style = Bars
→ Ретрансмиссии будут видны как красные полосы на фоне общего трафика
```

---

## Типы инцидентов и исправления

| Симптом | Вероятная причина | Инструмент проверки | Исправление |
| :--- | :--- | :--- | :--- |
| **Высокий Retrans Rate (>5%)** | Проблемы L1/L2 (плохой кабель, ошибки CRC), перегрузка узлов. | `ethtool -S`, `nstat` | Заменить кабель, проверить NIC, расширить канал. |
| **Рост счетчика Timeouts** | Превышен лимит ретрансмиссий (по умолчанию 15). Сессия закрыта ядром. | `nstat -az TcpExtTCPTimeouts` | Увеличить `tcp_retries2`, проверить маршрут. |
| **Checksum Error** | Ошибки оперативной памяти (ECC) или некорректная работа NIC Offloading. | `nstat -az TcpInCsumErrors` | Отключить checksum offload (`ethtool -K eth0 tx off`), проверить память. |
| **Рост TailLossProbe** | Потери на коротких транзакциях (например, завершение HTTP-ответа). | `nstat -az TcpExtTCPTailLossProbe` | Увеличить `tcp_notsent_lowat`, оптимизировать приложение. |
| **Высокий rtt под нагрузкой** | Bufferbloat: переполнение буферов на маршрутизаторах. | `ss -ti`, `tcprtt` | Включить AQM (fq_codel, CAKE), уменьшить `net.core.rmem_max`. |
| **Zero Window** | Приложение не успевает читать из сокета. | `nstat -az TcpExtTCPWindowFull` | Увеличить `SO_RCVBUF`, оптимизировать обработку. |
| **ListenOverflows / ListenDrops** | Приложение не вызывает `accept()` достаточно быстро. | `nstat -az TcpExtListenOverflows` | Увеличить `somaxconn`, оптимизировать `accept()`. |
| **Spurious RTO** | Ложный таймаут из-за нестабильного RTT. | `nstat -az TcpExtTCPSpuriousRto` | Увеличить `tcp_rto_min` (для локальных сетей: 5 мс). |
| **Высокий Retrans Rate + crc_errors** | Аппаратная проблема NIC или кабеля. | `ethtool -S eth0 \| grep -i crc` | Заменить кабель, обновить драйвер NIC. |

---

## Практические сценарии

### Сценарий 1: Дифференциация типов потерь
- **Случайные потери:** `retrans` растет, но метрика `rtt` в `ss` остается стабильной. Характерно для беспроводных сетей (помехи).
- **Перегрузка (Congestion):** `retrans` растет одновременно с ростом `rtt` и `mdev`. Характерно для переполнения очередей на маршрутизаторах (Bufferbloat).

```bash
# Автоматическое определение типа потерь
#!/bin/bash
DST=${1:-8.8.8.8}
RTT_BASELINE=$(ss -ti dst "$DST" | awk '/rtt:/{print $2}' | cut -d/ -f1)
sleep 5
RTT_NOW=$(ss -ti dst "$DST" | awk '/rtt:/{print $2}' | cut -d/ -f1)
RETRANS=$(ss -ti dst "$DST" | awk '/retrans:/{print $NF}' | cut -d/ -f2)

if [ "$RETRANS" -gt 0 ]; then
    RTT_DIFF=$(echo "$RTT_NOW - $RTT_BASELINE" | bc 2>/dev/null || echo 0)
    if (( $(echo "$RTT_DIFF > 10" | bc -l 2>/dev/null || echo 0) )); then
        echo "PEREGRUZKA: rtt вырос с $RTT_BASELINE до $RTT_NOW мс"
    else
        echo "SLUCHAINYE POTERI: rtt стабильно (~$RTT_BASELINE мс), retrans=$RETRANS"
    fi
else
    echo "NET POTERI"
fi
```

### Сценарий 2: Диагностика отброшенных соединений на приеме
Если внешние клиенты жалуются на обрывы, но `tcpdump` показывает дошедшие пакеты SYN:
```bash
nstat -az TcpExtListenDrops TcpExtListenOverflows
# → TcpExtListenDrops                100                0.0
# → TcpExtListenOverflows            85                 0.0
```
**Интерпретация:** `ListenOverflows` указывает на то, что приложение не успевает вызывать `accept()`, а `ListenDrops` может означать нехватку памяти под структуры сокета.

### Сценарий 3: Поиск причины высокого Retransmission Rate
```bash
#!/bin/bash
# multi_step_diagnose.sh <ip>

IP=${1:-8.8.8.8}
echo "=== Шаг 1: Глобальная статистика ==="
nstat -az | grep -E 'TcpRetransSegs|TcpOutSegs|TcpExtTCPTimeouts|TcpExtTCPFastRetrans'

echo
echo "=== Шаг 2: Состояние соединения ==="
ss -ti dst "$IP"

echo
echo "=== Шаг 3: Проверка NIC ==="
ethtool -S eth0 2>/dev/null | grep -iE 'error|drop|crc' | head -10

echo
echo "=== Шаг 4: Проверка очередей ядра ==="
nstat -az | grep -iE 'Queue|Overflow|Drop|Window'

echo
echo "=== Шаг 5: Retransmission Rate ==="
RETRANS=$(nstat -az TcpRetransSegs 2>/dev/null | awk '/TcpRetransSegs/{print $2}')
OUT=$(nstat -az TcpOutSegs 2>/dev/null | awk '/TcpOutSegs/{print $2}')
if [ "$OUT" -gt 0 ] 2>/dev/null; then
    RATE=$(echo "scale=2; $RETRANS * 100 / $OUT" | bc 2>/dev/null)
    echo "Retransmission Rate: ${RATE}%"
    if (( $(echo "$RATE > 5" | bc -l 2>/dev/null || echo 0) )); then
        echo "!!! ВНИМАНИЕ: Retransmission Rate выше 5% !!!"
    fi
fi
```

### Сценарий 4: Мониторинг Spurious Retransmissions
```bash
# Проверка ложных ретрансмиссий
nstat -az | grep -iE 'Spurious|TCPSpurious'
# → TcpExtTCPSpuriousRtxHostQueues    142    0.0
# → TcpExtTCPSpuriousRto               23    0.0

# Соотношение ложных к общим
TOTAL=$(nstat -az TcpRetransSegs 2>/dev/null | awk '/TcpRetransSegs/{print $2}')
SPURIOUS=$(nstat -az TcpExtTCPSpuriousRto 2>/dev/null | awk '/TcpExtTCPSpuriousRto/{print $2}')
if [ "$TOTAL" -gt 0 ] 2>/dev/null; then
    RATIO=$(echo "scale=2; $SPURIOUS * 100 / $TOTAL" | bc 2>/dev/null)
    echo "Spurious Retransmissions: ${RATIO}% от общих ретрансмиссий"
fi
```

### Сценарий 5: Непрерывный мониторинг всех счетчиков надежности
```bash
#!/bin/bash
# monitor_reliability.sh — непрерывный мониторинг с алертами

THRESHOLD_RETRANS_RATE=5
THRESHOLD_TIMEOUTS=10
INTERVAL=10

echo "=== TCP Reliability Monitor ==="
echo "Retransmission Rate Threshold: ${THRESHOLD_RETRANS_RATE}%"
echo "Timeouts Threshold: ${THRESHOLD_TIMEOUTS} per interval"
echo "Interval: ${INTERVAL}s"
echo

while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

    # Получение счетчиков
    RETRANS=$(nstat -az TcpRetransSegs 2>/dev/null | awk '/TcpRetransSegs/{print $2}')
    OUT=$(nstat -az TcpOutSegs 2>/dev/null | awk '/TcpOutSegs/{print $2}')
    TIMEOUTS=$(nstat -az TcpExtTCPTimeouts 2>/dev/null | awk '/TcpExtTCPTimeouts/{print $2}')
    FAST=$(nstat -az TcpExtTCPFastRetrans 2>/dev/null | awk '/TcpExtTCPFastRetrans/{print $2}')
    TLP=$(nstat -az TcpExtTCPTailLossProbe 2>/dev/null | awk '/TcpExtTCPTailLossProbe/{print $2}')
    CSUM=$(nstat -az TcpInCsumErrors 2>/dev/null | awk '/TcpInCsumErrors/{print $2}')
    SPURIOUS=$(nstat -az TcpExtTCPSpuriousRto 2>/dev/null | awk '/TcpExtTCPSpuriousRto/{print $2}')

    # Расчет Retransmission Rate
    if [ "$OUT" -gt 0 ] 2>/dev/null; then
        RATE=$(echo "scale=2; $RETRANS * 100 / $OUT" | bc 2>/dev/null)
    else
        RATE="0.00"
    fi

    # Вывод
    echo "[$TIMESTAMP] Rate: ${RATE}% | Retrans: $RETRANS | Timeouts: $TIMEOUTS | Fast: $FAST | TLP: $TLP | CsumErr: $CSUM | Spurious: $SPURIOUS"

    # Алерты
    if (( $(echo "$RATE > $THRESHOLD_RETRANS_RATE" | bc -l 2>/dev/null || echo 0) )); then
        echo "  >>> ALERT: Retransmission Rate ${RATE}% превышает порог ${THRESHOLD_RETRANS_RATE}%!"
    fi
    if [ "$TIMEOUTS" -gt "$THRESHOLD_TIMEOUTS" ] 2>/dev/null; then
        echo "  >>> ALERT: Timeouts ${TIMEOUTS} превышают порог ${THRESHOLD_TIMEOUTS}!"
    fi
    if [ "$CSUM" -gt 0 ] 2>/dev/null; then
        echo "  >>> ALERT: Checksum Errors detected!"
    fi

    sleep "$INTERVAL"
done
```

---

## Prometheus / Grafana: алертинг

Для продакшн-мониторинга используйте `node_exporter` сcollector` `tcpstat` и настройте следующие алерты в Prometheus:

```yaml
# alerts/tcp_reliability.yml
groups:
  - name: tcp_reliability
    rules:
      - alert: HighTcpRetransmissionRate
        expr: |
          rate(node_tcp_retrans_segs_total[5m])
          / rate(node_tcp_out_segs_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High TCP retransmission rate on {{ $labels.instance }}"
          description: "Retransmission rate is {{ $value | humanizePercentage }}."

      - alert: TcpRetransmissionSpike
        expr: |
          rate(node_tcp_retrans_segs_total[1m]) > 100
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "TCP retransmission spike on {{ $labels.instance }}"
          description: "Retransmission rate exceeded 100/sec for 2 minutes."

      - alert: TcpTimeoutsIncreasing
        expr: |
          increase(node_tcp_ext_timeouts_total[5m]) > 50
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "TCP timeouts increasing on {{ $labels.instance }}"

      - alert: TcpChecksumErrors
        expr: |
          increase(node_tcp_in_csum_errors_total[5m]) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "TCP checksum errors on {{ $labels.instance }}"
          description: "Checksum errors indicate hardware/memory issues."
```

---

## Production Runbook: Быстрая диагностика TCP

### Чек-лист (5 минут)

```bash
# Шаг 1: Общее состояние TCP-стека
ss -s
# → Обратить внимание на: timewait > 5000, orphaned > 100, syn-recv > 100

# Шаг 2: Проблемные соединения (высокий RTT, мало cwnd, потери)
ss -tin | awk '$4 != "0" || $6 < 10 {print}'
# → Если cwnd < 10: проверить loss, initcwnd, congestion control

# Шаг 3: Переполнение очередей
nstat -az | grep -E 'ListenOverflows|ListenDrops|TCPBacklogDrop'
# → Если ListenOverflows > 0: увеличить somaxconn / backlog приложения

# Шаг 4: Ретрансмиссии и таймауты
nstat -az | grep -E 'TCPRetransSegs|TCPTimeouts|TCPSpuriousRto'
# → Если RetransSegs > 1%: проверить loss на линке (ethtool -S, tc qdisc)

# Шаг 5: Keepalive и закрытие
nstat -az | grep -E 'TCPKeepAlive|TCPAbortOn|TCPTimeWait'
# → Если AbortOn > 0: приложение закрывает соединения (проверить логи)
# → Если TimeWait > 10000: включить tcp_tw_reuse=1

# Шаг 6: ip tcp_metrics (кэш RTT/window)
ip tcp_metrics show | wc -l
# → Если много записей (>1000): проверить актуальность (flush при смене маршрута)

# Шаг 7: conntrack (если используется NAT/firewall)
conntrack -S 2>/dev/null
# → Если insert_failed > 0: увеличить nf_conntrack_max
```

### Интерпретация результатов

| Шаг | Норма | Аномалия | Действие |
| :--- | :--- | :--- | :--- |
| `ss -s` timewait | < 5000 | > 10000 | `tcp_tw_reuse=1`, `ip_local_port_range` расширить |
| `ss -s` syn-recv | < 100 | > 500 | `tcp_syncookies=1`, `tcp_max_syn_backlog` увеличить |
| `ss -tin` cwnd | > 10 | < 5 | Проверить loss (`nstat \| grep Retrans`), сменить CC на BBR |
| ListenOverflows | 0 | > 0 | `somaxconn` увеличить, backlog приложения увеличить |
| RetransSegs (rate) | < 0.1% | > 1% | `ethtool -S eth0` (NIC errors), `tc qdisc show` (queue loss) |
| TCPTimeouts (rate) | < 0.01% | > 0.1% | Проверить firewall (DROP vs REJECT), keepalive time |
| AbortOn | 0 | > 0 | Приложение закрывает соединения — проверить логи |
| conntrack insert_failed | 0 | > 0 | `nf_conntrack_max` увеличить, `nf_conntrack_buckets` увеличить |

---

## Дополнительная информация

### См. также
- **[Production Tuning](../production_tuning.md):** Keepalive, database tuning, ip tcp_metrics, L4 LB, busy polling.
- **[Механизмы ретрансмиссии](./retransmission.md):** Теоретические основы RTO, Fast Retransmit и RACK.
- **[Подтверждения (ACK)](./acknowledgments.md):** Влияние SACK на эффективность восстановления данных.
- **[Контрольная сумма](./checksum.md):** Алгоритм Internet Checksum, Silent Drop, диагностика.
- **[Порядковые номера](./sequence_numbers.md):** PAWS, wrap-around, SYN Cookies.
- **[Скользящее окно](./sliding_window.md):** Flow Control, SWS, Window Scale.
- **[Концепции надежности](./concepts.md):** Архитектура механизмов, QUIC comparison.
- **[Оптимизация TCP в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md):** Параметры тюнинга для снижения потерь.
- **[Диагностика TCP-соединений](../connection/tcp_connection_diagnostics.md):** Анализ состояний соединений.
- **[Диагностика перегрузок](../congestion/tcp_congestion_diagnostics.md):** Анализ cwnd и алгоритмов управления перегрузкой.

### Стандарты (RFC)
- **RFC 6298:** Computing TCP's Retransmission Timer.
- **RFC 6675:** A Conservative Loss Recovery Algorithm based on SACK.
- **RFC 8985:** The TCP Tail Loss Probe (TLP) Algorithm.
- **RFC 4653:** F-RTO: Forward RTO-Recovery (справедливое восстановление после ложного RTO).
- **RFC 3522:** The Eifel Detection Algorithm for TCP.
