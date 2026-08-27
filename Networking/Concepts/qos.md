# QoS (Quality of Service)

## Определения

**QoS (Quality of Service)** — набор технологий для управления сетевым трафиком, позволяющий предоставлять различным типам данных разные приоритеты и гарантии обслуживания.

Ключевые параметры, на которые влияет QoS:
- **Bandwidth (Пропускная способность):** объем данных, передаваемый в единицу времени.
- **Latency (Задержка):** время прохождения пакета от отправителя к получателю (Serialization delay, Propagation delay, Queuing delay).
- **Jitter (Джиттер):** колебание задержки во времени. Критично для UDP-трафика (голос, видео).
- **Packet Loss (Потеря пакетов):** процент пакетов, не достигших цели. Обычно вызван переполнением очередей (tail drop).

Дополнительные важные параметры:
- **Goodput (Полезная пропускная способность):** реальный объем полезных данных, исключая заголовки, повторные передачи и переданные, но отброшенные пакеты.
- **Availability (Доступность):** процент времени, в течение которого сеть доступна для обслуживания трафика (целевые значения для VoIP — 99.999%, "пять девяток").

## Предварительные требования

Перед настройкой QoS необходимо иметь представление о топологии сети, характерных потоках и точках управления трафиком.

### Среда и инструменты
- **ОС:** Linux с пакетом `iproute2` (утилита `tc`). В Debian/Ubuntu: `sudo apt install iproute2`. В RHEL/CentOS/Fedora: `sudo dnf install iproute`.
- **Аппаратное обеспечение:** NIC, поддерживающий Multi-Queue (mq), для распределения очередей по ядрам CPU.
- **Доступ:** root-права для изменения дисциплин очередей.
- **Базовая диагностика:** `ip link show`, `ethtool -S eth0` (статистика интерфейса), `ss`, `tcpdump`.

### Точка Trust Boundary
Правила классификации и маркировки должны применяться как можно ближе к источнику трафика (сервер, рабочия станция, точка доступа). За пределами доверенной зоны маркировка может быть сброшена или подменена.

### Зависимости от других технологий
- **[Структура IP-пакета](../OSI_TCP_IP_Model/Network_layer/Protocols/ip_packet_structure.md)** — поля DSCP/ECN в заголовке.
- **[VLAN — виртуальные сети](../../Protocols/VLAN/vlan_8021q_frame.md)** — поле PCP/CoS в теге 802.1Q.
- **[LLDP-MED](../../Protocols/lldp.md)** — распределение политик QoS через Network Policy TLV.
- **[DHCP: Обзор](../../Protocols/DHCP/dhcp_overview.md)** — опция 114 для автоматической передачи политик QoS.
- [Алгоритмы управления перегрузкой TCP](../../Protocols/TCP/congestion/tcp_congestion_control_overview.md) — взаимодействие AQM и алгоритмов TCP.

## Модели и архитектуры QoS

Существует три основные модели реализации качества обслуживания в сетях:

1. **Best Effort (Максимальные усилия):** модель по умолчанию. Сеть обрабатывает все пакеты одинаково, не давая никаких гарантий. Используется в Internet.
2. **IntServ (Integrated Services):** резервирование ресурсов «сквозным» методом от отправителя до получателя для каждого потока данных. Использует протокол **RSVP** (Resource Reservation Protocol). Масштабируемость низкая, так как роутеры должны хранить состояние каждого потока (stateful).
3. **DiffServ (Differentiated Services):** современный стандарт. Трафик классифицируется на границе сети (Edge), маркируется, и промежуточные узлы (Core) обрабатывают его на основе меток (**Per-Hop Behavior, PHB**). Высокая масштабируемость (stateless core).

### Архитектура Edge-to-Core
- **Edge Router (Граница):** классификация, маркировка (DSCP), policing, accounting.
- **Core Router (Ядро):** обработка только на основе меток (PHB), без хранения состояния потоков.
- **Access Layer:** конечные устройства (IP-телефоны, камеры), получающие приоритет через L2 CoS (PCP) или L3 DSCP.

