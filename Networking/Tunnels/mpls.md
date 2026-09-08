# MPLS (Multiprotocol Label Switching) — коммутация по меткам

## Определения

**MPLS (Multiprotocol Label Switching)** — технология высокопроизводительной передачи данных, работающая на уровне L2 (канального уровня, по терминологии RFC 2828; часто обозначается как L2.5 из-за положения заголовка между Ethernet и IP). Она объединяет гибкость маршрутизации L3 со скоростью коммутации L2, используя фиксированные метки (labels) для принятия решений о пересылке вместо анализа длинных IP-заголовков.

> **Важный нюанс терминологии:** MPLS формально является L2-технологией (согласно RFC 2828, секция 22). Заголовок MPLS (Shim Header) вставляется между L2-заголовком (Ethernet) и L3-заголовком (IP), образуя два L2-заголовка одного уровня. Это аналогично инкапсуляции IP-в-IP — второй IP-пакет не становится L4. Обозначение «L2.5» является распространённым, но неформальным.

**LSR (Label Switching Router)** — маршрутизатор, поддерживающий MPLS.
- **Ingress LER (Label Edge Router):** Входной узел. Классифицирует входящий IP-пакет, определяет его FEC и накладывает (Push) одну или несколько меток.
- **Transit LSR (P-Router):** Промежуточный узел ядра. Выполняет замену (Swap) входящей метки на исходящую на основе таблицы LFIB.
- **Egress LER:** Выходной узел. Снимает (Pop) последнюю метку и передает пакет получателю (обычно через классическую IP-маршрутизацию).

**LSP (Label Switched Path)** — однонаправленный виртуальный путь через MPLS-сеть, по которому следуют пакеты с одинаковыми метками.

**FEC (Forwarding Equivalence Class)** — группа пакетов (например, с общим префиксом назначения или одинаковым классом обслуживания), которые обрабатываются идентично и коммутируются по одному и тому же LSP.

**PHP (Penultimate Hop Popping)** — оптимизация, при которой предпоследний LSR снимает транспортную метку. Это избавляет выходной LER от «двойного просмотра» (сначала в таблице меток, затем в таблице маршрутизации IP).

---

## Применимость в корпоративных сетях (Enterprise)

MPLS в Enterprise имеет смысл только при наличии потребности в сервисах, которые он предоставляет (L3VPN, L2VPN, TE, QoS через метки). Если таких потребностей нет в горизонте нескольких лет, внедрение MPLS является неоправданным усложнением сети: требуется минимум один протокол динамического распределения меток (LDP, RSVP-TE или SR), что добавляет сложности без извлекаемой выгоды.

Enterprise, чья транспортная сеть сопоставима по масштабу с операторской (например, транснациональные корпорации с собственной глобальной транспортной сетью), могут рассматривать MPLS как viable вариант. В остальных случаях достаточным решением являются оверлейные технологии (VXLAN, IPsec, SD-WAN).

---

## Основные концепции

### Плоскости сетевого устройства

Сетевое устройство традиционно делится на три плоскости:

- **Data Plane (Датаплейн):** Передача и обработка целевого (пользовательского) трафика. В современных устройствах реализован на специализированных микросхемах **ASIC** (Application Specific Integrated Circuit). ASIC обеспечивает аппаратную обработку на сверхвысоких скоростях, но имеет ограниченную гибкость по сравнению с CPU. Если появляется новый протокол, его поддержка в ASIC реализуется только при следующем поколении чипов.
- **Control Plane (Контролплейн):** Передача и обработка служебного трафика (протоколы маршрутизации, LDP, RSVP-TE). Реализуется на CPU. Объёмы контрол-трафика несопоставимы с дата-трафиком, поэтому хватает производительности обычных процессоров (не обязательно топовых). Гибкость: для поддержки нового протокола достаточно обновить сетевую операционную систему (НОС), устройство менять не нужно.
- **Management Plane (Менеджментплейн):** Передача и обработка трафика управления (SSH, Telnet, SNMP, Netconf, sFlow/NetFlow). Часто реализуется на том же CPU, что и Control Plane, что позволяет вендорам объединять их в единый «управляющий плейн».

