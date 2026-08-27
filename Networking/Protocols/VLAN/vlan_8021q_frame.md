# Формат кадра 802.1Q и тегирование VLAN

## Определения

**IEEE 802.1Q** — основной отраслевой стандарт канального уровня (L2), определяющий механизм тегирования (encapsulation) Ethernet-кадров. Позволяет передавать трафик нескольких логических сетей (VLAN) через один физический канал.

**VLAN Tag (тег)** — 4-байтовый заголовок, вставляемый в Ethernet-кадр между MAC-адресом источника и полем EtherType. Содержит идентификатор VLAN и параметры приоритезации.

**Терминация (Untagging)** — процесс удаления VLAN-тега перед отправкой кадра через порт доступа (Access) конечному устройству, которое не поддерживает 802.1Q.

## Базовые концепции

### Структура кадра 802.1Q

При тегировании стандартный кадр Ethernet II расширяется. Поле **VLAN Tag** вставляется после **Source MAC**.

**Схема кадра:**

```text
| Dest MAC (6) | Src MAC (6) | TPID (2) | TCI (2) | EtherType (2) | Data (46-1500) | FCS (4) |
                              └────────┬─────────┘
                                   VLAN Tag
```

#### Поля тега (VLAN Tag)

| Поле | Размер | Описание |
| :--- | :--- | :--- |
| **TPID (Tag Protocol Identifier)** | 16 бит | Идентификатор протокола. Стандартное значение `0x8100` указывает, что далее следует тег 802.1Q. |
| **TCI (Tag Control Information)** | 16 бит | Управляющая информация, определяющая параметры VLAN и приоритета. |

**Детальная структура TCI (16 бит):**

| Подполе | Биты | Описание |
| :--- | :--- | :--- |
| **PCP** (Priority Code Point) | 3 бита | Маркировка приоритета (0–7) согласно **IEEE 802.1p** (Class of Service). |
| **DEI / CFI** | 1 бит | В современных сетях — **DEI** (Drop Eligible Indicator). В старых — **CFI** (Canonical Format Indicator). |
| **VID** (VLAN Identifier) | 12 бит | Идентификатор VLAN (0–4095). |

### Подробный разбор полей TCI

#### 1. PCP (Priority Code Point)
Используется для управления качеством обслуживания ([QoS](../../Concepts/qos.md)) на уровне L2.

| PCP | Сокращение | Назначение |
| :--- | :--- | :--- |
| **0** | BE | Best Effort (стандартный трафик по умолчанию) |
| **1** | BK | Background (фоновый трафик) |
| **2** | EE | Excellent Effort (бизнес-критичный трафик) |
| **3** | CA | Critical Applications (критические приложения) |
| **4** | VI | Video (видео, чувствительное к задержкам) |
| **5** | VO | Voice (голос, IP-телефония) |
| **6** | IC | Internetwork Control (протоколы маршрутизации) |
| **7** | NC | Network Control (критически важный сетевой трафик) |

#### 2. DEI и CFI
- **DEI (Drop Eligible Indicator):** Используется совместно с PCP. Если бит установлен в 1, это указывает, что кадр может быть отброшен в первую очередь при перегрузке (congestion).
- **CFI (Canonical Format Indicator):** Историческое поле. Использовалось для индикации совместимости между Ethernet и Token Ring. В современном Ethernet-оборудовании всегда установлено в 0 или интерпретируется как DEI.

#### 3. VID (VLAN Identifier)
Определяет принадлежность кадра конкретной сети. 12-битное поле позволяет создать 4096 значений.

| Диапазон VID | Описание |
| :--- | :--- |
| **0** | **Priority Tagging:** Кадр не принадлежит конкретному VLAN, но несет информацию о приоритете (PCP). |
| **1** | **Default VLAN:** Стандартный идентификатор "по умолчанию". Часто используется как Native VLAN. |
| **2 – 4094** | **User VLANs:** Доступный диапазон для пользовательских сетей. |
| **4095** | **Reserved:** Зарезервировано для системных целей (иногда используется как wildcard). |

### Влияние на MTU и размер кадра

