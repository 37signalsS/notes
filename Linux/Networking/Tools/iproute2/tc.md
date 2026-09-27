# tc: Управление трафиком (Traffic Control)

## Определения

* **`tc` (Traffic Control)** — утилита пакета `iproute2` для настройки механизмов управления трафиком в ядре Linux (QoS). Позволяет классифицировать, приоритизировать, ограничивать и эмулировать сетевой трафик.
* **`qdisc` (Queuing Discipline)** — дисциплина очереди. Механизм, определяющий алгоритм обработки пакетов (очередь, буферизация, отбрасывание) перед передачей драйверу сетевой карты.
* **`class`** — узел в иерархии `tc`, позволяющий разделять полосу пропускания между разными типами трафика.
* **`filter`** — классификатор, определяющий, в какой класс должен попасть пакет на основе его свойств (IP, порт, протокол, flower-поля).
* **`action`** — действие, выполняемое над пакетом после классификации (например, `drop`, `mirred`, `pedit`, `pass`).
* **HTB (Hierarchical Token Bucket)** — классическая дисциплина для иерархического шейпинга (ограничения скорости) и приоритизации трафика с поддержкой заимствования полосы.
* **TBF (Token Bucket Filter)** — простая бесклассовая дисциплина для точного ограничения скорости (шейпинга) без иерархии. Работает по принципу «токен-ведро»: токены добавляются с фиксированной скоростью, каждый пакет потребляет токены, избыток буферизуется или отбрасывается.
* **fq_codel (Fair Queuing Controlled Delay)** — дисциплина для борьбы с **bufferbloat**. Изолирует потоки и активно управляет задержкой через алгоритм CoDel.
* **CAKE (Common Applications Kept Enhanced)** — современная «универсальная» дисциплина, комбинирующая шейпинг и справедливое распределение очереди с минимальной настройкой. Включает фильтрацию ACK и host-fairness.
* **IFB (Intermediate Functional Block)** — виртуальное устройство, используемое для перенаправления входящего (ingress) трафика с физического интерфейса с целью его полноценного шейпинга (так как входящая очередь `ingress` в Linux — бесклассовая и поддерживает только policing).
* **clsact (Classifier Action)** — специальная qdisc, позволяющая прикреплять фильтры (включая eBPF) как на входящий (ingress), так и на исходящий (egress) трафик без создания иерархии классов.
* **flower** — современный классификатор, позволяющий matcher-ить пакеты по полям L2–L4 и использовать аппаратную выгрузку (Hardware Offload) на NIC.

> Основные концепции QoS (Policing vs Shaping, DiffServ, ECN, борьба с bufferbloat) описаны в файле [QoS](../../../../Networking/Concepts/qos.md). Эмуляция сетевых проблем — в [tc netem](./tc_netem.md).

## Основные команды tc

### Структура команды

```text
tc [OPTIONS] OBJECT COMMAND [ARGUMENTS]

OBJECTS: qdisc, class, filter, action, state
OPTIONS: -s (статистика), -d (детали), -j (JSON), -p (pretty JSON), -n (числовые ID)
COMMANDS: add, del, replace, change, show, get
```

### Управление qdisc

```bash
# Просмотр всех qdisc на интерфейсе
tc qdisc show dev eth0

# Просмотр с детализированной статистикой (критично для диагностики)
tc -s qdisc show dev eth0

# Добавление корневой qdisc
sudo tc qdisc add dev eth0 root fq_codel

# Замена корневой qdisc (без ошибки «RTNETLINK answers: File exists»)
sudo tc qdisc replace dev eth0 root fq_codel

# Удаление корневой qdisc (удаляет всю иерархию под ней)
sudo tc qdisc del dev eth0 root

# Удаление ingress-qdisc
sudo tc qdisc del dev eth0 ingress
```

### Управление class

```bash
# Просмотр классов
tc class show dev eth0

# Просмотр классов со статистикой
tc -s class show dev eth0

# Добавление класса (HTB)
sudo tc class add dev eth0 parent 1: classid 1:10 htb rate 200mbit ceil 1gbit prio 0
```

### Управление filter

```bash
# Просмотр фильтров
tc filter show dev eth0

# Просмотр фильтров со статистикой (счётчики совпадений)
tc -s filter show dev eth0

# Добавление фильтра (flower)
sudo tc filter add dev eth0 parent 1: protocol ip flower ip_proto tcp dst_port 80 flowid 1:10
```