> **Важно:** Конкретный протокол всегда однозначно принадлежит одной из плоскостей. Нет протоколов, одновременно относящихся к Data и Control или к Control и Management.

Маршрутизация относится к Control Plane, а форвардинг — к Data Plane. Это ключевое различие: маршрутизация — процесс определения пути (Next Hop), а форвардинг — процесс передачи пакетов на основе готовой информации (таблицы FIB/LFIB). На маршрутизаторах без ASIC форвардинг также выполняется на CPU, но не перестаёт быть форвардингом.

### Структуры данных в LSR

1.  **LIB (Label Information Base):** Хранит все метки, полученные от соседних узлов через протоколы распределения метков. Аналог RIB для маршрутов. Хранится в RAM.
2.  **FIB (Forwarding Information Base):** Классическая таблица маршрутизации IP. Содержит только лучшие маршруты (после selection process из RIB). На ASIC-устройствах хранится в TCAM; на software-устройствах — в RAM.
3.  **LFIB (Label Forwarding Information Base):** Таблица, используемая Data Plane для коммутации. Связывает входящую метку и интерфейс с исходящей меткой и следующим узлом (Next Hop). На ASIC хранится в TCAM; на software — в RAM. Размер LFIB несопоставимо меньше FIB за счёт агрегации маршрутов в FEC.

**Структуры записей для работы с метками:**

- **FTN (FEC-to-NHLFE Map):** Соответствие FEC-записи NHLFE. Работает на Ingress LER (LER принимает трафик без метки, определяет FEC по Destination IP и выбирает NHLFE, содержащую выходную метку и интерфейс).
- **ILM (Incoming Label Map):** Отображает входной интерфейс и входную метку в выходной интерфейс и выходную метку. Работает на Transit LSR/P-Router.
- **NHLFE (Next Hop Label Forwarding Entry):** Содержит информацию о выходном интерфейсе, выходной метке и (опционально) nexthop для данного FEC.

### Заголовок MPLS (Shim Header)

MPLS вставляет 4-байтовый заголовок между заголовками L2 (Ethernet) и L3 (IP).

| Поле | Размер | Описание |
| :--- | :--- | :--- |
| **Label** | 20 бит | Значение метки (0–1048575). Метки 0–15 зарезервированы. |
| **TC (Traffic Class)** | 3 бита | Ранее EXP. Используется для QoS (приоритезация трафика). Может маппироваться 1:1 на CoS в VLAN-теге. Возможных значений 8, что недостаточно для полного DSCP (64 значения). |
| **S (Bottom of Stack)** | 1 бит | Указывает, является ли эта метка последней в стеке (1 — последняя). |
| **TTL (Time to Live)** | 8 бит | Аналог TTL в IP. Защищает от бесконечных циклов в LSP. Фактически является hop limit, как в IPv6. |

### Стек меток (Label Stack)

MPLS позволяет накладывать несколько меток на один пакет. Это основа для иерархических сервисов:
- **Транспортная метка (Top Label):** Доставляет пакет через ядро сети к нужному PE-маршрутизатору.
- **Сервисная метка (Bottom Label):** Определяет, какому клиенту (VRF) или интерфейсу (L2VPN) принадлежит пакет на выходе.

**Направление роста стека:** Стек растёт в сторону L2-заголовка (влево). Последняя метка (Bottom of Stack) находится ближе всего к L3-заголовку. Для добавления верхней метки она помещается между L2 и текущей верхней меткой.

**Глубина стека:** Теоретически не ограничена протоколом, но на практике ограничена аппаратной реализацией ASIC (обычно 5–8 меток). Если приходит пакет со стеком, превышающим поддерживаемую глубину, он отбрасывается.

### Назначение меток (Label Distribution)

Ключевое правило: **метка всегда назначается downstream-маршрутизатором** (тем, кто ближе к месту назначения). Upstream-маршрутизатор (ближе к источнику) только получает информацию о метке и помечает ею пакеты.

- Направление назначения меток: от Egress LER через все Transit LSR к Ingress LER для конкретного FEC.
- Направление движения трафика: от Ingress LER через Transit LSR к Egress LER.
- Аналогия с BGP: если маршрут передаётся справа налево, трафик по нему идёт слева направо. То же самое с метками.

