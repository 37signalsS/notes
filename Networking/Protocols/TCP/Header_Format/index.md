# Формат заголовка TCP

## Определения

**Заголовок TCP (TCP Header)** — управляющая информация, добавляемая к данным прикладного уровня для формирования сегмента. Он содержит поля, необходимые для обеспечения надежности, управления потоком и контроля перегрузок.

**Основные параметры (RFC 9293):**
- **Минимальный размер:** 20 байт (без опций).
- **Максимальный размер:** 60 байт (с 40 байтами опций).
- **Выравнивание:** 32 бита (4 байта).
- **Порядок байтов:** Big-Endian (сетевой порядок байтов).

---

## Методология диагностики

При анализе заголовка TCP следуйте иерархии:

1. **Уровень 1: Структура пакета** — размер заголовка, контрольная сумма, тип пакета.
2. **Уровень 2: Флаги и опции** — какие флаги установлены, какие опции согласованы.
3. **Уровень 3: Семантика полей** — что означают Seq/Ack/Window в контексте конкретного соединения.
4. **Уровень 4: Диагностика** — отклонения от ожидаемого поведения (bad checksum, Zero Window, неожиданные флаги).

---

## Базовые концепции

### Структура заголовка (битовая схема)

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Source Port          |       Destination Port        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Sequence Number                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Acknowledgment Number                      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Data Offset| Rsrvd |C|E|U|A|P|R|S|F|         Window         |
|             |       |W|C|R|C|S|S|Y|I|                         |
|             |       |R|E|G|K|H|T|N|N|                         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           Checksum            |         Urgent Pointer        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Options (variable, 0-40 B)                 |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Детальное описание полей

#### 1. Порты источника и назначения (Source / Destination Ports)
16 бит каждое поле (диапазон 0–65535).
- **Well-known (0–1023):** зарезервированы за системными сервисами (HTTP=80, HTTPS=443, SSH=22).
- **Registered (1024–49151):** назначаемые IANA приложениям.
- **Dynamic/Ephemeral (49152–65535):** клиентские порты, автоматически выделяемые ОС.
- *Подробнее:* [Сетевые порты](../../../Concepts/network_ports.md).

#### 2. Порядковый номер (Sequence Number)
32-битное число. В обычном режиме указывает номер первого байта данных в сегменте.
- Если установлен флаг **SYN**, это начальный порядковый номер (ISN). Первый байт данных будет иметь номер `ISN + 1`.
- ISN генерируется псевдослучайно (RFC 6528) для защиты от спуфинга.
- *Подробнее:* [Sequence Numbers в TCP](../reliability_mechanisms/sequence_numbers.md).

#### 3. Номер подтверждения (Acknowledgment Number)
32-битное число. Содержит номер следующего байта, который отправитель ожидает получить.
- Поле валидно только при установленном флаге **ACK**.
- В 3-way handshake: сервер в SYN-ACK ставит `ack = ISN_client + 1`.
- *Подробнее:* [Acknowledgments (ACK) в TCP](../reliability_mechanisms/acknowledgments.md).

#### 4. Смещение данных (Data Offset / Header Length)
4 бита. Указывает размер TCP-заголовка в **32-битных словах** (не в байтах!).
- **Формула:** `Размер заголовка (байт) = Data Offset × 4`.
- Минимальное значение `5` ($5 \times 4 = 20$ байт).
- Максимальное значение `15` ($15 \times 4 = 60$ байт).
- Позволяет определить, где заканчивается заголовок и начинаются данные.
- Если опции не заполняют 32-битное слово, добавляется **padding** (нулевые байты) для выравнивания.

**Пример:** Если согласованы опции MSS (4 байта), Window Scale (3 байта) и Timestamps (10 байт):
```
20 (базовый) + 4 (MSS) + 3 (WS) + 10 (TS) = 37 байт
37 не кратно 4 → добавляется 3 байта padding = 40 байт
Data Offset = 40 / 4 = 10
```

#### 5. Зарезервировано (Reserved)
6 бит (RFC 9293 расширило с 4 до 6). Должны быть установлены в `0`.
- Ранее 4 бита (RFC 793) → 6 бит (RFC 9293).
- Биты 7 и 8 байта 13 были заняты под ECN (CWR, ECE) ещё в RFC 3168.

#### 6. Управляющие флаги (Control Bits / Flags)

