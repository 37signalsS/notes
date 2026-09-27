# Структура IP-пакета (IPv4)

## Определения

**IP-пакет (IP Datagram)** — базовая единица данных на сетевом уровне модели **OSI**, обеспечивающая независимую доставку информации между узлами сети. Пакет состоит из управляющей части — **заголовка (Header)** и полезной нагрузки — **данных (Payload)**.

- **Размер заголовка:** От 20 байт (базовый) до 60 байт (с учетом опций). IHL (Internet Header Length) указывает размер заголовка в 32-битных словах: `IHL × 4 = размер в байтах`.
- **Максимальный размер пакета:** Ограничен полем `Total Length` (16 бит) — до 65 535 байт. В реальных сетях Ethernet размер пакета обычно составляет **1500 байт** (MTU).
- **PDU (Protocol Data Unit):** На L3 PDU называется **Packet (Пакет)**. Внутри пакета: L4-сегмент (TCP/UDP) или L4-дейтаграмм.

## Связь с соседними уровнями

```text
┌────────────────────────────────────────────────────────────────────────┐
│ L4 — TCP / UDP / ICMP                                                 │
│   TCP: Segment = 20-60B Header + Data (MSS ≤ MTU - IP_Header)        │
│   UDP: Datagram = 8B Header + Data (размер ≤ MTU - IP_Header)        │
│   ICMP: Message = 8B Header + Data (размер ≤ MTU - IP_Header)        │
│   Передаёт Segment/Datagram в L3 через Interface (NIC)               │
└──────────────────────┬─────────────────────────────────────────────────┘
                       ↓ передаёт Segment (L4 PDU) в L3
┌────────────────────────────────────────────────────────────────────────┐
│ L3 — IP (IPv4 / IPv4 Packet)                                         │
│   ┌──────────────────────────────────────────────────────────────┐    │
│   │ PDU: Packet (Пакет)                                         │    │
│   │ Header: 20B (min) — 60B (max) для IPv4                     │    │
│   │ Total Length: Header + Payload (≤ 65535 байт)               │    │
│   │ Ключевые поля: Version, IHL, DSCP/ECN, Total Length,       │    │
│   │   Identification, Flags, Offset, TTL, Protocol, Checksum,  │    │
│   │   Source IP, Destination IP, Options                        │    │
│   │ DF=1 → PMTUD (отправить ICMP PTB при MTU mismatch)         │    │
│   │ DF=0 → IP-фрагментация (разбить на фрагменты ≤ MTU)        │    │
│   │ TTL → защита от петель маршрутизации                        │    │
│   │ Protocol → указывает L4 протокол (TCP=6, UDP=17, ICMP=1)   │    │
│   └──────────────────────────────────────────────────────────────┘    │
│   Инкапсуляция: L3-пакет → L2-кадр (Ethernet frame)                 │
│   MTU определяет Max L3 PDU Size                                     │
└──────────────────────┬─────────────────────────────────────────────────┘
                       ↓ передаёт Packet (L3 PDU) в L2
┌────────────────────────────────────────────────────────────────────────┐
│ L2 — Ethernet / Wi-Fi / PPP / PPPoE                                   │
│   Ethernet: DST MAC (6B) + SRC MAC (6B) + EtherType (2B) + Payload │
│   EtherType 0x0800 = IPv4                                            │
│   EtherType 0x86DD = IPv6                                            │
│   Макс. Payload L2 (Ethernet MTU) = 1500 байт                       │
│   → Max L3 PDU = 1500 байт (IPv4 без опций)                         │
└────────────────────────────────────────────────────────────────────────┘
```