Для обратного трафика метки назначаются независимо и могут отличаться от прямых (симметрия не гарантирована).

### Операции с метками

Всего три операции, выполняемые независимо для каждого уровня стека:

- **Push:** Наложение метки (Ingress LER). Если стек уже содержит метки, новая метка добавляется поверх.
- **Swap:** Замена метки на следующем значении (Transit LSR). Даже если значение не меняется, Swap всё равно выполняется, потому что изменяется TTL (декрементируется на 1). Поэтому 4 байта заголовка перезаписываются в любом случае.
- **Pop:** Снятие метки (Egress LER или Penultimate LSR при PHP).

### Масштабирование за счёт FEC

MPLS не кодирует Destination IP в метке. Метка — это локальный идентификатор фиксированной длины, ассоциированный с FEC. Экономия достигается за счёт агрегации:
- Если в FIB миллион префиксов, а FEC определяется агрегированным префиксом /24, меток может быть всего ~40 000.
- Поиск по таблице меток (LFIB) выполняется значительно быстрее, чем Longest Prefix Match по таблице форвардинга (FIB).

### MPLS и плоскости устройства

При работе с MPLS:
- **Data Plane:** ASIC обрабатывает заголовок MPLS, выполняет Swap/Pop и форвардинг.
- **Control Plane:** CPU обрабатывает протоколы распределения меток (LDP, RSVP-TE, BGP-LU), строит LIB и формирует LFIB.
- **Management Plane:** Один CPU с Control Plane; управление через CLI, SNMP, Netconf.

В аварийных ситуациях администратор может получить прямой доступ к Data Plane (просмотреть содержимое TCAM/регистров ASIC) для диагностики несоответствий между Control Plane и реальной программой ASIC.

### MPLS как L2-технология

Согласно RFC 2828, секция 22, MPLS является L2-технологией. Заголовок MPLS (Shim Header) вставляется между L2 (Ethernet) и L3 (IP), образуя два заголовка одного уровня. Это аналогично инкапсуляции IP-in-IP: второй IP-пакет не становится L4. Обозначение «L2.5» — распространённый, но неформальный эвфемизм.

### Segment Routing (SR-MPLS)

Современная эволюция MPLS, где путь кодируется как список сегментов (меток) в заголовке пакета на входном узле.
- **Преимущества:** Устраняет необходимость в LDP и RSVP-TE. Все управление путями переносится в расширения IGP или SDN-контроллер.
- **Масштабируемость:** Не требует хранения состояния путей на промежуточных узлах (Stateless core).

---

## Протоколы управления (Control Plane)

Отвечают за обмен информацией о маршрутах и распределение меток для построения LSP.

### LDP (Label Distribution Protocol)

- Основной протокол для автоматического построения LSP на основе топологии IGP (OSPF/IS-IS).
- Работает по принципу "Hop-by-Hop": каждый узел доверяет IGP в выборе кратчайшего пути.
- Транспорт: UDP 646 (обнаружение соседей), TCP 646 (сессия обмена метками).
- RFC 5036, 6720, 7552.
- Создан на основе проприетарного протокола **TDP** (Tag Distribution Protocol) от Cisco.
- **LSP Trigger:** По умолчанию назначает метки только для /32 (host routes). Доступные режимы: `lsp-trigger all` (все FEC), `lsp-trigger ip-prefix-list` (выборочно), `lsp-trigger none` (отключено).

### RSVP-TE (Resource Reservation Protocol — Traffic Engineering)

- Используется для построения путей с заданными параметрами (пропускная способность, задержка).
- Поддерживает явную маршрутизацию (Explicit Routing), позволяя строить пути в обход кратчайшего маршрута IGP.

### BGP-LU (Labeled Unicast)

- Передача меток внутри BGP сессий (RFC 3107). Часто используется в Inter-AS MPLS и больших иерархических сетях.

### MP-BGP (Multiprotocol BGP)

- Распространяет метки для сервисов L2VPN, L3VPN, VPLS/EVPN.
- Используется в **Kompella mode** (для L2VPN/VPLS) в отличие от **Martini mode** (LDP для point-to-point L2VPN).

