# Порядковые номера в TCP (Sequence Numbers)

## Определения

**Порядковый номер (Sequence Number)** — 32-битное беззнаковое целое число в заголовке TCP, идентифицирующее позицию первого байта данных конкретного сегмента в общем потоке. TCP рассматривает передаваемые данные как непрерывную ленту байтов, где каждому байту присвоен уникальный номер.

**Начальный порядковый номер (Initial Sequence Number, ISN):** Значение, выбираемое каждой стороной (клиентом и сервером) при установке соединения (флаг SYN). Согласно **RFC 6528**, ISN генерируется с использованием криптографически стойкого PRNG, чтобы предотвратить атаки предсказания номеров (Session Hijacking).

**Sequence Number Space (Пространство порядковых номеров):** 32-битное поле, принимающее значения от `0` до `2^32 - 1` (4 294 967 295). Номера образуют циклическое пространство: после `2^32 - 1` следующее значение — `0`. Любой сегмент в потоке идентифицируется уникальным порядковым номером первого байта его полезной нагрузки.

---

## Пространство порядковых номеров (Sequence Number Space)

### Визуализация

32-битное поле TCP заголовка образует циклическое пространство:

```text
        0                                    2^32 - 1
        |                                      |
        ▼                                      ▼
   ┌────────────────────────────────────────────────┐
   │  0  1  2  3  ...  ...  ...  4294967293  4294967294  4294967295  │
   └────────────────────────────────────────────────┘
        ▲                                              │
        └──────────── wrap-around ─────────────────────┘
```

### Классификация сегментов по номеру порядка

Каждый сегмент TCP classified по отношению к текущему `rcv_nxt` (ожидаемому порядковому номеру) получателя:

```text
                    ◄── Окно приема ──►
   ─────────────────────────────────────────────────────────────
   │  Устаревшие     │  Принятые        │  Ожидаемые    │ Будущие  │
   │  (old/obsolete) │  (received)      │  (expected)   │          │
   ─────────────────────────────────────────────────────────────
                    ▲                   ▲
               rcv_nxt                rcv_nxt + rcv_wnd
```

- **Old/Obsolete:** `seq < rcv_nxt` — сегмент уже был принят или устарел. Отбрасывается (дубликат).
- **In-window (Попадающие в окно):** `rcv_nxt ≤ seq < rcv_nxt + rcv_wnd` — сегмент попадает в текущее окно приема. Данные принимаются.
- **Future (Будущие):** `seq ≥ rcv_nxt + rcv_wnd` — сегмент за пределами окна. Отбрасывается (Window Update required).

---

## Правила инкрементации (Виртуальные байты)

Порядковый номер увеличивается пропорционально количеству переданных байтов полезной нагрузки. Однако управляющие флаги также потребляют номерное пространство:

### Стоимость каждого типа сегмента

| Тип сегмента | Потребление порядкового номера | Пример |
| :--- | :--- | :--- |
| **SYN** | 1 виртуальный байт | `seq=1000` → следующий `seq=1001` |
| **FIN** | 1 виртуальный байт | `seq=1000` → следующий `seq=1001` |
| **Данные** |等于 данных (payload length) | `seq=1000, len=1460` → следующий `seq=2460` |
| **RST** | 0 байт (не потребляет) | `seq=1000` → следующий `seq=1000` |
| **ACK без данных** | 0 байт (не потребляет) | `seq=1000` → следующий `seq=1000` |

### Пример полного обмена

```text
Клиент → Сервер:  SYN, seq=1000                  (SYN: +1)
Сервер → Клиент:  SYN-ACK, seq=5000, ack=1001    (SYN: +1)
Клиент → Сервер:  ACK, seq=1001, ack=5001        (ACK без данных: +0)
Клиент → Сервер:  PSH, seq=1001, len=100         (данные: +100)
Сервер → Клиент:  ACK, seq=5001, ack=1101        (ACK без данных: +0)
Клиент → Сервер:  FIN, seq=1101                  (FIN: +1)
Сервер → Клиент:  ACK, seq=5001, ack=1102        (ACK без данных: +0)
```

---

## Начальный порядковый номер (ISN)

### Алгоритм генерации (RFC 6528)

ISN генерируется с использованием криптографически стойкого PRNG. Основные принципы:

```text
ISN = MD5( 5-tuple + secret ) + (ticks / 4)
```

- **5-tuple:** `{source IP, destination IP, source port, destination port}` — уникальная идентификация соединения.
- **secret:** Случайный 32-битный ключ ядра, генерируемый при каждой перезагрузке.
- **ticks / 4:** Увеличение ISN на 1 каждые 4 микросекунды (μs) — защита от атак предсказания.

### Свойства ISN