Вставка 4-байтового тега увеличивает общий размер кадра.

- **Standard Frame:** 1518 байт (без преамбулы).
- **802.1Q Tagged:** 1522 байта.

**Важные нюансы:**
1. **Baby Giant Frames:** Кадры размером чуть больше стандартного Ethernet (до 1600 байт). Современное оборудование поддерживает их автоматически (MRU 1522+).
2. **Jumbo Frames:** Кадры размером до 9000+ байт. Используются в СХД (iSCSI) и высокопроизводительных сетях.
3. **Double Tagging (QinQ):** Добавляет еще 4 байта (итого 1526 байт).

### Устаревшие технологии (ISL)

До стандартизации 802.1Q компания Cisco использовала проприетарный протокол **ISL (Inter-Switch Link)**. 
- **Отличия:** ISL не модифицирует кадр внутри, а инкапсулирует его целиком (добавляет 26 байт заголовка и 4 байта CRC).
- **Статус:** Полностью вытеснен 802.1Q и не поддерживается на современном оборудовании.

### QinQ (IEEE 802.1ad) — двойное тегирование

**QinQ (Q-in-Q)** — технология двойного тегирования, определенная стандартом **IEEE 802.1ad**. Позволяет провайдерам L2-транспорта (Metro Ethernet) пробрасывать клиентские VLAN через свою сеть, сохраняя изоляцию между клиентами.

#### Принцип работы

1. **Клиент** отправяет кадр со своим тегом 802.1Q (C-tag, TPID=0x8100).
2. **Порт клиента (Customer Edge)** на коммутаторе провайдера добавляет **второй тег** — сервисный (S-tag, TPID=0x88a8).
3. **Сеть провайдера** транзитно пересылает кадра с двумя тегами (Inner C-tag + Outer S-tag).
4. **Порт назначения** удаляет S-tag и передает клиенту кадр с его оригинальным C-tag.

**Структура кадра QinQ:**

```text
| Dest MAC (6) | Src MAC (6) | S-TPID (2) | S-TCI (2) | C-TPID (2) | C-TCI (2) | EtherType (2) | Data (46-1500) | FCS (4) |
               └──────────────────┬─────────────────────┘ └──────────────────┬─────────────────────┘
                         Outer VLAN (Service)                  Inner VLAN (Customer)
                          TPID: 0x88a8                        TPID: 0x8100
```

#### Диапазоны MTU для QinQ

| Конфигурация | Размер кадра | MTU (payload) | Описание |
| :--- | :--- | :--- | :--- |
| **Standard Ethernet** | 1518 байт | 1500 байт | Без тегов |
| **802.1Q (1 тег)** | 1522 байта | 1500 байт | Один тег добавляет 4 байта, но MTU payload не меняется |
| **QinQ (2 тега)** | 1526 байт | 1500 байт | Два тега = 8 байт заголовка |
| **QinQ + Jumbo** | 9018+ байт | 9000+ байт | Для внутри-ЦОД транспорта |

> **Важно:** Физический MTU линка должен поддерживать кадры ≥1526 байт. Если MTU физического интерфейса = 1500, кадры QinQ будут отбрасываться. Увеличьте MTU до 1508+ на всех портах транзитной сети.

#### Типы QinQ

| Тип | Описание | Применение |
| :--- | :--- | :--- |
| **Basic QinQ** | Statisное добавление S-tag на порту клиента | Простые Metro Ethernet сегменты |
| **Selective QinQ** | Добавление S-tag в зависимости от C-tag (VLAN mapping) | Сложные топологии с мульти-клиентами |
| **Flexible QinQ** | Динамическое маппирование C-tag → S-tag через policy | Крупные провайдеры с VLAN-планом |

#### Конфигурация QinQ на Cisco IOS

```cisco
! На порту клиента (Customer Edge)
interface GigabitEthernet0/1
 description *** Customer A ***
 switchport mode trunk
 switchport vlan mapping disable          ! Отключение VLAN translation
 service instance 100 ethernet
  encapsulation dot1q 10-100              ! Клиентские VLAN 10-100
  rewrite ingress tag push dot1q 1000     ! Добавление S-tag VLAN 1000
  bridge-domain 1000
```