### Особенности работы нескольких протоколов

По стандарту, в одном MPLS-домене может одновременно использоваться несколько протоколов динамического распределения меток (аналогично нескольким IGP в одной сети). Метки от разных протоколов попадают в общий LIB, а LFIB формируется на его основе.

> **CR-LDP:** Устаревший протокол, полностью вытесненный RSVP-TE. На текущий момент не используется.

---

## Практические сценарии

### Версии ядра и пакетов

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **Ядро Linux** | 4.1 (базовая поддержка MPLS) | 5.10+ (полная поддержка, включая P2MP LSP) |
| **iproute2** | 3.12 | 5.15+ |
| **FRRouting** | 7.0 | 9.1+ (стабильный LDP, Segment Routing) |

### Аппаратные требования

- **CPU:** MPLS в Linux — программная реализация. Для высоких нагрузок (более 10 Гбит/с) рекомендуется использование DPDK или аппаратных NIC с поддержкой MPLS offload (Mellanox ConnectX-5+).
- **NIC:** Для аппаратного ускорения — Intel E810, Mellanox ConnectX-5/6. Поддержка RSS Over MPLS и checksum offload.
- **RAM:** Минимум 256 МБ для базовой маршрутизации. Для полной таблицы BGP + MPLS — от 2 ГБ.

### Установка зависимостей

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install frr iproute2 tcpdump

# RHEL/CentOS/Rocky
sudo dnf install frr iproute tcpdump

# Проверка версии FRR
vtysh -c "show version"
# → FRRouting 9.1.0 (...)
```

### Включение MPLS в ядре

MPLS-модули не загружаются автоматически. Без их загрузки таблицы LFIB будут пусты, а LDP-сессии не установятся.

```bash
# Загрузка модулей (временно)
sudo modprobe mpls_router
sudo modprobe mpls_iptunnel

# Проверка загрузки
lsmod | grep mpls
# → mpls_router           24576  0
# → mpls_iptunnel         16384  0

# Сохранение модулей для автозагрузки
echo "mpls_router" | sudo tee -a /etc/modules-load.d/mpls.conf
echo "mpls_iptunnel" | sudo tee -a /etc/modules-load.d/mpls.conf
```

### Настройка sysctl

```bash
# Лимит меток в таблице (максимум 1048575)
sudo sysctl -w net.mpls.platform_labels=1048575

# Включение MPLS на конкретных интерфейсах
sudo sysctl -w net.mpls.conf.eth0.input=1
sudo sysctl -w net.mpls.conf.eth1.input=1
sudo sysctl -w net.mpls.conf.lo.input=1

# Включение IP-форвардинга (обязательно для маршрутизатора)
sudo sysctl -w net.ipv4.ip_forward=1

# Сохранение настроек
cat <<EOF | sudo tee /etc/sysctl.d/90-mpls.conf
net.mpls.platform_labels = 1048575
net.mpls.conf.eth0.input = 1
net.mpls.conf.eth1.input = 1
net.mpls.conf.lo.input = 1
net.ipv4.ip_forward = 1
EOF

sudo sysctl -p /etc/sysctl.d/90-mpls.conf
```

**Важно:** Параметр `net.mpls.conf.<interface>.input` устанавливается **отдельно для каждого интерфейса**. При добавлении нового интерфейса необходимо повторить настройку — иначе метки на него приходить не будут, ошибок не будет, но трафик будет отброшен.

---

### Сравнение с оверлейными технологиями

| Характеристика | MPLS | VXLAN |
| :--- | :--- | :--- |
| **Уровень** | L2.5 (Shim) | L3 (UDP/IP Overlay) |
| **Оверхед** | 4 байта (на одну метку) | ~50 байт |
| **Аппаратная поддержка** | Требует специализированных ASIC | Широкая поддержка в современных NIC и коммутаторах |
| **Основное применение** | Магистрали ISP, L3VPN, Traffic Engineering | ЦОД, виртуализация, SD-WAN |

### Настройка MPLS в Linux (iproute2)

В современном Linux поддержка MPLS включена в ядро и управляется через `iproute2`.

#### 1. Подготовка системы

```bash
# Загрузка необходимых модулей
sudo modprobe mpls_router
sudo modprobe mpls_iptunnel

