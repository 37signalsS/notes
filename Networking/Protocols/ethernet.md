# Ethernet — технология локальных сетей

## Определения

**Ethernet** — технология для создания проводных локальных компьютерных сетей **LAN (Local Area Network)**. Вместе с Wi-Fi составляет основу большинства современных сетей. В семиуровневой модели взаимодействия открытых систем **OSI (Open Systems Interconnection)** Ethernet охватывает **Физический (L1)** и **Канальный (L2)** уровни.

**Кадр Ethernet (Frame)** — единица передачи данных на канальном уровне, содержащая физические адреса отправителя и получателя, данные и контрольную сумму.

**Пакет Ethernet** — полная единица передачи на физическом уровне, включающая преамбулу, начальный ограничитель кадра **SFD (Start Frame Delimiter)**, кадр канального уровня и контрольную последовательность кадра **FCS (Frame Check Sequence)**.

### Визуальный обзор Ethernet в модели OSI

```
┌─────────────────────────────────────────────────────────────────┐
│                    Прикладной уровень (L7-L5)                    │
│              HTTP, DNS, SSH, SMTP, ...                          │
├─────────────────────────────────────────────────────────────────┤
│                    Транспортный уровень (L4)                     │
│                   TCP         │        UDP                       │
├──────────────────────────────┼──────────────────────────────────┤
│                    Сетевой уровень (L3)                          │
│                   IPv4        │        IPv6                      │
│              ┌────────────────┴────────────────┐                │
│              │   ARP (0x0806) → MAC-адрес       │                │
├──────────────┴────────────────────────────────┴─────────────────┤
│              Канальный уровень (L2) — IEEE 802.3 Ethernet        │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │  LLC (802.2) │  │     MAC      │  │   802.1Q (VLAN)    │     │
│  │  Мультиплекс│  │  Адресация   │  │   Тегирование      │     │
│  │  протоколов  │  │  + доступ    │  │   кадров            │     │
│  └─────────────┘  └──────────────┘  └────────────────────┘     │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Кадр Ethernet II (DIX)                      │   │
│  │  ┌────────┬────────┬──────────┬─────────┬──────┐        │   │
│  │  │  Dst   │  Src   │ EtherType│ Payload │ FCS  │        │   │
│  │  │ MAC    │ MAC    │ 2 bytes  │46-1500  │ 4B   │        │   │
│  │  │ 6 bytes│ 6 bytes│          │ bytes   │      │        │   │
│  │  └────────┴────────┴──────────┴─────────┴──────┘        │   │
│  └─────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                    Физический уровень (L1)                      │
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────┐              │
│  │ Витая    │  │  Оптоволокно │  │   DAC/AOC    │              │
│  │  пара    │  │  SM / MM     │  │  Direct      │              │
│  │Cat5e-8   │  │  (LC/MPO)    │  │  Attach      │              │
│  └──────────┘  └──────────────┘  └─────────────┘              │
│                                                                 │
│  Preamble (7B) │ SFD (1B) │ Ethernet Frame │ IPG (12B)         │
└─────────────────────────────────────────────────────────────────┘
```

- **Создание (1973):** Роберт Меткалф в Xerox PARC на основе сети Aloha.
- **Стандартизация (1980-е):** Консорциум **DIX (Digital Equipment Corporation, Intel, Xerox)** → первый стандарт **IEEE (Institute of Electrical and Electronics Engineers)** 802.3 в 1983 году.
- **Доминирование (1990-е):** Вытеснил конкурирующие технологии (Token Ring, FDDI) благодаря простоте и дешевизне.

### Стандарты IEEE 802.3

Семейство стандартов IEEE 802.3 описывает различные поколения технологии, адаптированные для меди и оптики.