| Уровень | PDU | Размер | Ключевые данные |
| :--- | :--- | :--- | :--- |
| **L4 — TCP** | Segment | 20-60B Header + Data | SRC/DST Port, Seq, Ack, Flags, Window, MSS |
| **L4 — UDP** | Datagram | 8B Header + Data | SRC/DST Port, Length, Checksum |
| **L4 — ICMP** | Message | 8B Header + Data | Type, Code, Checksum, ID, Sequence |
| **L3 — IPv4** | **Packet** | **20-60B Header + Data** | **Version, IHL, DSCP, ECN, Total Length, ID, Flags, Offset, TTL, Protocol, Checksum, Src IP, Dst IP** |
| **L3 — IPv6** | Packet | 40B Header + Extension Headers | Version, Traffic Class, Flow Label, Payload Length, Next Header, Hop Limit, Src/Dst |
| **L2 — Ethernet** | Frame | 14B Header + Payload + 4B FCS | DST MAC, SRC MAC, EtherType |

## Инкапсуляция: полная картина

```text
                    Инкапсуляция L4 → L3 → L2
┌────────────────────────────────────────────────────────────────────────┐
│                          L2 Frame (Ethernet)                          │
│ ┌──────────┬──────────┬────────────┬──────────────────────┬─────────┐ │
│ │ DST MAC  │ SRC MAC  │ EtherType  │    L3 Payload        │   FCS   │ │
│ │  (6B)    │  (6B)    │  (2B)      │  (IP Packet)         │  (4B)   │ │
│ │          │          │  0x0800    │                      │         │ │
│ └──────────┴──────────┴────────────┴──────────────────────┴─────────┘ │
│                                                                1500B │
│ ┌────────────────────────────────────────────────────────────────────┐ │
│ │                      L3 Packet (IPv4)                             │ │
│ │ ┌──────────────────────────────┬────────────────────────────────┐ │ │
│ │ │      IP Header (20-60B)      │         IP Payload            │ │ │
│ │ │  Version(4) IHL(4) DSCP(6)  │   (L4 Segment / Datagram)     │ │ │
│ │ │  ECN(2) Total Length(16)     │                                │ │ │
│ │ │  ID(16) Flags(3) Offset(13) │                                │ │ │
│ │ │  TTL(8) Protocol(8)         │                                │ │ │
│ │ │  Checksum(16)               │                                │ │ │
│ │ │  Source IP (32)             │                                │ │ │
│ │ │  Destination IP (32)        │                                │ │ │
│ │ │  Options (0-40B, optional)  │                                │ │ │
│ │ └──────────────────────────────┴────────────────────────────────┘ │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────────────────┐ │
│ │                   L4 Segment (TCP)                                │ │
│ │ ┌──────────────────────────────┬────────────────────────────────┐ │ │
│ │ │    TCP Header (20-60B)       │       TCP Payload              │ │ │
│ │ │  Src Port(16) Dst Port(16)  │   (Application Data)           │ │ │
│ │ │  Seq(32) Ack(32)            │                                │ │ │
│ │ │  Flags(16) Window(16)       │                                │ │ │
│ │ │  Checksum(16) Urgent(16)    │                                │ │ │
│ │ │  Options (0-40B)            │                                │ │ │
│ │ └──────────────────────────────┴────────────────────────────────┘ │ │
│ └────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

## Структура заголовка IPv4

### Визуальная схема (по 32-битным словам)

Заголовок организован в виде 32-битных слов. Сетевой порядок байтов — **Big-Endian**.

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|Version|  IHL  |    DSCP   |ECN|         Total Length         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|         Identification        |Flags|     Fragment Offset    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Time to Live |    Protocol   |        Header Checksum       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Source Address                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Destination Address                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Options                    |    Padding    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Таблица полей заголовка

| Смещение (бит) | 0–3 | 4–7 | 8–15 | 16–31 |
| :--- | :--- | :--- | :--- | :--- |
| **0** | Version (4) | IHL (4) | DSCP (6) / ECN (2) | Total Length (16) |
| **32** | Identification (16) | Flags (3) | Fragment Offset (13) | |
| **64** | Time to Live (8) | Protocol (8) | Header Checksum (16) | |
| **96** | Source IP Address (32) | | | |
| **128** | Destination IP Address (32) | | | |
| **160** | Options (переменная длина, если IHL > 5) | | | |

## Детальное описание полей

### 1. Version (Версия) — 4 бита

Всегда `4` для IPv4. Позволяет приемнику понять, по каким правилам разбирать заголовок. Значения:

| Значение | Протокол |
| :--- | :--- |
| `4` | IPv4 |
| `6` | IPv6 |
| `5` | MIT XEROX PUP (исторический) |
| `7` | CATNIP (исторический) |

### 2. IHL (Internet Header Length) — 4 бита

Длина заголовка в **32-битных словах**. Минимальное значение `5` (20 байт). Если используются опции, IHL увеличивается.

| IHL | Размер заголовка | Описание |
| :--- | :--- | :--- |
| `5` | 20 байт | Базовый заголовок (без опций) |
| `6` | 24 байт | +32 бита опций |
| `7` | 28 байт | +64 бита опций |
| ... | ... | ... |
| `15` | 60 байт | Максимум (40 байт опций) |

**Формула:** `Размер заголовка (байт) = IHL × 4`. Необходимо чтобы `IHL × 4` делилось на 4 (всегда кратно 32 битам).

### 3. DSCP и ECN (Качество обслуживания) — 8 бит

#### DSCP (Differentiated Services Code Point) — 6 бит

Маркировка приоритета трафика для QoS (RFC 2474). Маршрутизаторы и коммутаторы используют DSCP для определения очереди обработки пакета.

| Категория | DSCP (Dec) | DSCP (Bin) | Имя | Описание |
| :--- | :--- | :--- | :--- | :--- |
| **Best Effort** | 0 | 000000 | BE | Обычный трафик (по умолчанию) |
| **Class Selector** | 8 | 001000 | CS1 | Низкий приоритет (Bulk) |
| | 16 | 010000 | CS2 | Средний приоритет |
| | 24 | 011000 | CS3 | Высокий приоритет |
| | 32 | 100000 | CS4 | Критический |
| | 40 | 101000 | CS5 | Мультикаст |
| | 48 | 110000 | CS6 | Сетевой контроль |
| | 56 | 111000 | CS7 | Сетевой контроль |
| **Assured Forwarding** | 10 | 001010 | AF11 | Низкий приоритет (getClass) |
| | 12 | 001100 | AF12 | Низкий (средняя потеря) |
| | 14 | 001110 | AF13 | Низкий (высокая потеря) |
| | 18 | 010010 | AF21 | Средний приоритет |
| | 20 | 010100 | AF22 | Средний (средняя потеря) |
| | 22 | 010110 | AF23 | Средний (высокая потеря) |
| | 26 | 011010 | AF31 | Высокий приоритет |
| | 28 | 011100 | AF32 | Высокий (средняя потеря) |
| | 30 | 011110 | AF33 | Высокий (высокая потеря) |
| | 34 | 100010 | AF41 | Очень высокий приоритет |
| | 36 | 100100 | AF42 | Очень высокий (средняя потеря) |
| | 38 | 100110 | AF43 | Очень высокий (высокая потеря) |
| **Expedited Forwarding** | 46 | 101110 | EF | Низкая задержка (VoIP, Video) |
| **Voice Admit** | 44 | 101100 | VA | Голосовой трафик |

#### ECN (Explicit Congestion Notification) — 2 бита

Позволяют маршрутизаторам уведомлять хосты о перегрузке **без отбрасывания пакетов** (RFC 3168). Требует поддержки на L4 (TCP).

| ECN (Bits) | Значение | Описание |
| :--- | :--- | :--- |
| `00` | Non-ECT | ECN не поддерживается (обычный трафик) |
| `01` | ECT(1) | ECN поддерживается (пакет может быть помечен) |
| `10` | ECT(0) | ECN поддерживается (пакет может быть помечен) |
| `11` | CE (Congestion Experienced) | Маршрутизатор сообщает о перегрузке |

**Механизм:** Маршрутизатор при перегрузке ставит `ECN=11` (CE) вместо отбрасывания. Получатель (TCP) отправляет `ECE=1` (ECN Echo) отправителю. Отправитель снижает `cwnd` (Congestion Window) и отправляет `CWR=1` (Congestion Window Reduced).

### 4. Total Length (Общая длина) — 16 бит

Длина всего IP-пакета (заголовок + данные) в байтах.

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| Минимальный размер | 20 байт | Заголовок без данных |
| Максимальный размер | 65 535 байт | 2^16 - 1 |
| Типичный размер (Ethernet) | ≤ 1500 байт | MTU Ethernet |
| Jumbo Frame | ≤ 9000 байт | Если поддерживается |
| Связь с MTU | `Total Length ≤ MTU` | Если больше → фрагментация или ICMP PTB |

**Формула:** `Data_size = Total Length - (IHL × 4)`.

**Total Length vs MTU:**
- **Total Length** — размер конкретного пакета (поле в заголовке)
- **MTU** — максимальный разрешённый размер пакета для данного сегмента сети
- Если `Total Length > MTU` и `DF=1` → ICMP Type 3 Code 4 (PMTUD)
- Если `Total Length > MTU` и `DF=0` → фрагментация

### 5. Identification (Идентификатор) — 16 бит

Уникальное число, присваиваемое исходному пакету. Позволяет отличить фрагменты пакета А от фрагментов пакета Б.

- **Инкрементируется** на 1 для каждого отправленного пакета (на Linux: `net.ipv4.ip_idents_resume`)
- **Общий для всех фрагментов** одного пакета
- **Не имеет значения для нефрагментированных пакетов** (но может использоваться для IP-маршрутизации и ACL)

### 6. Flags (Флаги) — 3 бита

| Бит | Имя | Значение |
| :--- | :--- | :--- |
| Bit 0 (Reserved) | `R` | Зарезервирован (всегда 0) |
| Bit 1 | `DF` | **Don't Fragment** — запрет фрагментации. Если `DF=1` и пакет > MTU → ICMP PTB |
| Bit 2 | `MF` | **More Fragments** — признак продолжения. Если `MF=1` → за этим фрагментом следуют другие |

**DF=1 используется в PMTUD** — определение минимального MTU на всём пути. Подробнее: **[Фрагментация IP-пакетов](./ip_fragmentation.md)**.

### 7. Fragment Offset (Смещение фрагмента) — 13 бит

Смещение данных фрагмента относительно начала исходного пакета. Измеряется в **8-байтовых блоках (октетах)**.

| Параметр | Значение |
| :--- | :--- |
| Размер поля | 13 бит |
| Единица измерения | 8 байт (октет) |
| Максимальное смещение | 8191 × 8 = 65 528 байт |
| Формула | `Offset (октеты) = Byte_Range_Start / 8` |

### 8. Time to Live (TTL) — 8 бит

Счётчик «жизни» пакета. Каждый маршрутизатор уменьшает TTL на 1. При достижении 0 пакет уничтожается, а отправителю летит **ICMP Time Exceeded**. Это защищает от петель маршрутизации.

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| Размер | 8 бит | 0–255 |
| Максимальное значение | 255 | При начальном значении 255 |
| Типичное значение (Linux) | 64 | `net.ipv4.ip_default_ttl=64` |
| Типичное значение (Windows) | 128 | `DefaultTTL=128` |
| Типичное значение (macOS) | 64 | `net.inet.ip.ttl=64` |
| ICMP-сообщение | Type 11 Code 0 | Time Exceeded in Transit |
| Аналог в IPv6 | **Hop Limit** | То же назначение, другое имя |

**TTL вtraceroute:**
- `traceroute` отправляет пакеты с TTL=1, 2, 3...
- Каждый маршрутизатор отвечает ICMP Time Exceeded
- Последний узел отвечает ICMP Port Unreachable (UDP traceroute) или ICMP Echo Reply (ICMP traceroute)

### 9. Protocol (Протокол) — 8 бит

Указывает тип данных в Payload (протокол следующего уровня). Аналогичен полю `Next Header` в IPv6.

| Номер | Протокол | Описание | L4 PDU |
| :--- | :--- | :--- | :--- |
| `1` | **ICMP** | Служебные сообщения | Message |
| `2` | **IGMP** | Управление мультикастом | Message |
| `6` | **TCP** | Надёжная доставка | Segment |
| `17` | **UDP** | Ненадёжная доставка | Datagram |
| `41` | **IPv6-in-IPv4** | Туннелирование IPv6 в IPv4 | Packet |
| `47` | **GRE** | Туннелирование (General Routing Encapsulation) | Packet |
| `50` | **ESP** | IPsec Encapsulating Security Payload | Packet |
| `51` | **AH** | IPsec Authentication Header | Packet |
| `89` | **OSPF** | Open Shortest Path First (динамическая маршрутизация) | Packet |
| `103` | **PIM** | Protocol Independent Multicast | Packet |
| `112` | **VRRP** | Virtual Router Redundancy Protocol | Packet |
| `132` | **SCTP** | Stream Control Transmission Protocol | Chunk |

**Полный список:** [IANA Protocol Numbers](https://www.iana.org/assignments/protocol-numbers/protocol-numbers.xhtml)

### 10. Header Checksum (Контрольная сумма) — 16 бит

Проверяет целостность **только заголовка** (не данных). Пересчитывается на каждом маршрутизаторе из-за изменения TTL.

**Алгоритм:** 16-битная добавочная сумма (one's complement sum) всех 16-битных слов заголовка. Если результат не `0xFFFF` → заголовок повреждён.

**Примечания:**
- В IPv6 контрольная сумма заголовка **отсутствует** (для ускорения обработки)
- Контрольная сумма TCP/UDP включает **псевдозаголовок** (Source IP, Dst IP, Protocol, Length) — связывает L3 и L4
- В Linux: `net.ipv4.ip_check_timestamp` — проверка timestamp опций
- Для有一些 NIC (multi-queue): `ethtool -K eth0 tx-checksum-ipv4 off` — аппаратный offload (может скрыть ошибки)

### 11. Options (Опции) — переменная длина (0–40 байт)

Редко используются в современном интернете из-за рисков безопасности и проблем с производительностью:

| Опция | Код | Описание | Опасность |
| :--- | :--- | :--- | :--- |
| **End of Options** | 0 | Конец опций (pad) | Нет |
| **No Operation** | 1 | Выравнивание (pad) | Нет |
| **Record Route** | 7 | Записывает пройденные IP-адреса (до 9 хопов) | Information leak |
| **Strict Source Routing** | 137 | Пакет обязан пройти через указанный путь | Spoofing, Bypass ACL |
| **Loose Source Routing** | 131 | Пакет обязан пройти через указанные узлы (порядок не важен) | Spoofing, Bypass ACL |
| **Timestamp** | 68 | Время прохождения через узлы | Timing attacks |
| **Router Alert** | 148 | Маршрутизатор должен обработать пакет (RSVP, IGMP) | DoS |
| **Security** | 130 | military classification (RFC 1108, deprecated) | Information leak |
| **Stream ID** | 136 | For SATNET (historical) | Deprecated |

**Sysctl защита от опций:**
```bash
# Отключить обработку опций (самый безопасный вариант)
sysctl -w net.ipv4.conf.all.accept_options=0    # Может отбрасывать пакеты с опциями
sysctl -w net.ipv4.conf.default.accept_options=0

