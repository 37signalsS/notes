# Скользящее окно в TCP (Sliding Window)

## Определения

**Скользящее окно (Sliding Window)** — фундаментальный механизм протокола TCP, обеспечивающий управление потоком данных (Flow Control) и оптимизацию пропускной способности. Он позволяет отправителю передавать несколько сегментов подряд (пакетами «в полете»), не дожидаясь подтверждения (ACK) для каждого из них.

**Bandwidth-Delay Product (BDP)** — произведение пропускной способности канала (Bandwidth) на время кругового обхода (RTT). BDP определяет максимальный объем данных, который физически может находиться в сети в любой момент времени («в трубе»). Если размер скользящего окна меньше BDP, канал связи будет недоиспользован.

**Effective Window (Эффективное окно)** — реальный объем данных, разрешенный к отправке. Определяется как минимум из двух ограничений: окна получателя (rwnd) и окна перегрузки (cwnd).

**Receiver Window (rwnd)** — размер свободного места в приемном буфере получателя, анонсируемый в каждом ACK-сегменте. Защищает получателя от переполнения.

**Congestion Window (cwnd)** — окно перегрузки, определяемое отправителем. Защищает сеть от перегрузки. Рассчитывается алгоритмами управления перегрузкой (CUBIC, BBR).

---

## Окно отправителя (Sender Window)

### Структура

Окно представляет собой логический буфер, разделенный указателями на 4 зоны:

```text
               ◄────────────── Окно (Window) ──────────────►
               ┌───────────────────────┬───────────────────┐
 подтверждено  │      в полете         │  можно отправить  │  нельзя
 (отброшено)   │ (отправлено, без ACK) │ (в рамках лимита) │ (вне окна)
               └───────────────────────┴───────────────────┘
               ▲                       ▲                   │
               │                       │                   │
         LastByteAcked           LastByteSent       LastByteAcked + Win
```

- **Левая граница (Left Edge):** Сдвигается вправо при получении новых подтверждений (ACK). Все байты левее границы подтверждены и могут быть удалены из буфера отправителя.
- **Правая граница (Right Edge):** Рассчитывается как `Левая граница + Effective Window`. Сдвигается вправо, открывая возможность для отправки новых данных.
- **In-flight Window:** `LastByteSent - LastByteAcked` — объем данных, отправленных, но еще не подтвержденных. Не может превышать `min(cwnd, rwnd)`.

### Состояния окна отправителя

```text
┌─────────────────────┐
│  Старт соединения   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Slow Start         │  cwnd = initcwnd (обычно 10 MSS)
│  (Экспоненциальный  │  cwnd *= 2 за RTT
│   рост)             │  Отправка = min(cwnd, rwnd)
└─────────┬───────────┘
          │ cwnd >= ssthresh
          ▼
┌─────────────────────┐
│ Congestion Avoidance│  cwnd += MSS²/cwnd  (линейный рост)
│ (Линейный рост)     │  Отправка = min(cwnd, rwnd)
└─────────┬───────────┘
          │ потеря пакета
          ▼
┌─────────────────────────────┐
│ Recovery (Fast Retransmit)  │  ssthresh = cwnd/2
│ или RTO                     │  cwnd = ssthresh (Fast Recovery)
│                             │  cwnd = 1 MSS (RTO)
└─────────────────────────────┘
```

---

## Окно получателя (Receiver Window)

### Структура

Получатель поддерживает собственное окно для контроля того, сколько данных отправитель может отправить, не переполняя приемный буфер:

```text
◄────────────── Окно получателя ──────────────►
┌──────────────────┬──────────────────────────┐
│  принято         │  свободное место         │  ожидает
│  (в буфере)      │  (доступно для приема)   │  (недоступно)
└──────────────────┴──────────────────────────┘
▲                                        ▲
│                                        │
RCV.NXT                         RCV.NXT + RCV.WND
(следующий                    (предел окна:
 ожидаемый                     RCV.NXT + rwnd)
 номерSeq)
```