## Основные механизмы

Процесс обработки QoS обычно делится на несколько этапов:

| Механизм | Описание |
| :--- | :--- |
| **Классификация** | Идентификация трафика (ACL, NBAR, DPI, Flower). Определение, к какому классу относится пакет. |
| **Маркировка** | Установка меток в заголовки (DSCP на L3, PCP на L2). |
| **Congestion Management** | Управление очередями при наличии затора. Алгоритмы планирования (FIFO, PQ, WFQ, CBWFQ, HTB). |
| **Congestion Avoidance** | Предотвращение перегрузок до переполнения очередей (WRED, ECN). |
| **Conditioning** | Приведение трафика к заданному профилю скорости (Policing и Shaping). |

## Классификация и маркировка

Для того чтобы сетевые устройства понимали, как обрабатывать пакет, он должен быть промаркирован как можно ближе к источнику (**Trust Boundary**).

### Уровень L2 (Data Link)
Используется поле **PCP (Priority Code Point)** в теге 802.1Q (VLAN). Поле состоит из 3 бит (значения 0–7):
- **0 (Best Effort):** стандартный трафик.
- **1 (Background):** фоновый трафик (peer-to-peer, бэкапы).
- **3 (Best Effort — Class 1):** критичный при трафике Best Effort.
- **4 (Video — Class 2):** видеотрафик низкого приоритета (видеонаблюдение).
- **5 (Voice):** рекомендуемый приоритет для голоса.
- **6 (Video — Class 1):** видеоконференции, стриминг.
- **7 (Control):** критический сетевой трафик (Routing protocols, LLDP).

### Уровень L3 (Network)
Используется поле **DSCP (Differentiated Services Code Point)** в заголовке IPv4/IPv6 (6 бит). DSCP определяет **PHB (Per-Hop Behavior)** — способ обработки пакета узлом.

#### Основные классы DSCP:
- **Default (BE / CS0):** значение 0. Стандартный трафик.
- **EF (Expedited Forwarding):** значение 46. Гарантирует низкую задержку и джиттер. Используется для VoIP.
- **AF (Assured Forwarding):** гарантированная доставка. Делится на 4 класса, в каждом 3 уровня вероятности сброса (Drop Precedence).
  - Формат: `AFxy`, где `x` — класс (1-4, приоритет очереди), `y` — вероятность сброса (1-3, выше — вероятнее сброс).
  - Пример: `AF41` (высокий приоритет, низкий риск сброса) против `AF43` (высокий приоритет, высокий риск сброса).
- **CS (Class Selector):** значения CS1–CS7 для обратной совместимости с IP Precedence.
- **LE (Lower Effort):** значение 8 (бывший IP Precedence 1). Используется для фонового трафика, который должен уступать дорогу Best Effort.

#### ECN (Explicit Congestion Notification)
Использует последние 2 бита поля Traffic Class/ToS. Позволяет узлу уведомлять отправителя о заторе **без отбрасывания пакетов**.
- Роутер выставляет бит **CE (Congestion Experienced)**.
- Получатель уведомляет отправителя (через TCP флаги ECE/CWR).
- Отправитель снижает скорость передачи.
- Критично для современных протоколов и L4S.

### IPv6 Flow Label
Поле **Flow Label** (20 бит) в заголовке IPv6 позволяет помечать пакеты одного логического потока. Роутеры могут использовать это поле для QoS и балансировки (ECMP) без глубокого разбора заголовков TCP/UDP.

### Маркировка в Linux (iptables/nftables)
Для маркировки пакетов на хосте используются правила `iptables` (legacy) или `nftables` (современный):