# Или более точно: игнорировать Source Routing
sysctl -w net.ipv4.conf.all.accept_source_route=0
sysctl -w net.ipv4.conf.default.accept_source_route=0
```

## Практические сценарии

### 1. Траблшутинг через TTL (Traceroute)

Утилита `traceroute` намеренно шлет пакеты с последовательно возрастающим TTL (1, 2, 3...), заставляя каждый маршрутизатор на пути выдавать ICMP-ответ об истечении времени. Так строится карта хопов.

```bash
# Linux: UDP traceroute (по умолчанию)
traceroute 8.8.8.8

# Linux: ICMP traceroute (как в Windows)
traceroute -I 8.8.8.8

# Linux: TCP traceroute (обходит файрволы)
traceroute -T -p 80 8.8.8.8

# Просмотр TTL в реальном времени
tcpdump -v 'ip[8] == 1' -c 5   # Пакеты с TTL=1 (traceroute first hop)
```

### 2. Анализ полей IP-заголовка через tcpdump

Для захвата и анализа полей IP-заголовка используется **[tcpdump — сетевой анализатор пакетов](../../../../Linux/Diagnostics/Networking/tcpdump.md)**. Примеры BPF-фильтров для конкретных полей IPv4:

```bash
# Просмотр пакетов с установленным флагом DF (Don't Fragment)
# Бит 6 в байте 6 (flags + fragment offset = byte 6-7)
tcpdump -v 'ip[6] & 64 != 0'

