# Протокол TCP (Transmission Control Protocol): Обзор

## Определения

**TCP (Transmission Control Protocol)** — основной протокол транспортного уровня (L4) в стеке TCP/IP. Он обеспечивает надежную, упорядоченную и безошибочную доставку непрерывного потока байт между приложениями поверх ненадежной сетевой инфраструктуры (IP).

**Ключевые термины:**
- **Сегмент (Segment):** Единица данных TCP (PDU — Protocol Data Unit), инкапсулированная в IP-пакет. Состоит из заголовка (20–60 байт) и данных (payload).
- **Поток байт (Byte Stream):** Абстракция передачи: TCP не сохраняет границы прикладных сообщений. Данные передаются как единая лента байт; приложение может читать/писать их любыми порциями.
- **ISN (Initial Sequence Number):** Криптографически генерируемый начальный порядковый номер (RFC 6528), выбираемый каждым узлом при установке соединения для защиты от атак предсказывания Seq.
- **RTT (Round-Trip Time):** Время в миллисекундах от отправки сегмента до получения подтверждения (ACK). Определяет скорость роста cwnd и значения RTO.
- **MSS (Maximum Segment Size):** Максимальный размер полезных данных (payload) в одном сегменте (без заголовков TCP и IP). Согласовывается в SYN-пакетах. Типичное значение: 1460 для MTU 1500.

---

## Основные концепции

### Ключевые характеристики

| Характеристика | Описание | Механизмы реализации |
| :--- | :--- | :--- |
| **Надежность** | Гарантия доставки данных в целостности. | Подтверждения (ACK), ретрансмиссии (RTO, Fast Retransmit, RACK-TLP), контрольные суммы (RFC 1071). |
| **Упорядоченность** | Восстановление исходного порядка данных при их перемешивании в сети. | Порядковые номера (Sequence Numbers), буфер ожидания (out-of-order queue). |
| **Ориентация на соединение** | Требуется установка логической сессии перед передачей. | Трехэтапное рукопожатие (3-way Handshake: SYN, SYN-ACK, ACK). |
| **Управление потоком (Flow Control)** | Защита получателя от переполнения локального буфера. | Скользящее окно приема (Receiver Window, `rwnd`), Zero Window Probe. |
| **Управление перегрузкой (Congestion Control)** | Защита сетевых узлов от заторов и отбрасывания пакетов. | Окно перегрузки (`cwnd`), алгоритмы AIMD, CUBIC, BBR/BBRv3. |
| **Полный дуплекс** | Данные передаются в обоих направлениях одновременно. | Каждая сторона имеет собственные Seq/Ack, независимые окна. |

### Место в сетевой модели и эволюция (2026)

TCP работает на **транспортном уровне** и служит стандартом де-факто для подавляющего большинства критичных к надежности приложений.

```text
┌─────────────────────────────────────────────────────────────────┐
│  Прикладной уровень                                              │
│  HTTP/1.1, HTTP/2, HTTP/3, SMTP, SSH, gRPC, MySQL, PostgreSQL  │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│  Транспортный уровень                                           │
│  TCP ← Надежность + Управление потоком + Контроль перегрузки   │
│  UDP ← Минимальные накладные расходы, без гарантий              │
│  QUIC ← HTTP/3, User-Space TCP, 0-RTT,мультиплексирование     │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│  Сетевой уровень                                                │
│  IPv4, IPv6                                                     │
└─────────────────────────────────────────────────────────────────┘
```

**Историческая эволюция:**

