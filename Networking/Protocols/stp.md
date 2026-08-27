# STP — протокол связующего дерева

## Определения

**Сетевая петля (Network Loop)** — ситуация в коммутируемых сетях L2 (Layer 2 — канальный уровень), когда между устройствами существует более одного активного физического пути. Это приводит к широковещательным штормам и нестабильности таблиц MAC-адресов.

**Широковещательный шторм (Broadcast Storm)** — экспоненциальный рост широковещательного (broadcast) и многоадресного (multicast) трафика из-за наличия петель. Вызывает полную загрузку пропускной способности каналов и отказ сетевой инфраструктуры.

**STP (Spanning Tree Protocol — протокол связующего дерева, IEEE 802.1D)** — сетевой протокол канального уровня, предназначенный для обнаружения и логической блокировки избыточных путей. Позволяет предотвращать петли, сохраняя при этом возможность использования резервных физических соединений.

**Ключевая идея:** STP строит логическое дерево (spanning tree) с одним корневым коммутатором (Root Bridge), блокируя избыточные порты для разрыва замкнутых циклов.

## Основные концепции

### Причины возникновения петель

В сетях Ethernet кадры не имеют поля TTL (Time to Live), как IP-пакеты. Если в топологии L2 возникает петля, кадры могут циркулировать в ней бесконечно.

**Сценарий возникновения:**

1. Хост отправляет широковещательный кадр (например, [ARP-запрос](./arp.md)).
2. Коммутаторы рассылают broadcast во все порты, кроме входящего (механизм flooding).
3. Кадр начинает циркулировать по замкнутому контуру.
4. Каждый проход кадра через коммутатор может порождать дополнительные копии, что приводит к лавинообразному росту трафика.

**Последствия:** отказ сети, высокая нагрузка на CPU коммутаторов, «прыгающие» MAC-адреса в таблицах коммутации (один и тот же адрес видится за разными портами).

### Формат BPDU (Bridge Protocol Data Unit)

Коммутаторы обмениваются двумя типами BPDU:

**Configuration BPDU (802.1D):**

| Поле | Байты | Описание |
| :--- | :--- | :--- |
| Protocol ID | 2 | Всегда 0 (STP) |
| Version | 1 | 0 = 802.1D, 2 = RSTP/MSTP |
| Message Type | 1 | 0x00 = Config, 0x02 = TCN, 0x80 = RSTP |
| Flags | 1 | TC (Topology Change), TCA, Proposal, Agreement, Role, Forwarding, Learning |
| Root ID | 8 | Bridge ID корневого коммутатора |
| Root Path Cost | 4 | Стоимость пути от отправителя до Root Bridge |
| Sender Bridge ID | 8 | Bridge ID отправителя |
| Port ID | 2 | Идентификатор порта отправителя (приоритет + номер) |
| Message Age | 2 | Текущий «возраст» BPDU (в 1/256 сек). Увеличивается на 1 при прохождении через коммутатор. Max Age = 20 сек |
| Max Age | 2 | Максимальный допустимый возраст BPDU (по умолчанию 20 сек). Если BPDU не приходит > Max Age, порт считается недоступным |
| Hello Time | 2 | Интервал отправки BPDU (по умолчанию 2 сек). Root Bridge рассылает Configuration BPDU каждые Hello Time |
| Forward Delay | 2 | Задержка в состояниях Listening → Learning → Forwarding (по умолчанию 15 сек). Используется дважды: 2 × Forward Delay = 30 сек до Forwarding |

**TCN BPDU (Topology Change Notification):**
- Отправляется от изменённого порта в сторону Root Bridge.
- Содержит только Protocol ID, Version и Message Type (0x80).
- Root Bridge отвечает Configuration BPDU с флагом TCA (Topology Change Acknowledge).

#### Таймеры STP

| Таймер | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **Hello Time** | 2 сек | Интервал рассылки Configuration BPDU от Root Bridge |
| **Forward Delay** | 15 сек | Время пребывания в Listening и Learning перед переходом в Forwarding |
| **Max Age** | 20 сек | Время ожидания BPDU; при превышении — пересчёт топологии |
| **Message Age** | 0 → Max Age | Текущий возраст BPDU; увеличивается на 1 сек на каждом хопе |

