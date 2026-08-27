# Магистральные порты (Trunk) и Native VLAN

## Определения

**Trunk-порт (Магистральный порт)** — порт сетевого устройства, способный передавать трафик нескольких VLAN одновременно по одному физическому или логическому линку. Использует механизм тегирования согласно стандарту **IEEE 802.1Q**. Trunk-порты используются для связи коммутаторов между собой, подключения к маршрутизаторам (Router-on-a-Stick), гипервизорам и серверам, которым необходимо работать в нескольких VLAN.

**Native VLAN (Собственный VLAN)** — настройка порта Trunk, определяющая, к какому VLAN принадлежит трафик, передаваемый без 802.1Q тега. По умолчанию (Cisco) — **VLAN 1**. По стандарту IEEE 802.1Q, Native VLAN — это VLAN, для которого коммутатор не добавляет тег при отправке кадра через Trunk и не ожидает тег при получении нетегированного кадра.

**PVID (Port VLAN ID)** — идентификатор VLAN по умолчанию для нетегированных кадров на порту. Термин используется в оборудовании Huawei, HP (Aruba), Juniper, а также в сетевом стеке Linux. На портах Trunk значение PVID совпадает со значением Native VLAN.

**Voice VLAN** — технология (преимущественно Cisco), позволяющая порту работать как "мини-транк", принимая нетегированный трафик данных (Data VLAN) и тегированный трафик голоса (Voice VLAN) от IP-телефона одновременно.

**DTP (Dynamic Trunking Protocol)** — проприетарный протокол Cisco для автоматического согласования режима порта (Access/Trunk) между коммутаторами. По умолчанию порты Cisco находятся в режиме `dynamic desirable`, что означает попытку установить Trunk. DTP является вектором атак (Switch Spoofing), поэтому рекомендуется его отключение на всех портах командой `switchport nonegotiate`.

## Базовые концепции

### Механизм обработки трафика (Ingress/Egress)

Работа Native VLAN основана на правилах обработки кадров при входе на порт и выходе из него.

#### 1. Обработка входящего трафика (Ingress)
- Если на Trunk-порт поступает **тегированный** кадр, коммутатор проверяет VID в теге и направляет кадр в соответствующий VLAN (если он разрешен в списке Allowed VLANs).
- Если на Trunk-порт поступает **нетегированный** кадр, коммутатор "навешивает" на него тег с ID, равным настроенному **Native VLAN (PVID)**.
- Если разрешенная VLAN не в списке Allowed VLANs, кадр отбрасывается (даже если тег корректен).

#### 2. Обработка исходящего трафика (Egress)
- Если ID кадра **не совпадает** с Native VLAN, кадр отправляется с тегом 802.1Q.
- Если ID кадра **совпадает** с Native VLAN, тег удаляется (или не добавляется), и кадр уходит в линию нетегированным.
- При включённом `vlan dot1q tag native` (Cisco) или аналогичной настройке, тег добавляется даже для Native VLAN — это рекомендуемая мера безопасности.

### Сравнение терминологии вендоров

| Концепция | Cisco IOS | Huawei (VRP) | Juniper (Junos) | Linux (bridge-vlan) |
| :--- | :--- | :--- | :--- | :--- |
| Режим порта | `switchport mode trunk` | `port link-type trunk` | `set interfaces ... family ethernet-switching port-mode trunk` | `vlan_filtering 1` на мосту |
| Нетегированный VLAN | `switchport trunk native vlan <ID>` | `port trunk pvid vlan <ID>` | `native-vlan-id <ID>` | `bridge vlan add dev <iface> vid <ID> pvid untagged` |
| Разрешенные VLAN | `switchport trunk allowed vlan <list>` | `port trunk allow-pass vlan <list>` | `vlan members [<list>]` | `bridge vlan add dev <iface> vid <ID>` (для каждого VLAN) |
| Отключение DTP | `switchport nonegotiate` | Нет аналога (DTP — Cisco) | Нет аналога | Не применимо |
| Тегирование Native | `vlan dot1q tag native` | `port trunk vlan-tag native` | Не применимо (всегда тегирует) | Не применимо |

### Механизм Trunk-согласования

В оборудовании Cisco Trunk-порт может быть настроен следующими способами:

1. **Статический Trunk** (`switchport mode trunk`) — порт принудительно работает в режиме Trunk. DTP-кадры отправляются, но согласование не требуется.
2. **Dynamic Desirable** (`switchport mode dynamic desirable`) — порт активно пытается установить Trunk, отправляя DTP-кадры. Перейдет в Access, если на другом конце порт в Access или Dynamic Auto.
3. **Dynamic Auto** (`switchport mode dynamic auto`) — порт пассивно ожидает DTP-кадры. Перейдет в Trunk, только если другая сторона в Dynamic Desirable или Trunk.
4. **Статический Access** (`switchport mode access`) — порт всегда работает как Access, не отвечает на DTP.

> **Важно:** Режимы Dynamic Desirable и Dynamic Auto создают уязвимость Switch Spoofing. На production-портах всегда используйте статический режим (`trunk` или `access`) с `switchport nonegotiate`.

### Управление списком разрешенных VLAN (VLAN Pruning)

По умолчанию через магистральный порт разрешены все VLAN (1–4094). Использование **VLAN Allowed List** — обязательная мера безопасности и оптимизации:
- Предотвращает распространение широковещательного трафика в сегменты, где он не нужен.
- Защищает от несанкционированного доступа к служебным или приватным подсетям.
- Снижает нагрузку на CPU коммутатора при обработке.broadcast-трафика.

```
# Cisco: добавление и удаление VLAN из разрешённого списка
switchport trunk allowed vlan add 100
switchport trunk allowed vlan remove 1

# Huawei: аналогичная операция
port trunk allow-pass vlan add 100
port trunk allow-pass vlan remove 1
```

### Native VLAN и STP

Native VLAN имеет прямое влияние на работу Spanning Tree Protocol:

- **PVST/PVST+ (Cisco):** для каждого VLAN создается отдельный экземпляр STP. Native VLAN определяет, какой STP-инстанс обрабатывает нетегированные BPDU на Trunk-порту.
- **Mismatch эффект:** если Native VLAN не совпадает на двух концах Trunk, BPDU из одного VLAN могут попасть в другой, что приводит к непредсказуемым переходам портов в состояние Blocking/Forwarding.
- **RSTP/MSTP:** в Multi-Instance STP маппинг VLAN на инстансы может усугубить проблему mismatch — трафик одного VLAN оказывается в неправильном STP-инстансе.

### Глобальные и интерфейсные команды

Некоторые команды Native VLAN работают на глобальном уровне (влияют на все Trunk-порты), а некоторые — на интерфейсном:

| Уровень | Команда (Cisco) | Эффект |
| :--- | :--- | :--- |
| **Глобальный** | `vlan dot1q tag native` | Принудительное тегирование Native VLAN на всех Trunk-портах |
| **Интерфейсный** | `switchport trunk native vlan <ID>` | Задаёт Native VLAN для конкретного порта |
| **Глобальный** | `vtp mode transparent` | Отключает VTP-синхронизацию (влияет на扩散 VLAN-базы) |
| **Интерфейсный** | `switchport trunk allowed vlan <list>` | Ограничивает VLAN на конкретном порту |

## Практические сценарии

### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **Cisco** | Коммутаторы Catalyst (2960, 3560, 3750, 9200, 9300, 9400, 9500, 9600); IOS 15.0(2)SE+ |
| **Huawei** | Серия S5700, S6700, S9300; VRP V800R010+ |
| **Juniper** | EX2200, EX3300, EX4200, EX4300; Junos 12.x+ |
| **Linux** | Ядро 3.8+ (для `vlan_filtering`); утилиты `iproute2` (`ip`, `bridge`) |
| **Права** | Привилегированный доступ (`enable 15` / `super` / `root`) |

### Сценарий 1: Настройка Trunk на Cisco IOS

Базовая безопасная конфигурация магистрального порта.

```cisco
interface GigabitEthernet0/24
 description *** Link to Aggregation-SW ***
 # Принудительная установка режима
 switchport mode trunk
 # Отключение динамического согласования (DTP)
 switchport nonegotiate

 # Безопасность Native VLAN (уходим от VLAN 1)
 switchport trunk native vlan 999

 # Ограничение списка разрешенных сетей
 switchport trunk allowed vlan 10,20,999

 # Принудительное тегирование Native VLAN (профилактика VLAN Hopping)
 vlan dot1q tag native
```