| Год | Событие | RFC |
| :--- | :--- | :--- |
| 1981 | Первая спецификация TCP | RFC 793 |
| 1988 | Алгоритмы контроля перегрузки ( Tahoe/Reno) | RFC 1001 |
| 1994 | TCP selective acknowledgment (SACK) | RFC 1896 |
| 2001 | Window Scale, Timestamps, PAWS | RFC 1323 |
| 2004 | D-SACK (Duplicate SACK) | RFC 2883 |
| 2009 | CUBIC — де-факто в Linux | — |
| 2013 | ECN (Explicit Congestion Notification) | RFC 3168 |
| 2016 | TCP Fast Open (TFO) | RFC 7413 |
| 2016 | BBR — новый подход к CC | — |
| 2017 | MPTCP (Multi-path TCP) | RFC 8684 |
| 2022 | Консолидированная спецификация | RFC 9293 |
| 2024 | BBRv3 (стабильный) | — |
| 2024 | L4S (Low Latency, Low Loss, Scalable) | RFC 9330 |
| 2025 | RACK-TLP (loss detection) | RFC 8985 |

**Сравнение с альтернативами:**

| Параметр | TCP | UDP | QUIC (HTTP/3) |
| :--- | :--- | :--- | :--- |
| **Надежность** | Гарантия доставки (ACK, ретрансмиссии) | Нет гарантий | Гарантия доставки (поверх UDP) |
| **Порядок** | Гарантирован (Seq) | Нет порядка | Гарантирован (per-stream) |
| **Соединение** | Требуется handshake (1 RTT) | Stateless | Handshake (0–1 RTT) |
| **Head-of-line blocking** | Да (один поток) | Нет | Нет (мультиплексирование) |
| **Шифрование** | TLS отдельно (1–2 RTT) | Не mandated | TLS 1.3 интегрирован (0-RTT) |
| **Смена IP** | Разрывает соединение | Нет соединения | Connection Migration |
| **Применение** | БД, файлы, REST API, SSH | DNS, VoIP, стриминг,игры | CDN, браузеры, микросервисы |

### Структура сегмента TCP

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
├─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┤
│          Источник (Source Port)        │       Назначение (Dst Port)│
├─────────────────────────────────────────┼───────────────────────────┤
│              Номер последовательности (Sequence Number)             │
├─────────────────────────────────────────┼───────────────────────────┤
│           Номер подтверждения (Acknowledgment Number)               │
├───────┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┤
│Offset │R│E│U│A│P│R│S│F│        Окно приема (Window Size)           │
├─────────────────────────────────────────┼───────────────────────────┤
│       Контрольная сумма (Checksum)      │ Указатель срочности (Urg) │
├─────────────────────────────────────────┼───────────────────────────┤
│                     Опции (0–40 байт)   │ ...                       │
└─────────────────────────────────────────┴───────────────────────────┘
```

**Поля заголовка:**

| Поле | Размер | Описание |
| :--- | :--- | :--- |
| **Source Port** | 16 бит | Порт отправителя (0–65535) |
| **Destination Port** | 16 бит | Порт получателя |
| **Sequence Number** | 32 бит | Порядковый номер первого байта данных в сегменте |
| **Acknowledgment Number** | 32 бит | Номер следующего ожидаемого байта (только с ACK=1) |
| **Data Offset** | 4 бита | Длина заголова в 32-битных словах (5–15 слов = 20–60 байт) |
| **Reserved** | 3 бита | Зарезервировано (RFC 9293) |
| **Flags (Control Bits)** | 9 бит | CWR, ECE, URG, ACK, PSH, RST, SYN, FIN |
| **Window Size** | 16 бит | Размер окна приема (в байтах, с учетом масштабирования) |
| **Checksum** | 16 бит | Контрольная сумма заголовка + данных + псевдозаголовок |
| **Urgent Pointer** | 16 бит | Смещение до «срочных» данных (редко используется) |
| **Options** | 0–320 бит | MSS, Window Scale, SACK, Timestamps, NOP, EOL, TFO, MPTCP |

**Псевдозаголовок (для Checksum):** IPv4 — `Src IP (32) + Dst IP (32) + Protocol (8) + TCP Length (16)`. IPv6 — аналогично, с добавлением extension header length.

**8 флагов (Flags):**

| Флаг | Бит | Описание |
| :--- | :--- | :--- |
| **CWR** | 7 | Congestion Window Reduced — отправитель снижает cwnd |
| **ECE** | 6 | ECN-Echo — получатель CE-пакета или запрашивает ECN |
| **URG** | 5 | Urgent Pointer significant — данные для немедленной обработки |
| **ACK** | 4 | Acknowledgment field significant — все сегменты кроме SYN |
| **PSH** | 3 | Push Function — запрос немедленной доставки приложению |
| **RST** | 2 | Reset connection — сброс соединения |
| **SYN** | 1 | Synchronize sequence numbers — установка соединения |
| **FIN** | 0 | No more data from sender — корректное закрытие |

### Машина состояний TCP (FSM)

TCP определяет 11 состояний; переходы происходят по событиям (отправка/получение сегментов, таймауты):

```text
                    ┌──────────┐
                    │  CLOSED  │
                    └────┬─────┘
            ┌───────────┘└───────────┐
     Active Open              Passive Open
            ↓                       ↓
      ┌──────────┐           ┌──────────┐
      │ SYN_SENT │           │  LISTEN  │
      └────┬─────┘           └────┬─────┘
     ┌─────┘└─────┐              ┌┘└──┐
  SYN-ACK       ACK          SYN    Close
     ↓            ↓           ↓      ↓