- **RCV.NXT:** Следующий ожидаемый порядковый номер. Сдвигается вправо при получении данных.
- **RCV.WND:** Текущий размер окна接收者. Вычисляется как `бюфер_приема - (последний_принятый_байт - последний_переданный_приложению_байт)`.
- **Анонсирование:** Получатель передает `rwnd` в каждом ACK через поле `Window Size` заголовка TCP.

### Правила анонсирования окна (RFC 813, RFC 1122)

1. **Delayed ACK + Window Update:** Получатель может задерживать ACK до 500 мс (RFC 1122). Если окно обновилось, Window Update отправляется немедленно, даже если ACK задерживается.
2. **Zero Window Advertisement:** Если буфер заполнен, получатель отправляет ACK с `rwnd = 0`. Отправитель должен остановить передачу.
3. **Window Update после Zero Window:** Когда приложение прочитало данные из буфера, получатель отправляет ACK с обновленным `rwnd`. Этот ACK может прийти после потери — отсюда необходимость Persist Timer.
4. **Согласование Window Scale:** Значение `wscale` согласовывается только в SYN/SYN-ACK. После handshake оно фиксируется и не может измениться.

---

## Взаимодействие cwnd и rwnd

Реальное количество данных, которое TCP разрешает отправить в сеть, жестко ограничено двумя факторами:

```text
Effective Window = min(cwnd, rwnd)
В полете можно держать: (LastByteSent - LastByteAcked) <= min(cwnd, rwnd)
```

**Три сценария взаимодействия:**

| Сценарий | Условие | Ограничитель | Что происходит |
| :--- | :--- | :--- | :--- |
| **Сеть загружена** | `rwnd > cwnd` | cwnd | Отправитель адаптируется через CUBIC/BBR. rwnd получателя избыточен. |
| **Получатель медленный** | `rwnd < cwnd` | rwnd | Отправитель ограничен буфером получателя. Нет повышения пропускной способности. |
| **Идеальное равновесие** | `rwnd = cwnd` | оба | Максимальная пропускная способность. Канал полностью загружен. |

**Throughput ceiling (потолок пропускной способности):**
```text
Max Throughput = min(rwnd, cwnd) / RTT

Пример:
  rwnd = 256 КБ, cwnd = 1 МБ, RTT = 50 мс
  Max Throughput = 256 * 1024 / 0.05 = 5.12 Мбит/с

  Если увеличить rwnd до 1 МБ:
  Max Throughput = 1 * 1024 * 1024 / 0.05 = 20.48 Мбит/с
```

---

## Масштабирование окна (Window Scale)

### Проблема

В классическом TCP 16-битное поле `Window Size` ограничивает максимальное окно значением 65 535 байт (64 КБ). На каналах с высокой пропускной способностью и задержкой (например, 1 Гбит/с и RTT 100 мс, где BDP ~ 12.5 МБ) это станет «узким горлышком» (bottleneck).

### Решение (RFC 7323)

Введена опция **Window Scale (WSCALE)**. Она передает множитель сдвига (степень двойки от 0 до 14):

```text
Истинное окно = Window Size * 2^wscale
Максимальное окно = 65 535 * 2^14 = 1 073 725 440 байт (~1 ГБ)
```

**Примеры:**

| `wscale` | Множитель | Макс. окно | Типичный сценарий |
| :--- | :--- | :--- | :--- |
| 0 | x1 | 64 КБ | Старые системы, нет negotiation |
| 7 | x128 | 8 МБ | Серверы по умолчанию (Linux) |
| 9 | x512 | 32 МБ | Высокоскоростные линки |
| 14 | x16384 | 1 ГБ | Суперкомпьютеры, deep LFN |

### Краевые случаи Window Scale