1. **Случайность:** Невозможно предсказать ISN соединения, не зная секрета ядра.
2. **Уникальность:** Два соединения с одинаковым 5-tuple получают разные ISN (за счет времени и секрета).
3. **Монотонность:** ISN всегда увеличивается на 1 каждые 4 μs для данного 5-tuple.
4. **Защита от Session Hijacking:** Злоумышленник не может угадать ISN, чтобы подменить пакет.

### Согласование ISN в 3-way handshake

```text
Клиент:  SYN, seq=ISN_C
           │
           ▼
Сервер:  SYN-ACK, seq=ISN_S, ack=ISN_C + 1
           │                           ▲
           │                     (+1: потребление виртуального
           │                      байта SYN)
           ▼
Клиент:  ACK, seq=ISN_C + 1, ack=ISN_S + 1
```

---

## Обертывание счетчика (Wrap-around)

### Математика

При непрерывной передаче 32-битный счетчик порядковых номеров переполняется через 2^32 сегментов (не байтов, а порядковых номеров). Время до wrap-around зависит от пропускной способности:

```text
Wrap-around time = (2^32 × 8) / Bandwidth (в секундах)
```

### Расчет для различных скоростей

| Скорость канала | Время wrap-around | Риск |
| :--- | :--- | :--- |
| 10 Mbps | ~572 сек (~9.5 мин) | Низкий |
| 100 Mbps | ~57 сек | Средний |
| 1 Gbps | ~5.7 сек | Высокий |
| 10 Gbps | ~0.57 сек | Критический |
| 40 Gbps | ~0.14 сек | Критический |
| 100 Gbps | ~0.057 сек | Критический |

### Пример расчета (1 Gbps)

```text
Bits per second = 1 × 10^9 = 1 000 000 000
Time for 2^32 seq numbers = (2^32 × 8) / 10^9
                          = (4 294 967 296 × 8) / 10^9
                          ≈ 34.36 сек
                          ≈ 5.7 сек (для 32-битного seq space)

Замечание: Формула учитывает, что каждый байт = 1 seq number.
На практике: 1 Gbps / 8 = 125 МБ/с. 4 294 967 296 / 125 000 000 ≈ 34.4 сек
```

### Защита от wrap-around: PAWS (RFC 7323)

**PAWS (Protection Against Wrapped Sequence numbers)** решает проблему wrap-around:

- **Условие:** Требует обязательного использования опции **TCP Timestamps**.
- **Логика:** Каждый сегмент несет метку времени отправителя. Если входящий пакет имеет `seq`, попадающий в текущее окно, но его метка времени (`TSval`) меньше, чем последняя принятая метка для этого соединения, пакет отбрасывается как устаревший дубликат.
- **Точность:** Timestamps обновляются каждые 10 мс (Linux). Защита до wrap-around в ~24.8 дней (необходимоrequent reconnections или PAWS).

---

## Порядковый номер в разных фазах соединения

### SYN (Установление соединения)

```text
SYN_SENT:
  snd_una = ISN          (последний подтвержденный байт)
  snd_nxt = ISN + 1      (следующий для отправки)
  rcv_nxt = undefined    (ожидаем получение ISN сервера)

После получения SYN-ACK:
  snd_una = ISN          (SYN подтвержден)
  rcv_nxt = ISN_S + 1    (ISN сервера + потребленный виртуальный байт)
```

### ESTABLISHED (Передача данных)

```text
snd_una:  Последний подтвержденный байт (ACK Number от получателя)
snd_nxt:  Следующий байт для отправки
rcv_nxt:  Следующий ожидаемый байт от отправителя

Пример:
  snd_una = 1000     ← получатель подтвердил до 1000
  snd_nxt = 5000     ← отправили до 5000
  rcv_nxt = 2000     ← ожидаем байт 2000 от отправителя

  In-flight: snd_nxt - snd_una = 4000 байт
  Свободное место: rwnd - in_flight
```

### FIN_WAIT / CLOSE_WAIT (Закрытие соединения)

```text
Активное закрытие (FIN_WAIT_1):
  snd_nxt += 1        (FIN потребляет 1 виртуальный байт)
  snd_una ожидает ACK на FIN

Пассивное закрытие (CLOSE_WAIT):
  rcv_nxt += 1        (FIN потребляет 1 виртуальный байт)
  Отправляем FIN, snd_nxt += 1
```

### RST (Сброс соединения)

```text
RST не потребляет порядковый номер:
  seq RST =任意值 (обычно 0 или текущий snd_nxt)
  ACK на RST не генерируется
```

---

## Out-of-order сегменты

### Механизм

При потере или задержке одного сегмента в цепочке, получатель получает сегменты с порядковыми номерами, превышающими ожидаемый (`rcv_nxt`). Эти сегменты называются **out-of-order**:

```text
Отправитель:  Seg1(seq=1000) → Seg2(seq=2000) → Seg3(seq=3000)
Потеря Seg2!
Получатель:   Seg1(seq=1000) → OK, rcv_nxt=2000
              Seg3(seq=3000) → Out-of-order! Ожидается seq=2000
```

### Поведение получателя

1. **Out-of-order сегмент:** Принимается в буфер, но ACK генерируется для `rcv_nxt` (= 2000), а не для `rcv_nxt + len`.
2. **Duplicate ACK:** Каждый последующий out-of-order сегмент генерирует Duplicate ACK (ACK с тем же номером, что и предыдущий).
3. **После получения потерянного сегмента:** `rcv_nxt` сдвигается вправо на всю длину накопленных данных, ACK обновляется.

### Пример с SACK

```text
Получатель получил: Seg1(1000-2000), Seg3(3000-4000), Seg4(4000-5000)

ACK: ack=2000, sack {3000:5000}
     ▲         ▲
     │         │
  rcv_nxt    SACK-блок: принятые данные [3000, 5000)
  (ожидается 2000)
```

---

## Порядковый номер и ретрансмиссия

### Fast Retransmit (RFC 5681)

```text
Получатель генерирует 3 Duplicate ACK:
  ACK1: ack=2000 (Seg1 принят, Seg2 потерян)
  ACK2: ack=2000 (Seg3 принят, ожидаем Seg2)
  ACK3: ack=2000 (Seg4 принят, ожидаем Seg2)

Отправитель:
  1. Получает 3-й DupACK → обнаруживает потерю
  2. Ретрансмитирует Seg2 (seq=2000) БЕЗ ожидания таймера
  3. ssthresh = cwnd / 2
  4. cwnd = ssthresh + 3 MSS (Fast Recovery)
```

### RTO (Retransmission Timeout)

```text
Таймер RTO истекает без ACK:
  1. Ретрансмитируется сегмент с seq = snd_una (первый неподтвержденный)
  2. cwnd = 1 MSS (Slow Start)
  3. ssthresh = cwnd / 2
  4. Таймер RTO удваивается (экспоненциальный backoff)
```

### Partial ACK в Recovery (NewReno)

```text
В Recovery (Fast Recovery), ACK подтверждает часть потерянных данных:
  Вход в recovery: snd_una=1000, lost=[2000, 3000]
  Partial ACK: ack=2500 (подтверждено 2000-2500)
  → Ретрансмит следующий потерянный сегмент (seq=3000)
  → Не выход из Recovery до получения ACK, покрывающего все потерянное
```

---

## Практические сценарии

### Сценарий 1: Проверка абсолютных номеров в tcpdump

По умолчанию анализаторы показывают относительные номера (начиная с 0). Флаг `-S` позволяет увидеть реальные значения:

```bash
sudo tcpdump -i any -S -nn tcp port 80
# → IP 1.1.1.1.54321 > 2.2.2.2.80: Flags [S], seq 3845612348
# → IP 2.2.2.2.80 > 1.1.1.1.54321: Flags [S.], seq 1098234567, ack 3845612349
```

Результат: ACK в ответе на 1 больше, чем SYN Seq, что подтверждает потребление виртуального байта.

### Сценарий 2: Мониторинг срабатываний PAWS

```bash
nstat -az TcpExtPAWSEstab
# → TcpExtPAWSEstab    142    0.0
```

Ненулевое значение указывает на то, что PAWS защитил сессию от некорректных старых пакетов.

### Сценарий 3: Анализ порядковых номеров через tshark

```bash
# Абсолютные seq/ack номера
tshark -r capture.pcap -T fields \
  -e frame.number -e ip.src -e ip.dst \
  -e tcp.seq -e tcp.ack -e tcp.len \
  -e tcp.flags.str 2>/dev/null | head -20

# Out-of-order сегменты
tshark -r capture.pcap -Y "tcp.analysis.out_of_order" -T fields \
  -e frame.number -e ip.src -e tcp.seq -e tcp.len 2>/dev/null | head -10

# Дубликаты (старые seq номера)
tshark -r capture.pcap -Y "tcp.analysis.duplicate_ack" -T fields \
  -e frame.number -e ip.src -e tcp.ack -e tcp.analysis.duplicate_ack_num 2>/dev/null | head -10
```

### Сценарий 4: Wireshark фильтры для анализа seq

```
# Все пакеты с определенным seq диапазоном
tcp.seq >= 1000 && tcp.seq <= 2000

# Out-of-order сегменты
tcp.analysis.out_of_order

# Duplicate ACK (ошибки порядка)
tcp.analysis.duplicate_ack

# Retransmission (ретрансмиссия)
tcp.analysis.retransmission

# Fast Retransmit
tcp.analysis.fast_retransmission

# RTO retransmission
tcp.analysis.rto

# Сегменты с определенным seq
tcp.seq == 1234567890

# Window Update (seq не изменяется, но меняется rwnd)
tcp.analysis.window_update
```

