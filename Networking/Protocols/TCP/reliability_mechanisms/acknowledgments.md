# Подтверждения в TCP (Acknowledgments)

## Определения

**Подтверждение (Acknowledgment, ACK)** — основной механизм обратной связи в протоколе TCP, уведомляющий отправителя об успешном приеме потока байтов. Реализуется через установку битового флага **ACK** в заголовке и указание 32-битного **Acknowledgment Number**.

**Cumulative ACK (Кумулятивное подтверждение):** Схема, при которой `Acknowledgment Number` указывает на порядковый номер следующего байта, который получатель ожидает увидеть. Все байты с номерами меньше этого значения официально считаются принятыми и могут быть удалены из буфера отправителя.

**Selective ACK (SACK):** Опция заголовка TCP (RFC 2018), дополняющая кумулятивный ACK. Позволяет получателю указать конкретные диапазоны принятых данных за пределами кумулятивного ACK, что позволяет отправителю ретрансмитировать только потерянные сегменты.

**ACK Number (Номер подтверждения):** 32-битное поле в заголовке TCP, указывающее порядковый номер байта, который получатель ожидает получить следующим. Все байты с порядковыми номерами меньшими, чем ACK Number, считаются успешно доставленными.

**Duplicate ACK (Дублирующее подтверждение):** ACK с тем же значением Acknowledgment Number, что и предыдущий ACK. Генерируется при получении сегмента с порядковым номером, превышающим ожидаемый (gap detection). Три consecutive Duplicate ACK инициируют Fast Retransmit.

**Partial ACK (Частичное подтверждение):** ACK, который подтверждает только часть данных, ожидаемых в фазе восстановления (recovery). Отличается от Normal ACK тем, что не покрывает все данные, потерянные перед входом в recovery.

**ACK Compression (Сжатие подтверждений):** Явление, при котором несколько ACK, генерируемых получателем в течение определенного времени, группируются и отправляются пачками. Приводит к burst-эффекту на стороне отправителя.

---

## Семантика Acknowledgment Number

Поле `Acknowledgment Number` в TCP заголовке — **не подтверждение пакета**, а подтверждение потока байтов:

```text
Отправитель отправляет: Seq=1000, Len=500 (байты 1000-1499)
Получатель подтверждает: ACK=1500 (ожидает байт 1500 следующим)

Отправитель отправляет: Seq=1500, Len=300 (байты 1500-1799)
Получатель подтверждает: ACK=1800

Отправитель отправляет: Seq=1800, Len=200 (байты 1800-1999)
Потеря! Получатель подтверждает: ACK=1800 (ожидает 1800, т.к. 1800-1999 не дошло)
```

**Важно:** ACK Number указывает на **следующий ожидаемый байт**, а не на последний принятый. Это «open interval»: `[0, ACK Number)` — все байты в этом диапазоне подтверждены.

---

## Правила генерации ACK (RFC 1122, RFC 9293)

TCP должен генерировать ACK в следующих случаях:

### Немедленная генерация ACK (Immediate ACK)

1. **Сегмент с данными (длина > 0):** Получатель генерирует ACK на каждый принятый сегмент с данными (но с задержкой, см. Delayed ACK).
2. **Сегмент с URG флагом:** Немедленный ACK.
3. **Сегмент с RST флагом:** Немедленный ACK.
4. **Сегмент с SYN флагом** (установление соединения): Немедленный ACK.
5. **Отсутствие данных более 500 мс:** Таймер Delayed ACK истек, ACK отправляется немедленно.

### Отложенная генерация ACK (Delayed ACK)

RFC 1122 определяет следующее поведение:

- **Не более одного ACK на 2 принятых сегмента:** Если получены 2+ сегмента подряд с данными, один ACK подтверждает оба. Это снижает количество ACK-пакетов в 2 раза.
- **Задержка до 500 мс:** ACK может быть задержан до 500 мс (RFC 1122: 500 мс — верхний предел).
- **Linux:** Задержка от **40 мс** (минимум) до **200 мс** (по умолчанию). Значение `ato` в `ss -ti` показывает текущий порог.

```text
Временная шкала Delayed ACK:

0 мс     40 мс              200 мс                     500 мс
 |         |                  |                          |
 |         |                  |                          |
 ▼         ▼                  ▼                          ▼
 Fast     Минимальная        По умолчанию               RFC 1122
 ACK      задержка           задержка                    максимум
```