| Стандарт | Технология | Среда передачи | Макс. расстояние | Применение |
| :--- | :--- | :--- | :--- | :--- |
| **802.3** | Ethernet (10 Mbps) | Витая пара (Cat3/5), coax | 100 м / 500 м | Исторический, не используется |
| **802.3u** | Fast Ethernet (100 Mbps) | Витая пара (Cat5) | 100 м | Устарело, legacy устройства |
| **802.3ab** | Gigabit Ethernet (1 Gbps) | Витая пара (Cat5e) | 100 м | Современный стандарт рабочих мест |
| **802.3an** | 10GBASE-T (10 Gbps) | Витая пара (Cat6a/7) | 100 м | Серверы, high-end рабочие станции |
| **802.3bz** | NBASE-T (2.5G / 5G) | Витая пара (Cat5e/6) | 100 м | Wi-Fi 6/7 AP, рабочие станции |
| **802.3ae** | 10 GbE (10G) | Оптоволокно (SMF/MMF) | до 40 км | Ядро сети, серверы |
| **802.3by** | 25 GbE | Оптика / DAC | до 10 км | Server access (ЦОД) |
| **802.3bq** | 40GBASE-T | Витая пара (Cat8) | 30 м | Короткие линки в ЦОД |
| **802.3ba** | 40G / 100 GbE | Оптика / DAC | до 10-40 км | Spine-Leaf фабрики, магистрали |
| **802.3bs** | 200G / 400 GbE | Оптоволокно (SMF) | до 10 км | Высокопроизводительные кластеры |
| **802.3ck** | 100G / 400G per lane | Оптика / DAC | до 10 км | Серверные NIC, SmartNIC (с 2022) |
| **802.3df** | 800 GbE | Оптоволокно (SMF) | до 2-10 км | AI-кластеры, интерконнект ЦОД (с 2024) |

### Медиа передачи: медные и оптические кабели

#### Медная витая пара (Copper Twisted Pair)

| Категория | Макс. частота | Макс. скорость | Макс. расстояние | Применение |
| :--- | :--- | :--- | :--- | :--- |
| **Cat5e** | 100 МГц | 1 Гbps (1000BASE-T) | 100 м | Бюджетные офисы, дома |
| **Cat6** | 250 МГц | 1 Гbps / 10 Гbps (55 м) | 100 м / 55 м | Офисы, Wi-Fi 6 AP |
| **Cat6a** | 500 МГц | 10 Гbps (10GBASE-T) | 100 м | Серверы, ЦОД |
| **Cat7** | 600 МГц | 10 Гbps | 100 м | ЦОД, экранированные среды |
| **Cat8** | 2000 МГц | 25/40 Гbps (40GBASE-T) | 30 м | Короткие линки в ЦОД |

**Типы разъемов:** RJ-45 (стандарт), TERA/GG45 (Cat7), 8P8C (универсальный).

#### Оптоволокно (Fiber Optic)

| Тип | Диаметр | Длина волны | Макс. расстояние | Применение |
| :--- | :--- | :--- | :--- | :--- |
| **MMF OM3** | 50 мкм | 850/950 нм | 300 м (10G), 100 м (40G) | Серверные комнаты |
| **MMF OM4** | 50 мкм | 850/950 нм | 400 м (10G), 150 м (40G) | ЦОД, внутри здания |
| **MMF OM5** | 50 мкм | 850-953 нм | 400 м (100G SWDM) | ЦОД, WDM-приложения |
| **SMF OS1/OS2** | 9 мкм | 1310/1550 нм | до 10-80 км | Магистрали, междугородние |
| **SMF (DWDM)** | 9 мкм | C/L-банк (1528-1625 нм) | до 1000+ км | Трансконтинентальные магистрали |

**Типы разъемов:** LC (самый распространенный), SC (старые), MPO/MTP (40G/100G, 8-32 волокна), E2000 (с защитой).

#### Direct Attach Copper (DAC) и Active Optical Cable (AOC)

| Тип | Описание | Длина | Применение |
| :--- | :--- | :--- | :--- |
| **DAC (Passive)** | Пассивный медный кабель с разъемами | до 5 м | Inter-rack в ЦОД |
| **DAC (Active)** | Активный медный кабель с усилителями | до 10 м | Межстоечные соединения |
| **AOC** | Активный оптический кабель | до 100 м | Высокоскоростные линки в ЦОД |

### Питание через Ethernet (PoE)

Технология передачи электрической энергии вместе с данными по стандартной витой паре.

**Компоненты:**
- **PSE (Power Sourcing Equipment):** коммутатор или инжектор, подающий питание.
- **PD (Powered Device):** устройство, потребляющее питание (IP-телефон, камера, AP).
- **Классификация:** PD сообщает PSE свой класс мощности через сигналization (Resistive ID) или LLDP.

| Стандарт | Название | Макс. мощность (на PD) | Классы | Типы разъемов | Применение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **802.3af** | PoE | 12.95 Вт | 0-3 | RJ-45 | IP-телефоны, простые камеры |
| **802.3at** | PoE+ | 25.5 Вт | 0-4 | RJ-45 | Wi-Fi AP (802.11ac/n), PTZ-камеры |
| **802.3bt Type 3** | PoE++ (60W) | 51 Вт | 0-6 | RJ-45 | Видеоаналитика, LED-панели |
| **802.3bt Type 4** | PoE++ (90W) | 71.3 Вт | 0-8 | RJ-45 | Тонкие клиенты, ноутбуки, цифровые signage |