| Флаг | Бит (позиция в байте) | Описание | Когда устанавливается |
| :--- | :--- | :--- | :--- |
| **CWR** | 7 (старший) | Congestion Window Reduced | Отправитель снизил cwnd (ECN) |
| **ECE** | 6 | ECN-Echo | Получатель эхосирует CE-сигнал |
| **URG** | 5 | Urgent Pointer валиден | Данные помечены как «срочные» |
| **ACK** | 4 | Acknowledgment Number валиден | Все сегменты кроме SYN |
| **PSH** | 3 | Push — запрос немедленной доставки | Конец логической порции данных |
| **RST** | 2 | Reset — сброс соединения | Ошибка, неверное состояние, отказ |
| **SYN** | 1 | Synchronize — синхронизация номеров | Начало соединения (1-й и 2-й пакеты) |
| **FIN** | 0 (младший) | Finish — завершение передачи | Отправитель завершает отправку |

**Комбинации флагов (типичные):**
- `[S]` — SYN: начало соединения
- `[S.]` — SYN-ACK: подтверждение SYN
- `[.]` — ACK: просто подтверждение
- `[P.]` — PSH-ACK: данные с запросом немедленной доставки
- `[F.]` — FIN-ACK: нормальное закрытие соединения
- `[R]` — RST: принудительный сброс
- `[R.]` — RST-ACK: ответный сброс на подозрительный пакет
- `[E]` — ECE: уведомление о перегрузке (ECN)

**tcpdump-нотация:**
| Нотация | Флаг |
| :--- | :--- |
| `[S]` | SYN |
| `[S.]` | SYN-ACK |
| `[.]` | ACK |
| `[P]` | PSH |
| `[F]` | FIN |
| `[R]` | RST |
| `[E]` | ECE |
| `[W]` | CWR |
| `[U]` | URG |

#### 7. Размер окна (Window Size)
16 бит. Определяет количество байт, которое получатель готов принять в данный момент. Используется для управления потоком (Flow Control).
- С реальным масштабированием: `real_window = advertised_window × 2^wscale`.
- Максимальное значение без масштабирования: 65 535 байт.
- Максимальное значение с масштабированием (wscale=14): $2^{30}$ = 1 ГБ.
- *Подробнее:* [Управление потоком](../Flow_Control/index.md).

#### 8. Контрольная сумма (Checksum)
16 бит. Обязательный механизм проверки целостности (в отличие от UDP в IPv4).
- Проверяет: **псевдозаголовок + заголовок TCP + данные**.
- Если контрольная сумма неверна → **Silent Drop** (никакого RST, никакого ICMP).
- Отправитель узнает о потере только через RTO.
- *Подробнее:* [Контрольная сумма в TCP](../reliability_mechanisms/checksum.md).