**Важно:** Таймеры (Hello, Forward Delay, Max Age) наследуются от Root Bridge во всех Configuration BPDU. Все коммутаторы в домене STP работают с одинаковыми значениями.

### Алгоритм работы STP

Для построения топологии без петель коммутаторы обмениваются служебными кадрами — **BPDU (Bridge Protocol Data Unit)**.

1. **Выбор корневого коммутатора (Root Bridge):** коммутатор с наименьшим **Bridge ID**.
   - **Bridge ID (8 байт):** состоит из Приоритета (2 байта) и MAC-адреса (6 байт).
   - **Extended System ID:** В современных реализациях (PVST+, MSTP) приоритет делится на 4 бита собственно приоритета (кратно 4096) и 12 бит номера VLAN.
   - По умолчанию приоритет равен 32768. Рекомендуется назначать корневым наиболее производительный коммутатор ядра (устанавливая приоритет 4096 или 0).
2. **Выбор корневых портов (Root Ports):** на каждом не-корневом коммутаторе выбирается один порт с минимальной стоимостью пути (Path Cost) до Root Bridge.
3. **Выбор назначенных портов (Designated Ports):** в каждом сегменте сети выбирается один порт, ответственный за передачу трафика в сторону корня.
4. **Блокировка избыточных путей:** все остальные порты переводятся в состояние блокировки (Blocking/Discarding).

#### Стоимость пути (Path Cost)

Стоимость зависит от пропускной способности интерфейса. Существуют два стандарта: Short (16-bit) и Long (32-bit).

| Скорость | Cost (Short / 802.1D) | Cost (Long / 802.1t) |
| :--- | :--- | :--- |
| **10 Mbps** | 100 | 2,000,000 |
| **100 Mbps** | 19 | 200,000 |
| **1 Gbps** | 4 | 20,000 |
| **10 Gbps** | 2 | 2,000 |
| **40 Gbps** | 1 | 500 |
| **100 Gbps** | 1 | 200 |

#### Уведомление о смене топологии (TCN)

Когда порт падает или переходит в Forwarding, коммутатор генерирует **TCN BPDU**.
- TCN отправляется в сторону Root Bridge.
- Root Bridge устанавливает флаг **TC (Topology Change)** в конфигурационных BPDU.
- Получив такое уведомление, все коммутаторы временно сокращают время хранения MAC-адресов (Aging Time) с 300с до значения Forward Delay (15с), что позволяет быстро "забыть" неактуальные пути.

#### Состояния портов (802.1D vs 802.1w)

В классическом STP (802.1D) перестроение топологии занимает много времени из-за таймеров. В RSTP (802.1w) состояния оптимизированы:

| Состояние (802.1D) | Состояние (802.1w) | Передача данных | Обучение MAC | Задержка |
| :--- | :--- | :--- | :--- | :--- |
| **Blocking** | **Discarding** | Нет | Нет | 20 сек (Max Age) / Мгновенно в RSTP |
| **Listening** | **Discarding** | Нет | Нет | 15 сек (Forward Delay) |
| **Learning** | **Learning** | Нет | Да | 15 сек (Forward Delay) |
| **Forwarding** | **Forwarding** | Да | Да | — |
| **Disabled** | **Discarding** | Нет | Нет | — |

#### Роли портов в RSTP (Rapid STP)

RSTP вводит дополнительные роли для ускорения сходимости:
- **Root Port:** Лучший путь к Root Bridge.
- **Designated Port:** Лучший путь в сегмент сети.
- **Alternate Port:** Резервный путь к Root Bridge (заменяет Root Port при отказе мгновенно).
- **Backup Port:** Резервный путь в тот же сегмент (дублирует Designated Port).

**Типы линков в RSTP:**
- **Edge Port:** Порт к конечному устройству (мгновенно в Forwarding).
- **Point-to-Point:** Полнодуплексный линк между двумя коммутаторами (мгновенная сходимость через Proposal/Agreement).
- **Shared:** Полудуплексный линк (через хаб), работает по медленным таймерам 802.1D.

#### Механизм Proposal/Agreement (быстрая сходимость RSTP)

