# LLDP — протокол обнаружения канального уровня

## Определения

**LLDP (Link Layer Discovery Protocol)** — открытый стандарт протокола канального уровня (L2), позволяющий сетевым устройствам анонсировать информацию о себе (имя, модель, возможности, порт подключения) своим соседям в локальном сегменте сети. Описан в стандарте **IEEE 802.1AB**.

**LLDP-ADU (LLDP Agent Data Unit)** — единица данных LLDP, состоящая из набора TLV-структур.

**TLV (Type-Length-Value)** — формат кодирования данных, где указывается тип параметра, его длина и значение.

> **Важно:** LLDP работает только между непосредственно подключенными устройствами (Point-to-Point) и не маршрутизируется. Он является вендоронезависимой альтернативой проприетарному протоколу **CDP (Cisco Discovery Protocol)**.

> **См. также:** [Модель OSI](../OSI_TCP_IP_Model/osi_model.md), [Ethernet](./ethernet.md), [VLAN](./vlan.md)

## Основные концепции

### Назначение LLDP

LLDP используется для автоматического построения топологии сети, инвентаризации и диагностики физических подключений. С его помощью администратор может узнать, к какому порту коммутатора подключен сервер, не заходя в серверную.

**Типичные сценарии применения:**
- Автоматическое обнаружение соседнего оборудования (топология L2).
- Инвентаризация дата-центра: сервер автоматически сообщает коммутатору модель, имя, VLAN.
- Диагностика физических подключений: «Какой порт коммутатора подключен к этому серверу?»
- Автоматическая настройка Voice VLAN и QoS для IP-телефонов (LLDP-MED).
- Согласование PoE-мощности между PSE (Power Sourcing Equipment) и PD (Powered Device).
- Интеграция с системами управления сетью (SNMP, IPAM, CMDB) для построения топологии.

### Структура кадра LLDP

LLDP-кадр инкапсулируется непосредственно в Ethernet-фрейм с EtherType `0x88cc`. Нет IP- или TCP/UDP-заголовка — протокол работает на L2.

```
Ethernet Frame (LLDP)
├── Preamble (7 байт)
├── SFD (1 байт, 0xD5)
├── Destination MAC: 01:80:c2:00:00:0e (LLDP Multicast)
├── Source MAC: MAC-адрес отправителя
├── EtherType: 0x88cc (LLDP)
├── Payload: LLDPDU (Sequence of TLVs)
│   ├── TLV 1: Chassis ID (Type 1, Mandatory)
│   ├── TLV 2: Port ID (Type 2, Mandatory)
│   ├── TLV 3: Time To Live (Type 3, Mandatory)
│   ├── TLV 4+: Optional TLVs...
│   └── TLV 0: End of LLDPDU (Type 0, Mandatory)
└── FCS (4 байта)
```

**Ключевые параметры Ethernet-кадра LLDP:**
- **Destination MAC:** `01:80:c2:00:00:0e` — зарезервированный мультикаст-адрес для LLDP (не маршрутизируется, не пересылается через мосты/коммутаторыeyond пределов сегмента).
- **EtherType:** `0x88cc` — уникальный идентификатор LLDP в Ethernet.
- **VLAN-tagged:** LLDP-кадры могут быть тегированы (с VLAN tag 802.1Q), но по умолчанию передаются без тега в native VLAN.

### Механизм работы

1. **Анонсирование:** устройство периодически рассылает LLDPDU на мультикаст-адрес `01:80:c2:00:00:0e`.
2. **Сбор данных:** соседи принимают кадры и сохраняют информацию в свою MIB (Management Information Base).
3. **Хранение:** данные хранятся в течение TTL, указанного в пакете. Если новые данные не приходят, запись удаляется.
4. **Обновление:** при изменении информации (например, смена имени порта) устройство отправляет обновленный LLDPDU с новым TTL.

#### Таймеры и интервалы