```bash
# iptables (legacy): пометить SIP/VoIP трафик значением EF (DSCP 46)
sudo iptables -t mangle -A OUTPUT -p udp --dport 5060 -j DSCP --set-dscp-class EF
sudo iptables -t mangle -A OUTPUT -p udp --dport 5061 -j DSCP --set-dscp-class EF

# Видеоконференции (например, STUN/TURN на 3478) — AF41
sudo iptables -t mangle -A OUTPUT -p tcp --dport 3478 -j DSCP --set-dscp-class AF41
sudo iptables -t mangle -A OUTPUT -p udp --dport 3478 -j DSCP --set-dscp-class AF41

# Фоновый/Bulk трафик (торренты, бэкапы) — CS1 (ниже Best Effort)
sudo iptables -t mangle -A OUTPUT -p tcp --dport 6881:6889 -j DSCP --set-dscp-class CS1

# nftables (современный): аналогичные правила
sudo nft add rule inet filter forward ip dscp set ef udp dport { 5060, 5061 }
sudo nft add rule inet filter forward ip dscp set af41 tcp dport 3478
```

### L7 Классификация (NBAR / DPI)
Когда классификации по портам L4 недостаточно (например, для HTTPS на порту 443), используются:
- **NBAR (Network Based Application Recognition):** технология Cisco для анализа сигнатур приложений.
- **DPI (Deep Packet Inspection):** глубокий анализ содержимого пакетов для идентификации приложений (Skype, Torrent, Zoom).

## Управление скоростью: Policing и Shaping

| Характеристика | Policing (Ограничение) | Shaping (Сглаживание) |
| :--- | :--- | :--- |
| **Действие** | Мгновенно отбрасывает (drop) избыток | Задерживает в буфере (delay) |
| **Влияние на задержку** | Не вносит задержек | Увеличивает задержку (буферизация) |
| **Применение** | Обычно Ingress (вход от провайдера) | Обычно Egress (выход в сторону провайдера) |
| **Результат** | «Зубчатый» график скорости, много ретрансмиссий TCP | «Плавный» график скорости |

### Входящий Policing через ingress qdisc
Linux поддерживает нативный ingress policing через специальную qdisc `ingress` (handle `ffff:`):

```bash
# Ограничение входящего трафика на eth0 до 50 Мбит/с
sudo tc qdisc add dev eth0 handle ffff: ingress
sudo tc filter add dev eth0 parent ffff: protocol ip prio 10 \
    u32 match ip src 0.0.0.0/0 police rate 50mbit burst 10k drop
```

### H-QoS (Hierarchical QoS)
Иерархический QoS позволяет применять политики на нескольких уровнях.
- **Верхний уровень:** ограничение общей полосы для физического интерфейса или VLAN.
- **Нижний уровень:** распределение этой полосы между классами трафика (Voice, Data, Guest) внутри родительского шейпера.

## Алгоритмы управления очередями (Qdisc)

### Классификация дисциплин

| Дисциплина | Назначение | Особенности |
|------------|------------|-------------|
| **HTB** | Иерархический шейпинг | Гибкость, заимствование полосы, требует настройки фильтров. |
| **CAKE** | "Все в одном" | Идеально для интернет-шлюзов, авто-bufferbloat, host-fairness. |
| **fq_codel** | AQM (Active Queue Management) | Стандарт де-факто для LAN, минимизирует задержки. |
| **fq** | Fair Queuing + Pacing | Необходима для работы алгоритма **TCP BBR**. |
| **netem** | Эмуляция проблем | Задержки, потери, дублирование (для тестов). |
| **mq / mqprio** | Multi-queue | Оптимизация для многоочередных сетевых карт. |

### Multi-Queue (mq / mqprio)
Современные NIC поддерживают несколько аппаратных очередей (Hardware Queues). Дисциплина `mq` или `mqprio` распределяет эти очереди по доступным CPU-ядрам, снижая contention и повышая пропускную способность на десятках Гбит/с.

### Flower (современная классификация)
Классификатор `flower` позволяет использовать возможности аппаратной выгрузки (Hardware Offload):

```bash
# Направить трафик на порт 80 в класс 1:10
sudo tc filter add dev eth0 parent 1: protocol ip flower ip_proto tcp dst_port 80 flowid 1:10

# Аппаратная выгрузка фильтра (требуется поддержка драйвером)
sudo tc filter add dev eth0 ingress protocol ip flower \
    skip_sw dst_ip 192.168.1.100 action drop
# `skip_sw` — правило работает только в железе, не нагружая CPU.
```