Ключевой механизм, обеспечивающий сходимость RSTP за 1 RTT:

1. **Proposal:** Designated Port отправляет BPDU с флагом Proposal на Root Port другого коммутатора.
2. **Agreement:** Получив Proposal, коммутатор проверяет, что предложенный путь лучше текущего, и немедленно отвечает Agreement.
3. **Synchronized:** Все портыполучившего коммутатора (кроме Edge Port) переводятся в Discarding. Это предотвращает петли на время переконфигурации.
4. **Forwarding:** После обмена Proposal/Agreement оба порта переходят в Forwarding без задержки Forward Delay.

**Сравнение сходимости:**

| Сценарий | STP (802.1D) | RSTP (802.1w) |
| :--- | :--- | :--- |
| Падение Root Port | 30–50 сек (Max Age + 2×Forward Delay) | <1 сек (через Alternate Port) |
| Падение Designated Port | 30–50 сек | <1 сек (через Proposal/Agreement) |
| Новый коммутатор в топологии | 30–50 сек | <1 сек (Proposal/Agreement) |

### Эволюция протокола

| Протокол | Стандарт | Сходимость | Особенности |
| :--- | :--- | :--- | :--- |
| **STP** | IEEE 802.1D | 30–50 сек | Классический, медленный |
| **RSTP** | IEEE 802.1w | 1–10 сек | Rapid STP, быстрая сходимость |
| **MSTP** | IEEE 802.1s | 1–10 сек | Multiple STP, экземпляры для групп VLAN |
| **PVST+** | Cisco | 1–10 сек | Per-VLAN STP, экземпляр на каждый VLAN |

#### Особенности MSTP и PVST+

1. **PVST+ (Per-VLAN Spanning Tree Plus):**
   - Cisco-проприетарный (но поддерживается многими вендорами).
   - Запускает отдельный инстанс STP для каждого VLAN.
   - **Плюсы:** Гибкая балансировка (Load Balancing) — для VLAN 10 корень на Switch A, для VLAN 20 на Switch B.
   - **Минусы:** Высокая нагрузка на CPU при большом количестве VLAN (например, 500+).

2. **MSTP (Multiple Spanning Tree Protocol):**
   - Группирует VLAN в **инстансы (Instances)**. Например, Instance 1 (VLANs 1-50), Instance 2 (VLANs 51-100).
   - **Регионы MSTP:** Коммутаторы должны иметь одинаковое имя региона, номер ревизии и маппинг VLAN-to-Instance для совместной работы.
   - Взаимодействует с обычным STP через инстанс 0 (IST — Internal Spanning Tree).

## Практические сценарии

### Проверка и управление в Linux

В современных дистрибутивах Linux для управления мостами рекомендуется использовать связку `ip link` и `bridge` (пакет `iproute2`).

**Просмотр состояния моста:**
```bash
# Просмотр детальных параметров STP
ip -details link show type bridge
# → bridge stp_state 1 priority 32768 forward_delay 1500 ...

# Просмотр состояния портов
bridge link show
# → 2: eth0 state forwarding priority 32 cost 100
```

**Основные команды управления:**
```bash
# Включение STP
sudo ip link set br0 type bridge stp_state 1

# Установка приоритета (кратно 4096)
sudo ip link set br0 type bridge priority 4096

# Настройка PortFast (Edge Port) для интерфейса
sudo bridge link set dev eth0 edgeport on
```

### Настройка на промышленном коммутаторе

#### Cisco IOS

**Пример настройки MSTP:**

```cisco
! Включение MSTP
spanning-tree mode mst

! Настройка региона MSTP
spanning-tree mst configuration
 name REGION1
 revision 1
 instance 1 vlan 10, 20
 instance 2 vlan 30, 40
exit

! Приоритет Root Bridge для Instance 1
spanning-tree mst 1 priority 4096

! Приоритет Root Bridge для Instance 2
spanning-tree mst 2 priority 8192

! BPDU Guard на access-порту
interface GigabitEthernet0/1
 description to-server
 switchport mode access
 switchport access vlan 10
 spanning-tree portfast
 spanning-tree bpduguard enable

! Root Guard на порту к чужому сегменту
interface GigabitEthernet0/24
 description to-partner-switch
 switchport mode trunk
 spanning-tree guard root

! Loop Guard (глобально)
spanning-tree loopguard default

! Recovery err-disabled порта
interface GigabitEthernet0/1
 errdisable recovery cause bpduguard
 errdisable recovery interval 300
```