| Таймер | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **msgTxInterval** | 30 секунд | Интервал между периодическими LLDPDU (Transmit delay) |
| **msgFastInterval** | 1 секунда | Интервал быстрой отправки (при первом обнаружении или изменении) |
| **reinitDelay** | 1–2 секунды | Задержка перед повторной инициализацией LLDP-агента |
| **msgTxHold** | 4 | Множитель для TTL: TTL = msgTxHold × msgTxInterval (4 × 30 = 120 сек) |
| **TTL** | 120 секунд | Время жизни информации у соседа (по умолчанию) |

**Процесс обнаружения:**
1. Устройство впервые подключено к сети → отправляет LLDPDU с `msgFastInterval` (1 сек).
2. После первого ответа соседа переключается на `msgTxInterval` (30 сек).
3. Если сосед пропал — запись удаляется через TTL (120 сек).

### Структура TLV (Type-Length-Value)

LLDPDU представляет собой последовательность TLV-блоков. Формат заголовка TLV:
- **Type (7 бит):** определяет тип информации (0–127).
- **Length (9 бит):** длина поля Value в байтах (0–511).
- **Value (0–511 байт):** полезная нагрузка.

#### Обязательные TLV (Mandatory)

| TLV | Type | Размер | Описание |
| :--- | :--- | :--- | :--- |
| **End of LLDPDU** | 0 | 0 | Маркер конца пакета (обязателен в конце каждого LLDPDU) |
| **Chassis ID** | 1 | 1–255 | Уникальный ID отправителя (обычно MAC-адрес, но может быть SNMP OID, IP или серийный номер) |
| **Port ID** | 2 | 1–255 | Идентификатор порта отправителя (имя интерфейса, MAC-адрес порта или числовое значение) |
| **Time To Live** | 3 | 2 | Время актуальности информации у соседа в секундах (обычно 120) |

**Формат Chassis ID:**
| Subtype | Значение | Описание |
| :--- | :--- | :--- |
| 1 | MAC Address | 6 байт MAC-адреса |
| 2 | Network Address | IP-адрес (IPv4/IPv6) |
| 3 | Interface Name | Имя интерфейса (например, "GigabitEthernet0/1") |
| 4 | Port Address | MAC-адрес порта |
| 5 | SNMP OID | SNMP Object Identifier |

#### Важные опциональные TLV

| TLV | Type | Описание |
| :--- | :--- | :--- |
| **Port Description** | 4 | Человекочитаемое описание порта (например, "Server-Rack-1 Uplink") |
| **System Name** | 5 | Имя системы (hostname) |
| **System Description** | 6 | Описание системы (модель, версия ОС) |
| **System Capabilities** | 7 | Битовая маска функций: Bridge, Router, Station, WLAN AP, Telephone, DOCSIS, Other |
| **Management Address** | 8 | IP-адрес для удаленного управления (IPv4/IPv6) |
| **Organizationally Specific** | 127 | Вендор-специфичные TLV (PoE, VLAN, DCBX, и др.) |

**Суб-типы System Capabilities (битовая маска):**
| Бит | Назначение | Пример |
| :--- | :--- | :--- |
| 1 | Repeater | Повторитель (хаб) |
| 2 | Bridge | Коммутатор (L2) |
| 4 | WLAN Access Point | Точка доступа Wi-Fi |
| 8 | Router | Маршрутизатор (L3) |
| 16 | Telephone | IP-телефон |
| 32 | DOCSIS Cable Device | Кабельный модем |
| 64 | Station Only | Конечная станция (ПК, сервер) |

#### Organizationally Specific TLV (Type 127)

Эти TLV позволяют вендорам и стандартным организациям добавлять расширенную информацию:

| Организация | OUI | TLV Subtype | Описание |
| :--- | :--- | :--- | :--- |
| **IEEE 802.1** | 00:80:c2 | 1 | Port VLAN ID (PVID) |
| **IEEE 802.1** | 00:80:c2 | 2 | Protocol VLAN ID |
| **IEEE 802.1** | 00:80:c2 | 3 | VLAN Name |
| **IEEE 802.1** | 00:80:c2 | 4 | Protocol Identity |
| **IEEE 802.3** | 00:12:0f | 1 | MAC/PHY Configuration (auto-negotiation, speed, duplex) |
| **IEEE 802.3** | 00:12:0f | 2 | Power via MDI (PoE: class, power, PSE/PD status) |
| **IEEE 802.3** | 00:12:0f | 3 | Link Aggregation |
| **IEEE 802.3** | 00:12:0f | 4 | Maximum Frame Size (MTU) |
| **TIA LLDP-MED** | 00:12:bb | 1 | LLDP-MED Capabilities |
| **TIA LLDP-MED** | 00:12:bb | 2 | Network Policy (Voice VLAN, QoS) |
| **TIA LLDP-MED** | 00:12:bb | 3 | Location Identification |
| **TIA LLDP-MED** | 00:12:bb | 4 | Extended Power via MDI |
| **TIA LLDP-MED** | 00:12:bb | 5 | Inventory (Hardware/Firmware/Software) |
| **DCBX (CEE)** | 00:12:bb | 1 | Data Center Bridging Exchange (PFC/ETS) |

### Безопасность и риски

LLDP — это протокол, основанный на полном доверии.
1. **Сбор информации (Reconnaissance):** Злоумышленник, подключившись к порту, может мгновенно узнать имя коммутатора, модель ОС и структуру управления сетью.
2. **LLDP Poisoning:** Подделка LLDP-пакетов может привести к ошибкам в системах мониторинга топологии и неправильной автоматической настройке VLAN/QoS.
3. **Атака на LLDP-MED:** Злоумышленник может отправить поддельный LLDP-MED-пакет с неправильной Voice VLAN, заставив IP-телефон подключиться к враждебному VLAN.
4. **Рекомендации по защите:**
   - Отключайте LLDP на портах, смотрящих в сторону публичных зон или небезопасных клиентов.
   - Используйте `lldp transmit` / `lldp receive` для избирательного включения на конкретных портах.
   - На Cisco: `no lldp run` для глобального отключения; `no lldp transmit` / `no lldp receive` для отдельных портов.
   - Мониторинг: настройте алерты на появление новых LLDP-соседей в неожиданных сегментах.

## Практические сценарии (Linux)

В Linux наиболее распространенной реализацией является демон **lldpd**.

### 1. Установка и запуск

По умолчанию `lldpd` не установлен в большинстве дистрибутивов.

```bash
# Установка (Debian/Ubuntu)
sudo apt update && sudo apt install lldpd -y

# Запуск и добавление в автозагрузку
sudo systemctl enable --now lldpd
```

### 2. Настройка через systemd-networkd

Современный способ включения LLDP на серверах без установки дополнительных демонов.

#### Базовая конфигурация

```ini
# /etc/systemd/network/20-eth0.network
[Match]
Name=eth0

[Network]
# Принимать LLDP от соседей
LLDP=yes
# Рассылать информацию о себе
EmitLLDP=yes
```

#### Значения параметра EmitLLDP

| Значение | Описание |
| :--- | :--- |
| `no` | LLDP не отправляется (по умолчанию) |
| `yes` | Отправка LLDP на всех интерфейсах |
| `nearest-neighbor` | Отправка на multicast `01:80:c2:00:00:0e` (только ближайший сосед) |
| `customer-bridge` | Отправка на `01:80:c2:00:00:03` (для customer bridging, IEEE 802.1AB) |
| `customer-vlan-bridge` | Отправка на `01:80:c2:00:00:03` (для VLAN-aware bridge) |

#### Типичные сценарии

```ini
# /etc/systemd/network/10-bond0.network (aggregate link)
[Match]
Name=bond0

[Network]
LLDP=yes
EmitLLDP=nearest-neighbor
# Для bond — LLDP анонсирует информацию о виртуальном интерфейсе

# /etc/systemd/network/30-bridge0.network (bridge)
[Match]
Name=bridge0

[Network]
LLDP=yes
EmitLLDP=customer-bridge

# Для VLAN-aware bridge (dot1q)
# EmitLLDP=customer-vlan-bridge
```