**Диагностика PoE:**

```bash
# Cisco IOS — статус питания на порту
show power inline
show power inline Gi0/1 detail
show power inline | include Available
# → Available: 370.0 (W) — оставшийся бюджет

# Cisco — проверка класса PD
show cdp neighbors detail | include Power
show lldp neighbors detail | include Power

# LLDP-MED — согласование PoE через LLDP
show lldp interface Gi0/1 detail

# Linux — через sysfs (если PSE поддерживает)
cat /sys/class/net/eth0/device/power/class
cat /sys/class/net/eth0/device/power/limit
```

**Типичные проблемы PoE:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| PD не включается | Исчерпан Power Budget | `show power inline` — проверить доступную мощность |
| PD периодически перезагружается | Нестабильное питание, длинный кабель | Сократить длину кабеля (<100 м), проверить категорию |
| PoE+ не работает | PD требует класс 4, PSE поддерживает только af | Заменить PSE на 802.3at/bt совместимый |
| LLDP-MED не согласуется | LLDP отключен на порту | Включить LLDP, проверить `lldp transmit` |

### Тегирование VLAN: IEEE 802.1Q

**IEEE 802.1Q** — стандарт, определяющий вставку 4-байтового тега в Ethernet-кадр для идентификации принадлежности к **[VLAN (Virtual Local Area Network)](./vlan.md)**.

```
┌───────────────────────────────────────────────────────────────────┐
│   Стандартный кадр Ethernet II                                    │
│  ┌────────┬────────┬──────────┬─────────┬──────┐                 │
│  │  Dst   │  Src   │ EtherType│ Payload │ FCS  │                 │
│  └────────┴────────┴──────────┴─────────┴──────┘                 │
│                                                                   │
│   Кадр с тегом 802.1Q                                             │
│  ┌────────┬────────┬───────┬──────────┬─────────┬──────┐         │
│  │  Dst   │  Src   │ 802.1Q│ EtherType│ Payload │ FCS  │         │
│  │ MAC    │ MAC    │ Tag   │          │         │      │         │
│  │        │        │ 4 bytes│         │         │      │         │
│  └────────┴────────┴───────┴──────────┴─────────┴──────┘         │
│                                                                   │
│   Структура тега 802.1Q (4 байта):                                │
│  ┌──────────────────┬─────────┬───────────┐                      │
│  │    TPID          │  PRI    │  VID       │                      │
│  │   (0x8100)       │ 3 bits  │ 12 bits   │                      │
│  │   2 bytes        │ + CFI   │ 0-4095    │                      │
│  └──────────────────┴─────────┴───────────┘                      │
│   TPID: Tag Protocol Identifier (0x8100)                          │
│   PRI: приоритет (802.1p, для QoS)                                │
│   CFI: Canonical Format Indicator (deprecated, =0 для Ethernet)   │
│   VID: VLAN Identifier (0-4095; 0 и 4095 зарезервированы)        │
└───────────────────────────────────────────────────────────────────┘
```

**Режимы портов:**
- **Access (Untagged):** Порт принадлежит одной VLAN. Весь трафик помечается PVID (Port VLAN ID). Кадры не тегируются.
- **Trunk (Tagged):** Порт передаёт трафик нескольких VLAN. Кадры тегируются 802.1Q. Native VLAN передаётся без тега.
- **Hybrid:** Сочетание access и trunk на одном порту (Huawei, HP).

> **Подробности:** [VLAN — виртуальные локальные сети](./vlan.md), [Формат кадра 802.1Q](./VLAN/vlan_8021q_frame.md), [Trunk и Native VLAN](./VLAN/vlan_trunk_native.md).

### Агрегация каналов (Link Aggregation, IEEE 802.3ad/802.1AX)

**LACP (Link Aggregation Control Protocol)** — протокол, объединяющий несколько физических линков в один логический канал (Port Channel / Bonding). Увеличивает пропускную способность и обеспечивает отказоустойчивость.

**Преимущества:**
- Суммарная пропускная способность = N x скорость одного линка.
- Отказоустойчивость: при выходе из строя одного линка трафик перераспределяется.
- Балансировка нагрузки через хеширование (L2/L3/L4).

**Режимы Bonding (Linux):**