### clsact и eBPF
Дисциплина `clsact` является современной точкой входа для eBPF-программ в стеке `tc`:

```bash
# Создание точки прикрепления
sudo tc qdisc add dev eth0 clsact

# Прикрепление программы для классификации или модификации пакетов
sudo tc filter add dev eth0 ingress bpf da obj my_classifier.o sec ingress
```

## Борьба с Bufferbloat и современные алгоритмы

**Bufferbloat (Раздувание буферов)** — проблема, при которой избыточная буферизация на промежуточных узлах приводит к огромным задержкам при полной загрузке канала. Пакеты стоят в очереди секундами вместо того, чтобы быть отброшенными для сигнализации TCP о заторе.

Для решения используются алгоритмы **SQM (Smart Queue Management)**:

- **fq_codel (Flow Queue CoDel):** разделяет трафик на потоки (flows) и использует алгоритм CoDel для отбрасывания пакетов из «застоявшихся» очередей. Обеспечивает низкий пинг для игр и VoIP параллельно с тяжелыми загрузками.
- **CAKE (Common Applications Kept Enhanced):** развитие fq_codel. Включает в себя шейпинг, фильтрацию ACK-пакетов (ускоряет асимметричные каналы, например ADSL/LTE) и изоляцию по хостам (host fairness).
- **L4S (Low Latency, Low Loss, Scalable):** стандарт, обеспечивающий ультранизкие задержки за счет тесного взаимодействия приложения и сети через ECN.

## Практические сценарии

### Linux: базовый пример (fq_codel)

```bash
# Установка алгоритма fq_codel на интерфейс eth0
sudo tc qdisc add dev eth0 root fq_codel
```

### Linux: иерархический шейпинг (HTB + fq_codel)

Сценарий: гарантировать 200 Мбит для важного трафика, остальное (800 Мбит) — для фонового, с возможностью заимствования полосы.

```bash
# 1. Корневая дисциплина HTB
sudo tc qdisc replace dev eth0 root handle 1: htb default 20

# 2. Общий класс-родитель (1 Гбит)
sudo tc class add dev eth0 parent 1: classid 1:1 htb rate 1gbit ceil 1gbit

# 3. Класс для приоритетного трафика (rate — гарантия, ceil — максимум)
sudo tc class add dev eth0 parent 1:1 classid 1:10 htb rate 200mbit ceil 1gbit prio 0

# 4. Класс для обычного трафика
sudo tc class add dev eth0 parent 1:1 classid 1:20 htb rate 800mbit ceil 1gbit prio 1

# 5. Листовые дисциплины для борьбы с задержками внутри классов
sudo tc qdisc add dev eth0 parent 1:10 fq_codel
sudo tc qdisc add dev eth0 parent 1:20 fq_codel
```

### Linux: шейпинг входящего трафика (IFB)

Поскольку входящая очередь (`ingress`) поддерживает только Policing (отбрасывание), для полноценного Shaping (задержка в буфере) используется перенаправление на виртуальный интерфейс `ifb`.

```bash
# 1. Загрузка модуля и активация интерфейса
sudo modprobe ifb
sudo ip link set ifb0 up

# 2. Перенаправление входящего трафика с eth0 на ifb0
sudo tc qdisc add dev eth0 handle ffff: ingress
sudo tc filter add dev eth0 parent ffff: protocol ip u32 match u32 0 0 \
    action mirred egress redirect dev ifb0

# 3. Применение шейпинга на ifb0 (теперь трафик выглядит как исходящий для ifb0)
sudo tc qdisc add dev ifb0 root cake bandwidth 50mbit
```

### Linux: маркировка DSCP через iptables/nftables