### JSON-вывод для автоматизации

```bash
# Вывод в JSON-формате (ядра 5.x+)
tc -j qdisc show dev eth0

# Pretty JSON для чтения
tc -jp qdisc show dev eth0

# Фильтрация через jq
tc -j class show dev eth0 | jq '.[] | select(.parent == "1:")'
```

> `tc -j` доступен начиная с ядра 5.1+ и `iproute2` 5.1+. В старых системах используйте парсинг текстового вывода (`tc -s ... | awk ...`).

## Основные концепции

### Идентификаторы (Handles)

Каждый объект в `tc` идентифицируется числом в формате `major:minor`:
* **`1:`** — major-номер 1, minor-номер 0 (обычно корневая qdisc).
* **`1:10`** — minor-номер 10 внутри major-номера 1 (обычно идентификатор класса).
* **`ffff:`** — зарезервированный номер для ingress qdisc.
* **`0:`** — используется для root-класса в некоторых конфигурациях.

> При указании `handle` для корневой qdisc major-номер выбирается произвольно (обычно `1:`). Minor-номер корневой qdisc всегда `0`.

### Параметры rate, ceil, burst, latency

Понимание этих параметров критично для корректной настройки шейпинга:

| Параметр | Описание | Пример |
|:---|:---|:---|
| **rate** | Гарантированная пропускная способность (minimum). Класс всегда получает не менее этого значения при наличии трафика. | `rate 200mbit` |
| **ceil** | Максимально допустимая пропускная способность (maximum). Класс может заимствовать полосу до этого лимита, если соседние классы не используют свою. | `ceil 1gbit` |
| **burst** | Размер «ведра» токенов в байтах. Определяет, сколько данных можно передать мгновенно (всплеск). Слишком малый burst → потеря трафика; слишком большой → рост задержки. | `burst 15k` |
| **cburst** | Burst для ceil (заимствованная полоса). | `cburst 15k` |
| **latency** | Целевая задержка буферизации. Используется HTB для расчета burst. | `latency 10ms` |

> **Формула burst для HTB:** `burst = rate * latency / 8`. Например, для `rate 1gbit latency 10ms`: `burst = 1000000000 * 0.01 / 8 = 1250000` байт (~1.2 MB).

### Токен-ведро (Token Bucket)

Принцип работы TBF и HTB:

1. Токены добавляются в «ведро» со скоростью `rate` (в байтах/сек).
2. Каждый исходящий пакет потребляет количество токенов, равное размеру пакета.
3. Если токенов достаточно — пакет передаётся.
4. Если токенов недостаточно — пакет буферизуется (до `latency`) или отбрасывается при переполнении буфера.
5. Неиспользованные токены не накапливаются свыше размера `burst`.

### Интеграция с сетевым стеком

Дисциплина по умолчанию задается через `sysctl`:

* `net.core.default_qdisc` — выбор qdisc по умолчанию для новых интерфейсов (например, `fq_codel`, `fq` или `cake`).
* `tc` используется для тонкой настройки: создания классов, фильтров и лимитов для конкретных интерфейсов.

> Подробнее о выборе qdisc и влиянии на TCP: [Дисциплины очередей TCP](../../Concepts/tcp_tuning/tcp_queueing_disciplines.md).

### Структура QoS

```text
Физический интерфейс (eth0)
├── Корневая qdisc (1:) — Исходящий трафик (Egress Shaping)
│   ├── Класс 1:1 (Общий лимит)
│   │   ├── Класс 1:10 (Приоритетный) ──> qdisc (fq_codel)
│   │   └── Класс 1:20 (Обычный)      ──> qdisc (fq_codel)
│   └── Фильтры (Классификация)
│
└── Ingress qdisc (ffff:) — Входящий трафик (Ingress Policing)
    └── Фильтры (Redirect -> ifb0) ──> Полноценный шейпинг на ifb0
```

## Практические сценарии

### Ограничение скорости с помощью CAKE

CAKE — наиболее современный и простой способ настроить шейпинг. Он автоматически справляется с bufferbloat и справедливо делит полосу.

```bash
# Ограничить интерфейс eth0 скоростью 100 Мбит/с
sudo tc qdisc add dev eth0 root cake bandwidth 100mbit

# Проверка
tc qdisc show dev eth0
# → qdisc cake 8004: root refcnt 2 bandwidth 100Mbit ...
```