#### Валидация

```cisco
# Проверка режима порта и DTP
show interfaces switchport | include Administrative Mode|Negotiation of Trunking
# → Administrative Mode: trunk
# → Negotiation of Trunking: Off

# Проверка Native VLAN
show interfaces trunk | include Native VLAN
# → Native VLAN: 999

# Проверка разрешенных VLAN
show interfaces trunk | include Allowed VLAN
# → VLANs allowed on trunk: 10,20,999

# Проверка отсутствия DTP-кадров
show dtp interface Gi0/24
# → DTP interface state: Off

# Проверка активных VLAN на порту
show interfaces trunk
# → Port        Mode         Encapsulation  Status        Native vlan
# → Gi0/24      on           802.1q         trunking      999
# → Port        Vlans allowed on trunk
# → Gi0/24      10,20,999
```

### Сценарий 2: Настройка Trunk на Huawei (VRP)

```huawei
# Переход в режим конфигурации интерфейса
interface GigabitEthernet0/0/24
 description Link to Aggregation-SW

 # Установка режима Trunk
 port link-type trunk

 # Native VLAN (PVID на Huawei)
 port trunk pvid vlan 999

 # Разрешенные VLAN
 port trunk allow-pass vlan 10 20 999

 # Тегирование Native VLAN (опционально)
 port vlan-tag native
```

#### Валидация

```huawei
# Просмотр режима порта и VLAN
display port vlan interface GigabitEthernet0/0/24
# → Interface         LinkType    PVID  VLAN-Inner-Range
# → GE0/0/24          trunk       999   10,20,999

# Просмотр разрешенных VLAN
display port vlan allowed interface GigabitEthernet0/0/24
# → Allowed VLANs: 10,20,999

# Проверка Native VLAN (PVID)
display current-configuration interface GigabitEthernet0/0/24
# → port trunk pvid vlan 999
```

### Сценарий 3: Настройка Trunk на Juniper (Junos)

```juniper
set interfaces ge-0/0/24 description "Link to Aggregation-SW"
set interfaces ge-0/0/24 unit 0 family ethernet-switching port-mode trunk
set interfaces ge-0/0/24 unit 0 family ethernet-switching native-vlan-id 999
set interfaces ge-0/0/24 unit 0 family ethernet-switching vlan members [10 20 999]
```

#### Валидация

```juniper
# Просмотр конфигурации порта
show configuration interfaces ge-0/0/24

# Просмотр VLAN на интерфейсе
show ethernet-switching interface ge-0/0/24
# → Interface    State  VLAN members        Native VLAN
# → ge-0/0/24    up     10,20,999           999
```

### Сценарий 4: Настройка Trunk в Linux (VLAN-aware Bridge)

```bash
# 1. Создание моста с включенной фильтрацией VLAN
sudo ip link add name br0 type bridge vlan_filtering 1
sudo ip link set eth0 master br0
sudo ip link set br0 up

# 2. Настройка trunk-порта (eth0) — разрешаем VLAN 10, 20, 999
sudo bridge vlan add dev eth0 vid 10
sudo bridge vlan add dev eth0 vid 20
sudo bridge vlan add dev eth0 vid 999

# 3. Настройка Native VLAN (PVID) для нетегированного трафика
sudo bridge vlan add dev eth0 vid 999 pvid untagged

# 4. Удаление VLAN 1 по умолчанию (рекомендуется)
sudo bridge vlan del dev eth0 vid 1
sudo bridge vlan del dev eth0 vid 1 self
```

#### Валидация

```bash
# Просмотр таблицы VLAN на мосту
bridge vlan show
# → port    vlan ids
# → eth0    10
# →         20
# →         999 PVID Egress Untagged

# Проверка того, что VLAN 1 удалена
bridge vlan show | grep "eth0.*1PVID"
# → (не должно быть строк с VLAN 1)

# Просмотр всех VLAN на всех портах
bridge vlan show dev br0
```

### Сценарий 5: Настройка Voice VLAN (Cisco)

Режим "мини-транка" для подключения IP-телефонов.