#### Конфигурация QinQ на Juniper Junos

```juniper
interfaces ge-0/0/1 {
    unit 0 {
        family ethernet-switching {
            interface-mode trunk;
            vlan {
                members [vlan-1000];
            }
        }
    }
}
vlans vlan-1000 {
    vlan-id 1000;
    domain-id 1000;
    bridge-domains {
        domain customer-a {
            vlan-id 10;
            interface ge-0/0/1.0;
            vlan-id-list [10-100];
            vlan-tags {
                inner-dot1q;
                dot1q 1000;
            }
        }
    }
}
```

### VLAN Translation (Трансляция VLAN)

**VLAN Translation** — механизм замены одного VLAN ID на другой при прохождении кадра через коммутатор. Используется в Metro Ethernet, миграциях сетей и интеграции с VLAN-планами провайдера.

#### Типы трансляции

| Тип | Описание | Пример |
| :--- | :--- | :--- |
| **Port-based (TOVE)** | Все кадры на порту транслируются в один VLAN | Клиент в VLAN 10 → провайдер в VLAN 1000 |
| **VLAN-based (1:1)** | Каждый C-tag маппится на уникальный S-tag | VLAN 10 → 1000, VLAN 20 → 1001 |
| **N:1 (Many-to-One)** | Множество C-tag маппится в один S-tag | VLAN 10-50 → все в VLAN 1000 |
| **双向ная (Bidirectional)** | Маппинг работает в обе стороны | VLAN 10 ↔ VLAN 1000 |

#### Конфигурация VLAN Translation на Cisco

```cisco
! Порт клиента — трансляция VLAN 10 → VLAN 1000
interface GigabitEthernet0/1
 description *** Customer Access ***
 switchport mode access
 switchport access vlan 10
 switchport vlan mapping 10 1000          ! Трансляция 10 → 1000

! Порт провайдера — обратная трансляция
interface GigabitEthernet0/24
 description *** Uplink to Provider ***
 switchport mode trunk
 switchport trunk allowed vlan 1000
 switchport vlan mapping 1000 10          ! Обратная трансляция 1000 → 10
```

#### Конфигурация VLAN Translation на Linux (iproute2)

```bash
# Создание VLAN с трансляцией на уровне ядра
# Исходный тег 10 транслируется в 1000 при выходе
sudo ip link add link eth0 name eth0.1000 type vlan id 1000
sudo ip link set eth0.1000 up

# Применение tc (traffic control) для трансляции
sudo tc qdisc add dev eth0.1000 clsact
sudo tc filter add dev eth0.1000 ingress protocol 802.1Q flower vlan_id 10 action vlan pop 2 push vlan id 1000
```

## Практические сценарии

### Жизненный цикл тегированного кадра

1. **Ingress (Вход):** Кадр без тега поступает на Access-порт. Коммутатор добавляет тег с VID этого порта (PVID).
2. **Forwarding:** Коммутатор сверяется с таблицей MAC-адресов внутри конкретного VLAN.
3. **Trunking:** Если кадр передается на другой коммутатор через Trunk-порт, тег сохраняется.
4. **Egress (Выход):** Если выходной порт — Access, коммутатор удаляет тег (**Egress Untagging**).

### Диагностика тегов в Linux (tcpdump)

Для анализа тегированного трафика необходимо захватывать пакеты на физическом интерфейсе (не на сабинтерфейсе VLAN).

```bash
# Захват кадров 802.1Q на интерфейсе eth0
sudo tcpdump -i eth0 -e -nn vlan 10
```

**Разбор заголовка в HEX:**
```text
0x0000:  ... 8100 000a 0800 ...
              ^    ^    ^
              |    |    EtherType: IPv4 (0x0800)
              |    TCI: PCP=0, DEI=0, VID=10 (0x000a)
              TPID: 802.1Q (0x8100)
```

### Верификация тегов на коммутаторах

#### Cisco IOS/IOS-XE