**Конфликт с Nagle:** Если отправитель использует алгоритм Нагла и ожидает ACK перед отправкой следующего малого сегмента, а получатель задерживает ACK на 200 мс, возникает статическая задержка ровно 200 мс на каждом обмене. Решение: `TCP_NODELAY` или `TCP_QUICKACK`.

---

## Отложенные подтверждения (Delayed ACK)

### Механизм

Delayed ACK — оптимизация (RFC 1122), снижающая накладные расходы на передачу мелких ACK-пакетов:

1. **Piggybacking («прикрепление»):** Получатель задерживает ACK, надеясь «прикрепить» подтверждение к ответному пакету данных (например, HTTP-ответу). Это превращает 2 пакета (ACK + data) в 1.
2. **Порог подтверждения:** Если данных для отправки нет, получатель обязан отправить ACK после получения каждого второго сегмента MSS.
3. **Таймер:** В Linux таймер Delayed ACK: минимум 40 мс, по умолчанию 200 мс. Значение `ato` в `ss -ti` отражает текущий порог.

### QuickACK

В определенных ситуациях Linux отключает задержку и переходит в режим немедленных подтверждений:

- Во время **3-way Handshake** (SYN → SYN-ACK → ACK).
- Сразу после обнаружения потери (для ускорения **Fast Retransmit**).
- Если приложение явно запросило это через `TCP_QUICKACK`.
- При первых нескольких сегментах нового соединения (прогревочный период).

**tcp_quickack** — параметр в `ss -ti`. Если значение > 0, QuickACK активен и уменьшается с каждым отправленным ACK:

```bash
ss -ti dst 8.8.8.8
# → cubic rto:204 rtt:15.2/0.5 ato:40 quickack:4 cwnd:10
# quickack:4 → осталось 4 быстрых ACK перед возвратом к Delayed ACK
```

---

## Выборочные подтверждения (SACK)

### Назначение

При множественных потерях в одном окне кумулятивный ACK неэффективен — отправитель не знает, какие данные за пределами разрыва дошли до цели, и вынужден ретрансмитировать все сегменты начиная с потерянного (Go-Back-N).

SACK решает эту проблему, позволяя получателю указать конкретные диапазоны принятых данных.

### Формат опции SACK

```text
┌───────────────┬───────────────────┬───────────────────┐
│ Kind = 5      │ Length = 3+8*N    │ Block 1: Left1    │
│ (1 байт)      │ (1 байт)          │ (4 байта, NBO)   │
├───────────────┼───────────────────┼───────────────────┤
│ Block 1: Right1│ Block 2: Left2   │ Block 2: Right2   │
│ (4 байта)     │ (4 байта)         │ (4 байта)         │
├───────────────┴───────────────────┴───────────────────┤
│ ...до N блоков (N ≤ 4 в SACK v1, ≤ 34 в SACK v2)   │
└──────────────────────────────────────────────────────┘
```

- **Kind = 5:** Идентификатор опции SACK.
- **Length:** Длина опции = 2 + (8 × количество блоков).
- **Каждый блок:** 8 байт — `Left Edge` (4 байта) + `Right Edge` (4 байта).
- **Left Edge:** Первый байт диапазона (включительно).
- **Right Edge:** Последний байт диапазона + 1 (не включительно).

**Пример:** `sack 1 {2001:3001}` означает, что принят диапазон байтов `[2001, 3001)` = 1000 байт.

### SACK в SYN

SACK-Permitted опция (Kind=4, Length=2) передается в SYN/SYN-ACK для согласования поддержки SACK:

```text
Отправитель → Получатель: SYN, options [mss 1460, sackOK, wscale 7]
Получатель → Отправитель: SYN-ACK, options [mss 1460, sackOK, wscale 7]
```

Если одна из сторон не поддерживает SACK, опция не согласована, и используется только кумулятивный ACK.

### SACK в Linux: Нумерация

Linux нумерует SACK-блоки начиная с 1:
```text
sack 1 {2001:3001}   ← первый (и единственный) блок
sack 2 {1001:2001} {3001:4001}  ← два блока
```

---

## Duplicate SACK (DSACK)

### Назначение

DSACK (RFC 2883) расширяет SACK, позволяя отправителю определить, был ли сегмент ретрансмитирован ошибочно (spurious retransmission).