# Установка лимита меток и активация MPLS на интерфейсе
sudo sysctl -w net.mpls.platform_labels=100000
sudo sysctl -w net.mpls.conf.eth0.input=1
```

#### 2. Манипуляции с метками

**Наложение (Push) на Ingress:**
```bash
# Направить трафик к подсети 10.1.0.0/24 через шлюз с меткой 100
sudo ip route add 10.1.0.0/24 encap mpls 100 via inet 192.168.1.2 dev eth0
```

**Замена (Swap) на Transit LSR:**
```bash
# Пакеты с меткой 100 заменяем на метку 200 и отправляем дальше
sudo ip -f mpls route add 100 as 200 via inet 192.168.2.2 dev eth1
```

**Снятие (Pop) на Egress:**
```bash
# Снять метку 200 и передать пакет локальному стеку для маршрутизации IP
sudo ip -f mpls route add 200 dev lo
```

### Настройка через FRRouting (FRR)

FRR является индустриальным стандартом для реализации MPLS Control Plane на Linux.

#### Включение демонов

```bash
# Редактирование /etc/frr/daemons
sudo sed -i 's/^ldpd=no/ldpd=yes/' /etc/frr/daemons
# Убедитесь, что ospfd или isisd также включены (LDP требует IGP)

sudo systemctl restart frr
```

#### Пример настройки LDP в `vtysh`

```text
conf t
 !
 ! Router ID (обязательно — должен быть доступен через IGP)
 mpls ldp
  router-id 1.1.1.1
  !
  address-family ipv4
   discovery transport-address 1.1.1.1
   !
   interface eth0
   !
   interface eth1
   !
  exit-address-family
 !
end
write memory
```

#### Полный пример: LDP + OSPF (Ingress LSR)

```text
frr defaults traditional
hostname R1
!
interface eth0
 ip address 10.0.12.1/30
!
interface lo
 ip address 1.1.1.1/32
!
router ospf
 ospf router-id 1.1.1.1
 network 1.1.1.1/32 area 0
 network 10.0.12.0/30 area 0
!
mpls ldp
 router-id 1.1.1.1
 !
 address-family ipv4
  discovery transport-address 1.1.1.1
  !
  interface eth0
 !
!
end
```

#### Полный пример: Transit LSR (R2 между R1 и R3)

```text
frr defaults traditional
hostname R2
!
interface eth0
 ip address 10.0.12.2/30
!
interface eth1
 ip address 10.0.23.1/30
!
interface lo
 ip address 2.2.2.2/32
!
router ospf
 ospf router-id 2.2.2.2
 network 2.2.2.2/32 area 0
 network 10.0.12.0/30 area 0
 network 10.0.23.0/30 area 0
!
mpls ldp
 router-id 2.2.2.2
 !
 address-family ipv4
  discovery transport-address 2.2.2.2
  !
  interface eth0
  !
  interface eth1
 !
!
end
```

#### Полный пример: Egress LSR (R3)

```text
frr defaults traditional
hostname R3
!
interface eth0
 ip address 10.0.23.2/30
!
interface lo
 ip address 3.3.3.3/32
!
router ospf
 ospf router-id 3.3.3.3
 network 3.3.3.3/32 area 0
 network 10.0.23.0/30 area 0
!
mpls ldp
 router-id 3.3.3.3
 !
 address-family ipv4
  discovery transport-address 3.3.3.3
  !
  interface eth0
 !
!
end
```

### Диагностика и мониторинг

Для отладки LSP используются специализированные инструменты OAM (Operations, Administration, and Maintenance):

- **MPLS Ping:** Проверяет связность FEC по конкретному пути.
- **MPLS Traceroute:** Позволяет увидеть путь меток и обнаружить разрывы в LSP.

#### Просмотр таблиц

```bash
# Просмотр таблицы LFIB (ядро Linux)
ip -f mpls route show
# → UNICAST default via inet 10.0.12.2 dev eth0 metric 0

