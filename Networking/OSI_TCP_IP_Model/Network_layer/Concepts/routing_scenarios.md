# Практические сценарии маршрутизации

## Определения

**Шлюз по умолчанию (Default Gateway)** — сетевой узел (обычно маршрутизатор), которому хост пересылает IP-пакеты в случае, если адрес назначения находится за пределами текущей локальной подсети и для него нет более специфичного маршрута в таблице маршрутизации. В таблицах обозначается как `0.0.0.0/0` (IPv4) или `::/0` (IPv6).

**Прямая доставка (Direct Delivery)** — процесс передачи данных между узлами в рамках одного широковещательного домена (L2-сегмента), не требующий участия маршрутизатора на сетевом уровне.

**Косвенная доставка (Indirect Delivery)** — передача пакета через один или несколько промежуточных маршрутизаторов (хопов), когда отправитель и получатель находятся в разных подсетях.

**Longest Prefix Match (LPM)** — алгоритм выбора маршрута: из всех записей таблицы маршрутизации, покрывающих адрес назначения, выбирается запись с максимальной длиной префикса (маски). `/28` всегда приоритетнее, чем `/24`.

**Административная дистанция (Administrative Distance, AD)** — метрика «доверия» к источнику маршрутной информации. При равных метриках из разных протоколов побеждает источник с наименьшим AD (Static=1, eBGP=20, OSPF=110, iBGP=200). Подробнее: [Протоколы и оборудование L3](../routing_protocols_equipment.md).

**RIB (Routing Information Base)** — общая таблица всех маршрутов, полученных от всех протоколов маршрутизации и статических записей. Решения принимаются в Control Plane.

**FIB (Forwarding Information Base)** — таблица пересылки, экспортированная из RIB в ядро (Data Plane). Содержит только готовые записи: интерфейс, next-hop, метрику. Содержимое FIB видно через `ip route show` или `show ip cef`.

## Связь с соседними уровнями

```text
L4 (Транспортный) ← TCP/UDP определяют порты назначения; L4-балансировка (ECMP по 5-tuple)
       ↕
L3 (Сетевой)      ← IP-адресация, маршрутизация, выбор пути (RIB → FIB)
       ↕
L2 (Канальный)    ← ARP/NDP: резолвинг next-hop → MAC; фрагментация MTU
```

| Уровень | Взаимодействие с L3 |
| :--- | :--- |
| **L4 → L3** | TCP/UDP передают сегмент с указанием IP назначения; L3 определяет маршрут и инкапсулирует в IP-пакет |
| **L3 → L4** | При приёме L3 извлекает payload и передаёт в TCP/UDP по номеру протокола в заголовке IP |
| **L2 → L3** | ARP/NDP резолвят IP next-hop в MAC-адрес; Ethernet-кадр передаёт IP-пакет в L3 |
| **L3 → L2** | L3 инкапсулирует IP-пакет в L2-кадр, подставляя MAC-адрес следующего хопа |

### Инкапсуляция

```text
[Transport Segment (TCP/UDP)]  ← L4: порты
         ↓
[IP Packet: Src/Dst IP, TTL, Protocol]  ← L3: маршрутизация
         ↓
[Ethernet Frame: Src MAC, Dst MAC, Type] + [FCS]  ← L2: коммутация
         ↓
010101011...  ← L1: биты
```

**PDU L3:** Пакет (Packet). Заголовок IP: 20 байт (min) — 60 байт (max с опциями). IPv6: фиксированный 40-байтный заголовок.

## Базовые концепции

### Алгоритм принятия решения о маршрутизации (Routing Decision)

При отправке или пересылке IP-пакета сетевой стек выполняет следующие шаги:

1.  **Проверка локальности (On-link):** Применяется маска подсети к IP-адресу назначения. Если результат совпадает с адресом локальной сети одного из интерфейсов — используется **прямая доставка**. MAC-адрес получателя определяется через [ARP](../../../Protocols/arp.md) (IPv4) или [NDP](../../../Protocols/ipv6_overview.md#neighbor-discovery-protocol-ndp) (IPv6).
2.  **Поиск в таблице маршрутизации (LPM):** Если адрес внешний, ОС ищет совпадение по принципу **Longest Prefix Match** (выбор маршрута с самой длинной маской). Например, маршрут `/28` приоритетнее, чем `/24`.
3.  **Выбор метрики:** Если найдено несколько идентичных префиксов (например, два маршрута по умолчанию), выбирается запись с наименьшим значением метрики (административной дистанции).
4.  **Шлюз по умолчанию:** Если ни одного специфичного маршрута не найдено, пакет инкапсулируется в кадр с MAC-адресом **Default Gateway** и отправляется на него.

### Рекурсивный поиск маршрута

Если в таблице маршрутизации указан шлюз (Next-hop), который сам не является «соседом» по локальному сегменту, система выполняет рекурсивный поиск: она ищет маршрут к IP-адресу этого шлюза до тех пор, пока не найдет выходной интерфейс и MAC-адрес соседа.

## Практические сценарии

### Сценарий 1: Прямая доставка в одном L2-сегменте

**Условия:**
- Хост А: `192.168.1.10/24`, MAC: `AA:AA`
- Хост Б: `192.168.1.20/24`, MAC: `BB:BB`

**Процесс:**
1. Хост А видит, что `192.168.1.20` входит в его подсеть `192.168.1.0/24`.
2. Хост А проверяет свою ARP-таблицу. Если записи нет, отправляет широковещательный ARP-запрос.
3. Хост Б отвечает своим MAC.
4. Хост А инкапсулирует IP-пакет в Ethernet-кадр с **MAC назначения = BB:BB**.
5. Пакет доставляется через коммутатор напрямую.

### Сценарий 2: Маршрутизация через Default Gateway

**Условия:**
- Хост А: `192.168.1.10/24`, Gateway: `192.168.1.1`
- Цель: `8.8.8.8` (внешний IP)

**Процесс:**
1. Хост А определяет, что `8.8.8.8` — это внешняя сеть.
2. Ищет маршрут, находит только `0.0.0.0/0 via 192.168.1.1`.
3. Пакет инкапсулируется в кадр, где **IP назначения = 8.8.8.8**, но **MAC назначения = MAC шлюза** (`192.168.1.1`).
4. Маршрутизатор получает кадр, видит свой MAC, анализирует заголовок IP и пересылает пакет дальше.

### Сценарий 3: Асимметричная маршрутизация и Reverse Path Filter (rp_filter)

**Проблема:** Трафик входит в сервер через интерфейс `eth0`, но ответ, согласно таблице маршрутизации, должен уйти через `eth1`.

**Реализация в Linux (rp_filter):**
- **Strict (1):** Пакет отбрасывается, если обратный путь к адресу источника лежит через другой интерфейс.
- **Loose (2):** Пакет принимается, если к адресу источника есть *хотя бы какой-то* маршрут через любой интерфейс. Рекомендуется для сложных топологий и PBR.
- **Off (0):** Проверка отключена. Опасно (риск IP Spoofing).
Подробнее: **[RPF и uRPF — проверка обратного пути](../../../Protocols/rpf_urpf.md)**.

### Сценарий 4: Разделение трафика через Policy-Based Routing (PBR)

**Задача:** Направлять HTTP-трафик через одного провайдера, а трафик базы данных — через выделенный VPN-канал.

**Механизм:**
- Вместо одной таблицы `main` используются дополнительные таблицы.
- Правила выбора таблицы (`ip rule`) основываются на селекторах: IP источника, метка пакета (fwmark) или порт.

**Настройка в Linux (Practical):**

```bash
# 1. Создаём отдельные таблицы (не required, но помогает)
echo "100 isp1" >> /etc/iproute2/rt_tables
echo "200 vpn_db" >> /etc/iproute2/rt_tables

# 2. Заполняем таблицы
sudo ip route add default via 192.168.1.1 dev eth0 table isp1
sudo ip route add default via 10.8.0.1 dev tun0 table vpn_db

# 3. Добавляем правила (ip rule)
# HTTP-трафик (dport 80,443) → через ISP1
sudo ip rule add ipproto tcp dport {80,443} table isp1 priority 500

# Трафик от процесса postgres (UID 1001) → через VPN
sudo ip rule add uidrange 1001-1001 table vpn_db priority 1000

# Маркированные пакеты (fwmark) → через VPN
sudo ip rule add fwmark 0x1 table vpn_db priority 1500

# 4. Маркировка через nftables (если селекторов L3 недостаточно)
sudo nft add rule ip mangle prerouting meta l4proto tcp th dport {80,443} meta mark set 0x1

# 5. Проверка
ip rule show
ip route get 8.8.8.8 from 192.168.1.10  # → какой маршрут будет выбран
```

Подробнее: **[Маршрутизация на основе политик (PBR) в Linux](../../../../Linux/Networking/Policy_Based_Routing/index.md)** и **[Сценарии PBR](../../../../Linux/Networking/Policy_Based_Routing/scenarios.md)**.

### Сценарий 5: Изоляция через VRF (Virtual Routing and Forwarding)

**Задача:** Обеспечить работу нескольких изолированных сетевых окружений (например, `prod` и `dev`) на одном сервере, даже если их IP-адреса перекрываются.

**Концепция:**
- Каждая VRF-инстанция имеет свою собственную таблицу маршрутизации и набор привязанных интерфейсов.
- Трафик между VRF полностью изолирован на уровне L3.

**Настройка в Linux (Practical):**

```bash
# 1. Создаём VRF-объект
sudo ip link add vrf-prod type vrf table 100
sudo ip link add vrf-dev type vrf table 200

# 2. Привязываем интерфейсы
sudo ip link set eth1 vrf vrf-prod
sudo ip link set eth2 vrf vrf-dev

# 3. Заполняем таблицы (внутри VRF)
sudo ip route add default via 192.168.10.1 dev eth1 vrf vrf-prod
sudo ip route add default via 192.168.20.1 dev eth2 vrf vrf-dev

# 4. Проверка изоляции
ip route show vrf vrf-prod
ip route show vrf vrf-dev
ip route get 8.8.8.8 vrf vrf-prod  # → покажет маршрут только из vrf-prod

# 5. Меж-VRF связь (если нужна) — через routes в обеих таблицах
sudo ip route add 10.0.2.0/24 via 10.0.1.2 vrf vrf-prod
sudo ip route add 10.0.1.0/24 via 10.0.2.1 vrf vrf-dev
```

**VRF vs PBR (сравнение):**

| Характеристика | PBR | VRF |
| :--- | :--- | :--- |
| **Уровень изоляции** | Правила на пакеты | Полная изоляция L3-домена |
| **Масштабируемость** | Таблицы растут линейно | Интерфейсы привязаны к VRF |
| **Производительность** | Выше (меньше overhead) | Средняя (доп. объекты ядра) |
| **Сложность** | Средняя | Низкая (bind interface → done) |

Подробнее: **[VRF в Linux](../../../../Linux/Networking/vrf.md)**.

### Сценарий 6: Балансировка ECMP (Equal-Cost Multi-Path)

**Принцип:** Если до цели есть несколько маршрутов с одинаковой метрикой, трафик распределяется между ними.
- В Linux реализуется через `nexthop` в команде `ip route`.
- Позволяет суммировать пропускную способность каналов.
- Важно: во избежание Out-of-Order пакетов распределение обычно идет по хешу от 5-tuple потока.

**Настройка в Linux (Practical):**

```bash
# Вариант 1: Классический ECMP через nexthop
sudo ip route add default scope global \
    nexthop via 10.0.1.1 dev eth0 weight 1 \
    nexthop via 10.0.2.1 dev eth1 weight 1

# Вариант 2: Современный синтаксис через nexthop group (ядро 5.3+)
sudo ip nexthop add id 10 via 10.0.1.1 dev eth0
sudo ip nexthop add id 20 via 10.0.2.1 dev eth1
sudo ip nexthop add id 100 group 10/20   # ECMP группа
sudo ip route add default nhid 100

# Веса ( unequal-cost ECMP, kernel 5.2+)
sudo ip nexthop add id 11 via 10.0.1.1 dev eth0
sudo ip nexthop add id 21 via 10.0.2.1 dev eth1
sudo ip nexthop add id 101 group 11/21  # equal weight по умолчанию

# Проверка
ip route show
ip route get 8.8.8.8  # покажет nexthop group
ip -d route show       # детали FIB: hash buckets, multipath
```

**Важно:** при нефиксированном направлении (source IP может меняться) ECMP может вызвать Out-of-Order пакеты. Решение: `fib_multipath_hash_policy` или `ecmp` hash policy в ядре Linux.

### Сценарий 7: Blackhole маршрутизация (Null-routing)

**Задача:** Мгновенно заблокировать трафик к определенному IP или от него (например, при DDoS-атаке).
- Пакет направляется в «черную дыру» (в Linux: `ip route add blackhole <IP>`).
- Ядро отбрасывает пакет без отправки ICMP-ответа «Host Unreachable», что экономит ресурсы CPU.

**Настройка в Linux (Practical):**

```bash
# Blackhole: молча отбрасывает пакеты (без ICMP)
sudo ip route add blackhole 10.0.0.5/32

# Unreachable: отбрасывает + отправляет ICMP Host Unreachable
sudo ip route add unreachable 10.0.0.6/32

# Prohibit: отбрасывает + отправляет ICMP Administratively Prohibited
sudo ip route add prohibit 10.0.0.7/32

# Проверка
ip route show table all | grep -E "blackhole|unreachable|prohibit"

# DDoS-защита: блокировка целых подсетей-атакеров
sudo ip route add blackhole 203.0.113.0/24

# Откат
sudo ip route del blackhole 10.0.0.5/32
```

**Черная дыра vs маршрутизатор (陶瓷搪瓷):**

| Тип | ICMP-ответ | Использование |
| :--- | :--- | :--- |
| `blackhole` | Нет | DDoS-блокировка, защита CPU |
| `unreachable` | Host Unreachable | Проверка целостности (diagnostics) |
| `prohibit` | Admin Prohibited | Межсетевая политика (firewall-like) |

### Сценарий 8: Anycast маршрутизация

Принцип: Один IP-адрес принадлежит множеству географически распределенных серверов.
- Глобальная сеть (через BGP) доставляет пакет до топологически ближайшего узла.
- Используется в DNS (Root-серверы, 8.8.8.8) и CDN.
- Обеспечивает высокую доступность: если один узел падает, маршрут к нему исчезает, и BGP перенаправляет трафик на следующий ближайший узел.

**Настройка Anycast (Linux/BGP):**

```bash
# 1. Присваиваем Anycast-адрес на loopback
sudo ip addr add 10.0.0.100/32 dev lo

# 2. Объявляем префикс через BGP (FRRouting)
sudo vtysh -c "configure terminal" \
  -c "router bgp 65000" \
  -c "address-family ipv4 unicast" \
  -c "network 10.0.0.100/32"

# 3. Все узлы анонсируют один и тот же префикс
#    BGP доставит пакет ближайшему по AS Path

# Проверка (на всех узлах)
ip addr show lo | grep 10.0.0.100
sudo vtysh -c "show ip bgp 10.0.0.100/32"
```

### Сценарий 9: Расхождение RIB и FIB (Dataplane Troubleshooting)

**Проблема:** Маршрут присутствует в таблице маршрутизации (RIB), но пакеты уходят по неверному пути или теряются. Это часто происходит после динамических изменений BGP, настройки ECMP или внедрения Policy-Based Routing (PBR).

**Методы диагностики:**
1.  **В Linux:** Вместо обычного `ip route` используйте эмуляцию решения forwarding plane. Важно указывать `from`, так как правила `ip rule` могут направлять пакеты в разные таблицы в зависимости от источника.
    ```bash
    ip route get <destination-ip> from <source-ip>
    ```
    *Результат покажет конкретную таблицу, выбранный интерфейс и source address.*
2.  **Проверка правил:** Если в основной таблице (`main`) маршрут верен, но пакет уходит не туда, проверьте `ip rule`. Пакет может вообще не доходить до таблицы `main`.
3.  **На сетевом оборудовании:** Разделяйте проверку логики (Control Plane) и реальности (Data Plane).
    ```cisco
    show ip route <prefix>    # Решение процесса маршрутизации (RIB)
    show ip cef <destination>  # Реальная запись в таблице пересылки (FIB)
    ```
    *Если между ними есть расхождение, проблему следует искать в процессе инсталляции маршрутов, next-hop resolution или сбоях аппаратных таблиц (TCAM).*

**Высокопроизводительные платформы (high-end роутеры)**

**Проблема:** В routing table (RIB) маршрут отображается корректно: next-hop есть, метрики нормальные, протокол сходится. Но data-plane не использует этот маршрут — пакеты не уходят, и сеть «работает частично».

**Причины:** чаще всего связаны с ограничениями ASIC, рекурсивным разрешением next-hop или проблемами с adjacency.

**Диагностика:**

1.  **Проверка программирования маршрута в FIB/CEF:**
    ```cisco
    show ip cef <prefix> detail
    ```
    *Показывает детали записи FIB: state, recursive resolution, adjacency, ASIC-specific флаги.*

2.  **Проверка adjacency и L2-револвинг next-hop:**
    ```cisco
    show adjacency detail
    show ip arp <next-hop>
    ```
    *Если next-hop не разрешается через adjacency (ARP/NDP не resolved, или adjacency invalid), пакеты не будут пересылаться despite наличия маршрута в RIB.*

3.  **Проверка hardware table и дропов на high-end платформах:**
    ```cisco
    show platform hardware qfp active feature cef drop
    ```
    *QFP (Quantum Flow Processor) — специализированный процессор пакетов на Cisco high-end платформах (ASR 9000, NCS 5500, CRS). Команда показывает счётчики дропов, вызванных ASIC-ограничениями, ошибками adjacency, или переполнением hardware table.*

**Решение:**
- Корректировка рекурсивного next-hop (проверка reachability next-hop через IGP или static route)
- Перераспределение нагрузки по ASIC (optimization hash distribution на multi-ASIC платформах)
- Оптимизация L3 adjacency (очистка stale adjacency через `clear adjacency`)
- Проверка максимального количества маршрутов/entry в FIB для high-end маршрутизаторов (сравнение `show ip cef summary` с capacity спецификацией платформы)
- При TCAM overflow — агрегация префиксов или firmware update ASIC

### Сценарий 10: Default route из нескольких источников (BGP, OSPF, Static)

**Проблема:** На маршрутизаторе одновременно живет default route (`0.0.0.0/0`) из BGP, OSPF и static. Все протоколы сообщают, что выход есть, но трафик стабильно уходит через один uplink. Проблема в том, что `show ip route` показывает только итоговое решение общей RIB — сам процесс выбора остается скрытым.

**Ключевая идея:** установка маршрута — это не одно решение, а цепочка **нескольких независимых решений**: BGP выбирает свой best path по своим атрибутам, OSPF — свой по метрике, общая RIB выбирает источник-победитель по [административной дистанции](../routing_protocols_equipment.md#таблица-административных-дистанций-типовые-значения), а FIB в итоге решает, куда физически уйдет пакет. Именно на стыках этих уровней возникают самые неприятные сюрпризы: протокол может иметь рабочий маршрут, который так и не попадет ни в RIB, ни в FIB.

**Диагностика по уровням (сверху вниз):**

1.  **Что BGP считает лучшим кандидатом** — собственное best-path решение BGP до того, как маршрут предложен в общую RIB:
    ```cisco
    show ip bgp 0.0.0.0
    ```
    *Вывод покажет все полученные варианты default с их атрибутами и пометку best (>); причина выбора — вес, LOCAL_PREF, AS_PATH и т.д. Подробнее: [BGP](../../../Protocols/bgp.md).*

2.  **Что держит у себя OSPF** — внутренняя RIB процесса OSPF:
    ```cisco
    show ip ospf rib 0.0.0.0
    ```
    Здесь может выясниться, что оба протокола имеют рабочий default, но в общую RIB попадает только один: побеждает источник с меньшей AD (static = 1, eBGP = 20, OSPF = 110). Остальные маршруты остаются «в тени» своего протокола и не видны в `show ip route`.

3.  **Проверка конкретного потока** — эмуляция решения data plane для пары адресов:
    ```cisco
    show ip cef exact-route <src> <dst>
    ```
    *Показывает реальный интерфейс и next-hop, через которые данный поток будет отправлен. Критично при ECMP: распределение идет по хешу потока, поэтому разные пары src/dst могут уходить разными аплинками (см. Сценарий 6).*

4.  **Самый интересный случай:** выбранный RIB маршрут не устанавливается в FIB из-за проблем с рекурсивным разрешением next-hop (например, маршрут к next-hop сам исчез или не резолвится), и forwarding продолжает использовать другой доступный путь:
    ```cisco
    show ip cef 0.0.0.0 internal
    ```
    *Флаг internal раскрывает детали записи FIB, включая состояние recursive resolution. Результат: control plane убежден, что работает один канал, а пакеты реально уходят через другой.*

**Связь с другими сценариями:** частный случай расхождения Control Plane и Data Plane — см. Сценарий 9. Отличие в том, что здесь рассинхронизация возникает законно (проигравший по AD протокол) либо из-за неразрешенного рекурсивного next-hop, а не из-за сбоя инсталляции.

### Сценарий 10: Мультикаст и RPF-проверка

**Задача:** Обеспечить корректную доставку мультикаст-трафика при наличии асимметричной маршрутизации.

**Проблема:** В режиме PIM-SM (Protocol Independent Multicast — Sparse Mode) маршрутизатор выполняет RPF (Reverse Path Forwarding) проверку: пакет принимается только если он пришёл через интерфейс, который является «правильным» путём обратно к источнику. При асимметрии (разные пути для исходящего и входящего трафика) RPF-проверка может отбрасывать легитимные пакеты.

**Решение:**

```bash
# 1. Проверка RPF для конкретного источника
ip route get 10.0.0.1  # → какой интерфейс будет использован

# 2. Статический маршрут для RPF (если маршрут не symmetrical)
sudo ip route add 10.0.0.0/24 via 192.168.1.1

# 3. Проверка RPDB — какой интерфейс будет chosen для RPF
ip rule show
ip route get 10.0.0.1 from 192.168.100.50  # → source-specific lookup

# 4. Проверка через SNMP/Netlink
ip maddr show                    # мультикаст-адреса
cat /proc/net/igmp                # IGMP-состояние
```

**Подробнее:** [RPF и uRPF](../../../Protocols/rpf_urpf.md).

## Диагностика маршрутизации

### Диагностические команды Linux

```bash
# === Таблицы маршрутизации ===

# Просмотр всех таблиц
ip route show
ip route show table all                    # все таблицы (включая локальную, main, default)

# Поиск маршрута для конкретного IP (эмуляция FIB-решения)
ip route get 8.8.8.8
ip route get 8.8.8.8 from 192.168.1.10     # с указанием source (PBR)
ip route get 8.8.8.8 vrf vrf-prod           # внутри VRF

# Проверка правил (RPDB)
ip rule show
ip rule show table all                     # все правила с таблицами

# Проверка ARP/NDP (L2-револвинг)
ip neigh show
ip -6 neigh show

# === Мульти-path и ECMP ===

# Детали FIB (multipath, hash)
ip -d route show
ip -d route get 8.8.8.8  # → покажет nexthop, hash, flags

# Nexthop groups (ядро 5.3+)
ip nexthop show
ip nexthop get id 100

# === Мониторинг и логи ===

# Счётчики протоколов
nstat -az | grep -E "IpRoute|IpFrag|ICMP"
cat /proc/net/snmp | grep -E "Ip:|Tcp:|Udp:"

# Логирование изменений маршрутизации (auditd)
ausearch -k routing_changes -ts recent

# Проверка sysctl
sysctl net.ipv4.ip_forward
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.default.rp_filter
```

### Диагностические команды (Cisco/Network Equipment)

```cisco
# === Control Plane vs Data Plane ===

show ip route                              # RIB (все маршруты)
show ip route <prefix>                     # конкретный маршрут в RIB
show ip cef <destination>                  # FIB (реальная запись пересылки)
show ip cef exact-route <src> <dst>        # эмуляция для конкретного потока
show ip cef 0.0.0.0 internal              # детали записи FIB + recursive resolution

# === Протоколы маршрутизации ===

show ip bgp summary                        # статус BGP-сессий
show ip bgp 0.0.0.0                       # BGP best path для default route
show ip ospf neighbor                      # соседи OSPF
show ip ospf rib 0.0.0.0                  # внутренняя RIB OSPF
show ip ospf database                      # LSDB (Link-State Database)

# === Диагностика проблем ===

show ip arp                                # ARP-таблица (L2-револвинг next-hop)
show interface <if> | include drops        # счётчики потерь
debug ip routing                           # отладка изменений (аккуратно!)
debug ip packet detail <ACL>               # отладка пересылки конкретных пакетов
```

### Инструменты диагностики

| Инструмент | Назначение | Пример команды |
| :--- | :--- | :--- |
| `ip route get` | Эмуляция FIB-решения для IP | `ip route get 8.8.8.8 from 10.0.0.1` |
| `ip rule show` | Просмотр RPDB-правил | `ip rule show table all` |
| `mtr` | Трассировка с метриками по хопам | `mtr -rwc 100 8.8.8.8` |
| `traceroute` | Пошаговый путь до цели | `traceroute -n -I 8.8.8.8` |
| `tcpdump` | Захват пакетов на интерфейсе | `tcpdump -i eth0 -n 'host 8.8.8.8'` |
| `nftables` | Фильтрация/маркировка для отладки | `nft add rule ip mangle prerouting ip saddr 10.0.0.5 meta mark set 99` |
| `show ip cef` | Просмотр FIB (Cisco) | `show ip cef exact-route 10.0.0.1 8.8.8.8` |
| `bgpstream` | Анализ аномалий BGP в реальном времени | `bgpstream -p ris-live -f prefixes=8.8.8.0/24` |

## Безопасность маршрутизации

### Типичные атаки на маршрутизацию

| Атака | Описание | Защита |
| :--- | :--- | :--- |
| **BGP Hijacking** | Объявление чужого префикса через BGP | RPKI/ROA, BGPsec, мониторинг BGPStream |
| **Route Leak** | Ошибочное распространение транзитных маршрутов | BGP-политики, Prefix-List, AS-Path filters, IRR |
| **IP Spoofing** | Подмена IP-адреса источника пакета | `rp_filter=1` (Strict), uRPF, BCP38/84 |
| **ARP Spoofing** | Подмена MAC-адреса в ARP-таблице | DHCP Snooping, Dynamic ARP Inspection (DAI) |
| **ICMP Redirect** | Маршрутизатор перенаправляет хост на другой маршрут | Отключение: `net.ipv4.conf.all.accept_redirects=0` |
| **PMTU Black Hole** | Фрагментированные пакеты не доходят из-за неподдержки ICMP | `net.ipv4.ip_no_pmtu_disc=0`, Path MTU Discovery |
| **Source Routing** | Пакет содержит маршрут в заголовке IP (opzione route) | Отключение: `net.ipv4.conf.all.accept_source_route=0` |

### Рекомендуемые sysctl для безопасности

```bash
# Защита от IP Spoofing (rp_filter)
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.default.rp_filter=1

# Отключение опасных маршрутизирующих сообщений
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.all.accept_source_route=0

# Защита от ICMP Flood
net.ipv4.icmp_echo_ignore_broadcasts=1
net.ipv4.icmp_ratelimit=100
net.ipv4.icmp_ratemask=88089

# BCP38/84: фильтрация обратного пути
net.ipv4.conf.all.rp_filter=1
```

## Дополнительная информация

### Типичные ошибки
- **Маршрут на IP вместо сети:** Попытка добавить `10.0.0.5/24` вместо `10.0.0.0/24`. Всегда обнуляйте хостовую часть адреса в таблицах.
- **Забытый IP Forwarding:** На Linux-сервере, выступающем в роли роутера, должен быть включен параметр `net.ipv4.ip_forward = 1`.
- **ECMP без фиксации направления:** При нефиксированном source IP пакеты могут теряться или приходить в неверном порядке. Используйте `fib_multipath_hash_policy` или фиксируйте source.

### Связь с соседними уровнями OSI

- **[Сетевой уровень (L3)](./network_layer_overview.md)** — основы маршрутизации и IP-адресации.
- **[Протоколы и оборудование L3](../routing_protocols_equipment.md)** — BGP, OSPF, статическая и динамическая маршрутизация.
- **[MTU и PMTUD](../mtu_and_vpn.md)** — проблемы фрагментации и Path MTU Discovery.
- **[RPF и uRPF](../../../Protocols/rpf_urpf.md)** — проверка обратного пути и защита от IP Spoofing.

### См. также

- **[Маршрутизация в Linux](../../../../Linux/SystemAdministration/routing.md)** — команды и диагностика (`ip route`, `ip rule`, `nexthop`).
- **[PBR в Linux](../../../../Linux/Networking/Policy_Based_Routing/index.md)** — архитектура и база данных правил RPDB.
- **[Сценарии PBR](../../../../Linux/Networking/Policy_Based_Routing/scenarios.md)** — Dual-ISP, VPN-split, балансировка.
- **[VRF в Linux](../../../../Linux/Networking/vrf.md)** — изоляция L3-доменов.
- **[BGP: Глубокое погружение](../../../Protocols/bgp.md)** — атрибуты, сессии, Anycast.
- **[Протокол OSPF](../../../Protocols/ospf.md)** — Link-State маршрутизация.
- **[IP-пакет: структура](../Protocols/ip_packet_structure.md)** — заголовок IP, TTL, Protocol Number.