# Просмотр пакетов с конкретным TTL (например, меньше 10)
tcpdump -v 'ip[8] < 10'

# Фильтрация по протоколу OSPF
tcpdump 'ip proto 89'

# Просмотр пакетов с опциями (IHL > 5 = 20B)
tcpdump -v 'ip[0] & 0x0f > 5'

# Просмотр DSCP значения (первые 6 бит байта 1)
tcpdump -v 'ip[1] & 0xfc >> 2'

# Просмотр ECN значения (последние 2 бита байта 1)
tcpdump -v 'ip[1] & 0x03'

# Просмотр Total Length
tcpdump -v 'ip[2:2] > 1500'   # Пакеты больше MTU

# Просмотр Protocol
tcpdump -v 'ip[9] == 6'       # TCP
tcpdump -v 'ip[9] == 17'      # UDP
tcpdump -v 'ip[9] == 1'       # ICMP
```

### 3. MTU Black Hole

Если приложение шлет большие пакеты с флагом `DF=1`, а где-то на пути MTU меньше размера пакета, маршрутизатор его отбросит. Если при этом блокируется ICMP (Destination Unreachable), возникнет «черная дыра» — соединение виснет.

```bash
# Диагностика MTU Black Hole
ping -M do -s 1472 10.0.0.1            # Проверка MTU
tcpdump 'icmp[0] == 3 and icmp[1] == 4' -nn  # Проверка ICMP PTB
ss -ti | grep mss                      # Проверка MSS в соединениях