#### Просмотр соседей через systemd-networkd

```bash
# Просмотр LLDP-соседей (если lldpd не установлен)
networkctl lldp

# Или через networkctl
networkctl status eth0 | grep -i lldp
```

**Пример вывода networkctl lldp:**
```text
LINK              LLDP   NEIGHBORS
eth0              on     sw-core-01 (00:11:22:33:44:55), port GigabitEthernet0/1
eth1              on     sw-access-01 (aa:bb:cc:dd:ee:ff), port FastEthernet0/24
```

### 3. Работа с виртуальными интерфейсами (Bonding/Bridging)

#### Bonding

- **Рекомендация:** LLDP должен быть включен на **физических** интерфейсах (slave), а не на интерфейсе `bond0`. Это позволяет видеть, к каким портам коммутатора подключен каждый линк агрегации.
- **Поведение:** Если LLDP включен на `bond0`, пакеты отправляются через один slave (-dependent от режима bonding). Для полной видимости — LLDP на каждом slave-интерфейсе.
- **LACP и LLDP:** LLDP не конфликтует с LACP (802.3ad). LACP работает с Link Aggregation Group, а LLDP — с физическими портами. Используйте оба протокола.

```bash
# Пример: включить LLDP на slave-интерфейсах bond0
# /etc/systemd/network/25-bond0-slave.link
[Match]
MACAddress=aa:bb:cc:dd:ee:ff

[Link]
Name=bond0

# /etc/systemd/network/20-eth0.network (slave)
[Match]
Name=eth0

[Network]
LLDP=yes
EmitLLDP=nearest-neighbor
Bond=bond0
```

#### Bridging

- **Поведение:** Если физический интерфейс является частью моста (`br0`), демон `lldpd` автоматически "слушает" на нем трафик.
- **STP взаимодействие:** Если на коммутаторе включен STP, мультикаст LLDP может блокироваться или обрабатываться нестандартно (особенно на порту `designated` vs `root`).
- **VLAN-aware bridge:** Для bridge с поддержкой 802.1Q используйте `EmitLLDP=customer-vlan-bridge`.

```bash
# Проверка, что LLDP работает на порту моста
bridge fdb show | grep 01:80:c2:00:00:0e
# → 01:80:c2:00:00:0e dev eth0 master br0

# Просмотр LLDP через bridge-интерфейс
lldpcli show neighbors | grep -A5 "br0"
```

### 4. Просмотр соседей (lldpcli)

Для взаимодействия с демоном `lldpd` используется утилита `lldpcli`.

```bash
# Краткий список соседей
lldpcli show neighbors

# Подробная информация (включая возможности и порты)
lldpcli show neighbors details

# Мониторинг появления/исчезновения соседей в реальном времени
lldpcli watch

# Просмотр информации о конкретном интерфейсе
lldpcli show neighbors interface eth0

# Просмотр информации о локальном устройстве
lldpcli show chassis

# Просмотр 정보 о портах
lldpcli show ports
```

**Пример вывода `lldpcli show neighbors details`:**
```text
Interface:    eth0, via: LLDP, RID: 1, Time: 0 day, 00:01:23
  Chassis:     
    ChassisID: mac 00:11:22:33:44:55
    SysName:   sw-core-01
    SysDescr:  Cisco IOS Software, C2960 Software, Version 15.0(2)SE7
    MgmtIP:    192.168.1.254
    Capability: Bridge, enabled
    Capability: Router, enabled
  Port:        
    PortID:    ifname GigabitEthernet0/1
    PortDescr: Uplink to Server-Rack-1
    PortMAC:   00:11:22:33:44:55
  VLANS:       
    VLAN:      100 (untagged)
  Unknown TLVs:
    OUI:       IEEE 802.3, subtype: 2
      Power:   MDI Power: supported, enabled, PSE, 25.5W
```