```cisco
! Просмотр VLAN в тегах на порту
show interfaces switchport | include Access VLAN|Trunking

! Просмотр Native VLAN на Trunk-порту
show interfaces trunk
# → Native VLAN: 1

! Просмотр всех тегированных кадров на порту (debug)
debug vlan packet
# → show packet on GigabitEthernet0/1: VLAN 10 tagged

! Просмотр MAC-таблицы с VLAN
show mac address-table vlan 10
# → Mac Address Table: VLAN 10 entry count: 42
```

#### Juniper Junos

```juniper
# Просмотр VLAN на интерфейсе
show vlans detail | match "ge-0/0/1"
# → VLAN: customer-vlan, Tag: 10, Interfaces: ge-0/0/1.0

# Просмотр тегов на интерфейсе
show ethernet-switching interface ge-0/0/1 detail
# → Interface: ge-0/0/1, Mode: trunk, VLANs: [10, 20, 30]

# Просмотр MAC-таблицы с VLAN
show ethernet-switching table vlan customer
# → VLAN: customer, MAC: 00:1a:2b:3c:4d:5e, Port: ge-0/0/1
```

#### Arista EOS

```arista
# Просмотр VLAN на порту
show interfaces switchport | grep -i "Access VLAN|Trunking Native"
# → Access VLAN: 10 (inactive)
# → Trunking Native Mode VLAN: 1 (inactive)

# Просмотр VLAN-тегов в реальном времени
monitor interface vlan detail

# Просмотр MAC-таблицы с VLAN
show mac address-table vlan 10
# → Vlan: 10, Mac Address: 00:1a:2b:3c:4d:5e, Type: DYNAMIC, Port: Ethernet1
```

### Создание VLAN-интерфейсов в Linux

#### Вариант A: iproute2 (Временная настройка)

```bash
# Создание VLAN 10 на физическом интерфейсе eth0
sudo ip link add link eth0 name eth0.10 type vlan id 10
sudo ip addr add 192.168.10.100/24 dev eth0.10
sudo ip link set eth0.10 up

# Проверка созданного интерфейса
ip link show eth0.10
# → 3: eth0.10@eth0: <BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state UP
```

#### Вариант B: systemd-networkd (Персистентная настройка)

```ini
# /etc/systemd/network/10-vlan10.netdev
[NetDev]
Name=eth0.10
Kind=vlan

[VLAN]
Id=10
```

```ini
# /etc/systemd/network/20-eth0.network
[Match]
Name=eth0

[Network]
VLAN=eth0.10
Address=192.168.10.100/24
```

#### Вариант C: Netplan (Ubuntu)

```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  vlans:
    eth0.10:
      id: 10
      link: eth0
      addresses: [192.168.10.100/24]
```

#### Вариант D: QinQ на Linux

```bash
# Увеличение MTU для поддержки двух тегов
sudo ip link set dev eth0 mtu 1508

# Создание внешнего (Service) тега
sudo ip link add link eth0 name eth0.1000 type vlan protocol 802.1ad id 1000

# Создание внутреннего (Customer) тега поверх внешнего
sudo ip link add link eth0.1000 name eth0.1000.10 type vlan id 10

# Настройка IP-адреса
sudo ip addr add 192.168.10.100/24 dev eth0.1000.10

# Включение интерфейсов
sudo ip link set eth0 up
sudo ip link set eth0.1000 up
sudo ip link set eth0.1000.10 up

# Проверка
ip -d link show eth0.1000.10
# → 5: eth0.1000.10@eth0.1000: <BROADCAST,MULTICAST,UP> mtu 1500 ...
#    vlan protocol 802.1Q id 10 <REORDER_HDR>
```

## Дополнительная информация

### Типичные ошибки и их решения (Troubleshooting)