| Режим | Название | Балансировка | Отказоустойчивость | Требования |
| :--- | :--- | :--- | :--- | :--- |
| mode=0 | balance-rr | Round-robin | Да | Коммутатор:EtherChannel |
| mode=1 | active-backup | Нет (один активный) | Да | Нет особых |
| mode=2 | balance-xor | XOR hash | Да | EtherChannel/static |
| mode=3 | broadcast | Broadcast | Да | Нет особых |
| mode=4 | **802.3ad (LACP)** | L3/L4 XOR hash | Да | **LACP на коммутаторе** |
| mode=5 | balance-tlb | TX hash + RX adapt | Да | driver support |
| mode=6 | balance-alb | TX+RX adapt | Да | driver support |

> **Подробности:** [Агрегация каналов (Link Aggregation)](../Concepts/link_aggregation.md).

### Energy Efficient Ethernet (EEE, IEEE 802.3az)

Технология энергосбережения, переводящая интерфейс в режим низкого энергопотребления при отсутствии трафика.

**Принцип работы:**
1. При отсутствии трафика NIC отправляет **LPI (Low Power Idle)** сигнал.
2. Соседний интерфейс переходит в режим сна.
3. При появлении трафика NIC выходит из LPI за микросекунды.

**Проблемы:**
- Задержка «пробуждения» (wake-up latency) может вызывать пакетные потери.
- На загруженных серверах EEE бесполезен и вызывает нестабильность.
- Некоторые коммутаторы/ NIC работают с EEE некорректно — вызывают флапы.

```bash
# Просмотр поддержки EEE
ethtool --show-eee eth0
# → EEE settings for eth0:
# →   EEE status: enabled
# →   Tx LPI: 100 (usec)

# Отключение EEE (при проблемах)
sudo ethtool --set-eee eth0 eee off
```

### Подуровни канального уровня: LLC и MAC

Канальный уровень в стандартах IEEE 802 разделен на два подуровня:

1. **LLC (Logical Link Control — управление логическим каналом, IEEE 802.2):** Верхний подуровень.
   - Обеспечивает единый интерфейс для сетевого уровня (L3) независимо от физики.
   - Выполняет мультиплексирование протоколов (через поле SAP или SNAP).
2. **MAC (Media Access Control — управление доступом к среде):** Нижний подуровень.
   - Отвечает за физическую адресацию (**[MAC-адреса](../Concepts/mac_address.md)**).
   - Управляет доступом к физическому каналу (CSMA/CD или Full Duplex).
   - Формирует кадры и проверяет контрольную сумму (FCS).

### Управление доступом к среде: CSMA/CD

В классическом Ethernet с общей разделяемой средой используется метод **CSMA/CD (Carrier Sense Multiple Access with Collision Detection — множественный доступ с контролем несущей и обнаружением коллизий)**.

#### Алгоритм работы

1. **Carrier Sense (Контроль несущей):** Устройство слушает среду. Если она занята — ждет освобождения.
2. **Multiple Access (Множественный доступ):** Если среда свободна — начинает передачу кадра.
3. **Collision Detection (Обнаружение коллизий):** Во время передачи устройство продолжает слушать среду. Если сигналы накладываются (коллизия):
    - Передача прекращается, отправляется **JAM-сигнал** для оповещения всех узлов.
    - Устройство выдерживает случайную паузу (алгоритм экспоненциальной отсрочки) и повторяет попытку.

**Важно:** Коллизии возможны только при **полудуплексном (half-duplex)** режиме. В современных сетях с коммутаторами используется **полнодуплексный (full-duplex)** режим, где коллизии физически невозможны.

### Формирование кадров (Framing)

На физическом уровне кадр Ethernet дополняется служебными полями для синхронизации приемника и передатчика.

#### Структура пакета на физическом уровне (L1)

1. **Preamble (7 байт):** Чередующиеся биты `10101010`. Позволяет приемнику синхронизировать тактовую частоту.
2. **SFD (Start Frame Delimiter, 1 байт):** Последовательность `10101011`. Сигнализирует о начале собственно кадра канального уровня.
3. **Ethernet Frame (L2):** Данные (см. формат кадра ниже).
4. **IPG (Interpacket Gap, 12 байт / 96 бит):** Обязательная пауза между пакетами.

#### Wake-on-LAN (WoL)

Технология включения компьютера по сети.
- **Magic Packet:** Специальный кадр Ethernet, содержащий 6 байт `FF` и 16 повторений MAC-адреса целевого узла.
- **Работа:** Сетевая карта (NIC) продолжает получать питание в спящем режиме и "слушает" среду в ожидании Magic Packet. При его получении подается сигнал на включение (через шину PCIe или разъем WOL).