**Дополнительные параметры CAKE:**

```bash
# Шейпинг с указанием типа линка и DiffServ
sudo tc qdisc add dev eth0 root cake bandwidth 50mbit ethernet diffserv4

# Шейпинг для асимметричного канала (ADSL/LTE) с фильтрацией ACK
sudo tc qdisc add dev eth0 root cake bandwidth 10mbit atm ack-filter

# Шейпинг для VPN (виртуальный интерфейс)
sudo tc qdisc add dev tun0 root cake bandwidth 50mbit
```

### Простое ограничение скорости (TBF)

TBF — простейшая бесклассовая дисциплина для точного ограничения скорости без иерархии.

```bash
# Ограничение исходящего трафика до 50 Мбит/с
sudo tc qdisc add dev eth0 root tbf rate 50mbit burst 15k latency 10ms
```

**Параметры:**
* `rate 50mbit` — целевая скорость.
* `burst 15k` — допустимый всплеск (15 КБ).
* `latency 10ms` — максимальная задержка буферизации.

> TBF не поддерживает приоритизацию и иерархию. Для сложных сценариев используйте HTB или CAKE.

### Иерархическая приоритизация (HTB + fq_codel)

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

### Классификация трафика по портам и адресам

```bash
# Весь трафик на порт 443 (HTTPS) → приоритетный класс
sudo tc filter add dev eth0 parent 1: protocol ip flower ip_proto tcp dst_port 443 flowid 1:10

# Трафик от конкретного подсети → фоновый класс
sudo tc filter add dev eth0 parent 1: protocol ip flower src 10.0.0.0/8 flowid 1:20

# Просмотр добавленных фильтров
tc -s filter show dev eth0
```

### Входящий шейпинг через IFB (Intermediate Functional Block)

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

### Policing (ограничение входящего трафика без IFB)

Если полноценный шейпинг не нужен и достаточно простого отбрасывания избыточного трафика:

```bash
# Ограничение входящего трафика до 100 Мбит/с (пакеты сверх лимита отбрасываются)
sudo tc qdisc add dev eth0 handle ffff: ingress
sudo tc filter add dev eth0 parent ffff: protocol ip prio 1 u32 \
    match u32 0 0 police rate 100mbit burst 15k drop flowid :1
```

> Policing не буферизует пакеты — избыток мгновенно отбрасывается. Это приводит к TCP-ретрансмиссиям и «зубчатой» скорости. Для плавного шейпинга используйте IFB или TBF/CAKE на egress.

### Современная классификация (Flower) и аппаратная выгрузка

Классификатор `flower` позволяет использовать возможности аппаратной выгрузки (Hardware Offload) современных сетевых карт.

```bash
# Направить трафик на порт 80 в класс 1:10
sudo tc filter add dev eth0 parent 1: protocol ip flower ip_proto tcp dst_port 80 flowid 1:10

# Пример аппаратной выгрузки фильтра (требуется поддержка драйвером)
sudo tc filter add dev eth0 ingress protocol ip flower \
    skip_sw dst_ip 192.168.1.100 action drop
# `skip_sw` — правило работает только в железе, не нагружая CPU.

# Проверка поддержки аппаратной выгрузки
ethtool -k eth0 | grep -i hw-offload
# → hw-tc-offload: on
```

### Использование eBPF (clsact)

Дисциплина `clsact` является современной точкой входа для eBPF-программ в стеке `tc`.

```bash
# Создание точки прикрепления
sudo tc qdisc add dev eth0 clsact

# Прикрепление программы для классификации или модификации пакетов
sudo tc filter add dev eth0 ingress bpf da obj my_classifier.o sec ingress

# Просмотр прикреплённых BPF-программ
tc filter show dev eth0 ingress
```

### Маркировка DSCP через tc actions

```bash
# Установить DSCP EF (46) для VoIP-трафика на исходящем интерфейсе
sudo tc filter add dev eth0 parent 1: protocol ip flower ip_proto udp dst_port 5060 \
    action pedit munge ip dscp set 0xb8 flowid 1:10

# Проверка маркировки
sudo tcpdump -i eth0 -n 'ip[1] & 0xfc != 0'
```

### Персистентность настроек tc

Правила `tc` теряются при перезагрузке. Для восстановления существует несколько подходов:

**Вариант 1: Скрипт в `/etc/network/if-up.d/`** (классический)