**Пример вывода `lldpcli show chassis`:**
```text
Chassis:
  ChassisID:    mac 00:aa:bb:cc:dd:ee
  SysName:      server-rack-1-node-01
  SysDescr:     Ubuntu 22.04.3 LTS, Linux 5.15.0-91-generic
  MgmtIP:       10.0.1.100
  Capability:   Station, enabled
```

### 5. Диагностика с lldptool

Утилита `lldptool` является частью пакета `lldpd` и предоставляет более детальный контроль:

```bash
# Просмотр соседей-информации (кратко)
lldptool -n -i eth0

# Просмотр соседей-информации (детально)
lldptool -n -i eth0 -t

# Просмотр локальной информации
lldptool -i eth0 -S

# Просмотр информации о TLV
lldptool -T -i eth0 -V portdesc

# Просмотр LLDP-MED информации
lldptool -T -i eth0 -V medpower

# Просмотр IEEE 802.3 PoE-информации
lldptool -T -i eth0 -V power

# Просмотр VLAN-информации
lldptool -T -i eth0 -V vlan

# Включение/выключение LLDP на интерфейсе
lldptool -I eth0 -d disable
lldptool -I eth0 -d enable

# Просмотр статистики
lldptool -S -i eth0
```

### 6. Диагностика без демона (tcpdump)

Если демон не установлен, можно перехватить LLDP-кадры напрямую (EtherType `0x88cc`).

```bash
# Захват LLDP-фреймов на интерфейсе eth0
sudo tcpdump -i eth0 -nn -v ether proto 0x88cc

# Захват с увеличенным количеством данных
sudo tcpdump -i eth0 -nn -X -s 0 ether proto 0x88cc

# Фильтрация по мультикаст-адресу назначения
sudo tcpdump -i eth0 -nn ether dst 01:80:c2:00:00:0e

# Сохранение в файл для анализа
sudo tcpdump -i eth0 -nn -w lldp.pcap ether proto 0x88cc
```

**Пример вывода tcpdump:**
```text
12:34:56.789012 00:11:22:33:44:55 > 01:80:c2:00:00:0e, ethertype LLDP (0x88cc), length 114:
  TLV Type: Chassis ID (1), Length: 7, Subtype: MAC (1): 00:11:22:33:44:55
  TLV Type: Port ID (2), Length: 19, Subtype: Interface Name (3): GigabitEthernet0/1
  TLV Type: TTL (3), Length: 2, TTL: 120 sec
  TLV Type: System Name (5), Length: 14: sw-core-01
  TLV Type: System Description (6), Length: 51: Cisco IOS Software, C2960...
  TLV Type: Management Address (8), Length: 12: IPv4 192.168.1.254
  TLV Type: End (0), Length: 0
```

### 7. Настройка на коммутаторах

#### Cisco IOS

```bash
# Глобальное включение LLDP
conf t
lldp run

# Включение LLDP на конкретном порту
interface GigabitEthernet0/1
  lldp transmit
  lldp receive

# Настройка таймеров
conf t
lldp timer msgTxInterval 10       # Интервал отправки (по умолчанию 30)
lldp timer msgTxHold 4            # Множитель TTL (TTL = hold × interval)
lldp timer reinitDelay 2          # Задержка перед реинициализацией

# Отключение LLDP на порту
interface GigabitEthernet0/24
  no lldp transmit
  no lldp receive

# Просмотр соседей-информации
show lldp neighbors
show lldp neighbors detail
show lldp entry *

# Настройка LLDP-MED
conf t
lldp med-tlv-list
  network-policy voice vlan 100
  network-policy voice dscp 46
  extended-power 25.5
```

#### Juniper Junos

```bash
# Включение LLDP
set protocols lldp interface all

# Включение на конкретном интерфейсе
set protocols lldp interface ge-0/0/0

# Настройка таймеров
set protocols lldp transmission-interval 10
set protocols lldp hold-multiplier 4

# Отключение на интерфейсе
delete protocols lldp interface ge-0/0/24

# Просмотр соседей
show lldp neighbors
show lldp neighbors detail
show lldp interface

# LLDP-MED
set protocols lldp-med interface ge-0/0/0
```