#### Juniper Junos

**Пример настройки RSTP:**

```juniper
# Включение RSTP
set protocols rstp interface ge-0/0/0 edge
set protocols rstp interface ge-0/0/0 bpdu-guard

# Настройка MSTP
set protocols mstp bridge instance 1 vlan [vlan10 vlan20]
set protocols mstp bridge instance 2 vlan [vlan30 vlan40]
set protocols mstp bridge mst-id 1 priority 4096
set protocols mstp region REGION1
set protocols mstp region revision 1
set protocols mstp region vlan-regex "^(10|20|30|40)$"

# BPDU Guard на access-порту
set protocols rstp interface ge-0/0/1 edge
set protocols rstp interface ge-0/0/1 bpdu-guard

# Root Guard
set protocols rstp interface ge-0/0/24 no-root-port
```

**Проверка состояния (Junos):**

```bash
show spanning-tree bridge           # Состояние моста
show spanning-tree interface         # Состояния портов
show spanning-tree statistics         # Статистика BPDU
show spanning-tree mstp instance 1   # MSTP Instance 1
```

#### Linux (iproute2)

**Настройка VLAN-aware Bridge с MSTP:**

```bash
# Создание моста с VLAN filtering и STP
sudo ip link add br0 type bridge vlan_filtering 1 stp_state 1

# Установка приоритета (Instance 0)
sudo ip link set br0 type bridge priority 4096

# Настройка таймеров
sudo ip link set br0 type bridge hello_time 200 \
  max_age 2000 forward_delay 1500

# Настройка Edge Port
sudo bridge link set dev eth0 edge on

# Настройка стоимости (для 10Gbps)
sudo bridge link set dev eth0 cost 200

# Просмотр полного состояния STP
bridge -d link show
# → 2: eth0@eth0: <BROADCAST,MULTICAST,UP> ...
#   cost 200 priority 128.2 state forwarding

# Просмотр MSTP (если поддерживается ядром)
cat /sys/class/net/br0/bridge/stp_state
# → 1
```

### Диагностика проблем

**Симптомы некорректной работы:**
- Периодическая потеря связи на 30–50 секунд (пересчет топологии).
- Постоянные сообщения в логах о смене топологии — **TCN (Topology Change Notification)**.
- **EtherChannel Misconfiguration:** Если агрегированный канал не настроен как LACP с обеих сторон, STP может заблокировать один из линков или допустить петлю.

**Команды диагностики:**
- **Cisco:** `show spanning-tree summary`, `show spanning-tree mst`.
- **Juniper:** `show spanning-tree bridge`.
- **Linux:** `bridge vlan show`, `ip -s link show type bridge`.

#### Типичные ошибки и их диагностика

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Потеря связи на 30–50 сек | STP пересчитывает топологию (802.1D) | `show spanning-tree summary` — проверить время сходимости | Переход на RSTP: `spanning-tree mode rapid-pvst` |
| «Root Bridge» неожиданно сменился | Неконтролируемый коммутатор с приоритетом 0 | `show spanning-tree root` — кто Root? | `spanning-tree vlan X root primary` на нужном коммутаторе |
| Порт в err-disabled | BPDU Guard сработал | `show interfaces status err-disabled` | Убрать BPDU Guard или устранить источник BPDU; `shutdown`/`no shutdown` |
| Петля несмотря на STP | BPDU не доходят (однонаправленный линк) | Проверить связность: `ping` + `show spanning-tree inconsistentports` | Включить Loop Guard: `spanning-tree loopguard default` |
| MAC-адрес «прыгает» | Флапающий порт или петля | `show mac address-table` — MAC мигрирует между портами | Найти флапающий порт: `show interface | inc errors` |
| MSTP-инстансы не синхронизируются | Разные имена регионов | `show spanning-tree mst configuration` на всех коммутаторах | Привести имя региона, ревизию и маппинг к единому значению |
| 0-RTT RSTP не работает | Shared-лиinks или не все порты Point-to-Point | `show spanning-tree detail` — проверить тип линка | Переключить на полный дуплекс; `spanning-tree link-type point-to-point` |
| Высокий CPU при 500+ VLAN | PVST+ — отдельный экземпляр на каждый VLAN | `show spanning-tree summary` — количество инстансов | Переход на MSTP: группировка VLAN в инстансы |