# MSS Clamping (решение на шлюзе)
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu
```

Подробнее: **[MTU и PMTUD](../mtu_and_vpn.md)**, **[Фрагментация IP](./ip_fragmentation.md)**.

### 4. Просмотр заголовка в hex-редакторе

```bash
# Захват одного пакета и просмотр в hex
tcpdump -i eth0 -c 1 -X host 10.0.0.1
# Пример вывода:
# 0x0000:  4500 003c 1c46 4000 4006 b1e6 ac10 0a63  E..<.F@.@......c
# 0x0010:  ac10 0a0c 0014 0050 0000 0000 0000 0000  .......P........
# 0x0020:  5002 7210 0000 0000 0000 0000 0000 0000  P.r.............

# Разбор:
# 45        = Version(4) + IHL(5)  → заголовок 20 байт
# 00        = DSCP(0) + ECN(0)     → Best Effort
# 003c      = Total Length = 60 байт
# 1c46      = Identification = 7238
# 4000      = Flags(DF=1) + Offset(0)
# 40        = TTL = 64
# 06        = Protocol = TCP
# b1e6      = Header Checksum
# ac10 0a63 = Source IP = 172.16.10.99
# ac10 0a0c = Dest IP = 172.16.10.12
```

### 5. Полный анализ IP-пакета через Wireshark/tshark

```bash
# Просмотр всех полей IP-заголовка
tshark -r capture.pcap -T fields -e ip.src -e ip.dst -e ip.proto \
    -e ip.ttl -e ip.id -e ip.flags -e ip.dsfield.dscp \
    -e ip.dsfield.ecn -e ip.len -e ip.hdr_len