```cisco
interface GigabitEthernet0/5
 description *** User-PC + IP-Phone ***
 switchport mode access
 # Трафик от ПК (нетегированный) попадает в VLAN 10
 switchport access vlan 10
 # Трафик от телефона (тегированный) попадает в VLAN 50
 switchport voice vlan 50
 # Включение доверия к меткам CoS от телефона
 mls qos trust cos
```

#### Валидация

```cisco
# Проверка Voice VLAN
show interfaces switchport | include Voice VLAN
# → Voice VLAN: 50

# Проверка статуса порта
show interfaces Gi0/5 switchport
# → Administrative Mode: static access
# → Operational Mode: static access
# → Access Mode VLAN: 10 (VLAN010)
# → Voice VLAN: 50 (VLAN050)
```

### Сценарий 6: Диагностика несовпадения Native VLAN

#### Cisco — обнаружение через CDP/LLDP

```bash
# Проверка логов на предмет ошибок
# %CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch discovered on GigabitEthernet0/24 (999), with SW2 GigabitEthernet0/1 (1).

# Анализ текущих транков
show interfaces trunk

# Проверка CDP-соседей
show cdp neighbors detail
# → Device ID: SW2
# → Interface: GigabitEthernet0/1
# → Native VLAN: 1 (не совпадает с 999 на локальном порту)
```

#### Linux — проверка VLAN-aware Bridge

```bash
# Просмотр VLAN на всех портах моста
bridge vlan show

# Ожидаемый вывод при корректной настройке:
# port    vlan ids
# eth0    10
#         20
#         999 PVID Egress Untagged

# Проверка FDB (Forwarding Database) для конкретного VLAN
bridge fdb show br br0 | grep "vlan 10"
```

### Сценарий 7: Trunk между Cisco и Juniper (Cross-Vendor)

При настройке Trunk между коммутаторами разных вендоров необходимо учитывать различия в терминологии и поведении.

```cisco
! Cisco side
interface GigabitEthernet1/0/24
 description *** Link to Juniper EX4200 ***
 switchport mode trunk
 switchport nonegotiate
 switchport trunk native vlan 999
 switchport trunk allowed vlan 10,20,999
```

```juniper
# Juniper side
set interfaces ge-0/0/24 description "Link to Cisco Catalyst"
set interfaces ge-0/0/24 unit 0 family ethernet-switching port-mode trunk
set interfaces ge-0/0/24 unit 0 family ethernet-switching native-vlan-id 999
set interfaces ge-0/0/24 unit 0 family ethernet-switching vlan members [10 20 999]
```

#### Валидация (с обеих сторон)

```cisco
! Cisco
show interfaces trunk | include Native VLAN
# → Native VLAN: 999

show dtp interface Gi1/0/24
# → DTP interface state: Off
```

```juniper
# Juniper
show ethernet-switching interface ge-0/0/24
# → Interface    State  VLAN members        Native VLAN
# → ge-0/0/24    up     10,20,999           999
```

## Типичные ошибки и их решения (Troubleshooting)