# Просмотр таблицы LDP-связок (FRR)
vtysh -c "show mpls ldp binding"
# → 1.1.1.1/32
# →   FEC: 1.1.1.1/32
# →     Local label: imp-null (PHP)
# →     Remote label: 16

# Просмотр соседей LDP
vtysh -c "show mpls ldp neighbor"
# → VRF: default
# →   LDP Id: 2.2.2.2:0, Transport address: 2.2.2.2
# →     State: OPERATIONAL
# →     Hold time: 30 sec

# Просмотр MPLS-интерфейсов
vtysh -c "show mpls interface"
# → Interface        State  Protocol  MTU
# → eth0             up     LDP       1500
# → eth1             up     LDP       1500

# Просмотр статистики по интерфейсу
ip -s link show eth0
# → eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
# →     RX:  bytes packets errors dropped  missed   mcast
# →     TX:  bytes packets errors dropped carrier collsns
```

#### Захват MPLS-трафика

```bash
# Просмотр MPLS-меток в реальном времени
sudo tcpdump -i eth0 -n -e mpls
# → 12:34:56.789012 eth0 Out IP 10.0.12.1 > 10.0.23.2: ICMP echo request
# →   MPLS label 16 exp 0 [S] ttl 64

# Просмотр LDP-сессий (TCP 646)
sudo tcpdump -i eth0 -n tcp port 646

# Просмотр LDP Hello (UDP 646)
sudo tcpdump -i eth0 -n udp port 646
```

#### Проверка работы LDP

```bash
# Проверка, что LDP-сессия установлена
vtysh -c "show mpls ldp discovery"
# → Local LDP Identifier: 1.1.1.1:0
# → Discovery Sources:
# →   Interfaces:
# →     eth0: xmit/recv
# →       LDP Id: 2.2.2.2:0, Transport address: 2.2.2.2
# →           Hold time: 15 sec

# Проверка, что метки установлены в ядро
ip -f mpls route show
# → Recursion failed to find nexthop for label 16
```

### Тестирование в лаборатории (Network Namespaces)

Для тестирования MPLS-конфигураций не требуются физические устройства. Linux network namespaces позволяют запускать изолированные экземпляры FRR на одном хосте:

```bash
# Создание изолированных пространств имён
ip netns add R1
ip netns add R2
ip netns add R3

# Создание veth-пар между R1 и R2
ip link add r1-eth0 netns R1 type veth peer name r2-eth0 netns R2
ip netns exec R1 ip addr add 10.0.12.1/30 dev r1-eth0
ip netns exec R1 ip link set r1-eth0 up
ip netns exec R1 ip link set lo up

ip netns exec R2 ip addr add 10.0.12.2/30 dev r2-eth0
ip netns exec R2 ip link set r2-eth0 up
ip netns exec R2 ip link set lo up

# Аналогично для R2-R3
ip link add r2-eth1 netns R2 type veth peer name r3-eth0 netns R3
ip netns exec R2 ip addr add 10.0.23.1/30 dev r2-eth1
ip netns exec R2 ip link set r2-eth1 up

ip netns exec R3 ip addr add 10.0.23.2/30 dev r3-eth0
ip netns exec R3 ip link set r3-eth0 up
ip netns exec R3 ip link set lo up

# Включение MPLS в каждом пространстве имён
for ns in R1 R2 R3; do
  ip netns exec $ns sysctl -w net.mpls.platform_labels=100000
  ip netns exec $ns sysctl -w net.ipv4.ip_forward=1
done

ip netns exec R1 sysctl -w net.mpls.conf.r1-eth0.input=1
ip netns exec R2 sysctl -w net.mpls.conf.r2-eth0.input=1
ip netns exec R2 sysctl -w net.mpls.conf.r2-eth1.input=1
ip netns exec R3 sysctl -w net.mpls.conf.r3-eth0.input=1

# Запуск FRR в каждом пространстве (с отдельным конфигом)
ip netns exec R1 frr -f /etc/frr/R1/frr.conf
ip netns exec R2 frr -f /etc/frr/R2/frr.conf
ip netns exec R3 frr -f /etc/frr/R3/frr.conf
```

### Отладка LDP-сессий

```bash
# Включение отладки LDP
vtysh -c "debug mpls ldp"
vtysh -c "debug mpls ldp discovery"
vtysh -c "debug mpls ldp messages recv"
vtysh -c "debug mpls ldp messages sent"