#### Linux bridge (brctl / ip link)

```bash
# Проверка LLDP на интерфейсе моста
bridge fdb show | grep 01:80:c2:00:00:0e

# Включение отображения LLDP в bridge-интерфейсе
# (lldpd автоматически определяет master-устройство)

# Просмотр соседей через bridge
bridge -d link show
```

### 8. SNMP-доступ к LLDP MIB

LLDP хранит информацию в стандартных SNMP MIB, что позволяет централизованно собирать данные о топологии:

```bash
# Стандартные MIB для LLDP:
# - lldpLocChassisId    — Chassis ID локального устройства
# - lldpLocPortId       — Port ID локального устройства
# - lldpLocSysName      — System Name локального устройства
# - lldpRemChassisId    — Chassis ID удаленного соседа
# - lldpRemPortId       — Port ID удаленного соседа
# - lldpRemSysName      — System Name удаленного соседа
# - lldpRemManAddr      — Management Address удаленного соседа

# Чтение LLDPсоседей через SNMP (пример)
snmpwalk -v2c -c public 192.168.1.254 lldpRemChassisId.0
# → SNMPv2-MIB::lldpRemChassisId.0.1.1 = Hex-STRING: 00 11 22 33 44 55

snmpwalk -v2c -c public 192.168.1.254 lldpRemSysName.0
# → SNMPv2-MIB::lldpRemSysName.0.1.1 = STRING: "sw-core-01"

snmpwalk -v2c -c public 192.168.1.254 lldpRemPortId.0
# → SNMPv2-MIB::lldpRemPortId.0.1.1 = STRING: "GigabitEthernet0/1"
```

### 9. Автоматизация и интеграция

#### LLDP и CMDB (Inventory Management)

```bash
# Скрипт сбора LLDP-данных для CMDB
#!/bin/bash
lldpcli show neighbors -f json | jq '.lldp[] | {
  interface: .interface,
  chassis_id: .chassis.id,
  system_name: .chassis.name,
  port_id: .port.id,
  port_desc: .port.descr,
  mgmt_ip: .management-addresses[0],
  capabilities: .capabilities
}'
```

#### LLDP и Prometheus (экспорт метрик)

```bash
# Использование lldpd_exporter для Prometheus
# https://github.com/tynitech/lldpd_exporter
docker run -d --net=host \
  -e "LLDPD_URL=http://localhost:3599" \
  prom/lldpd-exporter

# Примеры метрик:
# lldp_neighbors_total{interface="eth0"} 1
# lldp_neighbor_uptime_seconds{interface="eth0"} 3600
```

### 10. Отладка проблем LLDP

#### Типичные ошибки и решения

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Соседи не отображаются** | LLDP отключен глобально | `show lldp` (Cisco); `lldpcli show chassis` (Linux) | Включить LLDP: `lldp run` (Cisco); `systemctl enable lldpd` (Linux) |
| **Соседи не отображаются** | LLDP отключен на порту | `show lldp interface Gi0/1` (Cisco) | Включить на порту: `lldp transmit` + `lldp receive` |
| **Соседи не отображаются** | Интерфейс DOWN | `ip link show eth0`; `show interface status` | Проверить физическое подключение; `ethtool eth0` |
| **Соседи не отображаются** | Native VLAN mismatch | `show vlan brief` (Cisco); `tcpdump -i eth0 ether proto 0x88cc` | Убедиться, что Native VLAN одинаков на обоих концах |
| **Соседи не отображаются** | Firewall блокирует multicast | `ebtables -L`; `bridge -d link show` | Разрешить `01:80:c2:00:00:0e` в ebtables/iptables |
| **Sosedi отображаются некорректно** | Устаревшие данные (TTL не истёк) | `lldpcli show neighbors` — проверить Time | Уменьшить TTL: `lldp timer msgTxHold 2` |
| **Дублирующиеся записи** | Несколько LLDP-агентов | `systemctl status lldpd`; `ps aux | grep lldp` | Оставить только один LLDP-агент (lldpd ИЛИ systemd-networkd) |
| **LLDP-MED не работает** | Mediatype не определен | `lldptool -T -i eth0 -V medcapabilities` | Включить LLDP-MED: `lldp med` (lldpd) |
| **PoE не согласуется** | LLDP-MED не отправляется | `lldptool -T -i eth0 -V power` | Проверить настройки PoE на коммутаторе |
| **SNMP не видит LLDP** | MIB не загружена | `snmpwalk -v2c -c public <ip> lldpRemChassisId.0` | Загрузить LLDP-MIB; проверить community string |