┌──────────┐              ┌──────────────┐
│ESTABLISHED│             │ SYN_RECEIVED │
└──────────┘              └──────┬───────┘
     │                         │
  Close                      ACK
     ↓                         ↓
┌──────────────┐         ┌──────────────┐
│ FIN_WAIT_1   │         │  ESTABLISHED │
└──────┬───────┘         └──────────────┘
   ┌────┘└────┐               │
SYN-ACK  FIN-ACK          Close
   ↓        ↓               ↓
┌──────────────┐        ┌──────────────┐
│  CLOSING     │        │  LAST_ACK    │
└──────┬───────┘        └──────┬───────┘
   ┌────┘└────┐               │
ACK      ACK              ACK
   ↓        ↓               ↓
┌──────────────┐        ┌──────────┐
│ FIN_WAIT_2   │        │  CLOSED  │
└──────┬───────┘        └──────────┘
   │
FIN
   ↓
┌──────────────┐
│  TIME_WAIT   │
└──────┬───────┘
   │
2 × MSL
   ↓
┌──────────┐
│  CLOSED  │
└──────────┘
```

**Сводная таблица состояний:**

| Состояние | Описание | Кол-во переходов |
| :--- | :--- | :--- |
| **CLOSED** | Нет соединения | Начальное/конечное |
| **LISTEN** | Сервер ожидает входящий SYN | От CLOSED |
| **SYN_SENT** | Клиент отправил SYN, ожидает SYN-ACK | От CLOSED |
| **SYN_RECEIVED** | Сервер получил SYN, отправил SYN-ACK, ожидает ACK | От LISTEN |
| **ESTABLISHED** | Соединение установлено, данные передаются | Целевое |
| **FIN_WAIT_1** | Отправлена FIN, ожидается ACK или FIN | От ESTABLISHED |
| **FIN_WAIT_2** | FIN подтвержден, ожидается FIN от другого узла | От FIN_WAIT_1 |
| **CLOSING** | Обе стороны отправили FIN одновременно | Редкое |
| **LAST_ACK** | Сервер отправил FIN, ожидает ACK | От ESTABLISHED |
| **TIME_WAIT** | Ожидание 2×MSL (60 сек) для гарантированной очистки | От FIN_WAIT_2/CLOSING |
| **CLOSE_WAIT** | Получатель FIN, ожидает закрытия приложением | От ESTABLISHED |

### Управление потоком (Flow Control)

**Скользящее окно (Sliding Window):** Получатель сообщает отправителю размер свободного буфера через поле `Window Size` в каждом ACK. Отправитель не может отправлять больше данных, чем указано в окне.

- **rwnd (Receiver Window):** Текущий размер окна接收者, обновляется в каждом ACK.
- **Zero Window:** Если буфер接收者 заполнен, он объявляет `win=0`. Отправитель останавливается и периодически отправляет Zero Window Probe для проверки.
- **Window Scale (RFC 7323):** Множитель для rwnd (сдвиг влево на `wscale` бит). Позволяет увеличить максимальное окно с 64 КБ до 1 ГБ. Согласовывается в SYN.

### Управление перегрузкой (Congestion Control)

**Цель:** Не перегружать сеть, контролируя количество данных «в полете» (in-flight).

- **cwnd (Congestion Window):** Окно перегрузки, определяемое отправителем. Отправитель не может отправлять больше `min(cwnd, rwnd)` данных.
- **Slow Start:** cwnd растет экспоненциально (cwnd += MSS за ACK) до порога `ssthresh`.
- **Congestion Avoidance:** cwnd растет линейно (cwnd += MSS²/cwnd за ACK).
- **Fast Retransmit:** При получении 3 DupACK немедленная ретрансмиссия без ожидания RTO.
- **Fast Recovery:** После Fast Retransmit — снижение cwnd (half) и продолжение передачи.
- **Алгоритмы:** Tahoe, Reno, NewReno, CUBIC (Linux default), BBR, BBRv3, DCTCP.
- **ECN (RFC 3168):** Маршрутизатор устанавливает CE-бит в IP-заголовке вместо отбрасывания. Получатель уведомляет отправителя через ECE-бит в TCP. Отправитель снижает cwnd и устанавливает CWR.
- **L4S (RFC 9330):** Dual-queue architecture с ECT(1) для микро-сигнализации о перегрузке. Снижает задержку до <10 мс при высокой пропускной способности.

---

## Структура документации TCP

Для глубокого изучения конкретных механизмов используйте следующие тематические разделы базы знаний:

| Раздел | Ссылка | Содержание |
| :--- | :--- | :--- |
| **Формат заголовка** | [Header_Format/index.md](./Header_Format/index.md) | Поля Seq/Ack, флаги, 32-битное выравнивание, MSS, SACK, TFO, MPTCP, ECN, pseudo-header, Internet Checksum. |
| **Опции TCP** | [Header_Format/options.md](./Header_Format/options.md) | Kind-Length-Value, MSS, Window Scale, SACK, Timestamps, TFO, MPTCP, ECN, NOP/EOL, 40-байтный бюджет. |
| **Практика анализа** | [Header_Format/practical.md](./Header_Format/practical.md) | tcpdump, tshark, Wireshark, ss, nstat, eBPF, Zero Window, RST, throughput, middlebox, PCAP. |
| **Установка соединения** | [connection/tcp_connection_overview.md](./connection/tcp_connection_overview.md) | 3-way handshake, ISN, опции, TFO, SYN cookie, MSS clamping. |
| **Состояния FSM** | [connection/tcp_connection_states.md](./connection/tcp_connection_states.md) | Все 11 состояний, переходы, таймауты, диагностика. |
| **Передача данных** | [connection/tcp_data_transfer.md](./connection/tcp_data_transfer.md) | Нумерация, сегментация, цикл передачи,重组. |
| **Закрытие соединения** | [connection/tcp_connection_termination.md](./connection/tcp_connection_termination.md) | 4-way handshake, TIME_WAIT, FIN_WAIT, CLOSE_WAIT, одновременное закрытие. |
| **Отказы и RST** | [connection/tcp_connection_refusal.md](./connection/tcp_connection_refusal.md) | RST, SYN cookie, backoff, LISTEN backlog, Half-open. |
| **Диагностика соединений** | [connection/tcp_connection_diagnostics.md](./connection/tcp_connection_diagnostics.md) | ss, nstat, tcpdump, Wireshark, eBPF, траблшутинг. |
| **Надежность** | [reliability_mechanisms/concepts.md](./reliability_mechanisms/concepts.md) | Seq/Ack, Checksum, ARQ, Delayed ACK, DupACK, Fast Retransmit, RACK-TLP. |
| **Порядковые номера** | [reliability_mechanisms/sequence_numbers.md](./reliability_mechanisms/sequence_numbers.md) | ISN, ISNCrement, Sequence Space, wrapped sequence. |
| **Ретрансмиссии** | [reliability_mechanisms/retransmission.md](./reliability_mechanisms/retransmission.md) | RTO, Fast Retransmit, Spurious Retransmission, Eifel. |
| **Check Sum** | [reliability_mechanisms/checksum.md](./reliability_mechanisms/checksum.md) | RFC 1071, pseudo-header, partial sum, hardware offloading. |
| **Скользящее окно** | [reliability_mechanisms/sliding_window.md](./reliability_mechanisms/sliding_window.md) | Sending window, advertisement, Zero Window,糊涂窗口综合征. |
| **Управление потоком** | [Flow_Control/index.md](./Flow_Control/index.md) | Sliding Window, Zero Window, Window Scale, автотюнинг, rwnd vs cwnd. |
| **Контроль перегрузки** | [congestion/tcp_congestion_control_overview.md](./congestion/tcp_congestion_control_overview.md) | AIMD, Slow Start, Fast Recovery, Bufferbloat, 14KB, ECN/L4S, BDP. |
| **Алгоритмы CC** | [congestion/tcp_congestion_algorithms.md](./congestion/tcp_congestion_algorithms.md) | Tahoe, Reno, NewReno, CUBIC, BBR, BBRv3, DCTCP, Vegas. |
| **initcwnd** | [congestion/tcp_initcwnd_and_optimization.md](./congestion/tcp_initcwnd_and_optimization.md) | Начальное окно, 10 MSS, оптимизация для CDN. |
| **Диагностика CC** | [congestion/tcp_congestion_diagnostics.md](./congestion/tcp_congestion_diagnostics.md) | Буферы, qdisc, tc, tcstat, Wireshark IO Graph. |
| **Nagle** | [tcp_nagle_algorithm.md](./tcp_nagle_algorithm.md) | Алгоритм Нагла, TCP_NODELAY, конфликт с Delayed ACK. |
| **Оптимизация TCP** | [../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md](../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md) | sysctl, eBPF, per-route tuning, буферы, очереди, keepalive. |
| **Production Tuning** | [production_tuning.md](./production_tuning.md) | Keepalive, database tuning (MySQL/PG/Redis), ip tcp_metrics, L4 LB, busy polling, production sysctl. |

---

## Практические сценарии

### Выбор протокола для архитектуры

| Сценарий | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Транзакционные системы (БД)** | TCP | Гарантия доставки: каждый запрос/ответ должен быть полным |
| **Передача файлов** | TCP | Надежность + контроль потока |
| **REST API / gRPC** | TCP | Гарантия целостности запросов/ответов |
| **SSH /SCP / SFTP** | TCP | Надежность критична |
| **DNS (записи)** | UDP (TCP для zone transfer) | Малые запросы, скорость критичнее |
| **VoIP / стриминг** | UDP | Задержка критичнее надежности |
| **Онлайн-игры** | UDP | Потери терпимы, задержка критична |
| **CDN / браузеры** | QUIC (HTTP/3) | 0-RTT, мультиплексирование, смена IP |
| **Микросервисы (RPC)** | gRPC over TCP или QUIC | Зависит от требований к латентности |

### Базовая диагностика в Linux

Проверка текущего состояния TCP-соединений — первая линия диагностики SRE:

```bash
# Сводная статистика сокетов по состояниям
ss -s
# → TCP:   150 (estab 120, closed 10, orphaned 5, timewait 10)