# Просмотр логов FRR
tail -f /var/log/frr/ldpd.log

# Типичные сообщения об ошибках:
# → "LDP session with neighbor X.X.X.X: no route to transport address"
#   Причина: transport-address не advertised через IGP
# → "LDP neighbor X.X.X.X: hold timer expired"
#   Причина: TCP-сессия не установлена или потеряны Hello-пакеты
```

---

## Типичные ошибки и их устранение

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| LDP-сессия в состоянии `INITIALIZED` | transport-address недоступен через IGP | Убедитесь, что loopback (router-id) объявлен в OSPF/IS-IS |
| Метки не появляются в `ip -f mpls route show` | Модуль `mpls_router` не загружен | `sudo modprobe mpls_router && sudo modprobe mpls_iptunnel` |
| MPLS-трафик дропается без ошибок | `net.mpls.conf.<iface>.input=0` | Включите MPLS на интерфейсе: `sysctl -w net.mpls.conf.eth0.input=1` |
| LDP Hello отправляются, но TCP не устанавливается | Firewall блокирует TCP 646 | Разрешите TCP 646 между LSR: `iptables -A INPUT -p tcp --dport 646 -j ACCEPT` |
| Метки поменялись, но трафик не идёт | Неверный nexthop или отсутствует маршрут к нему | Проверьте `ip route show` и `ip neigh show` для nexthop |
| PHP не работает (двойной lookup на Egress) | Egress LER не анонсирует `imp-null` | В FRR: `label local advertise explicit-null` |

---

## Безопасность

### Защита LDP-сессий

LDP не имеет встроенной аутентификации. Для защиты:

```text
mpls ldp
 neighbor 10.0.0.2 password MySecretKey
```

### Защита от подмены меток

- Фильтрация входящих MPLS-пакетов на границе сети.
- Использование GTSM (Generalized TTL Security Mechanism) — RFC 6720.

```text
mpls ldp
 address-family ipv4
  ttl-security hops 1
```

### ACL для MPLS-интерфейсов

```bash
# Разрешить MPLS только от доверенных соседей
sudo iptables -A INPUT -p mpls -s 10.0.12.0/24 -j ACCEPT
sudo iptables -A INPUT -p mpls -j DROP
```

---

## Ограничения и особенности

- **Без шифрования:** MPLS не шифрует данные. Для конфиденциальности требуется IPsec или MACsec.
- **Программная реализация в Linux:** В ядре MPLS — программная реализация. Для 40+ Гбит/с требуется DPDK или NIC с MPLS offload.
- **Ограничение стека:** В Linux поддерживается до 3 меток в стеке (ограничение ядра, не протокола).
- **MTU:** MPLS добавляет 4 байта на каждую метку. При стеке из N меток оверхед = 4×N байт. Убедитесь, что Path MTU учитывает этот оверхед.
- **Проблема фрагментации:** В отличие от IP, MPLS не поддерживает фрагментацию. Пакеты, превышающие MTU, отбрасываются.
- **Масштабирование LDP:** LDP не поддерживает явную маршрутизацию и не может учитывать пропускную способность. Для TE используется RSVP-TE или SR-MPLS.

---

## Дополнительная информация

- **[BGP: Глубокое погружение](../Protocols/bgp.md)** — использование расширенных сообществ для MPLS VPN.
- **[VRF в Linux](../../Linux/Networking/vrf.md)** — создание изолированных доменов маршрутизации для L3VPN.
- **[Segment Routing (SRv6)](../OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md)** — альтернативный подход к SR на базе IPv6.
- **[Туннелирование: Обзор](./tunneling_overview.md)** — сравнение с GRE, IPIP и VXLAN.
- **[FRRouting (FRR)](https://docs.frrouting.org/en/latest/ldpd.html)** — документация по LDP в FRR.
- **[RFC 5036](https://datatracker.ietf.org/doc/html/rfc5036)** — спецификация LDP.