### Механизм

1. Отправитель ретрансмитирует сегмент (Seq=2000, Len=1000).
2. Получатель уже получил этот сегмент (дубликат).
3. Получатель отправляет ACK с SACK-блоком, содержащим DSACK-информацию.
4. DSACK-блок = диапазон, для которого получатель уже имеет данные.

### DSACK vs SACK

| Параметр | SACK | DSACK |
| :--- | :--- | :--- |
| **Назначение** | Сообщить о принятых данных за пределами кумулятивного ACK | Сообщить о полученном дубликате |
| **Формат** | `sack N {Left:Right}` | `dupsack N {Left:Right}` |
| **Выявление spurious retransmission** | Нет | Да |
| **Влияние на rto_recovery** | Помогает оптимизировать ретрансмит | Позволяет откатить ssthresh при ложном срабатывании |
| **Включение** | `net.ipv4.tcp_sack=1` | `net.ipv4.tcp_dsack=1` |

### Пример в tcpdump

```bash
sudo tcpdump -ni any 'tcp' -v 2>/dev/null | grep -i 'sack\|dupsack'
# → ... ack 2001, options [nop,nop,sack 1 {1001:2001}], length 0
#    ^^^^^^^^^^^^
#    SACK-блок указывает на принятые данные [1001, 2001)
```

---

## ACK Clocking (Синхронизация по подтверждениям)

Подтверждения служат «метрономом» для отправителя. Приход каждого нового ACK открывает окно (`cwnd`) и позволяет отправить новые данные, что поддерживает стабильный темп передачи (self-clocking).

```text
Отправитель                       Получатель
    |                                 |
    |---- Seg1 (1000 bytes) --------->|
    |                                 |
    |<--- ACK 1001 ------------------|  → ACK Clock: "tick"
    |---- Seg2 (1000 bytes) -------->|
    |                                 |
    |<--- ACK 2001 ------------------|  → ACK Clock: "tick"
    |---- Seg3 (1000 bytes) -------->|
```

**ACK Compression** (сжатие ACK): Если ACK приходят к отправителю пачками (из-за задержек в обратном канале), вместо «тика-тика-тика» получается «тик-ТИК-ТИК», что вызывает burst-передачу и может вызвать потерю.

```text
Нормальный ACK Clock:
ACK1 (t=0)  ACK2 (t=50)  ACK3 (t=100)
   |             |             |
   ▼             ▼             ▼
 Send1         Send2         Send3

ACK Compression:
ACK1 (t=0)  ACK2 (t=5)  ACK3 (t=6)
   |             |             |
   ▼             ▼             ▼
 Send1      Burst2+3       (потеря!)
```

---

## Взаимодействие ACK с другими механизмами

### ACK и Congestion Window (cwnd)

Каждый ACK, подтверждающий новые данные, увеличивает `cwnd`:

```text
Slow Start:   cwnd += MSS  (за каждый ACK, подтверждающий MSS данных)
Cong. Avoid.: cwnd += MSS²/cwnd  (за каждый ACK)
```

Если ACK задерживается (Delayed ACK), рост `cwnd` замедляется. Если ACK потерян, `cwnd` не растет, что может ограничить throughput.

### ACK и Retransmission

- **3 Duplicate ACK** → Fast Retransmit (RFC 5681): `ssthresh = cwnd/2`, `cwnd = ssthresh + 3 MSS`.
- **Timeout** (ACK не пришел) → RTO: `cwnd = 1 MSS`, `ssthresh = cwnd/2`.
- **Partial ACK** в recovery (NewReno):触发 additional retransmission для следующего потерянного сегмента.

### ACK и Window Update

ACK может содержать обновление окна получателя (`rwnd`). Window Update может прийти отдельным ACK-пакетом (без данных), особенно после Zero Window:

```text
Получатель: ACK, rwnd=0         (Zero Window)
Приложение читает данные
Получатель: ACK, rwnd=16384     (Window Update)
```

---

## Eifel Detection (RFC 3522, RFC 4015)

Eifel — алгоритм обнаружения **spurious retransmission** (ложной ретрансмиссии) с использованием TCP Timestamps.

### Механизм