### Формат кадра Ethernet II (DIX)

Это наиболее распространенный формат кадра в современных сетях.

#### Структура кадра (L2)

| Поле | Размер | Описание |
| :--- | :--- | :--- |
| **Destination MAC** | 6 байт | Адрес получателя |
| **Source MAC** | 6 байт | Адрес отправителя |
| **EtherType** | 2 байта | Тип протокола L3 (например, 0x0800 для IPv4) |
| **Payload** | 46–1500 байт | Полезная нагрузка — **MTU (Maximum Transmission Unit)** |
| **FCS** | 4 байта | Контрольная сумма — **CRC (Cyclic Redundancy Check)** |

**Минимальный размер:** Если данных меньше 46 байт, добавляется дополнение (padding) до достижения минимальной длины кадра в 64 байта.

**Jumbo Frames:** Кадры с полезной нагрузкой до 9000 байт, используемые в высокопроизводительных сетях для снижения нагрузки на процессор.

## Практические сценарии

### Механизмы согласования и управления потоком

#### Автосогласование (Auto-negotiation, IEEE 802.3u)
Процесс выбора максимальной поддерживаемой скорости и дуплекса между двумя узлами.
- **Приоритет:** 100G > 40G > 10G > 1G > 100M. Full Duplex всегда предпочтительнее Half Duplex.
- **Duplex Mismatch:** Ошибка, при которой один конец настроен вручную (Full), а другой в Auto (падает в Half). Приводит к огромному количеству коллизий и CRC-ошибок. **Рекомендация:** всегда использовать `Auto` на обоих концах.

#### Flow Control (IEEE 802.3x)
Механизм предотвращения потерь пакетов при переполнении буферов приемника.
- **Pause Frames:** Приемник отправляет специальный кадр "PAUSE", заставляя передатчик приостановить отправку на несколько миллисекунд.
- **Минус:** Может вызывать эффект "разлива" заторов (Congestion Spreading) в сложных топологиях. В современных ЦОД чаще заменяется на **PFC (Priority-based Flow Control)** в рамках RoCE/iSCSI.

### Диагностика проблем L2

#### Общая таблица диагностики

| Проблема | Симптомы | Диагностика (Linux) | Диагностика (Cisco) | Решение |
| :--- | :--- | :--- | :--- | :--- |
| **Duplex Mismatch** | Высокие коллизии, CRC, низкий throughput | `ethtool eth0` — проверить Duplex | `show interfaces Gi0/1` — Half/Full | Включить Auto на обоих концах |
| **CRC Errors** | Пакеты отброшены, ретрансмиссии | `ethtool -S eth0 \| grep crc` | `show interfaces counters errors` | Заменить кабель, проверить разъем |
| **Dropped Packets** | Потеря пакетов, low throughput | `ethtool -S eth0 \| grep drop` | `show interfaces counters` | Увеличить ring buffer, offloading |
| **Speed/Duplex Mismatch** | Нет связи или низкая скорость | `ethtool eth0` | `show interfaces Gi0/1` | Синхронизировать настройки |
| **MTU Mismatch** | SSH работает, файлы нет | `ping -M do -s 1472 <ip>` | `ping size 1472 <ip>` | Согласовать MTU на всех линках |
| **Flapping** | Интерmittent connectivity | `ip monitor link` / `journalctl -k` | `show interfaces \| include line protocol` | Проверить кабель, SFP, STP |

#### Детальная диагностика (Linux)

```bash
# 1. Проверка состояния интерфейса
ip -s link show eth0
# → RX:  bytes=... errors=... dropped=... overrun=... mcast=...
# → TX:  bytes=... errors=... dropped=... carrier=... collsns=...

# 2. Подробная статистика NIC
ethtool -S eth0
# → key-indicative counters:
# →   rx_crc_errors: 0        ← ошибки контрольной суммы
# →   rx_missed_errors: 0     ← пакеты, потерянные NIC
# →   rx_fifo_errors: 0       ← переполнение FIFO
# →   tx_fifo_errors: 0       ← переполнение TX FIFO
# →   rx_length_errors: 0     ← некорректная длина кадра
# →   rx_frame_errors: 0      ← ошибки выравнивания

# 3. Проверка физического уровня
ethtool eth0
# → Speed: 10000Mb/s
# → Duplex: Full
# → Auto-negotiation: on
# → Link detected: yes

# 4. Уровни сигнала (оптика, DOM)
ethtool -m eth0
# →   RX power: -3.2 dBm (норма: -18...-3 dBm)
# →   TX power: -2.1 dBm
# →   Temperature: 45 C

# 5. Захват трафика для анализа L2
sudo tcpdump -i eth0 -e -vv -c 100
# → Показывает MAC-адреса, EtherType, VLAN tags, 802.1Q

# 6. Проверка ARP-таблицы (L2/L3 связность)
ip neigh show dev eth0
# → 192.168.1.1 lladdr 00:11:22:33:44:55 REACHABLE

# 7. Мониторинг ошибок в реальном времени
watch -n 1 'ethtool -S eth0 | grep -E "error|drop|crc|missed"'
```