1. **Middlebox stripping:** Некоторые промежуточные устройства (firewall, NAT) удаляют опцию Window Scale из SYN/SYN-ACK. Результат: `wscale:0,0` в `ss`, окно ограничено 64 КБ. **Диагностика:** `ss -ti dst <IP> | grep wscale` — если `0,0` при high-BDP канале, middlebox виноват.

2. **wscale mismatch:** Если клиент отправляет `wscale=7`, а сервер — `wscale=9`, каждая сторона масштабирует по-своему. Это нормально — `wscale` применяется только к собственному rwnd.

3. **Потеря Window Scale в SYN:** Если SYN-ACK с опцией Window Scale потерян, после retransmit handshake может не согласовать wscale. Результат: окно без масштабирования, катастрофически низкая скорость на LFN.

4. **Non-Scale Window:** Если в `ss -ti` нет `wscale` — окно не масштабируется. Причины: старое ядро, middlebox stripping, или опция не согласована.

---

## Проблема «глупого окна» (Silly Window Syndrome)

**SWS (Silly Window Syndrome)** — ситуация деградации производительности, когда из-за медленного чтения приложением или медленной генерации данных, сегменты отправляются микроскопическими порциями (например, по 1 байту). При этом накладные расходы (40 байт заголовков IP/TCP) превышают полезную нагрузку в 40 раз.

### Решение на стороне получателя (Алгоритм Кларка)

Получатель (алгоритм Дэвида Кларка) не должен объявлять увеличение окна (`rwnd`), пока свободное место в его буфере не достигнет:
- Либо размера **MSS** (Maximum Segment Size).
- Либо половины от общего размера буфера приема.

До достижения этого порога получатель должен анонсировать старое (меньшее) значение окна, либо `rwnd = 0`, заставляя отправителя копить данные.

### Решение на стороне отправителя (Алгоритм Нагла)

Отправитель (алгоритм Джона Нагла) предотвращает отправку множества мелких пакетов. Он задерживает отправку данных, меньших чем MSS, если в сети уже есть неподтвержденные данные (unacknowledged data).
- *Подробнее:* Описание конфликтов с Delayed ACK см. в [Алгоритм Нагла](../tcp_nagle_algorithm.md).

### Влияние tcp_adv_win_scale

Параметр `net.ipv4.tcp_adv_win_scale` определяет, какая доля буфера приема выделяется под application overhead (заголовки, bookkeeping):

```text
Доступный для данных объем:
  Если tcp_adv_win_scale > 0: buffer / 2^tcp_adv_win_scale
  Если tcp_adv_win_scale <= 0: buffer - buffer / 2^(-tcp_adv_win_scale)

По умолчанию tcp_adv_win_scale = 2:
  Данные = buffer / 4   <-- 75% буфера для overhead
  rwnd = buffer / 4     <-- 25% буфера для данных

Пример: buffer = 87380 байт
  Данные = 21845 байт --> rwnd = 21845 * 2^wscale
```

> **См. также:** [Flow Control](../Flow_Control/index.md) — полный разбор `tcp_adv_win_scale`, autotuning, Docker/Kubernetes tuning.

---

## Zero Window, Persist Timer и Window Probe

### Zero Window

Когда получатель не может принять данные (приложение медленно читает из сокета), он отправляет ACK с `rwnd = 0`:

```text
Отправитель                       Получатель
    |                                 |
    |---- data ---------------------->|
    |                                 | (буфер полон)
    |<--- ACK, rwnd=0 ---------------|
    |                                 |
    |   (stop sending)                |
    |                                 | (приложение прочитало 10 КБ)
    |<--- ACK, rwnd=10240 -----------|  <-- Window Update
    |                                 |
    |---- data ---------------------->|
```

**Проблема:** Если ACK с `rwnd > 0` (Window Update) будет потерян, соединение зависит (deadlock) — отправитель ждет разрешения, получатель ждет данные.

### Persist Timer и Zero Window Probe

**Persist Timer** предотвращает deadlock. По истечении таймера отправитель отправляет **Zero Window Probe** — маленький сегмент (обычно 1 байт данных), чтобы спровоцировать получателя на ответ с актуальным `rwnd`:

```text
Отправитель                       Получатель
    |                                 |
    |   ( Persist Timer expires )     |
    |---- Probe (1 byte) ------------>|
    |<--- ACK, rwnd=0 ---------------|  (всё еще полон)
    |                                 |
    |   (RTO * 2, exp. backoff)      |
    |---- Probe (1 byte) ------------>|
    |<--- ACK, rwnd=2048 ------------|  (окно освободилось!)
    |                                 |
    |---- data (normal) ------------->|
```

**Persist Timer Backoff:**
```text
Persist Timer = RTO * 2^n, где n = количество probe без ответа
Минимум: обычно 5 сек (RFC 1122 рекомендует 5-60 сек)
Максимум: 60 сек (по умолчанию в Linux: tcp_probe_interval=60)
```

### Window Full vs Zero Window

| Параметр | Window Full | Zero Window |
| :--- | :--- | :--- |
| **Определение** | Отправитель исчерпал rwnd, но передача продолжается (ACK в пути) | Получатель объявил rwnd = 0 |
| **Wireshark фильтр** | `tcp.analysis.window_full` | `tcp.analysis.zero_window` |
| **Причина** | Естественное поведение (ACK задерживается) | Приложение медленно читает из сокета |
| **Действие** | Отправитель ждет ACK | Отправитель останавливается, запускает Persist Timer |
| **Нормально?** | Да (редко, при высокой нагрузке) | Нет — симптом проблемы в приложении |

---

## BDP: расчет и практические примеры

### Формула

```text
BDP = Bandwidth * RTT

Max Throughput = min(rwnd, cwnd) / RTT
Необходимый rwnd = Bandwidth * RTT  (чтобы заполнить "трубу")
```

### Примеры для реальных сетей

| Сеть | Bandwidth | RTT | BDP | Необходимый rwnd | wscale | Мин. буфер |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **LAN (1Gbps)** | 1 Гбит/с | 0.5 мс | 62.5 КБ | 62.5 КБ | 0 | 64 КБ |
| **LAN (10Gbps)** | 10 Гбит/с | 0.1 мс | 125 КБ | 125 КБ | 0 | 128 КБ |
| **WiFi** | 100 Мбит/с | 5 мс | 625 КБ | 625 КБ | 3 | 512 КБ |
| **DSL** | 20 Мбит/с | 30 мс | 750 КБ | 750 КБ | 3 | 1 МБ |
| **4G/LTE** | 50 Мбит/с | 50 мс | 3.12 МБ | 3.12 МБ | 5 | 4 МБ |
| **Inter-DC (50ms)** | 1 Гбит/с | 50 мс | 6.25 МБ | 6.25 МБ | 6 | 8 МБ |
| **Inter-DC (100ms)** | 10 Гбит/с | 100 мс | 125 МБ | 125 МБ | 14 | 128 МБ |
| **Satellite** | 100 Мбит/с | 600 мс | 7.5 МБ | 7.5 МБ | 7 | 8 МБ |

### Быстрый расчет

```bash
# Формула: rwnd_bytes = Bandwidth_bps * RTT_sec
# Пример: 100 Мбит/с, 50 мс RTT
echo "scale=0; 100000000 * 0.05 / 8" | bc
# --> 625000 байт = 610 КБ --> нужен rwnd >= 610 КБ
```

---

## Взаимодействие окна с ретрансмиссией

Скользящее окно напрямую влияет на поведение ретрансмиссий:

1. **Retransmission Unambiguity:** При потере ACK отправитель не знает, какие данные подтверждены. Скользящее окно определяет, какие сегменты можно ретрансмитировать (в пределах окна).

2. **Window Shrinking:** Если получатель уменьшил `rwnd` (объявил меньшее окно), отправитель должен сократить окно. Это может привести к «замораживанию» части данных, которые уже в полете.