```bash
# iptables (legacy): пометить SIP/VoIP трафик значением EF (DSCP 46)
sudo iptables -t mangle -A OUTPUT -p udp --dport 5060 -j DSCP --set-dscp-class EF
sudo iptables -t mangle -A OUTPUT -p udp --dport 5061 -j DSCP --set-dscp-class EF

# Видеоконференции (например, STUN/TURN на 3478) — AF41
sudo iptables -t mangle -A OUTPUT -p tcp --dport 3478 -j DSCP --set-dscp-class AF41
sudo iptables -t mangle -A OUTPUT -p udp --dport 3478 -j DSCP --set-dscp-class AF41

# Фоновый/Bulk трафик (торренты, бэкапы) — CS1 (ниже Best Effort)
sudo iptables -t mangle -A OUTPUT -p tcp --dport 6881:6889 -j DSCP --set-dscp-class CS1

# nftables (современный): аналогичные правила
sudo nft add rule inet filter forward ip dscp set ef udp dport { 5060, 5061 }
sudo nft add rule inet filter forward ip dscp set af41 tcp dport 3478
```

### Linux: CAKE (упрощенный "все-в-одном" шейпинг)

```bash
# Ограничить интерфейс eth0 скоростью 100 Мбит/с с авто-bufferbloat
sudo tc qdisc add dev eth0 root cake bandwidth 100mbit

# Проверка
tc qdisc show dev eth0
# → Expected: qdisc cake 8004: root refcnt 2 bandwidth 100Mbit ...
```

### Linux: диагностика и мониторинг

```bash
# Просмотр текущей qdisc
tc qdisc show dev eth0
tc class show dev eth0
tc filter show dev eth0

# Статистика — байты/пакеты по классам, drops, overlimits
tc -s class show dev eth0

# Живая статистика (обновление раз в секунду)
watch -n 1 "tc -s class show dev eth0"

# Проверка маркировки DSCP пакетов
sudo tcpdump -i eth0 -n ip dscp > 0
# или
sudo tcpdump -i eth0 -n 'ip[1] & 0xfc == 0xb8'  # EF = 0xB8 >> 2
```

### Linux: сброс правил

```bash
# Удалить корневую дисциплину (удаляет всю иерархию под ней)
sudo tc qdisc del dev eth0 root

# Удалить ingress-дисциплину
sudo tc qdisc del dev eth0 ingress

# Удалить IFB
sudo ip link set dev ifb0 down
sudo tc qdisc del dev ifb0 root
```

### Реализация в MikroTik (RouterOS)

#### Simple Queue (Простая очередь)
Используется для быстрого ограничения скорости конкретных IP или интерфейсов.

```bash
# Ограничение IP 192.168.88.50 до 10 Мбит/с
/queue simple add name="Limit-IP-50" target=192.168.88.50/32 max-limit=10M/10M
```

#### PCQ (Per Connection Queue)
Автоматическое «справедливое» распределение полосы между всеми пользователями подсети.

```bash
# Настройка PCQ для равномерного распределения
/queue type add name=PCQ_down kind=pcq pcq-classifier=dst-address pcq-rate=5M
/queue simple add name="Fair-Share" target=192.168.88.0/24 queue=PCQ_down
```

#### Queue Tree (Иерархическая очередь)
Для сложных сценариев с приоритизацией по Mangle-меткам:

```bash
# Создание родительской очереди на интерфейсе ether1 (WAN, исходящий)
/queue tree add name="WAN-Parent" parent=ether1 packet-mark=no-mark limit-at=100M/100M \
    max-limit=1000M/1000M priority=8

# Приоритетный класс (Voice/Video)
/queue tree add name="Voice-Video" parent=WAN-Parent packet-mark=voip-traffic \
    limit-at=50M/50M max-limit=200M/200M priority=1

# Фоновый класс (bulk)
/queue tree add name="Bulk" parent=WAN-Parent packet-mark=bulk-traffic \
    limit-at=10M/10M max-limit=100M/100M priority=8
```

### Реализация в Cisco IOS/IOS-XE

#### Class-Based Weighted Fair Queueing (CBWFQ)
CBWFQ позволяет создавать классы на основе ACL, классифицировать трафик и гарантировать полосу.

