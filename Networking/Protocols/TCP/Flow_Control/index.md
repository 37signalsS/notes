# Управление потоком в TCP (Flow Control)

## Определения

**Управление потоком (Flow Control)** — это фундаментальный механизм протокола TCP, предназначенный для предотвращения переполнения буфера на стороне получателя. Он обеспечивает обратную связь, с помощью которой получатель сообщает отправителю о своей текущей способности принимать данные, гарантируя, что скорость передачи не превысит скорость обработки (вычитывания из сокета приложением).

**Ключевые термины:**

- **Receiver Window (rwnd):** размер свободного места в приемном буфере сокета, анонсируемый получателем в каждом ACK-сегменте.
- **Congestion Window (cwnd):** окно перегрузки — ограничение со стороны сети, определяемое отправителем. Реальное окно отправки = `min(rwnd, cwnd)`.
- **Effective Window (Эффективное окно):** реальный объем данных, разрешенный к отправке — минимум из rwnd и cwnd.
- **Zero Window (Нулевое окно):** состояние, при котором получатель сообщает `rwnd = 0`, принудительно останавливая отправку данных.
- **Silly Window Syndrome (SWS):** "синдром глупого окна" — неэффективный режим работы, при котором данные передаются крайне малыми порциями из-за частых обновлений окна малого размера.
- **Persist Timer:** таймер, запускаемый отправителем при получении Zero Window, для периодической отправки Zero Window Probe — чтобы избежать «тупика» при потере ACK с обновлением окна.
- **Nagle Algorithm:** механизм агрегации мелких данных отправителем для предотвращения «проблемы маленьких пакетов».

---

## Методология диагностики (Bottom-up)

Диагностика проблем управления потоком должна следовать иерархии:

1. **Уровень 1: Определение типа проблемы** — это проблема получателя (Zero Window,慢ный read) или отправителя (cwnd limited, потеря)?
2. **Уровень 2: Проверка буферов** — достаточно ли буферы rmem/wmem? Каков BDP канала?
3. **Уровень 3: Анализ поведения** — есть ли SWS, конфликт Nagle+Delayed ACK, потери?
4. **Уровень 4: Прикладной анализ** — корректно ли приложение читает/пишет данные?

**Принцип "Исключения":** Начинайте с проверки самых простых причин (сервис запущен? соединение established?), прежде чем углубляться в анализ таймеров и FSM-состояний.

---

## Основные концепции

### Механизм скользящего окна (Sliding Window)

Управление потоком реализуется через поле **Window Size** в заголовке TCP. Получатель динамически управляет правой границей окна отправителя.

**Логика взаимодействия:**
1. Приложение-получатель вычитывает данные из буфера.
2. Свободное место увеличивается.
3. Стек TCP отправляет ACK с обновленным значением `rwnd`.
4. Отправитель сдвигает границу разрешенных к отправке данных.

**Эффективное окно отправки:**
Реальный лимит данных "в полете" (Inflight) определяется как минимум из двух окон:
```text
Effective_Window = min(rwnd, cwnd)
```
Где `cwnd` — окно перегрузки (Congestion Window), защищающее сеть.

**Байтовая ориентация окна:** TCP использует байтовое скользящее окно с четырьмя ключевыми точками на стороне отправителя:
1. **LastByteAcked:** последний подтвержденный байт — левая граница окна.
2. **LastByteSent:** последний отправленный байт — данные "в полете".
3. **LastByteAcked + rwnd:** правая граница разрешенного к отправке.
4. **Данные за пределами окна:** не могут быть отправлены до получения ACK.

**Отношение Effective Window к Throughput:**
```
Throughput_ceiling = min(rwnd, cwnd) / RTT
```
Это ключевая формула: реальная пропускная способность определяется минимумом из двух ограничителей.

### Масштабирование окна (Window Scaling)

Поле `Window Size` в классическом заголовке TCP занимает 16 бит, что ограничивает максимальное окно значением 65 535 байт. Для современных высокоскоростных сетей (10GbE+) этого недостаточно.
Опция **Window Scale** (RFC 7323) позволяет использовать 14-битный множитель ($2^n$), расширяя теоретический предел окна до **1 ГБ**.
- Согласуется только во время 3-way handshake в пакетах SYN/SYN-ACK.
- Если одна из сторон не поддерживает опцию, обе обязаны использовать стандартные 64 КБ.
- Фактический размер окна: `advertised_window × 2^shift_count`.
- Максимальный shift_count = 14, что дает максимальное окно 2^30 = 1 ГБ.