1. Отправитель запоминает `TSval` в оригинальном сегменте.
2. При ретрансмиссии отправляет тот же `TSval`.
3. Получатель отвечает `TSecr = TSval` (эхо).
4. Отправитель сравнивает `TSecr` в ACK с `TSval` ретрансмитированного сегмента.
5. Если совпадают — ретрансмиссия была **spurious** (ложной).

### Причины spurious retransmission

- **路由振荡:** Временная потеря маршрута, после чего пакет дошел, но задержался.
- **LOST Reordering:** Пакет был reordered, не потерян, но отправитель誤認 его потерянным.
- **ACK Loss:** Пакет дошел, но ACK потерян.

### Влияние

При обнаружении spurious retransmission Eifel может:
- Откатить `ssthresh` (если он был понижен из-за «ложной» потери).
- Восстановить `cwnd` до значения до «потери».

```bash
# Проверка: включено ли Eifel в ядре
sysctl net.ipv4.tcp_ecn
# Eifel зависит от TCP Timestamps (net.ipv4.tcp_timestamps=1)
sysctl net.ipv4.tcp_timestamps
```

---

## Практические сценарии

### Сценарий 1: Анализ SACK в tcpdump

Наличие SACK-блоков в дампе — признак потерь в сети.

```bash
sudo tcpdump -ni any 'tcp' -v 2>/dev/null | grep -E 'sack|ack'
# → ... ack 1001, options [nop,nop,sack 1 {2001:3001}]
# → Результат: Получатель подтверждает получение блока 2001–3000,
#              но все еще ждет байт 1001 (разрыв в данных).
```

### Сценарий 2: Мониторинг задержек ACK через ss

Утилита `ss` показывает параметр `ato` (Acknowledgment Timeout):

```bash
ss -ti dst 8.8.8.8
# → cubic rto:204 rtt:15.2/0.5 ato:40 cwnd:10
```

- **ato:40:** Сокет в режиме QuickACK (малая задержка).
- **ato:200:** Сокет использует стандартный Delayed ACK.

### Сценарий 3: Глобальная статистика через nstat

Анализ эффективности работы механизмов подтверждения:

```bash
nstat -az TcpExtTCPACKCompressed TcpExtTCPACKDelayed TcpExtTCPPureAcks
# → TcpExtTCPACKDelayed    5230    0.0  ← кол-во отложенных ACK
# → TcpExtTCPACKCompressed  142    0.0  ← кол-во «склеенных» ACK (burst)
# → TcpExtTCPPureAcks       891    0.0  ← кол-во «пустых» ACK (без данных)
```

### Сценарий 4: Поиск SACK через tshark

```bash
# Все пакеты с SACK-опцией
tshark -r capture.pcap -Y "tcp.options.sack" -T fields \
  -e frame.time -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport \
  -e tcp.ack -e tcp.options.sack 2>/dev/null | head -10

# DSACK блоки (dupsack)
tshark -r capture.pcap -Y "tcp.analysis.dsack" -T fields \
  -e frame.time -e ip.src -e ip.dst -e tcp.options.sack 2>/dev/null | head -10

# Статистика по количеству SACK-блоков
tshark -r capture.pcap -Y "tcp.options.sack" -T fields \
  -e tcp.options.sack 2>/dev/null | wc -l
```

### Сценарий 5: Мониторинг Delayed ACK через bpftrace

```bash
# Отслеживание вызовов tcp_send_delayed_ack
sudo bpftrace -e 'kprobe:tcp_send_delayed_ack {
    printf("delayed_ack: pid=%d comm=%s\n", pid, comm);
}'

# Подсчет количества Delayed ACK по процессам
sudo bpftrace -e 'kprobe:tcp_send_delayed_ack {
    @[comm] = count();
}'

# Отслеживание Delayed ACK с временными метками
sudo bpftrace -e 'kprobe:tcp_send_delayed_ack {
    printf("%d %s delayed_ack ato=%d\n", nsecs, comm, (int)arg1);
}'
```

### Сценарий 6: Проверка SACK/DSACK в sysctl

```bash
# Включены ли SACK и DSACK
sysctl net.ipv4.tcp_sack net.ipv4.tcp_dsack
# → net.ipv4.tcp_sack = 1
# → net.ipv4.tcp_dsack = 1

# Статистика SACK-восстановлений
nstat -az | grep -i sackrecovery
# → TcpExtTCPSACKRecovery     120    0.0  ← кол-во recovery через SACK
```