3. **Recovery + Window:** В фазе Fast Recovery (RFC 5681) `cwnd` временно уменьшается. Если `rwnd` также мал, эффект مضется — отправитель почти не может передавать.

4. **Retransmission Window:** При RTO `cwnd` сбрасывается до 1 MSS. Если `rwnd` также = 1 MSS, передача почти остановлена.

```bash
# Проверка текущего состояния окна в соединении
ss -ti dst 8.8.8.8
# --> cubic rto:204 rtt:15.2/0.5 cwnd:10 rwnd:65536 snd_wnd:32768 rcv_space:14600
#     |         |         |       |        |            |
#     |         |         |       |        |            +--rcv_space: текущий rwnd
#     |         |         |       |        +--snd_wnd: размер отправительского окна
#     |         |         |       +--rwnd: объявленный получателем
#     |         |         +--cwnd: текущее окно перегрузки
#     |         +--rtt: время round-trip
#     +--rto: текущий RTO timeout
```

---

## Автоматическая настройка (TCP Autotuning)

### Механизм

Linux ядро автоматически настраивает размеры буферов на основе текущих условий сети:

```text
tcp_rmem = [min] [default] [max]
  +-- min:    Минимальный rwnd (обычно 4 КБ)
  +-- default: Начальный rwnd при установке соединения
  +-- max:    Максимальный rwnd (autotuning может достичь этого значения)

tcp_wmem = [min] [default] [max]
  +-- min:    Минимальный sndbuf
  +-- default: Начальный sndbuf
  +-- max:    Максимальный sndbuf
```

```bash
# Просмотр текущих значений
sysctl net.ipv4.tcp_rmem
# --> net.ipv4.tcp_rmem = 4096 131072 6291456

sysctl net.ipv4.tcp_wmem
# --> net.ipv4.tcp_wmem = 4096 16384 4194304

# Включение автоподстройки receive buffer (по умолчанию включено)
sysctl net.ipv4.tcp_moderate_rcvbuf
# --> net.ipv4.tcp_moderate_rcvbuf = 1
```

> **См. также:** [Flow Control](../Flow_Control/index.md) — полный разбор autotuning, DRS (Dynamic Receiver Sizing), sysctl параметры.

### tcp_notsent_lowat

Параметр `TCP_NOTSENT_LOWAT` определяет, сколько неотправленных данных может накапливаться в очереди сокета до того, как `poll()`/`select()`/`epoll()` сообщит о готовности записи:

```text
TCP_NOTSENT_LOWAT = 0   (по умолчанию) --> все буферы доступны для записи
TCP_NOTSENT_LOWAT = N   --> poll() вернет writable когда notsent <= N
```

**Зачем нужно:** Без ограничения `notsent` приложение может заполнить весь буфер отправки, увеличивая задержку (bufferbloat на уровне приложения). Установка `TCP_NOTSENT_LOWAT = 16384` (16 КБ) обеспечивает низкую задержку при высокой пропускной способности.

```bash
# Установка через setsockopt (в коде приложения)
setsockopt(fd, IPPROTO_TCP, TCP_NOTSENT_LOWAT, &val, sizeof(val));

# Или через sysctl (глобально, для всех соединений)
sudo sysctl -w net.ipv4.tcp_notsent_lowat=16384
```

> **См. также:** [Flow Control](../Flow_Control/index.md) — полный разбор `tcp_notsent_lowat`,的影响 на производительность.

---

## Практические сценарии

### Сценарий 1: Низкая скорость из-за отсутствия Window Scale

```bash
# Симптом: клиент reports низкую скорость (1-5 Мбит/с вместо 100 Мбит/с)
ss -ti dst 1.2.3.4
# --> cubic rto:204 rtt:15.2/0.5 cwnd:1000 rwnd:65535 rcv_space:14600
#                                                            ^^^^^^^^^^^
#                                                            rwnd = 65535 = 64 КБ (не масштабируется!)

# Диагностика: проверка wscale
ss -ti dst 1.2.3.4 | grep wscale
# --> wscale:7,7    (нормально)  ИЛИ  wscale:0,0  (проблема!)

# Решение:
# 1. Если wscale:0,0 -- middlebox stripping. Обновить firmware firewall/NAT.
# 2. Если wscale:7,7 -- проблема в другом месте (проверить rwnd).
```