#### Диагностический скрипт

```bash
#!/bin/bash
# LLDP Diagnostic Script
IFACE="${1:-eth0}"

echo "=== LLDP Diagnostics for $IFACE ==="
echo ""

# 1. Проверка состояния интерфейса
echo "--- Interface State ---"
if [ -f /sys/class/net/$IFACE/operstate ]; then
    STATE=$(cat /sys/class/net/$IFACE/operstate)
    echo "  operstate: $STATE"
    if [ "$STATE" != "up" ]; then
        echo "  WARNING: Interface is DOWN, LLDP will not work"
    fi
else
    echo "  Interface $IFACE not found"
    exit 1
fi

# 2. Проверка наличия lldpd
echo ""
echo "--- LLDP Daemon ---"
if systemctl is-active --quiet lldpd; then
    echo "  lldpd: running"
else
    echo "  lldpd: not running"
    echo "  Trying systemd-networkd LLDP..."
    if networkctl lldp 2>/dev/null | grep -q "$IFACE"; then
        echo "  systemd-networkd LLDP: active"
    else
        echo "  No LLDP agent found"
    fi
fi

# 3. Проверкасоседей
echo ""
echo "--- LLDP Neighbors ---"
if command -v lldpcli &>/dev/null; then
    lldpcli show neighbors interface $IFACE 2>/dev/null || echo "  No neighbors found via lldpcli"
elif command -v lldptool &>/dev/null; then
    lldptool -n -i $IFACE 2>/dev/null || echo "  No neighbors found via lldptool"
else
    echo "  Neither lldpcli nor lldptool available"
fi

# 4. Проверка через tcpdump (быстрый тест)
echo ""
echo "--- Quick tcpdump Test (2 seconds) ---"
timeout 2 tcpdump -i $IFACE -c 5 -nn ether proto 0x88cc 2>/dev/null || echo "  No LLDP packets captured"

# 5. Проверка multicast
echo ""
echo "--- Multicast Groups ---"
cat /proc/net/igmp | grep -A5 "eth0" 2>/dev/null | head -3 || echo "  IGMP info not available"

# 6. Проверка firewall
echo ""
echo "--- Firewall (ebtables) ---"
if command -v ebtables &>/dev/null; then
    ebtables -L 2>/dev/null | grep -i "80:c2\|lldp" || echo "  No LLDP-specific ebtables rules"
else
    echo "  ebtables not installed"
fi

echo ""
echo "=== Diagnostics Complete ==="
```

### 11. LLDP и полировка (LLDP Duration/Timer Tuning)

Для различных сценариев требуется настройка таймеров:

| Сценарий | msgTxInterval | TTL | Описание |
| :--- | :--- | :--- | :--- |
| **Стандартный** | 30 сек | 120 сек | По умолчанию, баланс нагрузки |
| **Быстрое обнаружение** | 5 сек | 20 сек | Дата-центр, быстрая топология |
| **Нагруженная сеть** | 60 сек | 240 сек | Снижение overhead |
| **VoIP/мультимедиа** | 10 сек | 40 сек | Быстрая настройка VLAN/QoS |

**Настройка на Linux (lldpd):**
```bash
# Быстрое обнаружение соседей
cat <<EOF | sudo tee /etc/lldpd.d/fast-discovery.conf
# Интервал отправки (секунды)
configure system msgTxInterval 5
# Множитель TTL (TTL = hold × interval)
configure system msgTxHold 4
# Задержка перед повторной инициализацией
configure system reinitDelay 1
EOF

sudo systemctl restart lldpd
```