| Проблема | Симптомы | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Native VLAN mismatch** | Широковещательный трафик попадает в неправильный VLAN; %CDP-4-NATIVE_VLAN_MISMATCH в логах | Разные Native VLAN на двух концах Trunk | На обоих концах установите одинаковую Native VLAN: `switchport trunk native vlan <ID>` (Cisco) / `port trunk pvid vlan <ID>` (Huawei) / `native-vlan-id <ID>` (Juniper) |
| **VLAN 1 traffic leak** | Служебный трафик (CDP, VTP, STP BPDU) появляется в пользовательских VLAN | VLAN 1 не отключена на Trunk-портах | `switchport trunk allowed vlan remove 1` (Cisco); `port trunk allow-pass vlan remove 1` (Huawei); удалите VLAN 1 из таблицы bridge (`bridge vlan del`) в Linux |
| **DTP Negotiation** | Порт неожиданно переключается в Trunk или Access; уязвимость Switch Spoofing | Порт в динамическом режиме (Dynamic Auto/Desirable) | `switchport mode trunk` + `switchport nonegotiate` (Cisco) |
| **Тег не добавляется** | Кадры приходят без тега на Trunk-порту | Порт настроен как Access, а не Trunk | Проверьте `show interfaces switchport` (Cisco) / `display port vlan` (Huawei) / `show ethernet-switching interface` (Juniper) |
| **Разрешенные VLAN не проходят** | Трафик для определенных VLAN не проходит через Trunk | VLAN отсутствует в списке Allowed VLANs | Добавьте VLAN: `switchport trunk allowed vlan add <ID>` (Cisco); `port trunk allow-pass vlan add <ID>` (Huawei) |
| **MTU drop с QinQ** | Пакеты >1500 байт отбрасываются; SSH работает, SCP зависает | MTU физического линка = 1500, а кадр QinQ = 1526 байт | Увеличьте MTU на всех портах транзитной сети до 1508+: `ip link set dev eth0 mtu 1508` (Linux), `mtu 1508` (Cisco) |
| **PCP/CoS не работает** | Приоритетный трафик не обрабатывается по-разному | QoS не настроен на уровне L2 | `mls qos` (Cisco), `set class-of-service forwarding-class` (Juniper) |
| **VLAN-интерфейс DOWN в Linux** | Интерфейс `eth0.XXX` не поднимается | Физический интерфейс `eth0` выключен или нет VLAN на коммутаторе | Проверьте `ip link show eth0`; проверьте `tcpdump -i eth0 -e vlan` на наличие входящих тегированных кадров |

### Порядок диагностики

1. **Физический уровень:** `show interfaces status` / `ip link show` — убедитесь, что линк UP.
2. **Режим порта:** `show interfaces switchport` / `display port vlan` — проверьте Access/Trunk/Native VLAN.
3. **VLAN-список:** `show interfaces trunk` / `bridge vlan show` — проверьте allowed VLANs.
4. **MAC-таблица:** `show mac address-table vlan <ID>` / `bridge fdb show` — есть ли записи в нужном VLAN.
5. **Тегирование:** `tcpdump -i <iface> -e vlan <ID>` — захватите и проверьте теги.
6. **MTU:** `ping -M do -s 1472 <dest>` — проверьте Path MTU.
7. **STP:** `show spanning-tree` / `bridge link show` — проверьте, что порты в правильном состоянии.

## Дополнительная информация

### Риски и безопасность

1. **VLAN Hopping (Double Tagging):** Эксплуатация Native VLAN для проброса кадров с двойным тегом.
   - **Механизм:** Атакующий отправляет кадр с двумя тегами 802.1Q. Внешний тег совпадает с Native VLAN транка. Первый коммутатор удаляет внешний тег, второй коммутатор видит внутренний тег и направляет кадр в целевую VLAN. Атака однонаправленная (ответный трафик не вернется).
   - **Защита:** Используйте `vlan dot1q tag native` для принудительного тегирования всего трафика в магистрали; измените Native VLAN с VLAN 1 на неиспользуемый ID.

2. **Switch Spoofing:** Злоумышленник эмулирует коммутатор в режиме `Dynamic Desirable`. Если порт жертвы находится в режиме по умолчанию (`Dynamic Auto`), устанавливается Trunk-соединение, открывающее доступ ко всем разрешенным VLAN.
   - **Защита:** `switchport nonegotiate` на всех портах; статические режимы (Access/Trunk).

3. **Native VLAN Mismatch:** Приводит к непредсказуемой маршрутизации L2-трафика и петлям STP (из-за несовпадения PVST инстансов).
   - **Решение:** Всегда настраивайте одинаковый Native VLAN на обоих концах линка; мониторьте логи на %CDP-4-NATIVE_VLAN_MISMATCH.

### Edge Cases

#### 1. Native VLAN Mismatch с Unicast Traffic

Если Native VLAN на одном конце Trunk = VLAN 10, а на другом = VLAN 20:
- **Unicast трафик** VLAN 10 будет доставлен в VLAN 20 (и наоборот).
- **Broadcast трафик** будет виден в обоих VLAN.
- **Решение:** Согласуйте Native VLAN на обоих концах или используйте нетегированный трафик только для service VLAN.

#### 2. Baby Giant Frames

Кадры размером 1504-1600 байт (802.1Q + небольшой payload) считаются "baby giants". Современное оборудование поддерживает их автоматически, но старые коммутаторы могут отбрасывать. Проверяйте через `show interfaces counters errors`.

