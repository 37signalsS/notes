# Опции TCP и ECN

## Определения

**Опции TCP (TCP Options)** — дополнительные поля переменной длины, расположенные в конце заголовка TCP (после поля Urgent Pointer). Они расширяют базовый протокол, позволяя согласовывать параметры производительности, улучшать надежность (SACK) и обеспечивать работу в современных высокоскоростных сетях.

**ECN (Explicit Congestion Notification)** — механизм явного уведомления о перегрузке, позволяющий промежуточным узлам (маршрутизаторам) сообщать конечным точкам о возникновении очередей без отбрасывания пакетов.

---

## Методология анализа

При изучении опций TCP следуйте иерархии:

1. **Уровень 1: Согласование** — какие опции обмениваются в SYN/SYN-ACK (handshake).
2. **Уровень 2: Семантика** — что каждая опция означает и как работает (механизм).
3. **Уровень 3: Ограничения** — какие проблемы возникают (blackhole, 40-байт бюджет).
4. **Уровень 4: Диагностика** — как проверить согласование через tcpdump/ss/tshark.

---

## Базовые концепции

### Общий формат опций TCP

Опции располагаются в заголовке TCP после поля Urgent Pointer и выравниваются по **32-битной границе**. Базовый заголовок = 20 байт; максимум = 60 байт → **максимум 40 байт опций**.

**Формат TLV (Type-Length-Value):**

| Поле | Размер (байт) | Описание |
| :--- | :--- | :--- |
| **Kind** | 1 | Тип опции (регистр IANA) |
| **Length** | 1 | Общая длина в байтах (включая Kind + Length) |
| **Value** | 0–38 | Данные опции |

**Служебные опции (1 байт, без Length/Value):**

| Опция | Kind | Описание |
| :--- | :--- | :--- |
| **EOL** | 0 | Конец списка опций |
| **NOP** | 1 | Выравнивание по 32-битной границе |

**Бюджет опций:** 40 байт — это абсолютный максимум. Если согласовано несколько опций, они должны поместиться в 40 байт. Суммарный размер опций не может превышать этот лимит.

### Таблица основных опций TCP

| Опция | Kind | Длина | Формат | Когда согласуется |
| :--- | :--- | :--- | :--- | :--- |
| **EOL** | 0 | 1 байт | — | Конец списка |
| **NOP** | 1 | 1 байт | — | Выравнивание |
| **MSS** | 2 | 4 байта | Kind + Length + 16-bit value | Только SYN |
| **Window Scale** | 3 | 3 байта | Kind + Length + shift.cnt | Только SYN |
| **SACK Permitted** | 4 | 2 байта | Kind + Length | Только SYN |
| **SACK Data** | 5 | Переменная | Kind + Length + blocks (8B/block) | ACK после handshake |
| **Timestamps** | 8 | 10 байт | Kind + Length + TSval(4) + TSecr(4) | Только SYN |
| **TFO** | 34 | 6–18 байт | Kind + Length + Cookie | Только SYN |
| **MPTCP** | 30 | Переменная | Kind + Length + subtypes | Только SYN |

### Типичный SYN-пакет с опциями

```text
TCP Header (20 байт базовый):
┌───────────────┬───────────────┬───────────────┬───────────────┐
│  Src Port     │  Dst Port     │  Seq Number   │  Ack Number   │
├───────────────┼───────────────┼───────────────┼───────────────┤
│  Data Offset  │  Flags [SYN]  │  Window       │  Checksum     │
├───────────────┴───────────────┴───────────────┴───────────────┤
│  Options (variable):                                          │
│  MSS=1460 (4B) → NOP (1B) → NOP (1B) → WS=7 (3B)           │
│  → NOP (1B) → SACK OK (2B) → TS val=123 ecr=0 (10B)        │
│  Total: 4 + 1 + 1 + 3 + 1 + 2 + 10 = 22 bytes              │
└───────────────────────────────────────────────────────────────┘
```

**Альтернативный порядок опций:**
```text
NOP, NOP, MSS=1460, NOP, NOP, WS=7, SACK OK, TS val=123 ecr=0
```

---

## Опция MSS (Maximum Segment Size)

### Детали

**Kind:** 2 | **Длина:** 4 байта (Kind + Length + 16-bit value).