#### Детальная диагностика (Cisco)

```bash
# 1. Состояние интерфейса
show interfaces GigabitEthernet0/1
# → GigabitEthernet0/1 is up, line protocol is up (connected)
# →   Full-duplex, 1000Mb/s, media type is RJ45
# →   input rate 1.2 Mbps, output rate 500 Kbps

# 2. Ошибки и статистика
show interfaces GigabitEthernet0/1 counters errors
# →   CRC: 0
# →   giants: 0
# →   runts: 0
# →   input errors: 0

# 3. Трансивер (оптика)
show interfaces GigabitEthernet0/1 transceiver
# →   rxPower: -4.2 dBm
# →   txPower: -2.8 dBm
# →   Temperature: 42 C

# 4. MAC-таблица (CAM)
show mac address-table interface GigabitEthernet0/1
# →   Vlan    Mac Address       Type        Ports
# →   10      aabb.ccdd.0011    DYNAMIC     Gi0/1

# 5. ARP-таблица
show arp | include GigabitEthernet0/1

# 6. Статистика VLAN
show vlan brief
show interfaces trunk
```

#### LED-индикация на коммутаторах

| Состояние LED | Значение | Действие |
| :--- | :--- | :--- |
| **Зеленый (постоянный)** | Связь установлена | Норма |
| **Зеленый (мигающий)** | Активность (передача/приём) | Норма |
| **Желтый/Оранжевый** | Скорость 10/100 Mbps (не 1G+) | Проверить категорию кабеля |
| **Красный** | Ошибка / Disabled | `show interfaces`, проверить STP |
| **Выключен** | Нет связи | Физическая проблема, проверить кабель |
| **Амбер (мигающий)** | Число ошибок превышает порог | `show interfaces counters errors` |

### Оптимизация производительности NIC в Linux

В высоконагруженных системах (High Load) стандартных настроек Ethernet недостаточно.

#### 1. NAPI (New API)
Механизм ядра Linux, уменьшающий количество прерываний от сетевой карты. Вместо того чтобы генерировать прерывание на каждый пакет, NIC переходит в режим опроса (polling), обрабатывая пакеты пачками.

#### 2. Ring Buffers (Кольцевые буферы)
Область памяти в сетевой карте для временного хранения входящих/исходящих кадров.
```bash
# Просмотр текущего размера буферов
ethtool -g eth0
# → Ring parameters for eth0:
# → Pre-set maxes:
# →   RX:     4096
# →   TX:     4096
# → Current:
# →   RX:     256
# →   TX:     256

# Увеличение буферов до максимума для предотвращения дропов (rx drops)
sudo ethtool -G eth0 rx 4096 tx 4096

# Проверка дропов
ethtool -S eth0 | grep drop
# → rx_missed_errors: 0
# → tx_dropped: 0
```

#### 3. Offloading (Разгрузка CPU)
Перенос части вычислений на сетевой адаптер:
- **TSO (TCP Segmentation Offload):** NIC сам делит большие пакеты на сегменты MTU.
- **LRO/GRO (Generic Receive Offload):** Объединение мелких входящих пакетов в один большой перед передачей в стек ядра.
- **HW Checksumming:** Аппаратная проверка контрольной суммы TCP/UDP.

```bash
# Просмотр текущих offload-ов
ethtool -k eth0
# → Features for eth0:
# →   rx-checksumming: on
# →   tx-checksumming: on
# →   tcp-segmentation-offload: on
# →   generic-receive-offload: on

# Отключение TSO (при проблемах)
sudo ethtool -K eth0 tso off

# Включение GRO
sudo ethtool -K eth0 gro on
```

#### 4. RSS (Receive Side Scaling)
Распределение входящих пакетов по CPU-ядрам через хеширование. Позволяет NIC использовать несколько ядер для обработки сетевого трафика.