| Проблема | Симптомы | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Тег не добавляется** | Кадры приходят без тега на Trunk-порту | Порт настроен как Access, а не Trunk | Проверьте `show interfaces switchport` (Cisco) или `show ethernet-switching interface` (Juniper). Убедитесь, что порт в режиме trunk. |
| **Native VLAN mismatch** | Широковещательный трафик попадает в неправильный VLAN | Разные Native VLAN на两端 Trunk-порта | На обоих концах Trunk установите одинаковую Native VLAN: `switchport trunk native vlan <ID>` (Cisco). |
| **MTU drop (QinQ)** | Пакеты >1500 байт отбрасываются, SSH работает, SCP зависает | MTU физического линка = 1500, а кадр QinQ = 1526 байт | Увеличьте MTU на всех портах транзитной сети до 1508+: `ip link set dev eth0 mtu 1508` (Linux), `mtu 1508` (Cisco). |
| **VLAN 1 traffic leak** | Служебный трафик (CDP, VTP) появляется в пользовательских VLAN | VLAN 1 не отключена на Trunk-портах | Отключите VLAN 1: `switchport trunk allowed vlan remove 1` (Cisco). Используйте `switchport nonegotiate` для отключения DTP. |
| **PCP не работает** | Приоритетный трафик не обрабатывается по-разному | QoS не настроен на уровне L2 | Убедитесь, что PCP/CoS включен: `mls qos` (Cisco), `set class-of-service forwarding-class` (Juniper). |
| **Double-tagged frames dropped** | Кадры с двумя тегами отбрасываются | Коммутатор не поддерживает QinQ или MTU слишком мал | Проверьте поддержку 802.1ad. Увеличьте MTU до 1508+. |
| **VLAN translation fails** | Трафик не проходит через трансляцию | Маппинг VLAN настроен неправильно | Проверьте `show vlan mapping` (Cisco) или `show vlans mapping` (Juniper). Убедитесь, что обе стороны маппинга существуют. |

### Порядок диагностики тегов

1. **Физический уровень:** `show interfaces status` — убедитесь, что линк UP.
2. **Режим порта:** `show interfaces switchport` — проверьте Access/Trunk/Native VLAN.
3. **VLAN-список:** `show interfaces trunk` — проверьте allowed VLANs.
4. **MAC-таблица:** `show mac address-table vlan <ID>` — есть ли записи в нужном VLAN.
5. **Тегирование:** `tcpdump -i <iface> -e vlan <ID>` — захватите и проверьте теги.
6. **MTU:** `ping -M do -s 1472 <dest>` — проверьте Path MTU.

### Best Practices

1. **Отключайте DTP:** На всех Trunk-портах используйте `switchport nonegotiate` (Cisco) для предотвращения автоматического согласования режима порта.
2. **Ограничивайте VLAN на Trunk:** Используйте `switchport trunk allowed vlan <list>` для передачи только необходимых VLAN.
3. **Не используйте VLAN 1:** Переведите все порты в пользовательские VLAN. VLAN 1 — стандартная цель для атак.
4. **Согласовывайте MTU:** Для QinQ увеличьте MTU на ВСЕХ портах транзитной сети, не только на портах клиентов.
5. **Мониторьте PCP:** Убедитесь, что приоритеты L2 (PCP) корректно маппятся на L3 (DSCP) для end-to-end QoS.
6. **Используйте 64-bit counters:** На высокоскоростных линках (10Gbps+) используйте `ifHCInOctets/ifHCOutOctets` вместо 32-bit counters для избежания переполнения.
7. **Проверяйте Native VLAN:** На всех Trunk-портах устанавливайте одну и ту же Native VLAN. Используйте unused VLAN (например, 999) вместо VLAN 1.
8. **Документируйте VLAN-план:** Ведите таблицу VLAN ID ↔ назначение ↔ диапазоны IP для каждого сегмента.

### Edge Cases

#### 1. Native VLAN Mismatch с Unicast Traffic

Если Native VLAN на одном конце Trunk = VLAN 10, а на другом = VLAN 20:
- **Unicast трафик** VLAN 10 будет доставлен в VLAN 20 (и наоборот).
- **Broadcast трафик** будет виден в обоих VLAN.
- **Решение:** Согласуйте Native VLAN на обоих концах или используйте нетегированный трафик только для service VLAN.

#### 2. VLAN hopping через Double Tagging