#### 3. Native VLAN и Management Access

Если Native VLAN используется для управления коммутатором (например, VLAN 999), а на Trunk-порту нетегированный трафик попадает в эту VLAN, злоумышленник может получить доступ к интерфейсу управления, подключившись к неиспользуемому порту. Решение: используйте отдельную Management VLAN, изолированную от Native VLAN.

### VTP (VLAN Trunking Protocol)

VTP — проприетарный протокол Cisco для синхронизации базы VLAN между коммутаторами через Trunk-порты.

| Версия | Возможности | Риск |
| :--- | :--- | :--- |
| **VTPv1/v2** | Только Normal Range (1-1005), без аутентификации | Новый коммутатор с более высоким Revision Number может **затереть** базу VLAN во всей домене |
| **VTPv3** | Extended Range (1-4096), парольная защита, primaries | Безопаснее, но требует ручной настройки |

**Рекомендация для production:** отключайте VTP и управляйте VLAN вручную или через automation (Ansible). VTPv1/v2 опасен — один неправильный коммутатор может удалить все VLAN.

```cisco
! Отключение VTP (рекомендуется)
vtp mode transparent

! Если используете VTPv3 — включите только на trusted портах
vtp domain PRODUCTION
vtp version 3
vtp password SECRET_VTP
vtp mode server
```

### Trunk и LACP (Port-Channel)

В production транки почти всегда идут через агрегацию каналов. Trunk без LACP — это single point of failure.

```cisco
! Port-Channel + Trunk (Cisco)
interface range GigabitEthernet1/0/23 - 24
 channel-group 1 mode active
 channel-protocol lacp

interface Port-channel1
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30,999
 switchport trunk native vlan 999
 switchport nonegotiate
```

### Резюме Best Practices

- **Изоляция Native VLAN:** Выделяйте отдельный VLAN ID (например, 999) для Native VLAN и не используйте его для передачи данных пользователей.
- **Минимизация разрешений:** Всегда явно указывайте список разрешенных VLAN (`switchport trunk allowed vlan`).
- **Явное тегирование:** Если оборудование позволяет, используйте тегирование Native VLAN (`vlan dot1q tag native`) для предотвращения атак.
- **Отключение DTP:** На всех Trunk-портах используйте `switchport nonegotiate` (Cisco).
- **Согласование Native VLAN:** На всех концах Trunk устанавливайте одинаковую Native VLAN.
- **LACP на транках:** Trunk без Port-Channel — single point of failure. Используйте LACP.
- **Документирование:** Ведите таблицу VLAN ID ↔ назначение ↔ Native VLAN для каждого сегмента.
- **Мониторинг:** Отслеживайте логи на %CDP-4-NATIVE_VLAN_MISMATCH и другие ошибки Trunk.

### Связанные документы

- **[VLAN — обзор](../vlan.md)** — основы сегментации и типы сетей.
- **[Формат кадра 802.1Q](./vlan_8021q_frame.md)** — детальный разбор структуры и полей тега.
- **[Безопасность портов: DTP и Port Security](./vlan_dtp_security.md)** — защита от атак на уровне доступа и магистралей.
- **[Жёсткая защита L2](./vlan_security_hardening.md)** — DHCP Snooping, DAI, IPSG, Root Guard.
- **[Меж-VLAN маршрутизация](./vlan_inter_vlan_routing.md)** — Router-on-a-Stick и L3-интерфейсы.
- **[VLAN в Linux](./vlan_linux_diagnostics.md)** — сабинтерфейсы, VLAN-aware Bridge, диагностика.
- **[QoS и приоритезация](../../Concepts/qos.md)** — управление очередями на основе меток 802.1p.
- **[Агрегация каналов (LACP)](../../Concepts/link_aggregation.md)** — Port-Channel, Bonding, MLAG/vPC.
- **[tshark — анализ трафика](../../ServicesAndTools/Wireshark/tshark_usage.md)** — VLAN-фильтры и анализ в командной строке.
- **[Проектирование VLAN](../../Concepts/vlan_l2_switching/vlan_design_patterns.md)** — VLAN ID allocation, naming conventions, production-ready топологии.