```bash
# Просмотр настроек RSS
ethtool -x eth0
# → RX flow hash indirection table for eth0 with 8 queue(s):
# →   0:  0  1  2  3  4  5  6  7

# Изменение количества очередей
sudo ethtool -L eth0 combined 8

# Просмотр распределения по ядрам
cat /proc/interrupts | grep eth0
```

#### 5. XPS (Transmit Packet Steering)
Приоритетная привязка TX-очередей к конкретным CPU-ядрам для уменьшения межпроцессорного трафика.

```bash
# Настройка XPS через sysfs
# Привязка TX queue 0 к CPU 0, queue 1 к CPU 1
echo 1 | sudo tee /sys/class/net/eth0/queues/tx-0/xps_cpus
echo 2 | sudo tee /sys/class/net/eth0/queues/tx-1/xps_cpus
```

#### 6. Interrupt Coalescing
Группировка прерываний для уменьшения нагрузки на CPU. NIC выдерживает паузу перед отправкой прерывания, накапливая пакеты.

```bash
# Просмотр текущих настроек
ethtool -c eth0
# → Coalesce parameters for eth0:
# →   rx-usecs: 3
# →   tx-usecs: 3

# Настройка (микросекунды)
sudo ethtool -C eth0 rx-usecs 10 tx-usecs 10 rx-frames 128 tx-frames 128
```

### Конфигурация портов коммутатора

#### Access-порт (подключение конечных устройств)

**Cisco IOS:**
```bash
Switch(config)# interface GigabitEthernet0/1
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 10
Switch(config-if)# spanning-tree portfast
Switch(config-if)# spanning-tree bpduguard enable
Switch(config-if)# description Server-Web01
```

**Juniper Junos:**
```bash
set interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members VLAN10
```

#### Trunk-порт (межкоммутаторное соединение)

**Cisco IOS:**
```bash
Switch(config)# interface GigabitEthernet0/24
Switch(config-if)# switchport mode trunk
Switch(config-if)# switchport trunk allowed vlan 10,20,30
Switch(config-if)# switchport trunk native vlan 999
Switch(config-if)# switchport nonegotiate
Switch(config-if)# description Trunk-to-SW02
```

**Juniper Junos:**
```bash
set interfaces ge-0/0/23 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/23 unit 0 family ethernet-switching vlan members [ VLAN10 VLAN20 VLAN30 ]
```

#### Diagnostic VLAN и port security

```bash
# Cisco — проверка состояния порта
show interface status
show interface Gi0/1 switchport
show vlan brief

# Cisco — port security
Switch(config)# interface GigabitEthernet0/1
Switch(config-if)# switchport port-security
Switch(config-if)# switchport port-security maximum 2
Switch(config-if)# switchport port-security violation restrict
Switch(config-if)# switchport port-security mac-address sticky
```

### Флап порта (Port Flapping)

**Флап (flap)** — циклический переход порта между состояниями up и down. Для STP каждое такое событие — topology change, пересчёт дерева и временная потеря связности. Даже один флапающий порт на загруженной сети создаёт заметные проблемы.

**Причины флапов:**
- **Физические:** Повреждённый кабель, разболтанный коннектор, неисправный SFP-модуль, электромагнитные помехи.
- **Программные:** Некорректная настройка EEE (802.3az), STP-проблемы, конфликты speed/duplex.
- **Аппаратные:** Неисправный порт коммутатора, проблема с PHY-чипом NIC.

#### Обнаружение

**Cisco:**

```cisco
show interfaces | include line protocol|changes
show interfaces counters errors
```

Порт с аномально высоким `Link-state change count` — источник проблемы.

**Linux:**

```bash
# Мониторинг в реальном времени
ip monitor link

# История флапов с таймстампами
journalctl -k | grep "NIC Link"

# Проверка ethtool
ethtool eth0 | grep "Link detected"
```

#### Физические причины

Типичные источники: повреждённый кабель, разболтанный коннектор, неисправный SFP-модуль. Для оптики проверяется уровень сигнала:

```bash
# Cisco
show interfaces Gi0/1 transceiver

# Linux (требует ethtool)
sudo ethtool -m eth0
# →   RX power: -3.2 dBm
# →   TX power: -2.1 dBm
# →   Temperature: 45 C
```

Критический показатель — `rx_power`. Если значение плавает или ниже допустимого порога — проблема в оптике или трансивере.

#### Программные причины