# Детальный просмотр параметров (cwnd, RTT, потери) конкретного соединения
ss -ti dst 8.8.8.8
# → cubic rto:204 rtt:15.2/0.5 ato:40 mss:1460 pmtu:1500 rcvmss:1460
# → cwnd:10 ssthresh:7 send 7.6Mbps retrans:0/0

# Просмотр загруженного алгоритма управления перегрузкой
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = cubic

# Проверка ECN
sysctl net.ipv4.tcp_ecn
# → net.ipv4.tcp_ecn = 2

# Быстрый поиск Zero Window
ss -tin state established | grep -E "rcv_space:0|win 0"

# Проверка всех TCP-соединений с флагами
ss -tin state established | awk '{print $1, $2, $3, $6}' | head -20

# Счетчики ошибок и ретрансмиссий
nstat -az | grep -E "TcpRetransSegs|TCPAbortOn|TcpInCsumErrors"

# Просмотр sysctl-параметров (важные)
sysctl net.ipv4.tcp_rmem net.ipv4.tcp_wmem net.core.rmem_max net.core.wmem_max
# → net.ipv4.tcp_rmem = 4096 131072 6291456
# → net.ipv4.tcp_wmem = 4096 65536 4194304
```

### Диагностика типичных проблем

| Симптом | Вероятная причина | Команда диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **Низкая скорость** | Малый cwnd, высокий RTT | `ss -ti dst $HOST \| grep -E "cwnd\|rtt\|send"` | Увеличить буферы, сменить CC на BBR |
| **Zero Window** | Буфер接收者 заполнен | `ss -tin \| grep rcv_space:0` | Увеличить `tcp_rmem`, оптимизировать приложение |
| **Частые RST** | Порт закрыт, timeout, память | `nstat -az \| grep Abort` | Проверить `ss -tlnp`, увеличить `tcp_mem` |
| **Ретрансмиссии** | Потери в сети | `nstat -az \| grep Retrans` | Диагностика сети, `tc qdisc` |
| **Высокий RTT** | Bufferbloat, очередь | `ss -ti \| grep rtt` | qdisc (fq_codel), L4S, ECN |
| **TIME_WAIT accumulation** | Короткие соединения | `ss -s \| grep timewait` | `tcp_tw_reuse=1`, keepalive |
| **SYN-флуд** | DoS-атака | `nstat -az \| grep SynRecv` | `tcp_syncookies=1`, `tcp_max_syn_backlog` |

### Тюнинг TCP для разных сценариев

**Высоконагруженные серверы (Nginx, Envoy):**
```bash
# Увеличение очередей
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=16384