```bash
#!/bin/bash
# /etc/network/if-up.d/99-tc-qos
# Применяется при поднятии интерфейса

IFACE="$IFACE"
[ -z "$IFACE" ] && IFACE="eth0"

tc qdisc del dev $IFACE root 2>/dev/null
tc qdisc del dev $IFACE ingress 2>/dev/null

tc qdisc add dev $IFACE root handle 1: htb default 20
tc class add dev $IFACE parent 1: classid 1:1 htb rate 1gbit ceil 1gbit
tc class add dev $IFACE parent 1:1 classid 1:10 htb rate 200mbit ceil 1gbit prio 0
tc class add dev $IFACE parent 1:1 classid 1:20 htb rate 800mbit ceil 1gbit prio 1
tc qdisc add dev $IFACE parent 1:10 fq_codel
tc qdisc add dev $IFACE parent 1:20 fq_codel
```

```bash
sudo chmod +x /etc/network/if-up.d/99-tc-qos
```

**Вариант 2: systemd-юнит** (современный)

```ini
# /etc/systemd/system/tc-qos.service
[Unit]
Description=Traffic Control QoS rules
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/tc-apply.sh
ExecStop=/usr/local/bin/tc-cleanup.sh

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now tc-qos.service
```

**Вариант 3: networkd-dispatcher** (для systemd-networkd)

```bash
# /etc/networkd-dispatcher/routable.d/99-tc-qos.sh
#!/bin/bash
IFACE=$IFACE
tc qdisc replace dev $IFACE root cake bandwidth 100mbit
```

```bash
sudo chmod +x /etc/networkd-dispatcher/routable.d/99-tc-qos.sh
```

> **Рекомендация для production:** systemd-юнит с `RemainAfterExit=yes` и `ExecStop` для корректного отката. Это обеспечивает управление жизненным циклом через `systemctl`.

## Диагностика и отладка

### Просмотр статистики

Ключ `-s` (statistics) критически важен для анализа работы очередей.

```bash
# Статистика qdisc
sudo tc -s qdisc show dev eth0

# Статистика классов (включая drops и overlimits)
sudo tc -s class show dev eth0

# Статистика фильтров (счётчики совпадений)
sudo tc -s filter show dev eth0

# Мониторинг в реальном времени
watch -n 1 "tc -s class show dev eth0"
```

**Ключевые показатели:**
* `sent`: общий объём переданных данных.
* `dropped`: пакеты, отброшенные из-за переполнения очередей или policing.
* `overlimits`: количество задержек пакетов из-за достижения лимита скорости.
* `backlog`: текущее количество пакетов, ожидающих в буфере.
* `qlen`: длина очереди (для FIFO-based qdisc).

### Диагностика: пакет меняется до выхода из интерфейса

Иногда маршрут выбран правильно, firewall ничего не блокирует, но трафик всё равно уходит не таким, каким его отправляет приложение. Между сетевым стеком и интерфейсом пакет может пройти через `tc`.

**Проверка правил filter:**

```bash
# Общий просмотр правил
sudo tc filter show dev eth0

# Для ingress-трафика
sudo tc filter show dev eth0 ingress

# С статистикой (счётчики пакетов/байт)
sudo tc -s filter show dev eth0

# Проверка, какие filter реально обрабатывают трафик
sudo tc -s filter show dev eth0 | grep -A5 "Sent"
```

**Полезные действия filter:**

* **Перенаправление:** `action mirred egress redirect dev ifb0`
* **Зеркалирование:** `action mirred egress mirror dev eth1`
* **Изменение полей:** `action pedit` — перезапись TTL, DSCP и других полей заголовка.
* **Отбрасывание:** `action drop`

Если у конкретного filter растут счётчики `Sent`, `bytes` или `packets`, правило реально обрабатывает трафик.

**Почему это сложно заметить:**
* `ip route get` покажет правильный интерфейс.
* `iptables`/`nftables` могут быть пустыми.
* Но пакет всё равно может быть перенаправлен или изменён внутри стека:
  * `eth0 → tc filter → redirect → ifb0`
  * `application → tc filter → изменение полей → eth0`

**Где встречается:** Серверы с QoS, Kubernetes CNI (Calico, Cilium), виртуализация, BPF-программы (eBPF/XDP).

При странном поведении трафика полезно смотреть не только `route` и `firewall`, но и `tc qdisc`, `tc filter` и счётчики actions.