# Экспорт в JSON (детальный разбор)
tshark -r capture.pcap -T json -Y "ip" | python3 -m json.tool

# Фильтрация по DSCP
tshark -r capture.pcap -Y "ip.dsfield.dscp == 46"   # EF (VoIP)

# Фильтрация по ECN
tshark -r capture.pcap -Y "ip.dsfield.ecn == 3"     # CE (Congestion)
```

### 6. Sysctl: настройка поведения IP

```bash
# Текущий TTL
sysctl net.ipv4.ip_default_ttl                     # Default: 64

# Включить/отключить IP forwarding (маршрутизатор)
sysctl -w net.ipv4.ip_forward=1                     # Включить

# Отключить ICMP redirect (защита от spoofing)
sysctl -w net.ipv4.conf.all.accept_redirects=0
sysctl -w net.ipv4.conf.default.accept_redirects=0

# Отключить Source Routing
sysctl -w net.ipv4.conf.all.accept_source_route=0
sysctl -w net.ipv4.conf.default.accept_source_route=0

# Включить instrumentation (логирование аномалий)
sysctl -w net.ipv4.conf.all.log_martians=1          # Логировать impossible packages
sysctl -w net.ipv4.conf.all.rp_filter=1             # Reverse Path Filtering

# Контроль фрагментации
sysctl net.ipv4.ipfrag_time                         # Timeout сборки (default=30)
sysctl net.ipv4.ipfrag_high_thresh                  # Макс. память (default=4MB)