Указывает максимальный объем данных (payload), который хост готов принять в одном TCP-сегменте.

**Ключевые правила:**
- Передается **только** в SYN-пакетах (установление соединения).
- В SYN-ACK сервер может вернуть свой MSS или не вернуть (клиент использует минимум).
- Если MSS не согласован → используется **значение по умолчанию: 536 байт** (RFC 9293).
- **Effective Send MSS** = MSS - (Timestamps if present: 12 bytes) - (SACK Permitted if present: 2 bytes).

**Расчет MSS:**
```text
Базовый MSS = MTU - IP_Header - TCP_Header
            = 1500 - 20 - 20
            = 1460 байт (Ethernet)

С Timestamps:  1460 - 12 = 1448
С SACK + TS:   1448 - 2  = 1446
```

**Значения MSS по умолчанию:**

| Сценарий | MSS | Примечание |
| :--- | :--- | :--- |
| Ethernet MTU 1500 | 1460 | Стандарт |
| PPPoE MTU 1492 | 1452 | PPPoE overhead |
| IPsec/VPN MTU 1420 | 1380 | Типично для WireGuard/IPsec |
| GRE/IPIP MTU 1400 | 1360 | Туннели |
| Железо по умолчанию (не согласовано) | 536 | RFC 9293 default |

**Проблема MSS Blackhole:**
Если маршрутизатор не поддерживает PMTUD и ICMP PTB заблокирован, пакеты с MSS=1460 могут дропаться. Решение — **MSS Clamping** на шлюзе:

```bash
# iptables
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
  -j TCPMSS --clamp-mss-to-pmtu

# nftables
nft add rule ip mangle forward tcp flags syn \
  tcp option maxseg size set tcp mss

# Принудительный MSS (например, для WireGuard MTU 1420)
iptables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN \
  -j TCPMSS --set-mss 1380
```