### Типичные ошибки

| Симптом | Причина | Решение |
|:---|:---|:---|
| `RTNETLINK answers: File exists` | Qdisc уже существует на интерфейсе | `sudo tc qdisc del dev eth0 root` перед повторным созданием, или используйте `replace` вместо `add` |
| `RTNETLINK answers: No such file or directory` | Интерфейс не существует | Проверьте `ip link show` |
| `tc command not found` | Пакет iproute2 не установлен | `sudo apt install iproute2` (Debian/Ubuntu) или `sudo dnf install iproute` (RHEL/Fedora) |
| TC не ограничивает скорость | Указано неверное имя интерфейса или неправильный класс | Проверьте `tc qdisc show dev eth0` и `tc -s class show dev eth0` |
| Ingress-шейпинг не работает | Модуль ifb не загружен | `sudo modprobe ifb`; для персистентности добавьте `ifb` в `/etc/modules-load.d/ifb.conf` |
| Правила пропадают после reboot | Нет persistence | Создайте systemd-сервис или скрипт в `/etc/network/if-up.d/` (см. раздел «Персистентность») |
| Пакеты не попадают в класс | Неверный фильтр или prio | Проверьте `tc -s filter show dev eth0` (счётчики совпадений) |
| Высокая задержка на priority-трафике | Неправильный burst/приоритет | Увеличьте `burst` или смените leaf-qdisc на `fq_codel` |
| `RTNETLINK answers: Invalid argument` | Несовместимые параметры (например, burst > ceil) | Проверьте соотношение burst/rate/latency |
| Скорость ограничена, но задержки высокие | Слишком большой burst | Уменьшите burst до `rate * latency / 8` |

### Удаление настроек

```bash
# Удалить корневую дисциплину (удаляет всю иерархию под ней)
sudo tc qdisc del dev eth0 root

# Удалить ingress-дисциплину
sudo tc qdisc del dev eth0 ingress

# Удалить IFB
sudo ip link set dev ifb0 down
sudo tc qdisc del dev ifb0 root 2>/dev/null || true

# Полный сброс (для скриптов)
sudo tc qdisc del dev eth0 root 2>/dev/null || true
sudo tc qdisc del dev eth0 ingress 2>/dev/null || true
```

## Сравнение дисциплин очередей

| Дисциплина | Назначение | Особенности | Когда использовать |
|:---|:---|:---|:---|
| **HTB** | Иерархический шейпинг | Гибкость, заимствование полосы, требует настройки фильтров. | Сложные сценарии с несколькими классами трафика. |
| **TBF** | Простой шейпинг | Минимальная настройка, точное ограничение скорости, без иерархии. | Одиночное ограничение скорости на интерфейсе. |
| **CAKE** | «Все в одном» | Идеально для интернет-шлюзов, авто-bufferbloat, host-fairness, фильтрация ACK. | Роутеры, VPN-шлюзы, асимметричные каналы. |
| **fq_codel** | AQM | Стандарт де-факто для LAN, минимизирует задержки. | Рабочие станции, серверы общего назначения. |
| **fq** | Fair Queuing + Pacing | Необходима для работы **TCP BBR** (EDT-планирование). | Высокопроизводительные серверы с BBR. |
| **netem** | Эмуляция проблем | Задержки, потери, дублирование (для тестов). | Тестирование, chaos engineering. |
| **mq / mqprio** | Multi-queue | Оптимизация для многоочередных NIC. | 10/25/40/100 GbE серверы. |

## Связанные темы

* **[tc netem](./tc_netem.md)** — детальное описание эмуляции сетевых проблем.
* **[QoS](../../../../Networking/Concepts/qos.md)** — общие концепции качества обслуживания (Policing, Shaping, DiffServ, ECN).
* **[Дисциплины очередей TCP](../../Concepts/tcp_tuning/tcp_queueing_disciplines.md)** — влияние qdisc на TCP-стек и выбор по ролям.
* **[Оптимизация TCP](../../Concepts/tcp_tuning/tcp_tuning_overview.md)** — настройка сетевого стека Linux.
* **[RSS, RPS, RFS](../../Concepts/rss_rps_rfs.md)** — многопоточная обработка трафика.
* **[Управление перегрузкой TCP](../../../../Networking/Protocols/TCP/Flow_Control/index.md)** — TBF и tc в контексте flow control.