### Сценарий 2: Ограничение через rwnd (получатель медленный)

```bash
# Симптом: cwnd растет, но rwnd мал
ss -ti dst 1.2.3.4
# --> cwnd:5000 rwnd:14600 rcv_space:14600
#     ^^^^^^                 ^^^^^^^^^^^
#     cwnd огромный          rwnd = 14600 = ~10 MSS

# Причина: приложение-получатель медленно читает из recv buffer
# Решение (на стороне получателя):
# 1. Увеличить SO_RCVBUF
setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &(int){1048576}, sizeof(int));

# 2. Или увеличить tcp_rmem max
sudo sysctl -w net.ipv4.tcp_rmem="4096 131072 16777216"

# 3. Проверить, что автоподстройка включена
sysctl net.ipv4.tcp_moderate_rcvbuf  # --> должен быть 1
```

### Сценарий 3: Zero Window + Persist Probe

```bash
# Диагностика Zero Window через tshark
tshark -r capture.pcap -Y "tcp.analysis.zero_window" -T fields \
  -e frame.time -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport \
  -e tcp.window_size_value 2>/dev/null | head -5

# Поиск Persist Probes
tshark -r capture.pcap -Y "tcp.analysis.zero_window_probe" -T fields \
  -e frame.time -e ip.src -e ip.dst -e tcp.len 2>/dev/null | head -5

# Непрерывный мониторинг Zero Window на сервере
while true; do
    nstat -az 2>/dev/null | awk '/TcpExtTCPWindowFull/{printf "WindowFull: %s ", $2} /TcpExtListenDrops/{printf "ListenDrops: %s\n", $2}'
    sleep 5
done
```

### Сценарий 4: Проверка BDP и подбор параметров

```bash
# Измерение RTT и расчет необходимого rwnd
RTT=$(ss -ti dst 8.8.8.8 | grep -oP 'rtt:\K[0-9.]+' | head -1)
BW_MBPS=100  # предполагаемая пропускная способность в Мбит/с

if [ -n "$RTT" ]; then
    RTT_SEC=$(echo "scale=6; $RTT / 1000" | bc)
    BDP_BYTES=$(echo "scale=0; $BW_MBPS * 1000000 * $RTT_SEC / 8" | bc)
    echo "RTT: ${RTT} мс, BDP: ${BDP_BYTES} байт"
    echo "Необходимый rwnd >= ${BDP_BYTES} байт"
    echo "Необходимый wscale >= $(echo "l($BDP_BYTES/65535)/l(2)" | bc -l 2>/dev/null | cut -d. -f1)"
fi
```

### Сценарий 5: Мониторинг autotuning через ss

```bash
# Мониторинг динамики окна в реальном времени
watch -n 1 'ss -ti dst 8.8.8.8 | head -3'

# Логирование изменений rwnd/cwnd
while true; do
    ts=$(date +%H:%M:%S)
    vals=$(ss -ti dst 8.8.8.8 | head -1 | awk '{
        for(i=1;i<=NF;i++) {
            if($i ~ /cwnd:/) printf "cwnd=%s ", $i
            if($i ~ /rwnd:/) printf "rwnd=%s ", $i
            if($i ~ /rcv_space:/) printf "rcv_space=%s ", $i
            if($i ~ /snd_wnd:/) printf "snd_wnd=%s ", $i
        }
    }')
    echo "$ts $vals"
    sleep 2
done | tee window_log.txt
```

---