### Сценарий 7: Wireshark фильтры для анализа ACK

```
# Все ACK-пакеты с данными (piggybacked ACK)
tcp.flags.ack == 1 && tcp.len > 0

# Delayed ACK (ACK без данных, пришедший через ~200мс после data)
tcp.flags.ack == 1 && tcp.len == 0 && tcp.analysis.delayed_ack

# SACK-блоки
tcp.options.sack

# Duplicate ACK
tcp.analysis.duplicate_ack

# Window Update (ACK с измененным rwnd)
tcp.analysis.window_update

# Pure ACK (ACK без данных)
tcp.flags.ack == 1 && tcp.len == 0 && !tcp.flags.syn && !tcp.flags.fin
```

---

## Диагностика

### Быстрый старт

```bash
# 1. Проверка режима ACK (QuickACK vs Delayed)
ss -ti dst <IP> | grep -oE 'ato:[0-9]+|quickack:[0-9]+'

# 2. Проверка SACK/DSACK
sysctl net.ipv4.tcp_sack net.ipv4.tcp_dsack

# 3. Статистика ACK-механизмов
nstat -az | grep -iE 'ACK|SACK|DSACK|delayed|quickack|compress'

# 4. Поиск SACK-блоков в дампе
tshark -r capture.pcap -Y "tcp.options.sack" 2>/dev/null | wc -l

# 5. Поиск Delayed ACK
tshark -r capture.pcap -Y "tcp.analysis.delayed_ack" 2>/dev/null | wc -l
```

### Счетчики nstat

| Счетчик | Описание |
| :--- | :--- |
| `TcpExtTCPACKDelayed` | Количество отложенных ACK (Delayed ACK). |
| `TcpExtTCPACKCompressed` | Количество «склеенных» ACK (ACK Compression). |
| `TcpExtTCPPureAcks` | Количество «пустых» ACK (ACK без данных). |
| `TcpExtTCPSACKRecovery` | Количество recovery через SACK. |
| `TcpExtTCPDSACKOldSent` | Количество отправленных DSACK (старые данные). |
| `TcpExtTCPDSACKOldRecv` | Количество принятых DSACK (старые данные). |
| `TcpExtTCPDSACKNewRecv` | Количество принятых DSACK (новые данные). |

---

## Справочник sysctl

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_sack` | 1 | SACK: 0=отключен, 1=включен. Обязателен для RFC 6675. |
| `net.ipv4.tcp_dsack` | 1 | D-SACK: 0=отключен, 1=включен. Помогает обнаруживать spurious retransmission. |
| `net.ipv4.tcp_timestamps` | 1 | TCP Timestamps (RFC 7323). Нужен для Eifel, PAWS, RTT measurement. |
| `net.ipv4.tcp_win_scale` | (auto) | Window Scale. Согласовывается в SYN. |

> **См. также:** Полный список sysctl — [Flow Control](../Flow_Control/index.md).

---

## Дополнительная информация

### См. также
- **[Порядковые номера](./sequence_numbers.md)** — база для расчета ACK Number.
- **[Механизмы ретрансмиссии](./retransmission.md)** — как Duplicate ACK и SACK инициируют восстановление.
- **[Алгоритм Нагла](../tcp_nagle_algorithm.md)** — причины сетевых «тупиков» при взаимодействии с Delayed ACK.
- **[Управление потоком (Flow Control)](../Flow_Control/index.md)** — Window Update, Zero Window, Persist Timer.
- **[Опции заголовка TCP](../Header_Format/options.md)** — битовая структура опций SACK и DSACK.
- **[Диагностика надежности](./diagnostics.md)** — полный каталог счетчиков, eBPF-инструменты.

### Стандарты (RFC)
- **RFC 9293:** Transmission Control Protocol (2022).
- **RFC 2018:** TCP Selective Acknowledgment Options (SACK).
- **RFC 2883:** An Extension to the Selective Acknowledgement (SACK) Option for TCP (DSACK).
- **RFC 3522:** The Eifel Detection Algorithm for TCP.
- **RFC 4015:** The Eifel Detection Algorithm for TCP (_errata_).
- **RFC 1122:** Requirements for Internet Hosts — Communication Layers (Delayed ACK, SWS).
- **RFC 5681:** TCP Congestion Control (ACK role in cwnd update).