# Эфемерные порты
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"
sudo sysctl -w net.ipv4.tcp_tw_reuse=1

# Keep-alive (обнаружение мертвых соединений)
sudo sysctl -w net.ipv4.tcp_keepalive_time=60
sudo sysctl -w net.ipv4.tcp_keepalive_intvl=10
sudo sysctl -w net.ipv4.tcp_keepalive_probes=6
```

**Low-Latency (gRPC, Redis):**
```bash
# Отключение Nagle для минимальной задержки
# В коде: setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &val, sizeof(val))

# Включение ECN
sudo sysctl -w net.ipv4.tcp_ecn=1

# Смена CC на BBR (меньше jitter)
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr
```

**Высокопроизводительные (Bulk Transfer):**
```bash
# Увеличение буферов (BDP = Bandwidth × RTT)
# 1 Gbps × 100ms = 12.5 MB → min. rmem/wmem ~16 MB
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216
sudo sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"
sudo sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"
```

---

## Дополнительная информация

### См. также

- **[Оптимизация TCP в Linux](../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — sysctl, eBPF, per-route tuning, буферы, очереди.
- **[Диагностика TCP](./connection/tcp_connection_diagnostics.md)** — ss, nstat, tcpdump, Wireshark, eBPF, траблшутинг.

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (2022) — консолидированная спецификация, заменяющая RFC 793, RFC 879, RFC 2873 и другие.
- **RFC 7323:** TCP Extensions for High Performance — Window Scale, Timestamps, PAWS.
- **RFC 5681:** TCP Congestion Control — базовые алгоритмы AIMD, Slow Start, Fast Recovery.
- **RFC 3168:** The Addition of Explicit Congestion Notification (ECN) to IP.
- **RFC 7413:** TCP Fast Open (TFO) — сокращение задержки handshake.
- **RFC 8684:** Multipath TCP (MPTCP) — агрегация каналов.
- **RFC 8985:** RACK-TLP — time-based loss detection.
- **RFC 9330:** Low Latency, Low Loss, Scalable throughput (L4S).