#### 9. Указатель важности (Urgent Pointer)
16 бит. Указывает смещение от текущего порядкового номера до байта, **следующего за** «срочными» данными.
- Действителен только при флаге **URG**.
- В RFC 793: urgent data = данные до Urgent Pointer.
- В Linux: обработка зависит от настройки `net.ipv4.tcp_urg_` (обычно включена).
- На практике используется **крайне редко**. Протоколы SSH, FTP, Telnet曾使用, но современные протоколы избегают URG.
- *Подробнее:* Urgent Pointer в [RFC 9293, Section 3.1.1](https://www.rfc-editor.org/rfc/rfc9293#section-3.1.1).

---

## Псевдозаголовок (Pseudo-header)

### Структура для IPv4

| Поле | Размер (байт) | Значение |
| :--- | :--- | :--- |
| **Source IP** | 4 | IP-адрес отправителя |
| **Dest IP** | 4 | IP-адрес получателя |
| **Reserved** | 1 | Всегда 0 |
| **Protocol** | 1 | Всегда 6 (TCP) |
| **TCP Length** | 2 | Длина заголовка TCP + длина данных |

**Общий размер IPv4-псевдозаголовка:** 12 байт.

### Структура для IPv6 (RFC 8200)

| Поле | Размер (байт) | Значение |
| :--- | :--- | :--- |
| **Source IP** | 16 | IPv6-адрес отправителя |
| **Dest IP** | 16 | IPv6-адрес получателя |
| **TCP Length** | 4 | Длина заголовка TCP + длина данных |
| **Zero** | 3 | Всегда 0 (зарезервировано) |
| **Next Header** | 1 | Всегда 6 (TCP) |

**Общий размер IPv6-псевдозаголовка:** 40 байт.

### Зачем нужен псевдозаголовок?

Псевдозаголовок связывает L3 (IP) и L4 (TCP), гарантируя:
1. Сегмент доставлен **правильному хосту** (IP-адреса).
2. Сегмент доставлен **правильному протоколу** (Protocol = 6).
3. Нет переполнения данных (TCP Length).

**Связь с NAT:** При прохождении через NAT IP-адреса изменяются → контрольная сумма TCP **пересчитывается** (псевдозаголовок изменился).

### Алгоритм вычисления контрольной суммы (Internet Checksum)

1. Поле Checksum в заголовке TCP устанавливается в **0**.
2. Весь блок (псевдозаголовок + TCP header + данные) разбивается на **16-битные слова**.
3. Если данных нечетное количество байт → добавляется **нулевой байт (padding)**.
4. Все слова суммируются в **арифметике обратного кода** (One's Complement):
   - Если перенос за 16 бит → прибавляется к младшему разряду.
5. Результат **инвертируется** (Bitwise NOT).
6. Записывается в поле Checksum.

**Пример (упрощенный):**
```text
Данные: [0x4500, 0x003C, 0x1C46, 0x4000, 0x4006, ...]
Сумма:  0x4500 + 0x003C + 0x1C46 + 0x4000 + 0x4006 + ... = 0xB79E
Carry:  0xB79E → нет переноса (старший бит = 0)
Инверт: ~0xB79E = 0x4861
Checksum = 0x4861
```

---

## Опции TCP

Опции располагаются после поля Urgent Pointer и выравниваются по 32-битной границе.

### Формат TLV (Type-Length-Value)

| Поле | Размер (байт) | Описание |
| :--- | :--- | :--- |
| **Kind** | 1 | Тип опции |
| **Length** | 1 | Общая длина (включая Kind и Length) |
| **Value** | 0–38 | Данные опции |

**Служебные опции (без Length/Value):**
- **EOL (Kind 0):** конец списка опций.
- **NOP (Kind 1):** выравнивание по 32-битной границе.

### Таблица основных опций

| Опция | Kind | Длина | Описание | Когда согласуется |
| :--- | :--- | :--- | :--- | :--- |
| **MSS** | 2 | 4 байта | Максимальный размер payload | Только в SYN |
| **Window Scale** | 3 | 3 байта | Множитель окна ($2^{shift}$) | Только в SYN |
| **SACK Permitted** | 4 | 2 байта | Поддержка SACK | Только в SYN |
| **SACK Data** | 5 | Переменная | Блоки подтвержденных данных | В ACK после handshake |
| **Timestamps** | 8 | 10 байт | TSval + TSecr (RTT, PAWS) | Только в SYN |
| **TFO** | 34 | 6–18 байт | Cookie для данных в SYN | Только в SYN |
| **MPTCP** | 30 | Переменная | Multi-path TCP | Только в SYN |

### Расчет влияния опций на MSS

```
Базовый MSS = MTU - 20 (IP) - 20 (TCP) = 1460
С Timestamps:  1460 - 12 (10B TS + 2B NOP) = 1448
С SACK + TS:   1448 - 2  (SACK Permitted) = 1446
```

---

## ECN (Explicit Congestion Notification)

### Биты ECN в заголовке TCP

| Флаг | Бит | Роль |
| :--- | :--- | :--- |
| **ECE** | 6 (в байте флагов) | Получатель эхосирует CE-сигнал → ACK с ECE=1 |
| **CWR** | 7 (в байте флагов) | Отправитель подтверждает снижение cwnd → следующий сегмент с CWR=1 |

### Биты ECN в заголовке IP (2 бита в Traffic Class/ToS)

| Значение | Название | Описание |
| :--- | :--- | :--- |
| `00` | Non-ECT | ECN не поддерживается (обычный трафик) |
| `01` | ECT(1) | ECN-совместимый (L4S: микро-сигналы перегрузки) |
| `10` | ECT(0) | ECN-совместимый (стандартный ECN) |
| `11` | CE | Congestion Experienced (устанавливается маршрутизатором) |

### Handshake ECN

```text
Клиент                          Сервер
   |  SYN [ECE, CWR]              |
   |------------------------------->|
   |  SYN-ACK [ECE]                |
   |<-------------------------------|
   |  ACK                           |
   |------------------------------->|
```

1. Клиент ставит **ECE + CWR** в SYN → запрашивает ECN.
2. Сервер подтверждает **ECE** в SYN-ACK → поддерживает ECN.
3. Далее: маршрутизатор ставит **CE=11** на IP-пакете → получатель шлет ACK с **ECE=1** → отправитель снижает cwnd и шлет следующий сегмент с **CWR=1**.

**Включение в Linux:**
```bash
sysctl -w net.ipv4.tcp_ecn=1
```

---

## Оптимизация: hardware offloading

### Checksum Offload

NIC вычисляет контрольную сумму аппаратно → экономит CPU.
- **tx-checksumming:** NIC вычисляет checksum при передаче.
- **rx-checksumming:** NIC проверяет checksum при приеме.

**Проблема:** `tcpdump` перехватывает пакет **до** вычисления checksum NIC → видит `bad cksum`.
**Решение:** Временно отключить для «чистого» захвата:
```bash
sudo ethtool -K eth0 tx off rx off
# ... анализ ...
sudo ethtool -K eth0 tx on rx on
```

### TSO/GRO

- **TSO (TCP Segmentation Offload):** NIC разбивает большой сегмент на MSS-порции.
- **GRO (Generic Receive Offload):** NIC объединяет несколько сегментов в один до 64 КБ.

**Влияние на захват:** При анализе трафика TSO/GRO искажают реальные размеры пакетов.
```bash
# Проверка
ethtool -k eth0 | grep -E 'segmentation|receive'

# Отключение
sudo ethtool -K eth0 tso off gro off
```

---

## Практические сценарии

### Сценарий 1: Анализ флагов через tcpdump

```bash
# Перехват SYN-пакетов с опциями
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0'
# → IP 1.1.1.1.54321 > 2.2.2.2.80: Flags [S], seq 1024, win 65535,
#   options [mss 1460,sackOK,wscale 7]
# → IP 2.2.2.2.80 > 1.1.1.1.54321: Flags [S.], seq 4096, ack 1025,
#   win 28960, options [mss 1460,sackOK,wscale 7]

# Анализ: если одна из сторон не вернула wscale, максимальная скорость
# будет ограничена ~5 Мбит/с при задержке 100 мс.

# Перехват RST-пакетов
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-rst != 0'

# Перехват FIN-пакетов
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-fin != 0'

# Перехват PSH-пакетов (данные с запросом на немедленную доставку)
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-push != 0'
```

### Сценарий 2: Определение согласованных опций

```bash
# Просмотр полного вывода с опциями
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | head -20

# Извлечение только опций через tshark
tshark -r capture.pcap -Y "tcp.flags.syn==1" \
  -T fields -e tcp.options.mss -e tcp.options.wscale \
  -e tcp.options.sack -e tcp.options.ts_val

# Быстрый анализ через ss
ss -ti dst 8.8.8.8
# → cubic rto:204 rtt:15.2/0.5 cwnd:10 mss:1460 wscale:7,7 ecn
```

**Интерпретация полей ss:**
- **mss:1460** — согласованный MSS (без Timestamps).
- **wscale:7,7** — множители окна (send=128, receive=128).
- **ecn** — ECN согласован.
- **cwnd:10** — текущее окно перегрузки (в MSS).
- **rto:204** — таймаут ретрансмиссии (мс).
- **rtt:15.2/0.5** — сглаженный RTT / отклонение (мс).

### Сценарий 3: Диагностика ошибок контрольной суммы

```bash
# Счетчики ошибок checksum
nstat -az | grep -i csum
# → TcpInCsumErrors    5    0.0
# Ненулевое значение → повреждение данных (плохой кабель, ошибка памяти)

# Проверка offloading на NIC
sudo ethtool -k eth0 | grep checksum
# → rx-checksumming: on
# → tx-checksumming: on
# Если включено → bad cksum в tcpdump ожидаем (ложная тревога)

# Отключение offloading для «чистого» захвата
sudo ethtool -K eth0 tx off rx off
# ... анализ ...
sudo ethtool -K eth0 tx on rx on
```

### Сценарий 4: Анализ Window Size и Zero Window

```bash
# Zero Window в дампе
sudo tcpdump -i any -nn 'tcp[14:2] = 0'

# Window Size = 0 для конкретного хоста
sudo tcpdump -i eth0 -vv 'tcp and host 10.0.0.1' | grep 'win 0'

# Wireshark-фильтры
# tcp.window_size == 0                    — Zero Window
# tcp.analysis.zero_window                — обнаружен Zero Window
# tcp.analysis.zero_window_probe          — Persist Probe
# tcp.analysis.zero_window_probe_ack      — ответ на Persist Probe
# tcp.analysis.window_update              — обновление окна
```

### Сценарий 5: Анализ через tshark (извлечение полей заголовка)

```bash
# Извлечение всех ключевых полей заголовка
tshark -r capture.pcap -T fields \
  -e frame.number \
  -e tcp.srcport -e tcp.dstport \
  -e tcp.seq -e tcp.ack \
  -e tcp.len -e tcp.window_size \
  -e tcp.flags -e tcp.flags.str \
  -e tcp.options.mss -e tcp.options.wscale \
  -e tcp.checksum -e tcp.urgent_pointer \
  2>/dev/null | head -20

# Анализ только handshake (SYN + SYN-ACK)
tshark -r capture.pcap -Y "tcp.flags.syn==1" \
  -T fields -e ip.src -e ip.dst \
  -e tcp.srcport -e tcp.dstport \
  -e tcp.seq -e tcp.ack \
  -e tcp.options.mss -e tcp.options.wscale \
  -e tcp.options.sack -e tcp.options.ts_val

# Фильтрация по флагам
tshark -r capture.pcap -Y "tcp.flags.reset==1"    # RST
tshark -r capture.pcap -Y "tcp.flags.fin==1"      # FIN
tshark -r capture.pcap -Y "tcp.flags.push==1"     # PSH
```

### Сценарий 6: Проверка MTU/MSS через path discovery

```bash
# Проверка текущего MTU
ip link show eth0 | grep mtu
# → mtu 1500

# PMTU discovery
sysctl net.ipv4.tcp_mtu_probing
# → net.ipv4.tcp_mtu_probing = 0

# Включение PMTU discovery
sudo sysctl -w net.ipv4.tcp_mtu_probing=1

# Проверка MSS через ss
ss -ti dst 8.8.8.8 | grep mss
# → mss:1460

# Расчет: MSS = MTU - 40
# 1500 - 20 (IP) - 20 (TCP) = 1460
# С Timestamps: 1460 - 12 = 1448
```

### Сценарий 7: Анализ через eBPF

```bash
# Трассировка событий TCP (состояния, ретрансмиссии)
sudo tcpstates -tw

# Трассировка ретрансмиссий (показывает Seq/Ack丢失)
sudo tcpretrans

# Трассировка падений пакетов (включая checksum errors)
sudo tcpdrop

# Длительность congestion state
sudo tcpcong 1 10

# Трассировка соединений
sudo tcpconnect -t
```

### Сценарий 8: Wireshark Expert Info

В Wireshark **Analyze → Expert Information** показывает:
- **Warnings:** Bad TCP checksum, Zero Window, Retransmission.
- **Errors:** Malformed packet, Invalid flags, Checksum error.
- **Notes:** Window update, ACKed unseen segment.

**Фильтры Wireshark для анализа заголовка:**
```
tcp.analysis.checksum_status           — статус проверки checksum
tcp.analysis.flags                     — все аномалии флагов
tcp.analysis.retransmission            — ретрансмиссии
tcp.analysis.duplicate_ack             — дублирующие ACK
tcp.analysis.out_of_order              — пакеты не по порядку
tcp.analysis.window_full               — окно заполнено
tcp.analysis.duplicate_ack             — 3+ DupACK → Fast Retransmit
```

---

## Диагностические команды (агрегированная секция)

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
```

### Kubernetes

```yaml
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
          sleep infinity
        securityContext:
          privileged: true
```

---

## Дополнительная информация

### См. также

- **[Опции TCP](./options.md)** — разбор MSS, SACK, Timestamps и Window Scale.
- **[Практика анализа](./practical.md)** — tcpdump, ss, eBPF, Wireshark.
- **[Контрольная сумма](../reliability_mechanisms/checksum.md)** — псевдозаголовок, алгоритм, offloading.
- **[Надежность TCP](../reliability_mechanisms/concepts.md)** — механизмы Seq/Ack и Checksum.
- **[Управление потоком](../Flow_Control/index.md)** — Window Size, Flow Control.
- **[Управление перегрузкой](../congestion/tcp_congestion_control_overview.md)** — CWR/ECE, ECN, cwnd.
- **[Оптимизация TCP в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — тюнинг сетевого стека ядра.
- **[Алгоритм Нагла](../tcp_nagle_algorithm.md)** — PSH flag и немедленная доставка.

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (современный стандарт, объединяющий RFC 793 и дополнения).
- **RFC 7323:** TCP Extensions for High Performance (Window Scale, Timestamps).
- **RFC 3168:** The Addition of Explicit Congestion Notification (ECN) to IP.
- **RFC 9330:** L4S (Low Latency, Low Loss, Scalable throughput) — ECN через ECT(1).
- **RFC 1071:** Computing the Internet Checksum — алгоритм контрольной суммы.
- **RFC 8200:** Internet Protocol, Version 6 — псевдозаголовок IPv6.
- **RFC 2018/6675:** TCP Selective Acknowledgment Options.
- **RFC 2883:** D-SACK Extension.
- **RFC 8985:** RACK-TLP — потеря пакетов через time-based loss detection.
- **RFC 6528:** Defending against Sequence Number Attacks — ISN генерация.