## Дополнительная информация

### Сравнение протоколов

| Характеристика | LLDP (802.1AB) | CDP (Cisco) | LLDP-MED (TIA-1057) |
| :--- | :--- | :--- | :--- |
| **Стандарт** | Открытый (IEEE) | Проприетарный (Cisco) | Открытый (TIA) |
| **Поддержка** | Все современные вендоры | Преимущественно Cisco | Оконечные устройства (VoIP, камеры) |
| **Мультикаст MAC** | `01:80:c2:00:00:0e` | `01:00:0c:cc:cc:cc` | `01:80:c2:00:00:0e` |
| **EtherType** | `0x88cc` | N/A (SAP) | `0x88cc` |
| **Расширяемость** | Очень высокая (TLV 127) | Ограничена вендором | Высокая (MED TLV) |
| **Voice VLAN** | Через IEEE 802.1 TLV | Встроен (native) | Встроен (Network Policy) |
| **PoE** | Через IEEE 802.3 TLV | Нет | Встроен (Extended Power) |
| **Inventory** | Ограниченный | Полный | Полный (serial, firmware, hardware) |
| **Location** | Нет | Нет | Встроен (Hemisphere, LCI) |

### LLDP-MED (Media Endpoint Discovery)

**LLDP-MED (ANSI/TIA-1057)** — расширение для оконечных устройств (VoIP, камеры, точки доступа).

#### Возможности LLDP-MED

| Возможность | Описание | Типичное применение |
| :--- | :--- | :--- |
| **Network Policy** | Автоматическая передача номера Voice VLAN и приоритетов QoS (CoS/DSCP) | IP-телефоны автоматически получают VLAN и QoS |
| **PoE Management** | Согласование потребляемой мощности (класс PoE) | Камеры, точки доступа Wi-Fi |
| **Inventory** | Передача серийных номеров и версий прошивок | Инвентаризация через SNMP |
| **Location** | Передача координат устройства | Геолокация для emergency services |
| **Extended Power** | Расширенное согласование PoE++ (802.3bt, до 90W) | Точки доступа Wi-Fi 6E/7, PTZ-камеры |

#### Типы Network Policy (LLDP-MED)

| Тип политики | Назначение | Параметры |
| :--- | :--- | :--- |
| **Voice** | Голосовой трафик | VLAN, CoS=5, DSCP=46 (EF) |
| **Voice Signaling** | Сигнализация (SIP/H.323) | VLAN, CoS=3, DSCP=24 (CS3) |
| **Video Conferencing** | Видеоконференции | VLAN, CoS=4, DSCP=34 (AF41) |
| **Video Streaming** | Стриминг видео | VLAN, CoS=4, DSCP=34 (AF41) |
| **Guest Voice** | Гостевой голос | VLAN, CoS=5, DSCP=46 (EF) |
| **Guest Video** | Гостевое видео | VLAN, CoS=4, DSCP=34 (AF41) |

### RFC и стандарты

- **IEEE 802.1AB-2016** — Link Layer Discovery Protocol (LLDP) (основной стандарт).
- **IEEE 802.1AB-2009** — LLDP (старая версия, все ещеактивно используется).
- **ANSI/TIA-1057-2006** — LLDP-MED (Media Endpoint Discovery).
- **IEEE 802.1AB-2016, Section 9** — Organizationally Specific TLV format.
- **IETF RFC 3436** — SNMP MIB for LLDP (lldpRemTable, lldpLocTable).
- **IEEE 802.1Q-2018** — VLAN-aware Bridge operation.

### См. также

- [Data Link Layer — безопасность](../OSI_TCP_IP_Model/data_link_layer.md#безопасность-l2) — CDP/LLDP reconnaissance.
- [systemd-networkd — LLDP](../../Linux/Networking/Settings/Persistent_Network/systemd_networkd.md) — LLDP в systemd-networkd.
- [QoS — LLDP-MED](../Concepts/qos.md) — Network Policy для Voice VLAN.