Если физический уровень чист, причина может быть в STP или неверной настройке Energy Efficient Ethernet (EEE).
- **EEE (IEEE 802.3az):** Переводит интерфейс в режим низкого энергопотребления при отсутствии трафика. Может вызывать задержки при "пробуждении" и в некоторых случаях — флапы.

```bash
# Отключение EEE в Linux при подозрениях на флапы
sudo ethtool --set-eee eth0 eee off
```

#### Защита от флапов (Port Error Disable)

**Cisco:**
```bash
# Включение errdisable для flap detection
Switch(config)# errdisable recovery cause link-flap
Switch(config)# errdisable recovery interval 300

# BPDU Guard на access-портах (защита от петли)
Switch(config)# interface range GigabitEthernet0/1-24
Switch(config-if-range)# spanning-tree bpduguard enable

# Storm Control (ограничение broadcast/multicast)
Switch(config-if)# storm-control broadcast level 10
Switch(config-if)# storm-control action shutdown
```

## Рекомендации по проектированию (Best Practices)

### Кабельная инфраструктура

1. **Соответствие категорий:** Используйте Cat6a для 10G-линий, Cat5e для 1G. Не смешивайте категории в одном линке.
2. **Длина:** Максимум 100 м для медных кабелей. Для 40GBASE-T (Cat8) — до 30 м.
3. **Маркировка:** Все кабели должны быть промаркированы с обоих концов. Используйте ленточную печать или термоусадку.
4. **Тестирование:** После прокладки выполняйте сертификационное тестирование (Fluke DTX/DSX). Проверяйте NEXT, Return Loss, Insertion Loss.
5. **Управление кабелями:** Используйте кабель-менеджменты, velcro-стяжки (не пластиковые хомуты — они повреждают кабели).

### Оптоволокно

1. **Тип волокна:** SMF (9 мкм) для расстояний >500 м, MMF (50 мкм) для внутри-зданий.
2. **Чистота разъемов:** Используйте лазерный микроскоп для проверки LC/MPO разъемов. Загрязнение — причина #1 потерь сигнала.
3. **Избегайте изгибов:** Минимальный радиус изгиба — 10x диаметр кабеля. Нарушение = потери.

### Производительность NIC

1. **Ring Buffers:** Увеличивайте до максимума на серверах с высокой нагрузкой.
2. **RSS:** Включайте на многоядерных серверах. Количество очередей = количество ядер (или до 16).
3. **Interrupt Coalescing:** Начинайте с `rx-usecs=3`, увеличивайте при высокой нагрузке.
4. **Offloading:** Включайте TSO, GRO, HW Checksumming по умолчанию.
5. **MTU:** Используйте Jumbo Frames (9000) в ЦОД для storage и кластеров. Согласовывайте на всех линках.

### Безопасность портов

1. **BPDU Guard:** На access-портах — всегда. Предотвращает петли от несанкционированных коммутаторов.
2. **Port Security:** Ограничивайте количество MAC-адресов на порту.
3. **DHCP Snooping:** Предотвращает rouge DHCP-серверы.
4. **Dynamic ARP Inspection (DAI):** Защита от ARP-спуфинга.
5. **802.1X:** Аутентификация устройств перед допуском к сети.

### Мониторинг

1. **SNMP:** Мониторинг интерфейсов, ошибок, utilization.
2. **NetFlow/sFlow:** Анализ трафика, выявление аномалий.
3. **Alerting:** Настройте алерты на: >1% packet loss, >80% utilization,CRC errors, link flaps.
4. **Захват трафика:** tcpdump/Wireshark для deep-dive диагностики.

## Дополнительная информация

### Связанные концепции

- **[MAC-адрес (Media Access Control)](../Concepts/mac_address.md)** — подробное описание физической адресации.
- **[Multicast и IGMP Snooping](./multicast.md)** — оптимизация групповой рассылки в Ethernet-сетях.
- **[VLAN (Virtual Local Area Network)](./vlan.md)** — виртуальные локальные сети и тегирование кадров (802.1Q).
- **[ARP (Address Resolution Protocol)](./arp.md)** — протокол разрешения IP-адресов в MAC-адреса.
- **[Агрегация каналов (Link Aggregation)](../Concepts/link_aggregation.md)** — LACP, Bonding, Port Channel.

### Ссылки и ресурсы

- [IEEE 802.3 Working Group](https://www.ieee802.org/3/) — официальная страница стандартов.
- [Wireshark Wiki: Ethernet](https://gitlab.com/wireshark/wireshark/-/wikis/Ethernet) — детали реализации и анализа трафика.