Атакующий может отправить кадр с двумя тегами:
- Внешний тег = Native VLAN порта接收ателя (удаляется при egress).
- Внутренний тег = целевой VLAN (становится основным).
- **Защита:** Отключите unused VLAN, используйте专用 Native VLAN для каждого Trunk, включите VLAN ACL.

#### 3. MTU Black Hole с QinQ

Если MTU физического линка = 1500, а кадр QinQ = 1526 байт:
- Малые пакеты (SSH, DNS) проходят успешно.
- Большие пакеты (SCP, HTTP) отбрасываются молча (нет ICMP unreachable из-за DF=1).
- **Диагностика:** `ping -M do -s 1472 <dest>` — должен показать "message too long".
- **Решение:** Увеличьте MTU до 1508+ на всех портах.

#### 4. Baby Giant Frames

Кадры размером 1504-1600 байт (802.1Q + небольшой payload) считаются "baby giants". Современное оборудование поддерживает их автоматически, но старые коммутаторы могут отбрасывать. Проверяйте через `show interfaces counters errors`.

#### 5. VLAN Translation и STP

При использовании VLAN Translation убедитесь, что STP-домены для исходного и целевого VLAN изолированы. В противном случае петли могут возникнуть из-за маппинга.

### Типы TPID для специальных задач

| TPID | Стандарт | Применение |
| :--- | :--- | :--- |
| **0x8100** | 802.1Q | Стандартный C-tag (Customer Tag). |
| **0x88a8** | 802.1ad | Сервисный S-tag для технологий QinQ. |
| **0x9100 / 0x9200** | Legacy | Устаревшие значения для каскадирования старых коммутаторов. |

### PCP → DSCP: Маппинг L2→L3

Для end-to-end QoS необходимо маппировать L2 PCP (802.1p) в L3 DSCP (IP ToS) и обратно:

| PCP (802.1p) | DSCP (Decimal) | DSCP (Hex) | Имя | Назначение |
| :---: | :---: | :---: | :--- | :--- |
| 0 | 0 | 0x00 | BE (Best Effort) | Обычный трафик |
| 1 | 10 | 0x0A | AF11 | Сквозной трафик (CS1) |
| 2 | 18 | 0x12 | AF21 | Массовые данные |
| 3 | 26 | 0x1A | AF31 | Видеоконференция |
| 4 | 34 | 0x22 | AF41 | Потоковое видео |
| 5 | 46 | 0x2E | EF (Expedited Forwarding) | Голос (VoIP) |
| 6 | 48 | 0x30 | CS6 | Сигнализация ( routing protocols) |
| 7 | 56 | 0x38 | CS7 (Network Control) | Управление сетью |

**Конфигурация trust на коммутаторе (Cisco):**
```cisco
! Доверие L2 PCP на входе (access port)
interface GigabitEthernet1/0/10
 mls qos trust cos

! Маппинг PCP→DSCP
mls qos map dscp-mutation PCP_TO_DSCP 10 18 26 34 46 48 56
```

Связано с **[QoS и приоритезация](../../Concepts/qos.md)** — полная теория и конфигурация CBWFQ, policing, shaping.

### Связанные документы

- **[VLAN — обзор](../vlan.md)** — общая концепция и преимущества технологии.
- **[Trunk и Native VLAN](./vlan_trunk_native.md)** — работа с магистральными и нетегированными портами.
- **[Настройка VLAN в Linux](./vlan_linux_diagnostics.md)** — практические примеры и диагностика в ОС.
- **[QoS и приоритезация](../../Concepts/qos.md)** — подробнее об управлении очередями на основе PCP.
- **[MTU, PMTUD и диагностика](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — влияние тегов на MTU и Path MTU Discovery.
- **[L2 Switching и VLAN](../../Concepts/vlan_l2_switching/practical_scenarios.md)** — практические сценарии с Linux bridge и QinQ.
- **[Wireshark — практические сценарии](../../ServicesAndTools/Wireshark/practical_scenarios.md)** — анализ VLAN-трафика в Wireshark.
- **[tshark — анализ в командной строке](../../ServicesAndTools/Wireshark/tshark_usage.md)** — VLAN-фильтры: `vlan.id == 10`.