# Проверка всех IP sysctl
sysctl -a | grep -E "^net\.ipv4\."
```

## IPv4 vs IPv6: сравнение заголовков

| Поле | IPv4 | IPv6 | Разница |
| :--- | :--- | :--- | :--- |
| **Version** | 4 бита (`4`) | 4 бита (`6`) | Идентично |
| **Заголовок** | 20-60 байт (переменный) | **40 байт (фиксированный)** | IPv6 фиксированный → быстрее |
| **QoS** | DSCP (6) + ECN (2) = 8 бит | Traffic Class (8 бит) | Аналогично |
| **Flow Label** | Нет | **20 бит** (маркер потока) | Только IPv6 |
| **Payload Length** | Total Length (16) | Payload Length (16) | Total = Header + Payload |
| **Identification** | 16 бит (обязательное) | В Fragment Header (32 бита) | IPv6: только при фрагментации |
| **Flags** | 3 бита (R, DF, MF) | В Fragment Header (MF + Reserved) | IPv6: только при фрагментации |
| **Fragment Offset** | 13 бит (в заголовке) | В Fragment Header (13 бит) | IPv6: только при фрагментации |
| **TTL/Hop Limit** | TTL (8 бит) | Hop Limit (8 бит) | Аналогично, разные имена |
| **Protocol** | Protocol (8 бит) | **Next Header (8 бит)** | Аналогичная роль |
| **Checksum** | Header Checksum (16 бит) | **Нет** | IPv6: для скорости |
| **Options** | В заголовке (IHL > 5) | **Extension Headers** | IPv6: вынесены |
| **Длина заголовка** | Variable (IHL) | Fixed (40B) | IPv6 проще |
| **Адреса** | 32 бита (SRC + DST) | **128 бит (SRC + DST)** | IPv6: больше адресов |
| **Minimum MTU** | 576 байт | **1280 байт** (обязательно) | IPv6: больше минимум |

**Преимущества IPv6:**
1. Фиксированный заголовок → аппаратные маршрутизаторы обрабатывают быстрее
2. Отсутствие контрольной суммы → меньше вычислений
3. Flow Label → ускоренная обработка пакетов одного потока
4. 32-битный Identification → меньше коллизий при фрагментации
5. Extension Headers → гибкость без увеличения базового заголовка

## Безопасность и векторы атак

| Атака | Поле | Описание | Митигация |
| :--- | :--- | :--- | :--- |
| **IP Spoofing** | Source IP | Поддельный Source IP для обхода ACL | RPF (Reverse Path Filtering); BCP38 |
| **TTL Expiration** | TTL | Attacker с TTL=1 → ICMP Time Exceeded → information disclosure | `sysctl net.ipv4.icmp_time_exceeded_rate_limit` |
| **Fragmentation Attack** | Flags/Offset | Tiny fragment → обход L4 ACL; Overlap → перезапись данных | Фильтрация фрагментов; De-frag before inspection |
| **Source Routing** | Options | Attacker задаёт путь для обхода файрвола | `sysctl net.ipv4.conf.all.accept_source_route=0` |
| **Record Route** | Options | Утечка информации о маршруте | Отключить опции; ACL |
| **Router Alert** | Options | DoS через обязательную обработку пакета | Фильтрация на входе |
| **Land Attack** | Src=Dst | Пакет с SRC=_DST_=localhost → петля | Фильтрация на входе |
| **Ping of Death** | Total Length | Pkg > 65535 → buffer overflow | Обновление ОС (fixed in Linux 2.0+) |

**Sysctl-защита:**
```bash
# Полный набор для сервера
sysctl -w net.ipv4.conf.all.accept_redirects=0
sysctl -w net.ipv4.conf.all.accept_source_route=0
sysctl -w net.ipv4.conf.all.rp_filter=1
sysctl -w net.ipv4.conf.all.log_martians=1
sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=1
sysctl -w net.ipv4.icmp_ignore_bogus_error_responses=1
```

## Дополнительная информация

### См. также
- [Обзор сетевого уровня (L3)](../Concepts/network_layer_overview.md) — фундаментальные принципы.
- [Фрагментация IP-пакетов](./ip_fragmentation.md) — глубокий разбор Flags, Offset, PMTUD, MSS Clamping.
- [MTU, PMTUD и диагностика в VPN/облаках](../mtu_and_vpn.md) — overhead туннелей, sysctl, cloud MTU.
- [Протокол ICMP](../../../Protocols/ICMP/icmp_overview.md) — ICMP Type 3 Code 4 (PTB), Type 11 (Time Exceeded).
- [ICMP Time Exceeded](../../../Protocols/ICMP/icmp_time_exceeded.md) — TTL=0 → ICMP Type 11.
- [ICMP Destination Unreachable](../../../Protocols/ICMP/icmp_destination_unreachable.md) — ICMP Type 3 Code 4 (PMTUD).
- [ICMP Redirect](../../../Protocols/ICMP/icmp_redirect.md) — ICMP Type 5 (gateway redirect).
- [IP-адресация](../../../Protocols/IP_addressing/ip_overview.md) — структура IPv4/IPv6 адресов.
- [Протокол TCP](../../../Protocols/TCP/overview.md) — MSS, Seq/Ack, Checksum, Options.
- [Протокол UDP](../../../Protocols/udp.md) — дейтаграммы, фрагментация.
- [Маршрутизация и оборудование L3](../routing_protocols_equipment.md) — RIB/FIB, TTL behavior.
- [Dual Stack IPv4/IPv6](../Concepts/ipv4_ipv6_dual_stack.md) — сравнение заголовков.
- [RFC 791: Internet Protocol](https://datatracker.ietf.org/doc/html/rfc791) — первоисточник спецификации.