```cisco
! 1. Определение классификаторов (class-maps)
class-map match-all VOICE
 match ip dscp ef
 match protocol sip

class-map match-all VIDEO
 match ip dscp af41

class-map match-all CRITICAL_DATA
 match ip dscp af21

class-map match-all SCAVENGER
 match ip dscp cs1

! 2. Политики (policy-maps)
policy-map CAMPUS-QOS
 class VOICE
  priority level 1 percent 10
 class VIDEO
  priority level 2 percent 30
 class CRITICAL_DATA
  bandwidth percent 40
  fair-queue
 class SCAVENGER
  bandwidth percent 5
 class class-default
  fair-queue
  bandwidth percent 15

! 3. Применение на интерфейсе (egress)
interface GigabitEthernet0/1
 service-policy output CAMPUS-QOS

! 4. Доверенная граница (edge): маркировка входящего трафика
policy-map TRUST-BOUNDARY
 class VOICE
  set dscp ef
 class VIDEO
  set dscp af41
 class SCAVENGER
  set dscp cs1
 interface GigabitEthernet0/2
  service-policy input TRUST-BOUNDARY
```

#### AutoQoS
Cisco предоставляет шаблоны для быстрого развертывания:

```cisco
! Автоматическая конфигурация для VoIP
auto qos voip trust

! Проверка Applied policy
show auto qos interface GigabitEthernet0/1
```

## Диагностика и устранение неполадок

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `RTNETLINK answers: File exists` | Qdisc уже существует на интерфейсе | `sudo tc qdisc del dev eth0 root` перед повторным созданием |
| `tc command not found` | Пакет iproute2 не установлен | `sudo apt install iproute2` или `sudo dnf install iproute` |
| TC не ограничивает скорость | Указано неверное имя интерфейса | Проверьте `ip link show` |
| Ingress-шейпинг не работает | Модуль ifb не загружен | `sudo modprobe ifb`; для персистентности добавьте `ifb` в `/etc/modules` |
| Правила пропадают после reboot | Нет persistence | Создайте systemd-сервис или скрипт в `/etc/network/if-up.d/` |
| Маркировка DSCP не проходит | ISP сбрасывает DSCP на edge | Внутренние DSCP работают только внутри автономной системы |
| Пакеты не попадают в класс | Неверный фильтр или prio | Проверьте `tc -s filter show dev eth0` (счетчики совпадений) |
| Высокая задержка на priority-трафике | Неправильный burst/приоритет | Увеличьте `burst` или смените qdisc на `fq_codel` |

### Проверка работы правил

```bash
# Проверка конфигурации qdisc/классов/фильтров
tc qdisc show dev eth0
tc class show dev eth0
tc filter show dev eth0

# Статистика по классам (байты, пакеты, dropped, overlimits)
tc -s class show dev eth0

# Проверка маркировки DSCP на лету
tcpdump -i eth0 -n ip dscp > 0

# Проверка PCP/VLAN
tcpdump -i eth0 -n vlan && echo "VLAN detected"

# Проверка задержки и джиттера
ping -c 100 <shaped-ip>
# Анализ: avg, mdev (jitter)
```

## Рекомендации и очистка

### Best Practices
1. **Применяйте QoS как можно ближе к источнику** (Trust Boundary). На серверах и точках доступа маркируйте трафик до выхода в сеть.
2. **Используйте `fq_codel` или `CAKE`** по умолчанию на всех интерфейсах. Они требуют минимальной настройки и эффективно борются с bufferbloat.
3. **Для асимметричных каналов** (ADSL/LTE) предпочитайте `CAKE` — он фильтрует ACK-пакеты и повышает эффективность.
4. **Для TCP BBR** используйте `fq` как листовую qdisc — BBR зависит от EDT (Earliest Departure Time) pacing.
5. **Не делайте полную маркировку на edge-роутерах** — классифицируйте и маркируйте на конечных устройствах (access layer), а на ядре только обрабатывайте PHB.
6. **Тестируйте на виртуальных интерфейсах (veth)** перед применением на production. Ошибки в tc не ломают связность, но могут вызвать потерю пакетов.
7. **Учитывайте, что DSCP часто сбрасывается ISP** на границе автономных систем. End-to-End QoS работают только внутри контролируемой инфраструктуры (MPLS, частные сети, VLAN).
8. **Используйте `watch -n 1 "tc -s class show dev eth0"`** для мониторинга в реальном времени.