**Флап порта:** частая смена топологии может быть вызвана флапающим портом. Подробнее — [Ethernet — флап порта](./ethernet.md#флап-порта-port-flapping).

#### Поиск петли L2 без доступа к коммутаторам

Если STP отключён или не справился, петля проявляется как широковещательный шторм: broadcast-фреймы множатся, загружают все порты, сеть деградирует за секунды.

**Первый признак — резкий рост broadcast-трафика:**

```bash
watch -n 1 'ip -s link show eth0 | grep -A2 RX'
```

Если счётчик пакетов растёт на тысячи в секунду при минимальной нагрузке — петля активна.

**Ловля шторма в реальном времени:**

```bash
tcpdump -i eth0 -n broadcast
```

Один и тот же фрейм, появляющийся несколько раз подряд с одинаковым содержимым, подтверждает петлю — фрейм циркулирует по кругу, tcpdump видит каждый проход.

**Определение источника по MAC:**

```bash
tcpdump -i eth0 -n -e broadcast | awk '{print $2}' | sort | uniq -c | sort -rn | head -10
```

MAC, встречающийся аномально часто, — вероятный источник или точка замыкания петли.

**Поиск дублирующихся фреймов по содержимому:**

```bash
tcpdump -i eth0 -w /tmp/capture.pcap
tcpdump -r /tmp/capture.pcap -n | awk '{print $NF}' | sort | uniq -c | sort -rn | head
```

**Физическая локализация.** Отключайте патч-корды по одному, наблюдая за счётчиками:

```bash
watch -n 1 'ip -s link show eth0 | grep -A1 RX'
```

Момент, когда счётчики перестали расти, указывает на последний отключённый кабель — он и есть замыкание.

> Если STP включён, но петля всё равно возникла — вероятно, BPDU Guard отключил порт (err-disabled), а петля успела замкнуться через другой путь. При малейшем доступе к коммутатору проверьте: `show interfaces status err-disabled`.

### Безопасность STP

| Функция | Описание | Место применения |
| :--- | :--- | :--- |
| **BPDU Guard** | Отключает порт (err-disabled) при получении BPDU | Access-порты |
| **Root Guard** | Блокирует порт (root-inconsistent), если через него получен BPDU с лучшим Bridge ID | Порты к чужим сегментам |
| **Loop Guard** | Переводит порт в loop-inconsistent, если BPDU перестали приходить (защита от однонаправленных линков) | Uplink-порты |
| **UDLD (UniDirectional Link Detection)** | Детектирует физическую однонаправленность линка на L2 (дополнение к Loop Guard) | Оптические линки |
| **BPDU Filter** | Игнорирует входящие и исходящие BPDU | Крайне осторожное применение для изоляции |

#### Конфигурация безопасности STP

**Cisco IOS:**

```cisco
! BPDU Guard — глобально на всех Edge Port
spanning-tree portfast bpduguard default

! BPDU Guard — на конкретном порту
interface GigabitEthernet0/1
 spanning-tree bpduguard enable

! Root Guard — на порту к внешнему сегменту
interface GigabitEthernet0/24
 spanning-tree guard root

! Loop Guard — глобально
spanning-tree loopguard default

! BPDU Filter — глобально (ОСТОРОЖНО: отключает STP на Edge Port)
spanning-tree portfast bpdufilter default

! Recovery err-disabled портов
errdisable recovery cause bpduguard
errdisable recovery cause udld
errdisable recovery interval 300

! Проверка заблокированных портов
show spanning-tree summary
show interfaces status err-disabled
show spanning-tree inconsistentports
```

**Juniper Junos:**

```juniper
# BPDU Guard на Edge Port
set protocols rstp interface ge-0/0/1 edge
set protocols rstp interface ge-0/0/1 bpdu-guard

# Root Guard (no-root-port)
set protocols rstp interface ge-0/0/24 no-root-port

# BPDU Filter (ОСТОРОЖНО!)
set protocols rstp interface ge-0/0/1 no-bpdu-send

# Проверка
show spanning-tree interface detail
show spanning-tree statistics
```

## Альтернативы STP в современных ЦОД

В крупных инфраструктурах (Leaf-Spine топологии) STP часто отключают или минимизируют его влияние, так как блокировка портов снижает общую пропускную способность и увеличивает время сходимости.

1. **LACP (Link Aggregation):** Объединение нескольких физических линков в один логический (Port Channel), что предотвращает петли на уровне связки и увеличивает пропускную способность. См.: **[Link Aggregation](../Concepts/link_aggregation.md)**.
2. **MLAG / vPC:** Технологии виртуализации коммутаторов, позволяющие подключать устройства к двум разным коммутаторам как к одному логическому, исключая необходимость STP на этих линках.
3. **TRILL / SPB:** Протоколы маршрутизации на уровне L2 (IS-IS), позволяющие использовать все доступные пути (Multipathing/ECMP) без блокировки портов.
4. **VXLAN + EVPN:** Современный стандарт построения оверлейных сетей. Петли устраняются на уровне Control Plane (BGP), а трафик передается через масштабируемую L3-фабрику. Это основной метод построения сетей в 2025-2026 годах.

## Дополнительная информация

### STP и VLAN

В сетях с большим количеством **VLAN (Virtual Local Area Network)** классический STP строит одно дерево для всех виртуальных сетей. Это приводит к невозможности балансировки нагрузки.

- **PVST+** создает дерево для каждого VLAN, что позволяет использовать разные физические пути, но увеличивает нагрузку на процессор коммутатора.
- **MSTP** объединяет VLAN в группы (инстансы), обеспечивая баланс между гибкостью и нагрузкой.

### Связанные документы

- **[VLAN](../vlan.md)** — виртуальные локальные сети.
- **[Ethernet](./ethernet.md)** — основы канального уровня.
- **[L2 Switching и VLAN](../Concepts/vlan_l2_switching/definitions_and_concepts.md)** — концепции коммутации.
- **[Жёсткая защита L2: BPDU Guard, Root Guard](../VLAN/vlan_security_hardening.md)** — production hardening на access и trunk портах.
- **[ARP](./arp.md)** — протокол разрешения адресов.
- **[VLAN Trunk/Native](./VLAN/vlan_trunk_native.md)** — работа с тегированным трафиком.
- **[Linux Bridge](../../Linux/Networking/Concepts/linux_bridge.md)** — STP в программных мостах.

### Стандарты и спецификации

| Стандарт | Описание |
| :--- | :--- |
| **IEEE 802.1D** | Классический STP (802.1D-2004 — интеграция RSTP) |
| **IEEE 802.1w** | RSTP — быстрая сходимость (встроен в 802.1D-2004) |
| **IEEE 802.1s** | MSTP — мультиинстансов STP для групп VLAN |
| **IEEE 802.1Q-2018** | VLAN + STP взаимодействие (§13) |
| **IEEE 802.1AB** | LLDP — обнаружение соседей (дополнение к STP) |
| **RFC 5227** | IPv4 Address Conflict Detection (упоминание в контексте STP) |

### Лучшие практики 2026

1. **RSTP вместо классического STP** — всегда используйте `rapid-pvst` или `mst` вместо `spanning-tree mode pvst`.
2. **BPDU Guard на всех Access-портах** — предотвращает подключение несанкционированных коммутаторов.
3. **Root Bridge на ядре** — назначайте приоритет 4096 на 가장 производительном коммутаторе ядра.
4. **MSTP для больших VLAN** — группируйте VLAN в инстансы вместо PVST+ при >100 VLAN.
5. **Loop Guard на Uplink-портах** — защита от однонаправленных линков, которые не видят BPDU Guard.
6. **Документирование топологии** — фиксируйте Root Bridge, роли портов и таймеры в CMDB.