**Важно:** Window Scale работает только если **обе** стороны анонсируют опцию в SYN. Если одна из сторон не поддерживает — обе переходят к стандартным 64 КБ.

### Проблема Silly Window Syndrome (SWS)

SWS возникает, когда данные передаются сегментами по несколько байт, что создает огромный оверхед на заголовки (40 байт TCP/IP на 1 байт данных).

**Причины SWS:**
- Получатель анонсирует маленькое окно (например, 1 байт свободного места).
- Отправитель заполняет это маленькое окно, генерируя крошечный сегмент.
- цикл повторяется → masses of tiny segments.

**Решение Кларка (получатель — Clark's Solution):**
Получатель не должен анонсировать увеличение окна, пока в буфере не освободится место размером хотя бы в 1 MSS (Maximum Segment Size) или 50% от общего размера буфера. Это предотвращает анонсирование тривиально малых окон.

**Реализация в Linux:**
- Ядро не анонсирует увеличение окна меньше `min(MSS, free_buffer/2)`.
- Управляется параметром `net.ipv4.tcp_adv_win_scale` (по умолчанию 1).

**Сторона отправителя — Алгоритм Нагла:**
Если в буфере есть неподтвержденные данные, мелкие порции данных буферизуются до прихода ACK или накопления данных для заполнения MSS. Отключается опцией `TCP_NODELAY`. Подробнее: [Алгоритм Нагла](../tcp_nagle_algorithm.md).

**Конфликт Nagle + Delayed ACK:**
Наиболее критическая проблема — отправитель ждет ACK (чтобы разрешить отправку малого сегмента), а получатель ждет данные для "приклеивания" ACK (Delayed ACK, 40-200 мс). Результат — задержка ровно на время таймера. Решение: `TCP_NODELAY` на отправителе.

### Sender vs Receiver Responsibilities

| Аспект | Отправитель | Получатель |
| :--- | :--- | :--- |
| **Буфер** | Send buffer (application → kernel) | Receive buffer (kernel → application) |
| **Окно** | Определяет effective window = min(cwnd, rwnd) | Анонсирует rwnd в каждом ACK |
| **SWS avoidance** | Nagle algorithm | Clark's solution + delayed ACKs |
| **Backpressure** | `SO_SNDBUF`, `TCP_NOTSENT_LOWAT` | `SO_RCVBUF`, `tcp_rcvbuf_autotuning` |
| **Zero Window** | Запускает Persist Timer, шлет probes | Уведомляет о rwnd=0 |
| **Flow control window** | `net.ipv4.tcp_wmem` | `net.ipv4.tcp_rmem` |

### Нулевое окно и Persist Timer

Когда получатель анонсирует `rwnd = 0`, отправитель останавливается и запускает **Persist Timer** (обычно RTO, с экспоненциальным бэкоффом).

**Проблема, которую решает Persist Timer:**
Если ACK с обновлением окна (Window Update) потеряется, отправитель и получатель попадут в "тупик": отправитель ждет открытия окна, получатель ждет данные.

**Mеханизм:** По таймеру отправитель шлет **Zero Window Probe** — 1 байт новых данных, чтобы получить ACK с актуальным `rwnd`.

**Паттерн Probe (с экспоненциальным бэкоффом):**
```
0.2s → 0.4s → 0.8s → 1.6s → 3.2s → 6.4s → 12.8s → ...
```
В Linux количество проб регулируется `net.ipv4.tcp_retries2`.

### MSS при установке соединения

MSS (Maximum Segment Size) обменивается в опции **MSS option** во время SYN/SYN-ACK:
- MSS = MTU - 40 (20 bytes IP header + 20 bytes TCP header).
- Типичное: 1460 байт (1500 MTU - 40).
- Path MTU Discovery (PMTU) может уменьшить MSS дальше.
- `net.ipv4.tcp_mtu_probing = 1` для включения PMTU.

### SACK опция (RFC 2018, RFC 6675)

**Selective Acknowledgment** — получатель сообщает отправителю какие именно блоки данных получены, а не только последовательный ACK.
- Позволяет переотправлять **только потерянные** сегменты (не все после первого разрыва).
- Включено по умолчанию: `net.ipv4.tcp_sack = 1`.
- **D-SACK (RFC 2883):** получатель сообщает о дубликатах данных, помогая отправителю обнаружить ложные ретрансмиссии.
- Критически важно для производительности на каналах с потерями.

### Timestamps опция (RFC 7323)

- Используется для измерения RTT (RTTM) и защиты от перемотки последовательностей (PAWS).
- Включено по умолчанию: `net.ipv4.tcp_timestamps = 1`.
- Добавляет накладные расходы 12 байт (2 × 4-byte timestamps + 2 bytes kind/length).
- PAWS: предотвращает прием старых сегментов от предыдущей инкарнации соединения.

---

## Реализация в Linux

### Автоматическая настройка (Autotuning)

Современные ядра Linux динамически изменяют размер буферов сокета для максимизации пропускной способности.

**Ключевые параметры ядра:**
- **`net.ipv4.tcp_rmem`**: границы буфера приема (min, default, max).
- **`net.ipv4.tcp_wmem`**: границы буфера отправки (min, default, max).
- **`net.ipv4.tcp_adv_win_scale`**: коэффициент резервирования памяти.
  - Под `rwnd` выделяется: $Buffer / 2^{tcp\_adv\_win\_scale}$.
  - Значение `1` (по умолчанию) означает, что 50% памяти сокета отдано под окно данных, а 50% — под служебные структуры (`sk_buff`).
- **`net.ipv4.tcp_moderate_rcvbuf`**: включает автотюнинг приема (по умолчанию 1).
- **`net.ipv4.tcp_notsent_lowat`**: контроль неотправленных данных (Linux 4.14+), позволяет приложению определять, когда данных в буфере отправки слишком много (по умолчанию INT_MAX — отключено).

**Формат tcp_rmem/tcp_wmem:**
```
net.ipv4.tcp_rmem = min default max
net.ipv4.tcp_wmem = min default max
```
- `min`: Гарантированный объем памяти даже в условиях Memory Pressure.
- `default`: Начальный размер буфера. Должен быть согласован с BDP.
- `max`: Верхняя граница для автотюнинга. **Не может превышать `net.core.[r|w]mem_max`.**

**Формула BDP (Bandwidth-Delay Product):**
```
Buffer = Bandwidth (bps) × RTT (s)
```
Пример: 10Gbps × 50ms = 62.5 MB. Для такого соединения max должен быть не менее 64 МБ.

**Глобальный лимит tcp_mem:**
Параметр `net.ipv4.tcp_mem` измеряется в **страницах памяти** (обычно 4 КБ) и имеет формат `low pressure high`:
- `low`: Порог, ниже которого ядро не ограничивает выделение памяти.
- `pressure`: При достижении этого порога ядро переходит в режим «давления памяти», отключая автотюнинг и пытаясь сжать буферы до значений `min`.
- `high`: Абсолютный предел. При его достижении новые данные отбрасываются (Drop), а соединения могут принудительно закрываться.

### Sysctl-параметры для тюнинга

#### Буферы

| Параметр | Значение по умолчанию | Рекомендация (высокая нагрузка) | Описание |
| :--- | :--- | :--- | :--- |
| `net.core.rmem_max` | 212992 (208KB) | 16777216 (16MB) | Абсолютный максимум буфера приема |
| `net.core.wmem_max` | 212992 (208KB) | 16777216 (16MB) | Абсолютный максимум буфера отправки |
| `net.core.rmem_default` | 212992 | 262144 (256KB) | Буфер приема по умолчанию |
| `net.core.wmem_default` | 212992 | 262144 (256KB) | Буфер отправки по умолчанию |
| `net.ipv4.tcp_rmem` | 4096 131072 6291456 | 4096 87380 16777216 | Буфер приема: min, default, max |
| `net.ipv4.tcp_wmem` | 4096 16384 4194304 | 4096 65536 16777216 | Буфер отправки: min, default, max |
| `net.ipv4.tcp_mem` | (pages) | зависит от RAM | Глобальные пороги памяти TCP |

**Важно:** `rmem_max`/`wmem_max` должны быть ≥ третьего значения `tcp_rmem`/`tcp_wmem`. Нижний лимит побеждает.

#### Окна и масштабирование

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_window_scaling` | 1 (включено) | Включает RFC 7323 Window Scale |
| `net.ipv4.tcp_adv_win_scale` | 1 | Доля буфера под окно: 1 = 1/2 для приложения, 1/2 для окна |
| `net.ipv4.tcp_moderate_rcvbuf` | 1 (включено) | Автотюнинг буферов приема |
| `net.ipv4.tcp_notsent_lowat` | INT_MAX (отключено) | Порог неотправленных данных (Linux 4.14+) |

#### Управление перегрузкой

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_congestion_control` | cubic | Текущий алгоритм |
| `net.ipv4.tcp_available_congestion_control` | cubic reno | Доступные алгоритмы |
| `net.ipv4.tcp_slow_start_after_idle` | 1 (включено) | Сброс cwnd после простоя |
| `net.ipv4.tcp_init_cwnd` | 10 | Начальное окно перегрузки (MSS) |

**Рекомендованные серверные настройки:**
```bash
# /etc/sysctl.d/99-tcp-tuning.conf
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_adv_win_scale = 1
net.ipv4.tcp_moderate_rcvbuf = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_ecn = 1
net.ipv4.tcp_notsent_lowat = 131072
```

### Диагностика через ss

Анализ параметров окна для конкретного соединения:
```bash
ss -ti dst 1.2.3.4
# → cubic rto:204 rtt:15.2/0.5 cwnd:1000 rcv_space:14600 wscale:7,7
```
- **`rcv_space`**: текущий объем данных, который сервер готов принять (анонсируемое `rwnd`).
- **`wscale`**: согласованные множители (например, `7,7` означает, что значения окна умножаются на 128).
- **`cwnd`**: текущее окно перегрузки (в MSS).
- **`ssthresh`**: порог медленного старта.
- **`retrans`**: счетчик ретрансмиссий (всего/потеряно).

**Детальный мониторинг:**
```bash
# Полный вывод для всех established соединений
ss -tin state established

# Ключевые поля:
#   cwnd:10       — окно перегрузки (в MSS)
#   ssthresh:128  — порог медленного старта
#   rto:204       — таймаут ретрансмиссии (мс)
#   rtt:1.2/0.5   — сглаженный RTT / отклонение (мс)
#   mss:1460      — максимальный размер сегмента
#   wscale:7,7    — множители окна (send, receive)
#   send 96.5Mbps — рассчитанная скорость отправки
#   retrans:0/0   — счетчики ретрансмиссий
#   bytes_acked:14600
#   bytes_received:5840

# Быстрая сводка CWND/RTT/ssthresh
ss -tinH state established | awk '{
  cwnd = rtt = ssthresh = ""
  for (i = 1; i <= NF; i++) {
    if ($i ~ /^rtt:/) { split($i, a, ":"); split(a[2], b, "/"); rtt = b[1] }
    else if ($i ~ /^cwnd:/) { split($i, a, ":"); cwnd = a[2] }
    else if ($i ~ /^ssthresh:/) { split($i, a, ":"); ssthresh = a[2] }
  }
  if (cwnd != "") printf "CWND: %s MSS, RTT: %s ms, ssthresh: %s\n", cwnd, rtt, ssthresh
}'

# Мониторинг конкретного соединения
ss -tin dst 10.20.0.5

# Использование памяти на сокет
ss -m state established
```

### Diagnostika через nstat

```bash
# Все TCP-счетчики
nstat --zeros Tcp*

# Ключевые счетчики, связанные с flow control:
#   TcpRetransSegs              — всего ретрансмитированных сегментов
#   TcpExtTCPTimeouts           — таймаутов RTO
#   TcpExtTCPLostRetransmit     — ретрансмитов, которые были ACK'нуты
#   TcpExtTCPSlowStartRetrans   — ретрансмитов во время slow start
#   TcpExtTCPSACKRecovery       — восстановлений на основе SACK
#   TcpExtTCPAbortOnMemory      — соединений, закрытых из-за нехватки памяти
#   TcpExtTCPAbortOnTimeout     — соединений, закрытых по таймауту
#   TcpExtListenOverflows       — переполнений listen backlog
#   TcpExtListenDrops           — отброшенных listen socket
#   TcpExtTCPAutoCork           — событий auto-corking
#   TcpExtTCPOrigDataSent       — сегментов исходных данных
#   TcpExtTCPSynRetrans         — ретрансмитов SYN
#   TcpExtTCPFastRetrans        — событий fast retransmit
#   TcpExtTCPFastRecovery       — событий fast recovery
#   TcpExtTCPFullUndo           — полных откатов cwnd
#   TcpExtTCPLossProbes         — TLP (tail loss probe) проб
#   TcpExtTCPLossProbeRecovery  — восстановлений TLP

# Показать только измененные счетчики
nstat Tcp*

# Сброс и показать все (включая нули)
nstat --reset --zeros Tcp*
```

### NIC-уровень: ethtool (Pause Frames)

IEEE 802.3x pause frames оперируют на уровне L2, отличаясь от TCP flow control.

```bash
# Просмотр настроек pause frames
ethtool -a eth0

# Вывод:
# Pause parameters for eth0:
# Autonegotiate: off
# RX: off
# TX: off

# Включение/отключение pause frames
ethtool -A eth0 rx on tx on     # Включить
ethtool -A eth0 rx off tx off   # Отключить

# Проверка
ethtool -S eth0 | grep pause
# rx_pause_frames: 0
# tx_pause_frames: 0
```

**Рекомендация для дата-центров:** Отключать на обеих сторонах, чтобы избежать каскадных пауз. Валидировать у оператора.

### Traffic Control (tc) — Управление очередями

```bash
# Просмотр текущего qdisc
tc qdisc show dev eth0

# Замена на FQ (обязательно для BBR pacing)
tc qdisc replace dev eth0 root fq

# FQ-CoDel (хороший по умолчанию для общего трафика)
tc qdisc replace dev eth0 root fq_codel

# Добавление трафик-шейпинга (пример: 1Gbps)
tc qdisc add dev eth0 root tbf rate 1gbit burst 64kb latency 10ms

# Мониторинг статистики qdisc
tc -s qdisc show dev eth0

# Netem для эмуляции потерь/задержек (тестирование)
tc qdisc add dev eth0 root netem loss 0.1% delay 50ms
```

**Ключевые qdiscs:**
- **fq**: Fair Queue — поддержка TCP pacing, масштабируется на миллионы потоков (обязательно для BBR).
- **fq_codel**: FQ + CoDel AQM — борьба с bufferbloat.
- **tbf**: Token Bucket Filter — точное ограничение скорости.
- **netem**: Network emulation — тестирование с задержками/потерями/джиттером.

---

## Практические сценарии

### Сценарий 1: Проблема «зависшего» приложения (Zero Window)

**Симптом:** Передача данных прекращается, в дампе трафика видны пакеты `TCP Zero Window`.
**Причина:** Приложение на стороне получателя перестало вызывать `read()`/`recv()`. Буфер заполнился, стек TCP выставил окно 0.
**Диагностика:**
1. Выполните `ss -tnp` на стороне получателя.
2. Проверьте колонку `Recv-Q`. Если она заполнена (равна размеру буфера) — проблема в прикладном коде.
3. Проверьте `tcpdump` на наличие Zero Window:
```bash
sudo tcpdump -i any -nn 'tcp[14:2] = 0' -l | head -20
```

### Сценарий 2: Зондирование окна (Zero Window Probing)

Когда окно закрывается до 0, отправитель запускает **Persist Timer**.
- Чтобы избежать "тупика" (если ACK с открытием окна потеряется), отправитель периодически шлет 1-байтовый сегмент.
- Получатель обязан ответить ACK с актуальным размером `rwnd`.
- В Linux количество проб регулируется `net.ipv4.tcp_retries2`.

### Сценарий 3: Диагностика receiver window full (Zero Window)

**Проблема:** Соединение зависает, Zero Window в дампе.

```bash
# Шаг 1: Проверка Zero Window на проводе
sudo tcpdump -i any -nn 'tcp[14:2] = 0' -l | head -20

# Шаг 2: Проверка Recv-Q (данные в очереди, не прочитанные приложением)
ss -tni state established | grep -E 'Recv-Q|ESTAB'
# → Recv-Q 65536 0 10.0.0.1:80 10.0.0.5:54321
# 65536 байт в очереди — приложение не читает!

# Шаг 3: Если Recv-Q растет → приложение медленно читает
# Профилирование recv() вызовов
strace -e trace=recv,recvfrom -T -p <APP_PID> 2>&1 | \
  awk '{ if (match($0, /<[0-9.]+>/)) { elapsed=substr($0, RSTART+1, RLENGTH-2); if (elapsed+0>0.01) print "SLOW RECV:", $0 } }'

# Шаг 4: Проверка давления памяти
free -m
cat /proc/pressure/memory

# Шаг 5: Проверка лимитов буферов
sysctl net.ipv4.tcp_rmem net.core.rmem_max
```

**Причины (в порядке вероятности):**
1. Приложение не читает из сокета медленно (блокирующие операции ввода-вывода).
2. Недостаточные буферы сокетов (tcp_rmem max слишком низкий, или лимит rmem_max).
3. Высокая CPU на получателе (задержка обработки заполняет буфер).
4. Давление памяти (ядро ограничивает выделение памяти сокетам).

**Решения:**
- Увеличить `net.ipv4.tcp_rmem` max и `net.core.rmem_max`.
- Оптимизировать цикл чтения приложения (non-blocking I/O, epoll).
- Включить автотюнинг TCP: `net.ipv4.tcp_moderate_rcvbuf = 1`.

### Сценарий 4: Диагностика sender congestion (cwnd limited)

**Проблема:** Скорость передачи низкая, `cwnd` не растет.

```bash
# Шаг 1: Проверка cwnd vs rwnd
ss -tin state established | awk '{
  for(i=1;i<=NF;i++){
    if($i~/cwnd:/) cwnd=$i
    if($i~/ssthresh:/) st=$i
  }
  print cwnd, st
}'
# → cwnd:10 ssthresh:128
# cwnd мал, ssthresh велик → соединение в Slow Start, но не растет

# Шаг 2: Если cwnd << ssthresh → все еще в slow start
# Если cwnd ≈ ssthresh и растет линейно → в congestion avoidance
# Если cwnd часто падает → происходят потери

# Шаг 3: Проверка счетчиков ретрансмиссий
nstat --zeros TcpExtTCPLossProbes TcpExtTCPFastRetrans TcpExtTCPTimeouts TcpRetransSegs

# Шаг 4: Проверка RTT
ss -tin state established | grep rtt

# Шаг 5: Расчет BDP
# BDP = Bandwidth × RTT
# Если cwnd × MSS < BDP, cwnd является "бутылочным горлышком"
```

**Решения:**
- Увеличить начальное окно: `net.ipv4.tcp_init_cwnd = 10`.
- Переключиться на BBR для каналов с потерями.
- Увеличить буферы для заполнения BDP.
- Отключить slow start after idle: `net.ipv4.tcp_slow_start_after_idle = 0`.

### Сценарий 5: Диагностика retransmission storms

**Проблема:** Массовые ретрансмиссии, скорость падает.

```bash
# Шаг 1: eBPF трассировка ретрансмиссий
sudo tcpretrans -c

# Шаг 2: Проверка nstat счетчиков
nstat --zeros TcpRetransSegs TcpExtTCPTimeouts TcpExtTCPSlowStartRetrans TcpExtTCPFastRetrans

# Шаг 3: Классификация типа ретрансмиссий
# - Timeout (RTO) → серьезная потеря или black hole
# - Fast retransmit (3 dup ACK) → потеря одного пакета
# - TLP (tail loss probe) → потеря в конце передачи

# Шаг 4: Проверка проблем с ECN
nstat TcpExtTCPAbortOnMemory TcpExtTCPAbortOnTimeout

# Шаг 5: Проверка middlebox interference
# Ищем RST, аномалии окон в tcpdump
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & (tcp-rst) != 0' -c 20

# Шаг 6: Проверка ошибок интерфейса
ethtool -S eth0 | grep -E 'error|drop|miss|crc'

# Шаг 7: Проверка bufferbloat
tc -s qdisc show dev eth0
# Если qlen постоянно высокий → bufferbloat
```

### Сценарий 6: Анализ через tcpdump при Zero Window

**Задача:** Найти Zero Window и Persist Probes в дампе.

```bash
# Захват Zero Window пакетов
sudo tcpdump -i eth0 -nn 'tcp[14:2] = 0 and (tcp[tcpflags] & tcp-syn) == 0'

# Захват с детализацией (win= поле)
sudo tcpdump -i eth0 -vv tcp and port 8080

# Сохранение в pcap для Wireshark
sudo tcpdump -i eth0 -w /tmp/tcp.pcap tcp and host 10.0.0.1

# Wireshark фильтры для анализа:
#   tcp.analysis.zero_window
#   tcp.analysis.zero_window_probe
#   tcp.analysis.zero_window_probe_ack
#   tcp.analysis.window_update
#   tcp.window_size == 0
```

### Сценарий 7: Анализ через strace при буферных проблемах

**Задача:** Определить, почему приложение не читает данные из сокета.

```bash
# Трассировка сетевых syscalls
strace -e trace=%network -p <PID>

# Трассировка socket + send/recv с таймингом
strace -e trace=socket,connect,send,sendto,recv,recvfrom,setsockopt,close -T -s 256 -p <PID>

# Поиск медленных recv() вызовов (приложение не читает → zero window)
strace -e trace=recv,recvfrom,recvmsg -T -p <PID> 2>&1 | \
  awk '{ if (match($0, /<[0-9.]+>/)) { elapsed=substr($0, RSTART+1, RLENGTH-2); if (elapsed+0>0.01) print "SLOW RECV:", $0 } }'

# Подсчет syscalls (горячие пути)
strace -c -p <PID>

# Трассировка полного цикла TCP клиента
strace -e trace=socket,connect,send,recv,close -s 512 curl http://example.com

# Обнаружение блокировок send buffer (write возвращает EAGAIN)
strace -e trace=write,writev,send,sendmsg -T -p <PID> 2>&1 | grep -E 'EAGAIN|EWOULDBLOCK'
```

### Сценарий 8: eBPF мониторинг flow control

```bash
# Трассировка переходов состояний TCP
sudo tcpstates -tw

# Трассировка ретрансмиссий (обнаружение потерь пакетов)
sudo tcpretrans -c

# Трассировка падений пакетов
sudo tcpdrop

# Длительность congestion state
sudo tcpcong 1 10

# Трассировка соединений (обнаружение сбоев подключения)
sudo tcpconnect -t

# Трассировка задержки соединений
sudo tcpconnlat
```

### Сценарий 9: Диагностика bufferbloat

**Проблема:** Высокая задержка при низкой скорости, большие очереди.

```bash
# Проверка очередей
tc -s qdisc show dev eth0
# → qdisc fq 0: root refcnt 2 limit 10000p bytes 10485760
#  Если qlen постоянно высокий → bufferbloat

# Проверка через Wireshark/tshark
tshark -r capture.pcap -Y "tcp.analysis.ack_rtt > 0.1" -T fields -e frame.time -e tcp.analysis.ack_rtt
```

---

## Диагностические команды (агрегированная секция)

### Мониторинг состояний

```bash
# Подсчет соединений по состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c

# Просмотр соединений с деталями flow control
ss -tin state established | grep -E 'cwnd|ssthresh|rtt|retrans|rcv_space|wscale'

# Просмотр Recv-Q и Send-Q
ss -tnp state established | awk '{print $1, $2, $3, $6}'
```

### Глобальная статистика

```bash
# Счетчики flow control
nstat -az | grep -E 'TcpExt(TCPTimeouts|TCPAbortOn|TCPTimeWait|TCPFastClose|TCPLostRetransmit)'

# Счетчики bufferbloat
nstat -az | grep -E 'TcpExt(TCPBacklogDrop|ListenOverflows|ListenDrops)'
```

### Захват пакетов

```bash
# Zero Window
sudo tcpdump -i eth0 -nn 'tcp[14:2] = 0'

# Window updates
sudo tcpdump -i eth0 -vv tcp and port 8080

# RST пакеты
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-rst != 0'

# Конкретное соединение
sudo tcpdump -i eth0 -nn 'host 10.0.0.1 and port 443'
```

### Полный диагностический скрипт

```bash
#!/bin/bash
# TCP Performance Diagnostic Script

echo "=== 1. TCP Connection Summary ==="
ss -s

echo -e "\n=== 2. Congestion Control Algorithm ==="
sysctl net.ipv4.tcp_congestion_control

echo -e "\n=== 3. Buffer Settings ==="
sysctl net.ipv4.tcp_rmem net.ipv4.tcp_wmem net.core.rmem_max net.core.wmem_max

echo -e "\n=== 4. Window Scaling ==="
sysctl net.ipv4.tcp_window_scaling net.ipv4.tcp_adv_win_scale

echo -e "\n=== 5. Active Connections with cwnd/rtt ==="
ss -tinH state established | awk '{
  cwnd=rtt=ssthresh=retrans=""
  for(i=1;i<=NF;i++){
    if($i~/^cwnd:/) {split($i,a,":"); cwnd=a[2]}
    if($i~/^rtt:/) {split($i,a,":"); split(a[2],b,"/"); rtt=b[1]}
    if($i~/^ssthresh:/) {split($i,a,":"); ssthresh=a[2]}
    if($i~/^retrans:/) {split($i,a,":"); retrans=a[2]}
  }
  if(cwnd!="") printf "CWND:%s ssthresh:%s RTT:%sms retrans:%s\n", cwnd, ssthresh, rtt, retrans
}' | head -20

echo -e "\n=== 6. TCP Retransmission Counters ==="
nstat --zeros TcpRetransSegs TcpExtTCPTimeouts TcpExtTCPFastRetrans TcpExtTCPLossProbes 2>/dev/null

echo -e "\n=== 7. Listen Socket Issues ==="
nstat --zeros TcpExtListenOverflows TcpExtListenDrops 2>/dev/null

echo -e "\n=== 8. Memory Pressure ==="
cat /proc/pressure/memory 2>/dev/null || echo "PSI not available"
free -m

echo -e "\n=== 9. Zero Window Detection (5s sample) ==="
timeout 5 tcpdump -i any -nn 'tcp[14:2] = 0' 2>/dev/null | wc -l

echo -e "\n=== 10. NIC Statistics ==="
for nic in $(ls /sys/class/net/ | grep -v lo); do
  echo "--- $nic ---"
  ethtool -S $nic 2>/dev/null | grep -E 'error|drop|miss|crc|pause' | head -10
done
```

---

## Docker и Kubernetes

### Docker

```bash
# Проверка параметров в контейнере
docker exec <container> sysctl net.ipv4.tcp_congestion_control
docker exec <container> sysctl net.ipv4.tcp_rmem

# Установка оптимальных параметров (на хосте)
sudo tee /etc/sysctl.d/99-docker-networking.conf << 'EOF'
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_sack = 1
net.ipv4.tcp_max_syn_backlog = 8192
net.core.somaxconn = 65535
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
EOF
sudo sysctl --system
```

**Важно:** Настройки sysctl применяются на уровне хоста, а не контейнера. В привилегированных контейнентах `net.ipv4.tcp_congestion_control` доступен только для чтения.

### Kubernetes DaemonSet для BBR

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: tcp-tuning
  namespace: kube-system
spec:
  selector:
    matchLabels:
      name: tcp-tuning
  template:
    metadata:
      labels:
        name: tcp-tuning
    spec:
      hostPID: true
      containers:
      - name: sysctl
        image: busybox
        command:
        - sh
        - -c
        - |
          sysctl -w net.ipv4.tcp_congestion_control=bbr
          sysctl -w net.core.rmem_max=16777216
          sysctl -w net.core.wmem_max=16777216
          sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"
          sleep infinity
        securityContext:
          privileged: true
```

### Docker-специфичные замечания

- **MTU**: Docker bridge по умолчанию 1500; убедитесь, что MTU хоста совпадает.
- **veth pairs**: Каждый контейнер подключается через veth pair; мониторьте падения на bridge.
- **conntrack**: `net.netfilter.nf_conntrack_max` — увеличивайте для высоконагруженных соединений.
- **`tcp_notsent_lowat`** (Linux 4.14+): установите per-socket для контроля неотправленных данных; полезно для стриминга в контейнерах.

---

## Дополнительная информация

### См. также

- **[Управление перегрузкой](../congestion/tcp_congestion_control_overview.md)** — разбор окна `cwnd` и его взаимодействия с `rwnd`.
- **[Алгоритмы управления перегрузкой](../congestion/tcp_congestion_algorithms.md)** — справочник по логике работы CUBIC, BBRv3, DCTCP.
- **[Диагностика перегрузки](../congestion/tcp_congestion_diagnostics.md)** — инструменты для анализа cwnd и ретрансмиссий.
- **[Оптимизация буферов в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_buffer_tuning.md)** — практическая настройка лимитов памяти.
- **[Алгоритм Нагла](../tcp_nagle_algorithm.md)** — борьба с неэффективной передачей мелких данных.

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (современная спецификация 2022 года).
- **RFC 7323:** TCP Extensions for High Performance (Window Scale, Timestamps, SACK).
- **RFC 5681:** TCP Congestion Control (Slow Start, Congestion Avoidance, Fast Retransmit, Fast Recovery).
- **RFC 2018:** TCP Selective Acknowledgment Options.
- **RFC 2883:** D-SACK Extension (Duplicate SACK).
- **RFC 3168:** ECN (Explicit Congestion Notification).
- **RFC 6928:** TCP Initial Window (IW=10).
- **RFC 813:** Window and Acknowledgment Strategy in TCP.
- **RFC 9438:** CUBIC for TCP (актуальная спецификация).
- **RFC 6675:** Conservative SACK Recovery.