### Очистка и откат

```bash
# Полный сброс QoS на интерфейсе eth0
sudo tc qdisc del dev eth0 root 2>/dev/null || true
sudo tc qdisc del dev eth0 ingress 2>/dev/null || true

# Удаление IFB
sudo ip link set dev ifb0 down 2>/dev/null || true
sudo tc qdisc del dev ifb0 root 2>/dev/null || true

# Удаление iptables-правил mangle (если маркировка больше не нужна)
sudo iptables -t mangle -D OUTPUT -p udp --dport 5060 -j DSCP --set-dscp-class EF
```

## Крайние случаи и ограничения

- **DoS через QoS:** Некорректные правила TC могут создавать искусственные очереди, приводящие к отказу обслуживания. Всегда тестируйте сценарии отказа (например, что происходит при исчерпании rate в корневом классе HTB).
- **Bufferbloat в гетерогенных сетях:** В сетях с переменной задержкой (спутник, мобильный интернет) даже `fq_codel` может давать всплески задержки. Используйте `CAKE` с параметром `ptm` для DSL/G.fast.
- **IPv6 RA и QoS:** Маркеры DSCP в Router Advertisement (RA) не обрабатываются стеком по умолчанию; требуется конфигурация на конечном хосте.
- **DoH/DoT и DPI:** Шифрование DNS-over-HTTPS/TLS предотвращает классификацию DNS-запросов по портам/сигнатурам. Требуется alternative классификация (IP destination, SNI в TLS, или separate VLAN).
- **Веб-туннели (HTTP/2, QUIC, WireGuard):** QUIC использует UDP с собственной управляющей логикой; классические правила по портам (443/UDP) не различим от других UDP-трафика без DPI. Используйте `flower` с HW offload или eBPF.
- **TC и ядерные модули:** Правила TC теряются при перезагрузке. Для persistence используйте systemd-unit или `/etc/network/if-up.d/`.
- **Иерархия классов:** HTB не поддерживает более одного уровня родителя на класс без правильного построения дерева (parent → child → grandchild требует явного указания parent для каждого).
- **Совместимость firmware:** Встроенные ОС (OpenWrt, RouterOS) имеют усеченный набор qdisc. Проверяйте доступность нужных дисциплин через `tc qdisc show`.

## Дополнительная информация

- [Качество real-time трафика](./real_time_traffic_quality.md) — детализация по играм, VoIP и стримингу.
- [Network Latency Optimization](../../Linux/Networking/Concepts/network_latency_optimization.md) — оптимизация задержек в Linux.
- [tc — управление трафиком](../../Linux/Networking/Tools/iproute2/tc.md) — практическое руководство по Linux Traffic Control.
- [Структура IP-пакета](../OSI_TCP_IP_Model/Network_layer/Protocols/ip_packet_structure.md) — описание полей DSCP/ECN в заголовке.
- [VLAN 802.1Q](../../Protocols/VLAN/vlan_8021q_frame.md) — поле PCP/CoS для QoS на L2.
- [LLDP-MED](../../Protocols/lldp.md) — автоматическая рассылка политик QoS.
- [DHCP: Обзор и работа протокола](../../Protocols/DHCP/dhcp_overview.md) — опция 114 (QoS Policy).
- [Алгоритмы управления перегрузкой TCP](../../Protocols/TCP/congestion/tcp_congestion_control_overview.md) — взаимодействие AQM и TCP congestion control.
- [RFC 2474: Differentiated Services Field](https://datatracker.ietf.org/doc/html/rfc2474) — DSCP поле.
- [RFC 3289: Management Information Base](https://datatracker.ietf.org/doc/html/rfc3289) — дляDiffServ MIB.
- [RFC 4594: Configuration Guidelines](https://datatracker.ietf.org/doc/html/rfc4594) — практические рекомендации по DSCP.