*Подробнее:* [Связь MTU и MSS](../../../OSI_TCP_IP_Model/transport_layer.md), [MSS Clamping](../../../OSI_TCP_IP_Model/Network_layer/ip_fragmentation.md#mss-clamping).

---

## Опция Window Scale (WSCALE)

### Детали

**Kind:** 3 | **Длина:** 3 байта (Kind + Length + shift.cnt).

Позволяет использовать окна приема более 64 КБ (до 1 ГБ). Без масштабирования максимум = 65 535 байт (16 бит в заголовке).

**Механизм:**
- Поле Window в заголовке TCP: 16 бит.
- Реальное окно = `advertised_window × 2^shift.cnt`.
- Значение `shift.cnt` (0–14) согласуется в SYN-пакетах.
- **Каждая сторона указывает свой shift.cnt** (отправитель и получатель могут использовать разные множители).

**Формула:**
```text
Real_Window = Header_Window × 2^shift.cnt
            = 65535 × 2^14
            = 65535 × 16384
            = 1 073 676 288 байт (~1 ГБ)
```

**Значения shift.cnt:**

| shift.cnt | Множитель | Макс. окно | BDP при RTT=100мс | Пропускная способность |
| :--- | :--- | :--- | :--- | :--- |
| 0 | 1 | 64 КБ | 5.2 Мбит/с | Низкая |
| 7 | 128 | 8 МБ | 655 Мбит/с | Средняя |
| 9 | 512 | 32 МБ | 2.56 Гбит/с | Высокая |
| 14 | 16384 | 1 ГБ | 81 Гбит/с | Очень высокая |

**BDP (Bandwidth-Delay Product):**
```text
BDP = Bandwidth × RTT
    = 1 Gbps × 100 ms
    = 100 Mbit = 12.5 MB

Для этого BDP нужен shift.cnt ≥ 14 (max window = 1 ГБ)
```

**Linux расчёт shift.cnt:**
```bash
# Ядро Linux вычисляет optimal shift.cnt на основе:
# 1. Размера socket receive buffer (net.core.rmem_max)
# 2. Текущего RTT (от адаптивного алгоритма)
# 3. Согласованного MSS

# Просмотр текущего буфера
sysctl net.ipv4.tcp_rmem
# → 4096 131072 6291456  (min default max в байтах)

# Просмотр MTU (влияет на MSS → на shift.cnt)
ip link show eth0 | grep mtu
```

*Подробнее:* [Управление потоком](../Flow_Control/index.md).

---

## Опция SACK (Selective Acknowledgment)

### Детали

#### SACK Permitted (Kind 4)

**Длина:** 2 байта (Kind + Length).

Согласуется в SYN/SYN-ACK → разрешает использовать SACK в данном соединении.

#### SACK Data (Kind 5)

**Длина:** Переменная (8 байт на блок × N блоков).

**Формат блока:**
```text
┌───────────────────────────────────────────────────┐
│  Left Edge of 1st Block (32 bits)                 │
├───────────────────────────────────────────────────┤
│  Right Edge of 1st Block (32 bits)                │
├───────────────────────────────────────────────────┤
│  Left Edge of 2nd Block (32 bits)                 │
├───────────────────────────────────────────────────┤
│  Right Edge of 2nd Block (32 bits)                │
├───────────────────────────────────────────────────┤
│  ... (до 4 блоков в IPv4, 3 в IPv6)              │
└───────────────────────────────────────────────────┘
```

**Ключевые правила:**
- **Left Edge** = первый подтвержденный байт блока.
- **Right Edge** = следующий байт после последнего подтвержденного (не включается).
- **Количество блоков:** максимум **3–4** (ограничение 40-байт бюджета опций).
- **Reneging:** если получатель установил SACK-блок → он **обязан** хранить эти данные до получения DupACK или ACK, подтверждающего получение.

**D-SACK (Duplicate SACK, RFC 2883):**
Если SACK-блок совпадает с уже подтвержденными данными → это **D-SACK**. Используется для:
- Определения **ложных ретрансмиссий** (отправитель отправил повторно то, что уже получено).
- Определения **потерь ACK** (ACK потерялся, хотя данные дошли).
- Определения **ретрансмиссий доReceive** (данные пришли до DupACK).

**Пример D-SACK:**
```text
Получатель имеет ACK=1000, SACK blocks:
[1000, 2000]  — новый блок
[500, 1000]   — D-SACK (уже было подтверждено ACK=1000)
```

*Подробнее:* [Диагностика надежности TCP](../reliability_mechanisms/diagnostics.md), [SACK](../reliability_mechanisms/selective_acknowledgments.md).

---

## Опция Timestamps (TS)

### Детали

**Kind:** 8 | **Длина:** 10 байт (Kind + Length + TSval(4) + TSecr(4)).

**Два назначения:**
1. **RTTM (Round-Trip Time Measurement):** Точное измерение RTT через эхо Timestamps.
2. **PAWS (Protection Against Wrapped Sequences):** Защита от перемотки номеров последовательностей при высоких скоростях.

**Формат:**
```text
┌───────────────────────────────────────────────────┐
│  Kind (1 байт): 8                                 │
├───────────────────────────────────────────────────┤
│  Length (1 байт): 10                              │
├───────────────────────────────────────────────────┤
│  TSval (4 байта): Timestamp Value (время отправки)│
├───────────────────────────────────────────────────┤
│  TSecr (4 байта): Timestamp Echo Reply            │
│                    (эхо последнего принятого TSval)│
└───────────────────────────────────────────────────┘
```

**Как работает RTTM:**
1. Отправитель ставит `TSval = текущее время`.
2. Получатель в ACK ставит `TSecr = TSval` (эхо).
3. Отправитель вычисляет: `RTT = текущее_время - TSecr`.

**Как работает PAWS:**
- При высоких скоростях (>1 Гбит/с) номера последовательностей могут «перемотаться» за время жизни пакета (MSL).
- PAWS использует монотонно возрастающие Timestamps для различения «старых» и «новых» пакетов.
- Если TSval < last_ts → пакет отбрасывается (PAWS violation).

**Влияние Timestamps на MSS:**
```text
Без Timestamps:  MSS = MTU - 20(IP) - 20(TCP) = 1460
С Timestamps:    MSS = 1460 - 12(10B TS + 2B NOP) = 1448
```

**Linux-параметры Timestamps:**
```bash
# Включение/выключение Timestamps
sysctl net.ipv4.tcp_timestamps     # 1=вкл (по умолчанию), 0=выкл

# Отключение Timestamps ускоряет handshake на ~0.5 RTT,
# но теряет RTTM и PAWS. НЕ рекомендуется.
```

---

## NOP и EOL: выравнивание

### EOL (End of Option List)

**Kind:** 0 | **Длина:** 1 байт.

- Указывает конец списка опций.
- Все оставшиеся байты в опциях (после EOL) игнорируются.
- На практике почти не используется — опции выравниваются через NOP.

### NOP (No Operation)

**Kind:** 1 | **Длина:** 1 байт.

- Используется как **заполнитель** для выравнивания последующих опций по 32-битной границе.
- Типичный сценарий: MSS (4B) → NOP (1B) → NOP (1B) → Window Scale (3B).

**Пример NOP-выравнивания:**
```text
MSS=1460 (4B) + NOP(1B) + NOP(1B) + WS=7 (3B) = 9B (не кратно 4)
→ добавляем NOP(1B) → 10B (не кратно 4)
→ добавляем NOP(1B) → 11B (не кратно 4)
→ добавляем NOP(1B) → 12B (кратно 4) ✓

Итого: MSS(4) + NOP(1) + NOP(1) + NOP(1) + WS(3) + NOP(1) + SACK(2) + TS(10) = 22B
```

**OS fingerprinting через NOP:**
Некоторые операционные системы используют разные комбинации NOP для выравнивания. Это используется для **fingerprinting** ОС по SYN-пакету.

---

## TCP Fast Open (TFO)

### Детали

**Kind:** 34 | **Длина:** 6–18 байт (Cookie).

Позволяет отправлять данные в первом SYN-пакете (без ожидания 3-way handshake).

**Handshake:**
```text
1. SYN [TFO Request]        → Сервер
2. SYN-ACK [TFO Cookie]     ← Сервер (генерирует Cookie через HMAC)
3. ACK + [Data + TFO Cookie] → Сервер (первая передача данных)
```

**Как работает Cookie:**
1. Клиент отправляет SYN с пустым TFO cookie.
2. Сервер генерирует Cookie (HMAC от IP клиента + секретный ключ) и отправляет в SYN-ACK.
3. Клиент кеширует Cookie. При следующем соединении → SYN + Cookie + Data.
4. Сервер проверяет Cookie → допускает данные до завершения handshake.

**Включение в Linux:**
```bash
# Включение TFO
sysctl -w net.ipv4.tcp_fastopen=3
# 0=выкл, 1=только клиент, 2=только сервер, 3=оба

# Размер очереди TFO запросов
sysctl -w net.ipv4.tcp_fastopen_key
```

*Подробнее:* [TCP Fast Open в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_fast_open.md).

---

## Multipath TCP (MPTCP)

### Детали

**Kind:** 30 | **Длина:** Переменная (10+ подтипов).

Агрегация нескольких сетевых интерфейсов (Wi-Fi + 5G, Ethernet + LTE) в одно логическое TCP-соединение.

**Подтипы (RFC 8684):**

| Subtype | Название | Описание |
| :--- | :--- | :--- |
| 0x0 | MP_CAPABLE | Согласование MPTCP capabilities |
| 0x1 | MP_JOIN | Присоединение нового subflow |
| 0x2 | DSS | Data Sequence Signal (данные) |
| 0x3 | ADD_ADDR | Добавление адреса |
| 0x4 | REMOVE_ADDR | Удаление адреса |
| 0x5 | MP_PRIO | Приоритет subflow |
| 0x6 | MP_FAIL | Ошибка (fallback на TCP) |
| 0x7 | MP_FASTCLOSE | Быстрое закрытие |
| 0x8 | MP_TCPRST | Сброс subflow |
| 0x9 | MP_CRYPTO | Криптографические ключи |
| 0xA | MP_PRIO | Приоритет (расширенный) |

**Сценарии использования:**
- **Handover:** Wi-Fi → 5G без разрыва соединения.
- **Aggregate:** общий Throughput = сумма Throughput всех интерфейсов.
- **Redundant:** дублирование данных через оба интерфейса (высокая надежность).

**Включение в Linux:**
```bash
# Проверка поддержки
modprobe mptcp
sysctl net.mptcp.enabled
# → 1 (включено)

# Управление subflows
ip mptcp endpoint add 192.168.1.100 subflow
ip mptcp endpoint add 10.0.0.50 subflow
```

---

## Механизм ECN и L4S

### Биты ECN в заголовке IP (L3)

2 бита в поле Traffic Class (IPv6) / ToS (IPv4):

| Значение | Название | Описание |
| :--- | :--- | :--- |
| `00` | Non-ECT | ECN не поддерживается (обычный трафик) |
| `01` | ECT(1) | ECN-совместимый (L4S: микро-сигналы) |
| `10` | ECT(0) | ECN-совместимый (стандартный ECN) |
| `11` | CE | Congestion Experienced (устанавливается маршрутизатором) |

**Когда ECT(0) vs ECT(1):**
- **ECT(0):** Стандартный ECN (RFC 3168).
- **ECT(1):** L4S (RFC 9330) — указывает маршрутизатору использовать **CE marking** для микро-сигналов перегрузки.

### Биты ECN в заголовке TCP (L4)

| Флаг | Бит (позиция в байте 13) | Описание |
| :--- | :--- | :--- |
| **ECE** | 6 | Получатель эхосирует CE-сигнал → ACK с ECE=1 |
| **CWR** | 7 | Отправитель подтверждает снижение cwnd → следующий сегмент с CWR=1 |

### Handshake ECN

```text
Клиент                              Сервер
   │                                    │
   │  SYN [ECE, CWR]                    │  ← клиент запрашивает ECN
   │───────────────────────────────────>│
   │                                    │
   │  SYN-ACK [ECE]                     │  ← сервер подтверждает ECN
   │<───────────────────────────────────│
   │                                    │
   │  ACK                                │  ← handshake завершен
   │───────────────────────────────────>│
   │                                    │
   │  ... данные ...                    │
   │                                    │
   │  [Пакет с CE=11]                   │  ← маршрутизатор ставит CE
   │<───────────────────────────────────│
   │                                    │
   │  ACK [ECE]                          │  ← получатель эхосирует CE
   │───────────────────────────────────>│
   │                                    │
   │  [Следующий сегмент] [CWR]          │  ← отправитель снижает cwnd
   │───────────────────────────────────>│
```

### L4S (Low Latency, Low Loss, Scalable)

**RFC 9330** — современный стандарт, использующий кодирование **ECT(1)** для сигнализации о микро-перегрузках.

**Как работает L4S:**
1. Маршрутизатор использует **_dualQ** — разделяет ECT(0) и ECT(1) трафик в разные очереди.
2. ECT(1) трафик обрабатывается **algorithmically** (Prague, BBRv3) — сверхнизкие задержки.
3. ECT(0) трафик обрабатывается **traditionally** (Cubic, Reno) — совместимость.
4. CE marking в ECT(1) очереди более агрессивный → микро-сигналы.

**Преимущества L4S:**
- RTT < 10 мс для real-time (gaming, video conferencing).
- Нет потери throughput.
- Обратная совместимость с legacy ECN.

**Включение в Linux:**
```bash
# Включение ECN
sysctl -w net.ipv4.tcp_ecn=1

# Проверка BBRv3 (альгоритм для L4S)
sysctl net.ipv4.tcp_congestion_control
# → bbr
```

---

## 40-байт бюджет и типичные комбинации

### Ограничение

Все опции должны поместиться в **40 байт** (60 байт заголовка - 20 байт базовый).

### Типичные комбинации SYN

| Опции | Размер (байт) | Примечание |
| :--- | :--- | :--- |
| MSS | 4 | Минимальный набор |
| MSS + NOP + WS | 4 + 2 + 3 = 9 | Средний набор |
| MSS + WS + SACK + TS | 4 + 3 + 2 + 10 = 19 | Полный набор |
| MSS + WS + SACK + TS + TFO | 4 + 3 + 2 + 10 + 6 = 25 | С TFO Cookie |
| MSS + WS + SACK + TS + TFO + MPTCP | 4 + 3 + 2 + 10 + 6 + 10+ = 35+ | Максимальный |

**Проблемы переполнения:**
Если суммарный размер опций > 40 байт → опции **обрезаются**, и接收атель может неправильно интерпретировать заголовок.

**Пример проблемы:**
```text
Ситуация: клиент отправляет MSS(4) + WS(3) + SACK(2) + TS(10) + TFO(10) + MPTCP(16) = 45 байт
Результат: MPTCP обрезается до 35 байт → MP_CAPABLE не полностью → fallback на TCP
```

### Комбинации с высоким overhead

| Опции | Бюджет | Статус |
| :--- | :--- | :--- |
| MSS + TS | 16 | ОК |
| MSS + WS + TS | 19 | ОК |
| MSS + WS + SACK + TS | 21 | ОК |
| MSS + WS + SACK + TS + TFO | 27 | ОК |
| MSS + WS + SACK + TS + TFO + MPTCP | 37+ | Рискованно |
| MSS + WS + SACK + TS + TFO + MPTCP + TCP-AO | 40+ | Overflow |

---

## Практические сценарии

### Сценарий 1: Расчет эффективного MSS

При стандартном MTU 1500 байт на Ethernet:
```text
Базовый MSS = 1500 (MTU) - 20 (IP) - 20 (TCP) = 1460 байт.
```
Если в заголовке присутствуют Timestamps (10 байт + 2 байта NOP для выравнивания):
```text
Эффективный MSS = 1460 - 12 = 1448 байт.
```

**Для туннелей (WireGuard, IPsec):**
```text
MTU = 1420 (WireGuard по умолчанию)
MSS = 1420 - 20 - 20 = 1380
```

### Сценарий 2: Диагностика согласованных опций через ss

```bash
# Проверка всех согласованных опций
ss -ti dst 8.8.8.8
# → cubic rto:204 rtt:15.2/0.5 cwnd:10 wscale:7,7 ecn mss:1460

# Интерпретация:
# - wscale:7,7 → множитель 128×128 (send, recv)
# - ecn → ECN согласован
# - mss:1460 → согласованный MSS
# - cwnd:10 → текущее окно перегрузки (×MSS = 14600 байт)
# - rto:204 → таймаут ретрансмиссии (мс)
# - rtt:15.2/0.5 → RTT и отклонение (мс)
```

### Сценарий 3: Проверка TFO Cookie

```bash
# Просмотр TFO cookie в SYN-пакете
sudo tcpdump -i eth0 -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | \
  grep -o 'tfo cookie [^ ]*'

# Более детально
sudo tcpdump -i eth0 -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | \
  head -5
# → IP 1.1.1.1.54321 > 2.2.2.2.80: Flags [S], seq 123456, win 65535,
#   options [mss 1460,sackOK,TS val 123 ecr 0,nop,wscale 7,tfo cookie 0a1b2c3d]

# Проверка через ss
ss -ti dst 2.2.2.2.80 | grep -o 'tfo'
```

### Сценарий 4: Выявление MSS Blackhole

```bash
# Симптом: SSH подключается, но зависает при ls/df
# Причина: PMTU Blackhole — ICMP PTB заблокирован

# Диагностика
ping -M do -s 1472 8.8.8.8
# → Если нет ответа — проблема MTU

# Проверка MSS в SYN
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | \
  grep -E 'mss|options'
# → Если MSS=1460 при MTU 1420 — проблема

# Решение: MSS Clamping
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
  -j TCPMSS --set-mss 1380
```

### Сценарий 5: Анализ Timestamps через tshark

```bash
# Извлечение Timestamps из handshake
tshark -r capture.pcap -Y "tcp.flags.syn==1" \
  -T fields -e tcp.options.ts_val -e tcp.options.ts_ecr 2>/dev/null | head -5
# → 1234567 0
# → 9876543 1234567

# Анализ Timestamps в data transfer
tshark -r capture.pcap -Y "tcp.len > 0" \
  -T fields -e frame.number -e tcp.seq -e tcp.options.ts_val \
  -e tcp.options.ts_ecr 2>/dev/null | head -10

# Фильтрация по Timestamps
tshark -r capture.pcap -Y "tcp.options.ts_val > 0" 2>/dev/null | head -5
```

### Сценарий 6: Диагностика ECN

```bash
# Проверка ECN в SYN-пакете
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | \
  head -5
# → Flags [S], ...  ← если есть ECE/CWR — ECN запрошен

# Проверка ECN через ss
ss -ti dst 8.8.8.8 | grep ecn
# → ecn (ECN согласован)

# Проверка ECN через nstat
nstat -az | grep -i ecn
# → TcpExtTCPACECwndReduce  5  ← CE-события
# → TcpExtTCPACECwndReduce  3  ← CWR-события

# Включение ECN
sudo sysctl -w net.ipv4.tcp_ecn=1
```

### Сценарий 7: Анализ SACK через tcpdump

```bash
# Поиск пакетов с SACK Data (Kind=5)
sudo tcpdump -i eth0 -nn 'tcp[12] & 0xf0 > 80' 2>/dev/null | head -5

# Анализ SACK блоков через tshark
tshark -r capture.pcap -Y "tcp.analysis.sack" \
  -T fields -e tcp.sack.left_edge -e tcp.sack.right_edge \
  2>/dev/null | head -10

# Проверка D-SACK
nstat -az | grep -i dsack
# → TcpExtTCPSACKDSackRecv  3  ← D-SACK получены
```

### Сценарий 8: Проверка 40-байт бюджета

```bash
# Анализ размера опций в SYN
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | \
  grep -o 'options \[.*\]' | awk '{print length($0)-10}'
# → 22 (байт опций)

# Если опции > 40 байт — проблема
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | \
  grep -o 'options \[.*\]' | while read opts; do
    len=$(echo "$opts" | sed 's/options \[//;s/\]//' | wc -c)
    if [ "$len" -gt 40 ]; then
      echo "WARNING: Options too large: $len bytes"
    fi
  done
```

### Сценарий 9: eBPF для мониторинга опций

```bash
# Трассировка событий TCP (опции в handshake)
sudo tcpstates -tw

# Трассировка MSS/WS согласования
sudo tcpconnect -t | head -20
# → bpf_sock_ops.cb_flags报告опции

# Трассировка SACK событий
sudo tcpretrans

# Мониторинг PAWS
nstat -az | grep PAWSEstab
# → TcpExtPAWSEstab  142  ← PAWS сработал
```

---

## Диагностические команды (агрегированная секция)

### Просмотр согласованных опций

```bash
# Через ss (ядро → опции)
ss -tinH dst 10.0.0.1 | grep -E 'mss|wscale|ecn|ts'

# Через tshark (pcap)
tshark -r capture.pcap -Y "tcp.flags.syn==1" \
  -T fields -e tcp.options.mss -e tcp.options.wscale \
  -e tcp.options.sack -e tcp.options.ts_val 2>/dev/null

# Через tcpdump (live)
sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' 2>/dev/null | \
  grep 'options'
```

### Мониторинг опций в реальном времени

```bash
# Временной срез (каждые 1 сек)
while true; do
  ss -tinH state established | grep -E 'mss|wscale' | head -1
  sleep 1
done

# Логирование в файл
ss -tinH state established >> /tmp/tcp_options.log &
```

### Глобальная статистика

```bash
# Ошибки опций
nstat -az | grep -E 'TcpExt(TCPAbortOn|ListenOverflows|ListenDrops)'

# SACK статистика
nstat -az | grep -i sack

# Timestamps статистика
nstat -az | grep -i timestamp

# ECN статистика
nstat -az | grep -i ecn
```

---

## Linux sysctl параметры

### MSS и MTU

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_mtu_probing` | 0 | PMTU discovery: 0=выкл, 1=вкл |
| `net.ipv4.route.min_advmss` | 256 | Минимальный MSS для PMTU |
| `net.ipv4.ip_no_pmtu_disc` | 0 | 0=PMTUD вкл, 1=выкл |

### Window Scale и буферы

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_window_scaling` | 1 | Window Scale: 1=вкл, 0=выкл |
| `net.core.rmem_max` | 212992 | Макс. размер receive buffer |
| `net.core.wmem_max` | 212992 | Макс. размер send buffer |
| `net.ipv4.tcp_rmem` | 4096 131072 6291456 | min default max receive buffer |
| `net.ipv4.tcp_wmem` | 4096 65536 4194304 | min default max send buffer |

### SACK

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_sack` | 1 | SACK: 1=вкл, 0=выкл |
| `net.ipv4.tcp_dsack` | 1 | D-SACK: 1=вкл, 0=выкл |
| `net.ipv4.tcp_fack` | 1 | Forward ACK: 1=вкл, 0=выкл |

### Timestamps и PAWS

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_timestamps` | 1 | Timestamps: 1=вкл, 0=выкл |
| `net.ipv4.tcp_paws` | 1 | PAWS: 1=вкл, 0=выкл |

### TFO

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_fastopen` | 1 | TFO: 0=выкл, 1=клиент, 2=сервер, 3=оба |
| `net.ipv4.tcp_fastopen_key` | Random | Ключ для TFO Cookie |

### ECN и L4S

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_ecn` | 0 | ECN: 0=выкл, 1=вкл, 2=только если маршрутизатор запрашивает |
| `net.ipv4.tcp_congestion_control` | cubic | Алогритм перегрузки (cubic, bbr, etc.) |

### Рекомендуемая конфигурация для высокопроизводительных серверов

```bash
# /etc/sysctl.d/99-tcp-high-performance.conf

# MSS/MTU
net.ipv4.tcp_mtu_probing=1

# Window Scale и буферы
net.ipv4.tcp_window_scaling=1
net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.ipv4.tcp_rmem=4096 87380 16777216
net.ipv4.tcp_wmem=4096 65536 16777216

# SACK
net.ipv4.tcp_sack=1
net.ipv4.tcp_dsack=1

# Timestamps
net.ipv4.tcp_timestamps=1

# TFO
net.ipv4.tcp_fastopen=3

# ECN
net.ipv4.tcp_ecn=1

# Алгоритм перегрузки
net.ipv4.tcp_congestion_control=bbr
```

---

## Docker и Kubernetes

### Docker

```bash
# Просмотр параметров в контейнере
docker exec <container> sysctl net.ipv4.tcp_window_scaling
docker exec <container> ss -ti dst 8.8.8.8

# Включение TFO в контейнере
docker exec <container> sysctl -w net.ipv4.tcp_fastopen=3

# Проверка MSS (для контейнерных сетей)
docker exec <container> ss -tin | grep mss
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: tcp-options-monitor
  namespace: kube-system
spec:
  selector:
    matchLabels:
      name: tcp-options-monitor
  template:
    metadata:
      labels:
        name: tcp-options-monitor
    spec:
      hostPID: true
      containers:
      - name: monitor
        image: busybox
        command:
        - sh
        - -c
        - |
          echo "=== TCP Options Summary ==="
          ss -tinH state established | grep -E 'mss|wscale|ecn|ts' | head -20
          echo ""
          echo "=== MSS Distribution ==="
          ss -tinH state established | grep -oP 'mss:\K[0-9]+' | sort | uniq -c | sort -rn
          echo ""
          echo "=== Window Scale Distribution ==="
          ss -tinH state established | grep -oP 'wscale:\K[0-9,]+' | sort | uniq -c | sort -rn
          echo ""
          echo "=== ECN Usage ==="
          ss -tinH state established | grep -c ecn
          echo " connections with ECN"
          sleep infinity
        securityContext:
          privileged: true
```

---

## Дополнительная информация

### См. также

- **[Формат заголовка TCP](./index.md)** — описание базовых полей и расположения флагов.
- **[Практика анализа](./practical.md)** — tcpdump, ss, eBPF, Wireshark.
- **[Управление потоком](../Flow_Control/index.md)** — глубокий разбор работы Window Scale.
- **[Надежность TCP](../reliability_mechanisms/concepts.md)** — Seq/Ack, Checksum, SACK.
- **[Оптимизация TCP в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — настройка системных параметров для опций.
- **[TCP Fast Open в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_fast_open.md)** — полная настройка TFO.
- **[MSS Clamping](../../../OSI_TCP_IP_Model/Network_layer/ip_fragmentation.md#mss-clamping)** — решение MSS Blackhole.
- **[MTU и VPN](../../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — overhead туннелей.

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (2022) — современный стандарт TCP.
- **RFC 7323:** TCP Extensions for High Performance — Window Scale, Timestamps, PAWS.
- **RFC 3168:** The Addition of Explicit Congestion Notification (ECN) to IP.
- **RFC 9330:** L4S (Low Latency, Low Loss, Scalable throughput) Overview (2023).
- **RFC 2018/6675:** TCP Selective Acknowledgment Options.
- **RFC 2883:** D-SACK Extension (Duplicate SACK).
- **RFC 8684:** Multipath TCP (MPTCP) — агрегация интерфейсов.
- **RFC 7413:** TCP Fast Open (TFO).
- **RFC 1071:** Computing the Internet Checksum.