### Сценарий 5: Мониторинг seq через bpftrace

```bash
# Отслеживание передачи сегментов с определенным seq
sudo bpftrace -e 'kprobe:tcp_sendmsg {
    printf("send: pid=%d comm=%s len=%d\n", pid, comm, (int)arg2);
}'

# Подсчет количества переданных байтов по процессам
sudo bpftrace -e 'kprobe:tcp_sendmsg {
    @[comm] = sum((int)arg2);
}'

# Отслеживание seq номеров в реальном времени (требует kprobe на tcp_transmit_skb)
sudo bpftrace -e 'kprobe:tcp_transmit_skb {
    printf("xmit: pid=%d comm=%s\n", pid, comm);
}'
```

### Сценарий 6: Проверка ISN через tcpdump

```bash
# Просмотр ISN клиента и сервера
sudo tcpdump -i any -nn 'tcp[tcpflags] & (tcp-syn) != 0' -v 2>/dev/null | \
  grep -E 'seq|ack' | head -6
# → Flags [S], seq 3845612348           ← ISN клиента
# → Flags [S.], seq 1098234567, ack 3845612349  ← ISN сервера, ack=ISN_C+1
```

### Сценарий 7: Анализ wrap-around в высокоскоростных сетях

```bash
# Проверка включены ли Timestamps (защита от wrap-around)
sysctl net.ipv4.tcp_timestamps
# → net.ipv4.tcp_timestamps = 1

# Проверка PAWS через nstat
nstat -az TcpExtPAWSEstab TcpExtPAWSCandidate
# → TcpExtPAWSEstab        0    0.0   ← сработал PAWS
# → TcpExtPAWSCandidate    0    0.0   ← кандидаты на PAWS
```

---

## Диагностика

### Быстрый старт

```bash
# 1. Просмотр ISN в handshake
sudo tcpdump -i any -nn 'tcp[tcpflags] & (tcp-syn) != 0' -v 2>/dev/null | head -4

# 2. Проверка Timestamps (защита от wrap-around)
sysctl net.ipv4.tcp_timestamps

# 3. Статистика PAWS
nstat -az TcpExtPAWSEstab TcpExtPAWSCandidate

# 4. Поиск out-of-order сегментов в дампе
tshark -r capture.pcap -Y "tcp.analysis.out_of_order" 2>/dev/null | wc -l

# 5. Поиск retransmissions
tshark -r capture.pcap -Y "tcp.analysis.retransmission" 2>/dev/null | wc -l
```

### Счетчики nstat

| Счетчик | Описание |
| :--- | :--- |
| `TcpExtPAWSEstab` | Количество сработок PAWS (защищенных сессий). |
| `TcpExtPAWSCandidate` | Количество пакетов-кандидатов на отбрасывание через PAWS. |
| `TcpExtTCPOFOQueue` | Количество out-of-order сегментов, помещенных в очередь. |
| `TcpExtTCPOFODrop` | Количество out-of-order сегментов, отброшенных из-за переполнения очереди. |

---

## Справочник sysctl

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_timestamps` | 1 | TCP Timestamps (RFC 7323). Нужен для Eifel, PAWS, RTT measurement. |
| `net.ipv4.tcp_sack` | 1 | SACK: 0=отключен, 1=включен. Согласовывается в SYN. |
| `net.ipv4.tcp_dsack` | 1 | D-SACK: 0=отключен, 1=включен. Помогает обнаруживать spurious retransmission. |
| `net.ipv4.tcp_window_scaling` | 1 | Window Scale: 0=отключен, 1=включен. Согласовывается в SYN. |

> **См. также:** Полный список sysctl — [Flow Control](../Flow_Control/index.md).

---

## Дополнительная информация

### См. также
- **[Подтверждения (ACK)](./acknowledgments.md)** — использование порядковых номеров для обратной связи.
- **[Скользящее окно](./sliding_window.md)** — взаимодействие seq с окном отправителя/получателя.
- **[Механизмы ретрансмиссии](./retransmission.md)** — как seq используется в Fast Retransmit и RTO.
- **[Опции TCP](../Header_Format/options.md)** — детали реализации Timestamps, необходимых для PAWS.
- **[Установка соединения (Handshake)](../connection/tcp_connection_overview.md)** — процесс согласования ISN, SYN Cookies.

### Стандарты (RFC)
- **RFC 9293:** Transmission Control Protocol (2022).
- **RFC 7323:** TCP Extensions for High Performance (PAWS, Timestamps).
- **RFC 6528:** Defending against Sequence Number Attacks (ISN generation).
- **RFC 5681:** TCP Congestion Control (sequence number role in recovery).
- **RFC 4987:** SYN Flooding Protection (SYN Cookies and ISN).
