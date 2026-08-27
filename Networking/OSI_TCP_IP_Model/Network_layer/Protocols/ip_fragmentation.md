# Фрагментация IP-пакетов

## Определения

**Фрагментация IP** — процесс разделения одного IP-пакета на несколько частей (фрагментов) меньшего размера. Это необходимо, когда пакет должен пройти через сегмент сети с **MTU (Maximum Transmission Unit)**, который меньше текущего размера пакета.

**MTU (Maximum Transmission Unit)** — максимальный размер полезной нагрузки кадра канального уровня (L2), который может быть передан в данном сегменте. Стандарт для Ethernet — **1500 байт**, для Jumbo Frames — до **9000 байт**.

**MSS (Maximum Segment Size)** — максимальный размер полезной нагрузки TCP-сегмента. Связан с MTU формулой: `MSS = MTU - (IP заголовок) - (TCP заголовок)`. Для Ethernet: `1500 - 20 - 20 = 1460 байт`.

**Fragment Offset** — 13-битное поле в заголовке IPv4, указывающее позицию данных фрагмента относительно исходного пакета. Измеряется в **8-байтовых блоках (октетах)**. Максимальное значение: `8191 × 8 = 65528 байт`.

**DF (Don't Fragment)** — флаг в заголовке IPv4 (Bit 1 в поле Flags). Если `DF=1`, фрагментация запрещена; промежуточный маршрутизатор обязан отбросить пакет и отправить ICMP Type 3 Code 4. Используется в PMTUD.

**MF (More Fragments)** — флаг в заголовке IPv4 (Bit 2 в поле Flags). Если `MF=1`, за данным фрагментом следуют другие. Последний фрагмент имеет `MF=0`.

**PMTU (Path MTU)** — минимальный MTU на всём пути от источника до назначения. Определяется PMTUD.

**Reassembly (Сборка)** — процесс восстановления исходного IP-пакета из фрагментов. В IPv4 выполняется на промежуточных маршрутизаторах И на хосте-получателе. В IPv6 — только на хосте-получателе.

## Связь с соседними уровнями

```text
┌────────────────────────────────────────────────────────────────────────┐
│ L4 — TCP / UDP                                                        │
│   TCP: MSS согласуется через TCP Options в SYN/SYN-ACK                │
│        TCP luôn имеет DF=1 (PMTUD)                                    │
│   UDP: MSS не используется; PMTUD опционален (sendmsg + DF)           │
│        Если DF=0 и пакет > MTU → IP-фрагментация                     │
│   ICMP: PTB (Packet Too Big) — сигнал о необходимости фрагментации    │
└──────────────────────┬─────────────────────────────────────────────────┘
                       ↓ передаёт Segment (L4) в L3
┌────────────────────────────────────────────────────────────────────────┐
│ L3 — IP (IPv4 / IPv6)                                                │
│   ┌──────────────────────────────────────────────────────────────┐    │
│   │ PDU: Packet (Пакет)                                         │    │
│   │ Заголовок: 20B (min) — 60B (max) для IPv4                  │    │
│   │ Поля фрагментации: Identification, Flags (DF/MF), Offset   │    │
│   │ DF=1 → PMTUD (отправить ICMP PTB при MTU mismatch)         │    │
│   │ DF=0 → IP-фрагментация (разбить на фрагменты ≤ MTU)        │    │
│   │ MTU определяет Max Total Length пакета (L3 PDU)             │    │
│   └──────────────────────────────────────────────────────────────┘    │
│   Инкапсуляция: L3-пакет → L2-кадр (Ethernet frame)                 │
│   L2 MTU (1500B) определяет Max L3 PDU Size                         │
└──────────────────────┬─────────────────────────────────────────────────┘
                       ↓ передаёт Packet (L3) в L2
┌────────────────────────────────────────────────────────────────────────┐
│ L2 — Ethernet / Wi-Fi / PPP / PPPoE                                   │
│   Ethernet MTU: 1500B (стандарт) / 9000B (Jumbo)                    │
│   PPPoE: MTU = 1492B (8B PPPoE header)                               │
│   Wi-Fi: MTU = 1500B (как Ethernet, но lower throughput)             │
│   VXLAN: MTU = 1500B → L3 MTU = 1450B (50B overlay overhead)        │
│   GRE:   MTU = 1500B → L3 MTU = 1476B (24B tunnel header)           │
│   PPP:   MTU = 1500B (или настроенное значение)                      │
└────────────────────────────────────────────────────────────────────────┘
```

| Уровень | PDU | Фрагментация | Ключевые поля |
| :--- | :--- | :--- | :--- |
| **L4 — TCP** | Segment | Не фрагментирует (MSS); DF=1 всегда | SRC Port, Dst Port, Seq, Ack, Flags |
| **L4 — UDP** | Datagram | Не фрагментирует; relies on IP fragmentation | SRC Port, Dst Port, Length |
| **L3 — IPv4** | Packet | **Фрагментация на хосте + маршрутизаторах** (DF=0) | Identification, Flags (DF/MF), Offset |
| **L3 — IPv6** | Packet | **Только на источнике**; маршрутизаторы не фрагментируют | Fragment Extension Header |
| **L2 — Ethernet** | Frame | Не фрагментирует; ожидает L3 PDU ≤ MTU | DST MAC, SRC MAC, EtherType, Payload |
| **ICMP** | Message | PTB (Type 3 Code 4 / v6 Type 2) | Code, Next-Hop MTU |

## Инкапсуляция при фрагментации

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ IPv4 Packet (4000 байт total)                                           │
│ ┌────────────┬────────────────────────────────────────────────────────┐  │
│ │ IP Header  │              Payload: 3980 байт                       │  │
│ │ 20 байт    │   (TCP Header + Data / UDP + Data / ...)              │  │
│ │ DF=0       │                                                        │  │
│ │ MF=0       │                                                        │  │
│ │ Offset=0   │                                                        │  │
│ └────────────┴────────────────────────────────────────────────────────┘  │
│                      ↓ MTU = 1500 (маршрутизатор или хост)              │
│ ┌────────────┬──────────────────────────┐  ← Фрагмент 1                │
│ │ IP Header  │   Payload: 1480 байт     │  MF=1, Offset=0              │
│ │ 20B        │   (IP ID=0xABCD)         │  Total: 1500B                │
│ └────────────┴──────────────────────────┘                               │
│ ┌────────────┬──────────────────────────┐  ← Фрагмент 2                │
│ │ IP Header  │   Payload: 1480 байт     │  MF=1, Offset=185            │
│ │ 20B        │   (IP ID=0xABCD)         │  Total: 1500B                │
│ └────────────┴──────────────────────────┘                               │
│ ┌────────────┬──────────────────────┐      ← Фрагмент 3                │
│ │ IP Header  │   Payload: 1020 байт │  MF=0, Offset=370               │
│ │ 20B        │   (IP ID=0xABCD)     │  Total: 1040B                   │
│ └────────────┴──────────────────────┘                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

> **Ключевой момент:** MAC-адреса (L2) меняются на каждом хопе. IP-адреса (L3) остаются неизменными. Фрагменты сохраняют оригинальный IP ID — это позволяет получателю отличить фрагменты разных пакетов.

## Базовые концепции

### Почему фрагментация нежелательна

В современной SRE-практике фрагментация считается «злом», которого следует избегать:
1.  **Нагрузка на ресурсы:** Маршрутизаторы тратят CPU на нарезку пакетов, а хосты — RAM и CPU на их хранение и сборку.
2.  **Амплификация потерь:** Если теряется хотя бы один фрагмент, весь исходный пакет считается битым. В случае TCP это вызывает повторную отправку **всех** фрагментов исходного пакета.
3.  **Проблемы с NAT и Firewall:** Поля портов L4 (TCP/UDP) находятся только в первом фрагменте. Последующие фрагменты часто блокируются «глупыми» файрволами или некорректно обрабатываются NAT.
4.  **Bufferbloat и Latency:** Процесс сборки вносит непредсказуемые задержки (jitter).
5.  **Проблемы с Stateful Firewall:** Состояние отслеживается по первому фрагменту; последующие фрагменты могут быть отброшены, если state table переполнена.
6.  **Проблемы с IPsec:** Многие IPsec-реализации требуют PPP (PMTUD) для корректного туннелирования; фрагментация внутри туннеля приводит к oversized outer packets.

### Кто фрагментирует

| Характеристика | IPv4 | IPv6 |
| :--- | :--- | :--- |
| Фрагментация на **хосте-отправителе** | Да (DF=0) | Да (DF=0, Fragment Header) |
| Фрагментация на **промежуточном маршрутизаторе** | Да (DF=0) | **Запрещено** |
| Сборка на промежуточных маршрутизаторах | Да (для фрагментов) | Нет |
| Сборка на **хосте-получателе** | Да | Да |
| MTU Discovery | ICMP Type 3 Code 4 + PMTUD | ICMPv6 Type 2 + PMTUD |
| Минимальный MTU | 576 байт (RFC 791) | **1280 байт** (RFC 8200, обязателен) |

## Механизм фрагментации в IPv4

В IPv4 фрагментация может выполняться как отправителем, так и промежуточными маршрутизаторами (хопами), если в заголовке сброшен флаг **DF**.

### Поля заголовка IPv4 для фрагментации

Для сборки пакета используются три поля (всего 32 бита служебной информации):

1.  **Identification (16 бит):** Уникальное число, присваиваемое исходному пакету. Позволяет отличить фрагменты пакета А от фрагментов пакета Б. Увеличивается на 1 для каждого отправленного пакета (на Linux: `net.ipv4.ip_idents_resume`).
2.  **Flags (3 бита):**
    - **Bit 0:** Зарезервирован (всегда 0).
    - **Bit 1 (DF — Don't Fragment):** Если 1 — фрагментация запрещена. Если пакет не лезет в MTU, он дропается с ICMP-ответом.
    - **Bit 2 (MF — More Fragments):** Если 1 — за этим фрагментом следуют другие. Если 0 — это последний фрагмент.
3.  **Fragment Offset (13 бит):** Смещение данных фрагмента относительно начала исходного пакета. Измеряется в **8-байтовых блоках (октетах)**. Максимально: `8191 × 8 = 65528 байт`.

### Алгоритм расчета (Пример)

Исходный пакет 4000 байт (20B заголовок + 3980B данные), MTU пути = 1500 байт.
Макс. объем данных в фрагменте: `1500 - 20 = 1480`. (1480 делится на 8).

| Фрагмент | Размер (Total) | Данные | MF | Offset (октеты) | Диапазон байт |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **№1** | 1500 | 1480 | 1 | 0 | 0 – 1479 |
| **№2** | 1500 | 1480 | 1 | 185 (1480/8) | 1480 – 2959 |
| **№3** | 1040 | 1020 | 0 | 370 (2960/8) | 2960 – 3979 |

> **Формула:** `Data_per_fragment = floor((MTU - IP_Header_Size) / 8) × 8`. Для MTU=1500, IPv4 Header=20: `floor(1480/8) × 8 = 1480`.

### Timeout сборки (Reassembly)

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `ipfrag_time` (Linux) | 30 секунд (по умолчанию) | Время ожидания всех фрагментов |
| `ipfrag_high_thresh` | 4MB (по умолчанию) | Макс. память для очереди фрагментов |
| `ipfrag_low_thresh` | 3MB (по умолчанию) | Порог освобождения памяти |
| Поведение при таймауте | Все фрагменты отбрасываются | Полная потеря пакета |
| **Reassembly на маршрутизаторе** | Только IPv4 (если DF=0) | Дополнительная нагрузка на CPU/RAM |

## Фрагментация в UDP (без MSS)

UDP не имеет механизма MSS. Каждый UDP-дейтаграмм — это один L3-пакет. Если UDP-пакет превышает MTU:

- **DF=0 (по умолчанию в Linux):** IP-фрагментация.
- **DF=1 (через `IP_MTU_DISCOVER`):** Если пакет > MTU → ICMP Type 3 Code 4 → приложение получает `EMSGSIZE`.

**Проблемы UDP + фрагментация:**
1. **DNS:** Ответ > 512B (UDP53) → фрагментация; ответ > 4096B →通常 UDP с DF=1 → ICMP PTB → TCP fallback.
2. **TFTP:** Сегменты 512B → обычно без фрагментации; при размере > 1472B (UDP) → фрагментация.
3. **NFS (UDP):** Historically использовалась фрагментация; modern NFS — TCP.
4. **VoIP (RTP/UDP):** Малые пакеты (20-172B), но при фрагментации — jitter и packet loss.

## Фрагментация в IPv6

Для разгрузки ядра интернета в IPv6 правила радикально изменены:
- **Маршрутизаторам запрещено фрагментировать пакеты.** Если пакет больше MTU интерфейса, маршрутизатор обязан его отбросить и отправить отправителю **ICMPv6 Type 2 (Packet Too Big)**.
- **End-to-End:** Фрагментировать данные может только узел-отправитель.
- **Минимальный MTU:** Все узлы IPv6 обязаны поддерживать MTU не менее **1280 байт**.
- **Fragment Header:** Информация о фрагментации вынесена в расширенный заголовок (Extension Header), который игнорируется всеми транзитными узлами.

### Пример фрагментации IPv6

Исходный пакет 4000 байт (40B заголовок + 3960B данные), MTU = 1500.
Макс. данных в фрагменте: `1500 - 40 (IPv6) - 8 (Fragment Header) = 1452`.

| Фрагмент | Total Size | Data | MF | Offset (октеты) | Диапазон байт |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **№1** | 1500 | 1452 | 1 | 0 | 0 – 1451 |
| **№2** | 1500 | 1452 | 1 | 181 (1452/8) | 1452 – 2903 |
| **№3** | 1148 | 1100 | 0 | 362 (2904/8) | 2904 – 4003 |

> **Разница с IPv4:** IPv6 добавляет 8-байтовый Fragment Header к каждому фрагменту; поле Identification перенесено в Extension Header и расширено до 32 бит (меньше коллизий).

## Path MTU Discovery (PMTUD)

### Принцип работы

```text
Хост A                                              Хост B
   │                                                    │
   │ 1. Пакет с DF=1 (размер = local MTU)              │
   │ ─────────────────────────────────────────────────→ │
   │                                                    │
   │    [Маршрутизатор] MTU < размер пакета             │
   │    → Отбрасывает пакет                             │
   │    → Отправляет ICMP Type 3 Code 4                │
   │      (Destination Unreachable / Fragmentation      │
   │       Needed and DF set / Next-Hop MTU = 1400)     │
   │ ←───────────────────────────────────────────────── │
   │                                                    │
   │ 2. Хост A уменьшает PMTU до 1400                  │
   │    и повторно отправляет данные                    │
   │ ─────────────────────────────────────────────────→ │
   │                                                    │
```

**Проблема PMTUD Black Hole:**
- Если файрвол блокирует ICMP Type 3 Code 4 → хост A не узнает об уменьшении MTU.
- Результат: большие пакеты (TCP segments > MTU) отбрасываются, но малые (SYN, ACK, keepalive) проходят.
- Симптом: SSH/HTTP подключаются, но зависают при передаче данных.

### Linux sysctl для PMTUD

```bash
# Просмотр текущих настроек PMTUD
sysctl net.ipv4.ip_no_pmtu_disc           # 0 = PMTUD включен (default)
                                           # 1 = PMTUD выключен (DF=0)
                                           # 2 = Always DF (PMTUD обязателен)
                                           # 3 = DF по умолчанию

# Кэш PMTU (Linux хранит PMTU для каждого пути)
sysctl net.ipv4.route.min_advmss          # Минимальный MSS для PMTU (default=256)
sysctl net.ipv4.ip_nonlocal_bind          # Разрешить привязку к не-локальным адресам (для PBR)

# Для туннелей (GRE/IPIP) — отключение PMTUD (NOPMTUDISC)
ip tunnel add tun0 mode gre local 10.0.0.1 remote 10.0.0.2 dev eth0
ip link set tun0 mtu 1400
ip link set tun0 type gre nopmtudisc     # Отключить PMTUD для туннеля
```

### Cisco IOS для PMTUD

```bash
# Включение PMTUD на интерфейсе
interface GigabitEthernet0/0
  ip mtu 1400
  ip tcp adjust-mss 1360                 # MSS Clamping

# Проверка PMTU для конкретного маршрута
show ip cache verbose
show ip route 10.0.0.0
show ip cef 10.0.0.1
```

### PMTUD vs PLPMTUD

| Характеристика | PMTUD (RFC 1191) | PLPMTUD (RFC 4821 / 8899) |
| :--- | :--- | :--- |
| **Уровень** | L3 (IP) | L4+ (TCP/UDP payload) |
| **Механизм** | DF=1 + ICMP PTB | Пробные сегменты + ACK |
| **Зависимость от ICMP** | Да (критична) | Нет |
| **Точность** | По сегментам пути | По реальному Path MTU |
| **Применение** | Основной метод | Резервный (при ICMP Blocked) |
| **Поддержка в Linux** | Ядро (net.ipv4.ip_no_pmtu_disc) | TCP PLPMTUD (RFC 8899, Linux 5.18+) |
| **Пример реализации** | ping -M do | QUIC (PLPMTUD native), TCP (PLPMTUD optional) |

## MSS Clamping (TCP MSS)

### Принцип работы

TCP MSS Clamping — техника на промежуточном маршрутизаторе (шлюзе), который изменяет значение MSS в TCP-пакетах SYN/SYN-ACK на лету. Это заставляет конечные хосты отправлять сегменты меньшего размера, не доводя до IP-фрагментации.

```text
Клиент (MTU=1500)                  Шлюз (MTU=1400)              Сервер
     │                                  │                          │
     │ SYN (MSS=1460)                  │                          │
     │ ──────────────────────────────────────────────────────────→ │
     │                                  │                          │
     │                      ┌──────────────────────┐              │
     │                      │ MSS Clamping:         │              │
     │                      │ MSS=1460 → MSS=1360  │              │
     │                      └──────────────────────┘              │
     │                                  │                          │
     │                                  │    SYN (MSS=1360)       │
     │ ←────────────────────────────────────────────────────────── │
     │                                  │                          │
     │    ACK (MSS=1360)                │                          │
     │ ──────────────────────────────────────────────────────────→ │
     │                                  │                          │
     │ Данные (≤1360B) ──────────────────────────────────────────→ │
```

### Конфигурация MSS Clamping

**iptables (Linux):**
```bash
# Синхронный MSS Clamping на шлюзе (_OUTPUT = от клиента к серверу)
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu

# Принудительный MSS = 1360 (для MTU=1400: 1400 - 20(IP) - 20(TCP) = 1360)
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --set-mss 1360

# То же для IPv6
ip6tables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu
```

**nftables (Linux):**
```bash
nft add rule ip mangle forward tcp flags syn tcp option maxseg size set tcp mss
```

**Cisco IOS:**
```bash
interface GigabitEthernet0/0
  ip tcp adjust-mss 1360

# Или более гибко через policy-map
policy-map MSS-CLAMP
  class class-default
    set tcp adjust-mss 1360
```

**MikroTik RouterOS:**
```bash
/ip firewall mangle add chain=forward protocol=tcp tcp-flags=syn \
    action=change-mss new-mss=1360
```

**PPP/PPPoE (Linux):**
```bash
# При PPPoE-соединении MTU=1492, MSS=1452
pppd mtu 1492 mru 1492
# Или через ip route:
ip route add default via 10.0.0.1 dev ppp0 advmss 1452
```

## Фрагментация в туннелях

### Туннели и MTU overhead

Каждый тип туннеля добавляет заголовки, уменьшающие доступный MTU для полезных данных:

| Тип туннеля | Overhead (байт) | L3 MTU | MSS (TCP) | Примечания |
| :--- | :--- | :--- | :--- | :--- |
| **GRE** | 24 | 1476 | 1436 | Без шифрования |
| **GRE + IPsec** | 24+20-50 | 1430-1456 | 1390-1416 | Транспортный/туннельный режим |
| **IPIP** | 20 | 1480 | 1440 | Простейший IP-in-IP |
| **WireGuard** | 60 | 1440 | 1400 | Noise Protocol + ChaCha20 |
| **OpenVPN (UDP)** | 60-80 | 1420-1440 | 1380-1400 | Зависит от cipher/auth |
| **L2TP/IPsec** | 50-70 | 1430-1450 | 1390-1410 | Двойной overhead |
| **VXLAN** | 50 | 1450 | 1410 | Overlay networking |
| **GENEVE** | 56-164 | 1336-1444 | 1296-1404 | Variable-length options |
| **STT** | 54-58 | 1442-1446 | 1402-1406 | TCP-like offload |
| **IPsec Tunnel** | 50-73 | 1427-1450 | 1387-1410 | AES-GCM/ESP |
| **WireGuard** | 60 | 1440 | 1400 | Noise Protocol |

### Поведение DF в туннелях

```bash
# Linux: копирование DF из внутреннего пакета во внешний (по умолчанию)
# Если внутренний пакет DF=1, внешний тоже DF=1
# Если MTU туннеля < MTU внутреннего → ICMP PTB → PMTUD

# Проверка текущего MTU туннеля
ip link show dev tun0
ip link show dev gre0

# Установка MTU туннеля (с учётом overhead)
ip link set dev tun0 mtu 1440     # WireGuard (1500 - 60)
ip link set dev gre0 mtu 1476     # GRE (1500 - 24)

# Отключение PMTUD для туннеля (NOPMTUDISC) — только для testing!
ip tunnel add tun0 mode gre remote 10.0.0.2 local 10.0.0.1 dev eth0
ip link set tun0 type gre nopmtudisc
```

## Безопасность и векторы атак

### Атаки на фрагментацию

| Атака | Описание | Опасность | Митигация |
| :--- | :--- | :--- | :--- |
| **Tiny Fragment Attack** | Первый фрагмент слишком мал для L4 заголовка (порты) | Обход ACL/Firewall (проверяют только первый фрагмент) | Фильтрация фрагментов; Require All Fragments;Stateless ACL |
| **Fragment Overlap** | Фрагменты с перекрывающимися Offset | Перезапись данных при сборке (Remote Code Execution) | Обновление ОС; De-fragmentation before inspection |
| **Ping of Death** | Фрагменты → assembled packet > 65535 байт | Buffer overflow (старые ОС) | Обновление ОС (fixed in Linux 2.0+, Windows 95+) |
| **Rose Attack** | Множество фрагментов с большими Offset | Memory exhaustion (DoS) | Ограничение `ipfrag_high_thresh`; Timeout `ipfrag_time` |
| **Teardrop** | Фрагменты с перекрывающимися/бесконечными Offset | Kernel panic (старые ОС) | Обновление ОС; фильтрация в ядре |
| **Fragment Flood** | Лавина фрагментов без завершения сборки | Reassembly buffer exhaustion (DoS) | `sysctl net.ipv4.ipfrag_high_thresh=4194304` |
| **ICMP PTB Spoofing** | Поддельные ICMP PTB → снижение PMTU | Blackhole; снижение throughput | `net.ipv4.icmp_errors_use_inbound_ifaddr=1` |

### Sysctl-защита от атак фрагментации

```bash
# Максимальный размер буфера фрагментов (prevents memory exhaustion)
sysctl -w net.ipv4.ipfrag_high_thresh=4194304    # 4MB (default)
sysctl -w net.ipv4.ipfrag_low_thresh=3145728     # 3MB (default)

# Timeout сборки фрагментов (prevents resource holding)
sysctl -w net.ipv4.ipfrag_time=30                 # секунд (default=30)

# Включить安全保障 (отбрасывать фрагменты с перекрытием)
sysctl -w net.ipv4.conf.all.accept_source_route=0
sysctl -w net.ipv4.conf.default.accept_source_route=0

# Отключить ICMP PTB redirect (защита от spoofing)
sysctl -w net.ipv4.icmp_errors_use_inbound_ifaddr=1

# IPv6: аналогичные настройки
sysctl -w net.ipv6.conf.all.accept_redirects=0
sysctl -w net.ipv6.conf.all.accept_source_route=0
```

## Практическая диагностика (Linux)

### Определение MTU и MSS

```bash
# Определение Path MTU до цели (DF=1, ICMP PTB)
ping -M do -s 1472 8.8.8.8            # 1472 + 20(IP) + 8(ICMP) = 1500
ping -M do -s 1472 -M 10.0.0.1        # MTU через конкретный интерфейс

# tracepath — определение MTU на каждом хопе
tracepath 8.8.8.8                      # Показывает MTU каждого маршрутизатора

# Просмотр текущего MTU интерфейса
ip -brief link show
ethtool eth0 | grep -i mtu            # Или: ethtool -S eth0 | grep MTU

# Просмотр MSS в TCP-соединениях
ss -ti state established | grep mss   # Показывает MSS для каждого соединения
ss -ti dst 10.0.0.1 | grep mss       # MSS для конкретного соединения
nstat -az | grep -i mss               # Статистика MSS
```

### Просмотр фрагментации и счётчиков

```bash
# Счётчики фрагментации в ядре
nstat -az | grep -E "Reasm|Frag|Fail"
#  Output:
#  IpReasmReqds    — количество запросов на сборку
#  IpReasmFails    — количество ошибок сборки (таймаут/переполнение)
#  IpReasmoks      — количество успешных сборок
#  IpFragCreates   — количество созданных фрагментов
#  IpFragFails     — количество ошибок фрагментации (нет памяти)
#  IpFragoks       — количество успешных фрагментаций

# Подробная статистика
cat /proc/net/snmp | grep -E "Ip:|Icmp:"
#  Ip: Forwarding DefaultTTL InReceives InHdrErrors InAddrErrors ForwDatagrams
#      InUnknownProtos InDiscards InDelivers OutRequests RoutingDiscards
#      ReasmReqds ReasmOks ReasmFails FragCreates FragOks FragFails

# Просмотр кэша PMTU (Linux хранит PMTU для каждого маршрута)
ip route show cache | grep -E "mtu|advmss"
#  10.0.0.1 via 10.0.0.254 dev eth0 src 10.0.0.100 mtu 1400 advmss 1360

# Просмотр текущего MTU на интерфейсе
cat /sys/class/net/eth0/mtu
ip link show dev eth0 | grep mtu

# Просмотр TCP-соединений с MSS
ss -ti | head -20
```

### tcpdump: захват фрагментов

```bash
# Захват всех фрагментированных пакетов (MF=1 или Offset>0)
tcpdump -i eth0 'ip[6:2] & 0x2000 != 0 or ip[6:2] & 0x1fff != 0' -nn

# Захват пакетов с DF=1
tcpdump -i eth0 'ip[6] & 0x40 != 0' -nn

# Захват ICMP PTB (Type 3 Code 4) — ключевой для PMTUD
tcpdump -i eth0 'icmp[0] == 3 and icmp[1] == 4' -nn

# Захват ICMPv6 Packet Too Big (Type 2)
tcpdump -i eth0 'icmp6[0] == 2' -nn

# Захват MSS в TCP SYN
tcpdump -i eth0 'tcp[tcpflags] & (tcp-syn) != 0' -nn -v | grep -i mss

# Захват всех фрагментов + их reconstruction (для анализа)
tcpdump -i eth0 -w fragments.pcap 'ip[6:2] & 0x2000 != 0 or ip[6:2] & 0x1fff != 0'
# Открыть в Wireshark: фрагменты автоматически реконструируются

# Захват фрагментов с фильтрацией по хосту
tcpdump -i eth0 host 10.0.0.1 and 'ip[6:2] & 0x2000 != 0 or ip[6:2] & 0x1fff != 0'
```

### Диагностика PMTUD Black Hole

```bash
# 1. Проверка: ping работает, но TCP висит?
ping 10.0.0.1                          # ← Работает
curl http://10.0.0.1/big-file          # ← Висит

# 2. Проверка MTU через ping с DF
ping -M do -s 1472 10.0.0.1            # Если "Message too long" → MTU < 1500

# 3. Проверка ICMP PTB
tcpdump -i eth0 'icmp[0] == 3 and icmp[1] == 4' -c 5

# 4. Проверка PMTU в кэше
ip route show cache | grep 10.0.0.1

# 5. Проверка MSS в соединении
ss -ti dst 10.0.0.1 | grep mss

# 6. Проверка是否有 фрагменты
nstat -az | grep -E "Frag|Reasm"

# 7. Проверка: файрвол блокирует ICMP?
iptables -L -n -v | grep -E "ICMP|icmp"
nft list ruleset | grep -E "icmp|icmpv6"

# 8. Проверка: sysctl
sysctl net.ipv4.ip_no_pmtu_disc
sysctl net.ipv4.icmp_errors_use_inbound_ifaddr
```

### Диагностика на Cisco/MikroTik

```bash
# Cisco: проверка фрагментации
show interface GigabitEthernet0/0 | include MTU|drops|error
show ip traffic | include Fragment
debug ip packet detail                  # ОСТОРОЖНО! только в lab

# Cisco: проверка ICMP PTB
show access-lists | include 3
show ip cache statistics

# MikroTik: проверка фрагментации
/tool profile
/monitor traffic interface=ether1

# MikroTik: MSS Clamping
/ip firewall mangle print where action=change-mss
```

## Типичные проблемы и чеклист

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **SSH подключается, но висит при ls/df** | PMTU Black Hole: ICMP PTB блокирован | `ping -M do -s 1472 <host>` + `tcpdump icmp` | Разрешить ICMP PTB; MSS Clamping |
| **curl/wget висит на больших файлах** | TCP MSS > Path MTU; фрагментация/отбрасывание | `ss -ti \| grep mss` + `ip route show cache` | MSS Clamping; `ip route change default` |
| **DNS-ответ > 512B обрезан** | UDP фрагментация; файрвол блокирует фрагменты | `tcpdump port 53 -nn` + `dig +dnssec +bufsize=4096` | Добавить правило для DNS фрагментов |
| **NFS/Kerberos зависает** | Фрагментация UDP; timeout сборки | `rpcdump -p <host>` + `tcpdump port 2049` | Переключить на TCP; MSS Clamping |
| **VPN-туннель: MTU mismatch** | overhead туннеля не учтён | `ip link show dev tun0` + `ping -M do -s <size>` | `ip link set dev tun0 mtu <MTU-overhead>` |
| **ipsec: pmtu discovery не работает** | ICMP PTB заблокирован на туннеле | `setkey -DP` (IPsec SA) + `tcpdump` | Включить ICMP на туннельном интерфейсе |
| **Фрагменты не собираются** | Таймаут `ipfrag_time`; переполнение буфера | `nstat -az \| grep ReasmFails` | Увеличить `ipfrag_high_thresh` |

## Сводная таблица

| Параметр | Значение |
| :--- | :--- |
| **Ethernet MTU** | 1500 байт |
| **Jumbo Frame MTU** | 9000 байт |
| **PPPoE MTU** | 1492 байт (1500 - 8B PPPoE) |
| **IPv4 Min MTU** | 576 байт (RFC 791) |
| **IPv6 Min MTU** | 1280 байт (RFC 8200, обязателен) |
| **MSS (Ethernet, TCP)** | 1460 байт (1500 - 20IP - 20TCP) |
| **MSS (PPPoE, TCP)** | 1452 байт (1492 - 20IP - 20TCP) |
| **IP Header (IPv4)** | 20 байт (min) — 60 байт (max) |
| **IP Header (IPv6)** | 40 байт (фиксированный) |
| **Fragment Header (IPv6)** | 8 байт |
| **DF Flag** | Bit 1 в Flags (IPv4) |
| **MF Flag** | Bit 2 в Flags (IPv4) |
| **Fragment Offset** | 13 байт (в 8-байтовых блоках) |
| **Max Offset (IPv4)** | 65528 байт (8191 × 8) |
| **Reassembly Timeout (Linux)** | 30 секунд (default) |
| **PMTU Black Hole** | ICMP PTB заблокирован → данные не доходят |
| **ICMP PTB (IPv4)** | Type 3 Code 4 |
| **ICMP PTB (IPv6)** | Type 2 |

## Дополнительная информация

### См. также
- **[MTU, PMTUD и диагностика в VPN/облаках](../mtu_and_vpn.md)** — overhead туннелей, MSS Clamping, sysctl, cloud MTU, Docker/Container MTU.
- **[Обзор сетевого уровня (L3)](../Concepts/network_layer_overview.md)** — PDU, инкапсуляция, маршрутизация, фрагментация IPv4 vs IPv6.
- **[Структура IP-пакета (IPv4)](./ip_packet_structure.md)** — заголовок IPv4: поля Identification, Flags, Offset.
- **[Протокол ICMP: Destination Unreachable](../../../Protocols/ICMP/icmp_destination_unreachable.md)** — ICMP Type 3 Code 4 (PMTUD).
- **[Протокол ICMP: Time Exceeded](../../../Protocols/ICMP/icmp_time_exceeded.md)** — ICMP Type 11 (сборка фрагментов).
- **[Обзор ICMP](../../../Protocols/ICMP/icmp_overview.md)** — все типы ICMP-сообщений.
- **[Протокол UDP](../../../Protocols/udp.md)** — UDP и фрагментация (без MSS).
- **[IPv6: Обзор](../../../Protocols/ipv6_overview.md)** — фрагментация в IPv6, Extension Headers.
- **[TCP: Алгоритмы контроля нагрузки](../../../Protocols/TCP/congestion/tcp_congestion_algorithms.md)** — PLPMTUD (RFC 8899).
- **[Routing Scenarios](../Concepts/routing_scenarios.md)** — PMTU Black Hole (сценарий).
- **[Маршрутизация и оборудование L3](../routing_protocols_equipment.md)** — RIB/FIB, ASIC/TCAM.