## Справочник sysctl

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_rmem` | 4096 131072 6291456 | Минимальный/начальный/максимальный receive buffer. |
| `net.ipv4.tcp_wmem` | 4096 16384 4194304 | Минимальный/начальный/максимальный send buffer. |
| `net.ipv4.tcp_moderate_rcvbuf` | 1 | Автоматическая настройка receive buffer (autotuning). |
| `net.ipv4.tcp_adv_win_scale` | 2 | Доля буфера для overhead. Данные = buffer / 2^wscale. |
| `net.ipv4.tcp_notsent_lowat` | 0xFFFFFFFF (все) | Лимит неотправленных данных для poll() writable. |
| `net.core.rmem_max` | 212992 | Максимальный размер receive buffer (ограничение setsockopt). |
| `net.core.wmem_max` | 212992 | Максимальный размер send buffer (ограничение setsockopt). |
| `net.core.rmem_default` | 212992 | Receive buffer по умолчанию. |
| `net.core.wmem_default` | 212992 | Send buffer по умолчанию. |
| `net.ipv4.tcp_window_scaling` | 1 | Window Scale (RFC 7323). Включать всегда. |
| `net.ipv4.tcp_timestamps` | 1 | TCP Timestamps (RFC 7323). Нужен для PAWS и Eifel. |

---

## Диагностика

### Инструменты

| Инструмент | Назначение | Пример |
| :--- | :--- | :--- |
| `ss -ti` | Состояние окна (cwnd, rwnd, wscale, rcv_space, snd_wnd) | `ss -ti dst 8.8.8.8` |
| `nstat` | Глобальные счетчики (WindowFull, ListenDrops) | `nstat -az \| grep -i window` |
| `tshark` | Анализ дампов (zero_window, window_full, window_update) | `tshark -r cap.pcap -Y "tcp.analysis.zero_window"` |
| `Wireshark IO Graph` | Визуализация window size по времени | IO Graph с фильтром `tcp.window_size` |

### Быстрый старт

```bash
# 1. Проверка текущего состояния окна
ss -ti dst <IP>

# 2. Проверка global window-related counters
nstat -az | grep -iE 'WindowFull|ListenOverflows|ListenDrops'

# 3. Поиск Zero Window в дампе
tshark -r capture.pcap -Y "tcp.analysis.zero_window" 2>/dev/null | head -5

# 4. Проверка Window Full
tshark -r capture.pcap -Y "tcp.analysis.window_full" 2>/dev/null | head -5

# 5. Проверка Window Update
tshark -r capture.pcap -Y "tcp.analysis.window_update" 2>/dev/null | head -5
```

> **См. также:** [Диагностика надежности](./diagnostics.md) — полный каталог счетчиков `nstat`, eBPF-инструменты, tcpdump/tshark фильтры, Prometheus/Grafana алерты.

---

## Дополнительная информация

### См. также
- **[Управление потоком (Flow Control)](../Flow_Control/index.md)** — концептуальная база защиты буферов, autotuning, Docker/Kubernetes tuning.
- **[Управление перегрузкой (Congestion Control)](../congestion/tcp_congestion_control_overview.md)** — механизмы расчета окна сети `cwnd`.
- **[Опции заголовка TCP](../Header_Format/options.md)** — битовая структура опции Window Scale.
- **[Повторная передача (Retransmission)](./retransmission.md)** — как rwnd/cwnd влияют на поведение ретрансмиссий.
- **[Концепции надежности](./concepts.md)** — архитектура механизмов, взаимодействие компонентов.
- **[Диагностика](./diagnostics.md)** — мониторинг WindowFull, Zero Window, autotuning.

### Стандарты (RFC)
- **RFC 9293:** Transmission Control Protocol (актуальный стандарт).
- **RFC 7323:** TCP Extensions for High Performance (Window Scale, PAWS, Timestamps).
- **RFC 1122:** Requirements for Internet Hosts (SWS, Nagle, Clark, Persist Timer).
- **RFC 813:** Window Scale and Persist Timer (SWS prevention).
- **RFC 5681:** TCP Congestion Control (cwnd interaction with window).
