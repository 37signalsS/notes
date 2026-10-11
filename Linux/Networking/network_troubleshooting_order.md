# Порядок диагностики сетевых проблем в Linux

## Определения

*   **Диагностика сети** — систематический процесс выявления, анализа и устранения сбоев сетевого взаимодействия на различных уровнях модели OSI.
*   **Связность (Connectivity)** — базовое состояние, при котором два сетевых узла могут успешно обмениваться данными.
*   **Маршрутизация (Routing)** — процесс выбора пути для передачи IP-пакета от источника к пункту назначения на основе таблиц маршрутизации.
*   **Соседство (Neighbor Discovery)** — механизмы определения соответствия между адресами L3 и L2 в локальном сегменте (ARP для IPv4, NDP для IPv6).
*   **MTU (Maximum Transmission Unit)** — максимальный размер полезного блока данных одного пакета, который может быть передан по интерфейсу без фрагментации.
*   **Network Namespace** — механизм изоляции ядра Linux, предоставляющий каждому namespace собственный стек: таблицы маршрутизации, правила firewall, интерфейсы и порты. При диагностике контейнеров и VRF необходимо учитывать, что `ip`/`ss`/`conntrack` по умолчанию показывают только текущий (init) namespace.
*   **Файрвол (Firewall)** — система фильтрации трафика на основе правил. В Linux используются `iptables` (legacy) и `nftables` (современный стандарт). Подсистема Netfilter/NFQUEUE может отбрасывать или модифицировать пакеты на любом уровне.
*   **Socket Buffer (Буфер сокета)** — область памяти ядра между сетевым стеком и приложением, где накапливаются данные до их чтения через `recv()`/`read()`. Переполнение приводит к `rcvbufErrors` (UDP) или Zero Window (TCP).
*   **Backlog (Очередь установки соединений)** — очередь SYN-RCVD соединений, ожидающих `accept()` в приложении. Управляется через `net.core.somaxconn` и `net.ipv4.tcp_max_syn_backlog`.
*   **MSS (Maximum Segment Size)** — максимальный размер сегмента данных TCP, обычно MTU-40 (для Ethernet с MTU 1500 → MSS 1460).
*   **rp_filter (Reverse Path Filtering)** — механизм ядра, отбрасывающий входящие пакеты с «нелогичных» интерфейсов. Значение 1 (Strict) часто вызывает проблемы при асимметричной маршрутизации.
*   **Conntrack (Connection Tracking)** — подсистема ядра Netfilter, отслеживающая состояние всех соединений для корректной работы NAT и фильтрации. При переполнении таблицы новые соединения дропаются silently.

## Основные концепции

### Ключевые принципы диагностики

1.  **Приоритет «снизу-вверх» (Bottom-Up):** Начинайте с физического уровня (L1) и двигайтесь к прикладному (L7). Ошибки в DNS бессмысленно диагностировать, если интерфейс находится в состоянии `DOWN`.
2.  **Симметричность потока:** В сетевом взаимодействии пакеты всегда должны иметь путь обратно. Отсутствие входящего трафика часто является следствием неверной маршрутизации на стороне получателя или шлюза.
3.  **Изоляция домена проблемы:** Определите, является ли проблема локальной (хост), сетевой (коммутатор/маршрутизатор) или удаленной (целевой сервер).
4.  **Разделяй и властвуй:** Используйте инструменты, специфичные для каждого уровня, чтобы подтвердить работоспособность стека шаг за шагом.

### Три стратегии диагностики

| Стратегия | Направление | Когда использовать |
| :--- | :--- | :--- |
| **Bottom-Up** | L1 → L7 | Неизвестна причина, нужно найти с начала |
| **Top-Down** | L7 → L1 | Приложение сообщает ошибку, нужно дойти до L1 |
| **Divide-and-Conquer** | L4/L3 (середина) | Быстрая локализация: «проблема выше или ниже L3?» |

**Bottom-Up** — дефолтная стратегия для неизвестной проблемы. Проверяет линк, ARP, маршруты, порты, DNS последовательно.

**Top-Down** — эффективна, когда есть явный симптом на прикладном уровне (например, HTTP 502). Начинаете с curl/openssl и «спускаетесь» к L1.

**Divide-and-Conquer** — fastest path для опытных инженеров. Проверяете L3 (ping gateway → ping remote). Если gateway пингуется, а remote нет — проблема в L3; если remote пингуется, но порт закрыт — проблема в L4.

### USE и RED методологии

**USE-методология (Brendan Gregg)** — для каждого ресурса:

| Метрика | Что проверить | Инструмент |
| :--- | :--- | :--- |
| **U**tilization | % времени использования | `sar -n DEV 1`, `ethtool -S` |
| **S**aturation | Очередь переполнена | `nstat -az \| grep -i drop`, `ethtool -S \| grep -i miss` |
| **E**rrors | Количество ошибок | `ethtool -S \| grep -i error`, `ip -s link show` |

**RED-методология (Tom Wilkie)** — для каждого сервиса:

| Метрика | Что проверить | Инструмент |
| :--- | :--- | :--- |
| **R**ate | Количество запросов/сек | Prometheus, nginx access log |
| **E**rrors | % ошибок | `curl -s ... \| jq .errors` |
| **D**uration | Латентность (p50/p99) | Prometheus histogram, curl timing |

### Иерархия уровней проверки (Методология)

| Уровень | Объект проверки | Основные инструменты | Что ищем |
| :--- | :--- | :--- | :--- |
| **L1/L2** | Физика и Линк | `ip -br link`, `ethtool`, `dmesg` | Состояние Link, ошибки (CRC, drops), скорость/дуплекс. |
| **L2 (VLAN/STP)** | Коммутация | `bridge vlan show`, `bridge link show` | Заблокированные порты STP, VLAN tagging. |
| **L3 (IP)** | Адресация | `ip -c addr` | Наличие IP-адресов, правильность масок и подсетей. |
| **L3 (Neighbors)** | Соседи | `ip neigh` | Наличие ARP (IPv4) или NDP (IPv6) записей. Статус FAILED. |
| **L3 (Routes)** | Маршруты | `ip route`, `ip rule` | Шлюз по умолчанию (GW), специфичные маршруты. |
| **L3 (ICMP)** | Связность | `ping`, `mtr` | Потери пакетов, задержки (RTT), промежуточные узлы. |
| **L4 (Ports)** | Службы | `ss -tulpn`, `nc`, `telnet` | Статус LISTEN, правильный bind (0.0.0.0 vs 127.0.0.1). |
| **L4 (Conntrack)** | Состояния | `conntrack -S`, `sysctl net.netfilter.nf_conntrack_count` | Переполнение таблицы, stale соединения. |
| **L3/L4 (Filter)** | Файрвол | `nft`, `conntrack`, `iptables` | Правила DROP/REJECT, переполнение таблицы состояний. |
| **L7 (DNS)** | Резолвинг | `resolvectl`, `dig`, `host` | Работа резолвера, доступность DNS-серверов. |
| **Deep Trace** | Ядро | `pwru`, `tcpdump`, `bpftrace` | Место исчезновения пакета внутри сетевого стека ядра. |

### Путь пакета (Packet Journey)

Для систематизации диагностики полезно представлять путь пакета:

```text
 NIC (DMA → Ring Buffer)
     ↓
 NAPI / SoftIRQ (NET_RX, ksoftirqd)
     ↓
 L3: IP (маршрутизация, фрагментация, Netfilter)
     ↓
 L4: TCP/UDP (состояние соединения, буферы)
     ↓
 Socket Buffer (приложение читает/не читает)
     ↓
 Приложение
```

Потери могут происходить на каждом этапе. Диагностика снизу-вверх позволяет локализовать этап максимально быстро.

## Практические сценарии

### Сценарий 1.5: Локальный трафик и обход физического интерфейса

Если приложение обращается к IP-адресу, который Linux считает своим локальным адресом, пакет никогда не отправляется на физический интерфейс. Это важный нюанс при диагностике: отсутствие трафика на `eth0` не означает отсутствия сетевого взаимодействия.

**Пример:**

```text
eth0 → 10.0.0.10/24
```

Приложение выполняет:

```bash
curl http://10.0.0.10:8080
```

Интуитивно кажется, что трафик пойдет через `eth0`, коммутатор и вернётся обратно. Но Linux сначала проверяет destination и видит, что `10.0.0.10` принадлежит самому хосту. Маршрут в таблице `local` (ID 255) имеет тип `local`:

```bash
ip route get 10.0.0.10
# → local 10.0.0.10 dev lo src 10.0.0.10
```

Поэтому физический `eth0` в этом обмене вообще не участвует:

```text
application
    ↓
local routing (таблица local)
    ↓
lo
    ↓
local socket
```

**Диагностика:**

```bash
# На eth0 ничего не увидите:
tcpdump -ni eth0 port 8080
# → (тишина, хотя curl успешно устанавливает соединение)

# А на loopback трафик будет виден:
tcpdump -ni lo port 8080
# → пакеты появятся
```

При этом `lo` — это не физический интерфейс, а отдельный путь `local delivery` внутри сетевого стека Linux.

**Практический вывод:**

Проверка «пакет дошёл до сервера через его сетевую карту?» иногда поставлена неправильно: если источник и destination находятся на одном хосте, пакет мог никогда не попасть на провод (wire).

**Типичные ошибки:**
- Ошибочный вывод «сеть не работает» на основании `tcpdump` на внешнем интерфейсе.
- Игнорирование loopback при диагностике localhost-сервисов.

### Сценарий 1: Проверка физического уровня и интерфейсов

Если интерфейс не активен, пакеты не покинут хост.

```bash
# Просмотр статуса всех интерфейсов
ip -br link
# → eth0 UP f0:2f:74:e1:5a:30 <BROADCAST,MULTICAST,UP,LOWER_UP>

# Анализ ошибок на уровне драйвера
sudo ethtool -S eth0 | grep -E "drop|error"
# → rx_errors: 0
# → rx_missed_errors: 125  # Признак нехватки ресурсов CPU для обработки прерываний

# Проверка скорости и дуплекса
ethtool eth0 | grep -E "Speed|Duplex|Link detected"
# → Speed: 1000Mb/s, Duplex: Full, Link detected: yes

# Проверка системного журнала на события Link Flapping
dmesg | grep -i "link" | tail -n 5
# → [123.45] igb 0000:01:00.0 eth0: Link is Down
# → [125.67] igb 0000:01:00.0 eth0: Link is Up 1000 Mbps Full Duplex

# Проверка ошибок на программном уровне
ip -s link show eth0
# → RX: bytes  packets  errors  dropped overrun mcast
# → 1234567    8901     12      45      0       0
```

**Валидация:**
```bash
# Ожидаемый результат: интерфейс UP, errors=0, dropped=0
ip -br link | grep eth0
# → eth0 UP ... <BROADCAST,MULTICAST,UP,LOWER_UP>

ethtool -S eth0 | grep -E "rx_errors|rx_missed_errors|rx_dropped"
# → rx_errors: 0
# → rx_missed_errors: 0
# → rx_dropped: 0
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Link detected: no` | Нет физической связи (кабель, SFP, порт коммутатора) | Заменить кабель/SFP, проверить порт коммутатора |
| CRC errors растут | Проблема с кабелем, разъёмом или SFP; duplex mismatch | Заменить кабель, проверить duplex (`ethtool eth0`) |
| `rx_missed_errors` растет | Ring Buffer NIC переполнен, CPU не успевает обрабатывать прерывания | Увеличить Ring Buffer (`ethtool -G eth0 rx 4096`), настроить RSS/RPS |
| `rx_fifo_errors` растет | Внутренний FIFO-буфер NIC переполнен | Проверить драйвер, снизить coalescing |
| Link Flapping | Нестабильное соединение (кабель, SFP, порт) | Заменить компоненты, проверить `ethtool -S` на коммутаторе |

**Best Practices:**
- Для 10G+ сетей: RX Ring Buffer ≥ 4096, количество очередей (`ethtool -l`) ≥ числа ядер, обрабатывающих сеть.
- Настройки Ring Buffer сохраняйте через systemd-networkd `.link` файлы или `ethtool` в `rc.local`/systemd unit.
- Всегда проверяйте duplex: mismatch (100 Full vs 100 Half) вызывает коллизии и потерю производительности.

**Edge Cases:**
- **Виртуальные машины (KVM/Xen):** Проверяйте virtio-net драйверы и настройки `vhost-net`. Гипервизор может ограничивать MTU и количество очередей.
- **Оптические интерфейсы (SFP):** Используйте `ethtool -m eth0` для проверки TX/RX Power. Низкий RX Power указывает на проблему с оптикой или patch-panel.
- **USB-Ethernet адаптеры:** Могут иметь ограничения по количеству очередей и поддерживаемым скоростям.

**Откат:**
```bash
# Если увеличение Ring Buffer вызвало проблемы:
sudo ethtool -G eth0 rx 256
# Или верните дефолтные значения из /etc/sysctl.d/
```

### Сценарий 2: L2-соседство (ARP и IPv6 NDP)

Если IP настроен, но связи нет или она периодически «замирает» (микро-фризы SSH/VoIP), проверьте, может ли хост найти соседа по MAC-адресу.

```bash
# 1. Просмотр таблицы соседей и статистики
ip -s neigh show
# → 192.168.1.1 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE  # IPv4 (ARP)
# → fe80::1 dev eth0 lladdr 00:11:22:33:44:55 STALE      # IPv6 (NDP)

# 2. Мониторинг ARP-трафика в реальном времени
# Ищем ARP Requests без ARP Reply
sudo tcpdump -ni eth0 arp

# 3. Корреляция задержек с ARP (одновременный мониторинг)
sudo tcpdump -ni eth0 "arp or icmp"
```

**Валидация:**
```bash
# Ожидаемый результат: все критические соседи в состоянии REACHABLE или STALE
ip neigh show | grep -v REACHABLE | grep -v STALE
# → (пусто или только probe-записи в процессе обновления)
```

**Признаки проблем с ARP:**
- **Состояние FAILED:** Сосед не ответил на запросы. Проверьте VLAN и изоляцию портов.
- **Микро-фризы:** Если в `tcpdump` видно 2–3 повторных ARP Request подряд — хост теряет соседа и блокирует трафик до пересогласования.
- **Флапание:** Запись быстро переходит REACHABLE → STALE → FAILED → REACHABLE. Возможен конфликт IP или нестабильный L2-сегмент.

**Если статус FAILED:**
1. Проверьте L2-связность (VLAN, транки).
2. Убедитесь, что ответчик не блокирует ARP/ICMPv6.
3. Проверьте MAC-таблицу на коммутаторе (`show mac address-table dynamic`).

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `FAILED` в `ip neigh` | Нет ответа на ARP/NDP | Проверить VLAN, порт коммутатора, firewall |
| Микро-фризы SSH | ARP пересогласование во время сессии | Увеличить `arp_ignore`/`arp_announce`, проверить STP |
| Флапание соседей | Конфликт IP, нестабильный L2 | Уникальные IP, стабильные кабели, отключить энергосбережение портов |
| Пустая ARP-таблица | Неправильный VLAN или изоляция портов | Проверить `bridge vlan show`, trunk-настройки |

**Best Practices:**
- Для статических ARP-записей на шлюз: `ip neigh add <gateway_ip> lladdr <mac> dev eth0 nud permanent` — исключает флапание.
- Увеличить `net.ipv4.neigh.default.gc_stale_time` для задержки удаления STALE записей (по умолчанию 60с).

**Edge Cases:**
- **VRF:** Каждый VRF имеет свою ARP-таблицу. Используйте `ip -n <vrf_name> neigh show`.
- **Дup IP адрес:** Два хоста с одним IP вызывают ARP-флапание. Проверяйте `arping -D` для детекции.
- **Bonding/LAG:** В bonded интерфейсах ARP-записи могут мигрировать между slave-интерфейсами.

**Откат:**
```bash
# Удалить статическую ARP-запись:
ip neigh del <gateway_ip> dev eth0
```

### Сценарий 3: Маршрутизация и MTU

Проблемы маршрутизации часто связаны с отсутствием `default gateway` или неверными правилами в `ip rule`.

```bash
# Проверка маршрута до конкретной цели
ip route get 8.8.8.8
# → 8.8.8.8 via 192.168.1.1 dev eth0 src 192.168.1.10 uid 0

# Тестирование Path MTU Discovery
ping -M do -s 1472 8.8.8.8
# → ping: local error: message too long, mtu=1450 # Указывает на наличие туннеля (VPN/VXLAN) с меньшим MTU

# Проверка таблицы маршрутизации
ip route show
# → default via 192.168.1.1 dev eth0 proto dhcp metric 100
# → 10.0.0.0/24 dev eth0 proto kernel scope link src 10.0.0.10

# Проверка политик маршрутизации (ip rule)
ip rule show
# → 0:      from all lookup local
# → 32766:  from all lookup main
# → 32767:  from all lookup default

# Проверка rp_filter
sysctl -a | grep "\.rp_filter"
# → net.ipv4.conf.all.rp_filter = 1
```

**Валидация:**
```bash
# Ожидаемый результат: маршрут существует, gateway доступен
ip route get 8.8.8.8
# → 8.8.8.8 via 192.168.1.1 dev eth0 src 192.168.1.10 uid 0

ping -c 1 -M do -s 1472 192.168.1.1
# → 64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=0.5 ms
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Network is unreachable` | Нет маршрута в таблице | Добавить маршрут через `ip route add` или настроить DHCP |
| `No route to host` | Маршрут есть, но nexthop недоступен (L2 или firewall) | Проверить `ip neigh` для gateway, firewall |
| `message too long` при `ping` | MTU mismatch (туннель, VLAN, VXLAN) | Уменьшить размер пинга, настроить MSS clamping (`iptables -t mangle`) |
| `Destination Host Unreachable` | `rp_filter` отбрасывает пакет при асимметричной маршрутизации | Установить `net.ipv4.conf.all.rp_filter=2` (Loose) |
| Два default gateway | Неправильные metrics или несколько DHCP-серверов | Проверить `ip route show` и `dhclient` конфигурацию |

**Best Practices:**
- Для туннелей (WireGuard, IPsec, VXLAN): настроить MSS clamping: `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu`.
- Использовать `ip route get` вместо `traceroute` для быстрой проверки маршрута до конкретного хоста.
- Для multi-homed хостов (несколько интерфейсов) проверять `ip rule show` и `ip route get` с разными source IP.

**Edge Cases:**
- **Асимметричная маршрутизация:** Входящий и исходящий трафик идут через разные интерфейсы. `rp_filter=1` отбрасывает такие пакеты. Решение: `rp_filter=2`.
- **VRF:** Маршруты изолированы по VRF. Используйте `ip route show table <vrf_name>` или `ip -n <vrf_name> route show`.
- **VPN/VXLAN:** Внутренний MTU туннеля ниже 1500. `ping -M do -s 1472` помогает обнаружить снижение MTU.

**Откат:**
```bash
# Удалить добавленный маршрут:
sudo ip route del 10.0.0.0/24 via 192.168.1.1
# Вернуть rp_filter:
sudo sysctl -w net.ipv4.conf.all.rp_filter=1
```

### Сценарий 4: Фильтрация и состояние conntrack

Если пакеты дропаются без видимых причин, проверьте правила файрвола, их порядок и таблицу состояний.

#### Диагностика порядка правил (First-match)
В большинстве систем правила обрабатываются сверху вниз. Слишком общее блокирующее правило в начале может отсекать трафик, который разрешен ниже.

```bash
# 1. Проверка iptables с номерами строк и счетчиками
# -v показывает количество пакетов/байтов, --line-numbers помогает найти "теневые" правила
sudo iptables -L INPUT -n -v --line-numbers
# → Chain INPUT (policy ACCEPT 0 packets, 0 bytes)
# → num  target     prot opt source               destination
# → 1    DROP       all  --  0.0.0.0/0            0.0.0.0/0            /* block all */
# → 2    ACCEPT     tcp  --  10.0.0.0/8           0.0.0.0/0            tcp dpt:22

# 2. Проверка nftables (итоговый ruleset со всеми jump и цепочками)
sudo nft list ruleset

# 3. Трассировка пакета в реальном времени (nftables)
# Позволяет увидеть, на каком именно правиле обработка завершается
sudo nft monitor trace
```

**Валидация:**
```bash
# Ожидаемый результат: счетчики разрешающих правил растут, блокирующие — нулевые (для легитимного трафика)
sudo iptables -L INPUT -n -v --line-numbers | grep -v "0     0"
# → 2    ACCEPT     tcp  --  10.0.0.0/8   0.0.0.0/0    tcp dpt:22 packets: 1523 bytes: 98765
```

#### Проверка ресурсов conntrack
```bash
# Проверка переполнения таблицы conntrack
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_count = 262140
# → net.netfilter.nf_conntrack_max = 262144 # Таблица заполнена, новые соединения будут дропаться

# Детальная статистика по состояниям
sudo conntrack -S
# → cpu=0  found=12345  insert=12340  drop=5  ...

# Логи ядра на предмет дропов
dmesg | grep -i "nf_conntrack: table full"
# → [12345.678] nf_conntrack: table full, dropping packet

# Проверка Reverse Path Filtering (дроп входящих пакетов с "нелогичных" интерфейсов)
sysctl -a | grep "\.rp_filter"
# → net.ipv4.conf.all.rp_filter = 1
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `nf_conntrack: table full` в dmesg | `nf_conntrack_max` исчерпан | Увеличить `net.netfilter.nf_conntrack_max`, сократить таймауты |
| Счетчики iptables/nft не растут для разрешающих правил | Блокирующее правило выше | Переместить разрешающее правило выше через `-I` или `insert` в nftables |
| Соединения не устанавливаются без явных DROP-правил | `rp_filter=1` при асимметричной маршрутизации | Установить `rp_filter=2` |
| Счетчик DROP растет для легитимного трафика | Неправильный порядок правил или слишком широкий критерий | Уточнить условия (source/destination, порт, интерфейс) |

**Best Practices:**
- Всегда используйте `--line-numbers` при просмотре правил. Изменение порядка через `-I` (insert) безопаснее, чем `-A` (append).
- Для nftables включите `meta nftrace set 1` для отладки порядка обработки.
- Сохраняйте конфигурацию: `iptables-save > /etc/iptables/rules.v4` или `nft list ruleset > /etc/nftables/rules.nft`.

**Edge Cases:**
- **Docker:** Docker автоматически добавляет правила в `nat` и `filter` таблицы. При проблемах проверяйте `iptables -t nat -L -n -v` и `iptables -L DOCKER -n -v`.
- **VRF и conntrack:** По умолчанию conntrack не разделяет соединения по VRF — при overlapping IP в разных VRF возможны коллизии (требуется VRF-aware conntrack в новых ядрах).
- **UDP race condition:** При параллельных UDP-запросах с одного сокета возможны задержки ровно 1000 мс или 5000 мс (таймауты ретрансмиссии). Решение: NodeLocal DNSCache, `single-request-reopen` (только glibc; musl/Alpine игнорирует).

**Откат:**
```bash
# Удалить добавленное правило:
sudo iptables -D INPUT -s 10.0.0.0/8 -p tcp --dport 22 -j ACCEPT
# Или для nftables:
sudo nft delete rule inet filter input handle <handle>
# Вернуть rp_filter:
sudo sysctl -w net.ipv4.conf.all.rp_filter=1
```

### Сценарий 5: Резолвинг имён (DNS)

В системах с `systemd-resolved` диагностика отличается от классического `resolv.conf`.

```bash
# Проверка глобального статуса DNS
resolvectl status
# → Global
# →       DNS Servers: 192.168.1.1
# →                    8.8.8.8

# Проверка, через какой сервер идет резолвинг для конкретного домена
resolvectl query google.com
# → google.com: 142.250.186.206 -- link: eth0

# Прямой запрос (обход кэша systemd-resolved)
dig +short +timeout=2 +tries=1 @8.8.8.8 google.com
# → 142.250.186.206

# Проверка NSS (итоговый результат «глазами системы»)
getent hosts google.com
# → 142.250.186.206 google.com
```

**Валидация:**
```bash
# Ожидаемый результат: resolvectl query возвращает IP, getent совпадает
resolvectl query google.com | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+'
# → 142.250.186.206

dig +short +timeout=2 google.com
# → 142.250.186.206
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `getent hosts` возвращает пустоту, `dig` работает | Проблема в NSS (`nsswitch.conf`) или локальном кэше | Проверить `/etc/nsswitch.conf`, сбросить `resolvectl flush-caches` |
| `dig @8.8.8.8` работает, `resolvectl` — нет | Локальный резолвер не проходит рекурсию или DNSSEC падает | Проверить логи `journalctl -u systemd-resolved` |
| `SERVFAIL` | Проблема на стороне authoritative сервера или DNSSEC | `dig +trace`, `dig +cd` для отключения DNSSEC проверки |
| Долгий резолвинг | DNS-сервер недоступен, slow fallback | Проверить `resolvectl status`, настроить `ndots` в `resolv.conf` |

**Best Practices:**
- Используйте `getent hosts` для проверки итогового результата, а не только `dig` — они используют разные пути.
- Для smoke test после изменения DNS: `dig +short +timeout=2 +tries=1 @<resolver> <domain>`.
- Для мониторинга: `resolvectl query` с таймаутом 2с в скрипте.

**Edge Cases:**
- **Alpine Linux / musl libc:** Отсутствует NSS, резолвинг идет напрямую через `/etc/resolv.conf`. `getent` не работает.
- **Split-horizon DNS:** Внутренний и внешний запросы к одному домену возвращают разные IP. `resolvectl query` показывает, какой интерфейс и сервер использовался.
- **DNSSEC:** `dig +dnssec` валидирует подписи. `dig +cd` отключает проверку (у diagnostician). `SERVFAIL` при включенном DNSSEC указывает на проблему с валидацией.

**Откат:**
```bash
# Восстановить классический /etc/resolv.conf (если использовали systemd-resolved):
sudo ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
# Или для NetworkManager:
sudo nmcli dev reapply
```

### Сценарий 6: Глубокая отладка с eBPF

Когда `tcpdump` видит пакет на входе, но приложение его не получает, пакет дропается внутри ядра.

```bash
# Отслеживание "путешествия" пакета по функциям ядра
sudo pwru --filter-dst-ip 8.8.8.8 --filter-dst-port 443
# → [timestamp] netif_receive_skb -> ip_rcv -> nft_do_chain -> [DROP]

# bpftrace для отслеживания конкретных функций
sudo bpftrace -e '
kprobe:napi_poll {
    @drops[comm] = count();
}
'

# Использование dropwatch (классика)
sudo dropwatch -l kas
```

**Валидация:**
```bash
# pwru показывает стек вызовов с указанием функции дропа
# → [timestamp] netif_receive_skb -> ip_rcv -> nf_hook_slow -> [DROP] nf_reject
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Пакет виден в `tcpdump`, но не в `ss` | Дроп на L3/L4 (firewall, conntrack, socket buffers) | `pwru`, `nft monitor trace` |
| `pwru` показывает `nft_do_chain` DROP | Правило nftables | Исправить порядок/условия правил |
| `pwru` показывает `ip_rcv` DROP | Проблема с маршрутизацией или `rp_filter` | Проверить `ip route`, `rp_filter` |

**Best Practices:**
- Используйте `pwru` для быстрого поиска места дропа.
- `dropwatch` полезен для мониторинга в реальном времени.
- Для постоянного мониторинга рассмотрите `bpftrace` скрипты с записью в Prometheus (через `bpftrace_exporter`).

**Edge Cases:**
- **Ядро без BTF:** `pwru` требует BTF информации. На старых дистрибутивах может потребоваться `btfgen` или установка пакета `linux-headers` с BTF.
- **High packet rate:** При >1M pps `pwru` может создавать нагрузка. Используйте фильтры по IP/порту.

**Откат:**
```bash
# Остановить pwru: Ctrl+C
# Остановить bpftrace: Ctrl+C
```

### Сценарий 7: Транспортный уровень и сокеты (L4)

Для детального анализа TCP/UDP соединений, метрик (RTT, cwnd, retrans) и диагностики проблем на уровне сокетов используйте файл **[Диагностика сокетов TCP в Linux](./Concepts/tcp_tuning/tcp_socket_diagnostics.md)** — он содержит полный справочник по `ss -ti`, `nstat`, `bpftrace` и практическим сценариям.

Краткий чек-лист для быстрого triage:

```bash
# Общая сводка по сокетам
ss -s
# → TCP:   150 (estab 120, closed 10, orphaned 5, timewait 10)

# Прослушиваемые порты и глубина очереди
ss -lntp
# → LISTEN 0 128 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1234,fd=6))

# Глобальные счетчики ошибок
nstat -az | grep -E "ListenDrops|ListenOverflows|RetransSegs|UdpInErrors"
# → TcpExtListenDrops 0 0.0
# → TcpExtTCPListenOverflows 0 0.0
```

**Валидация:**
```bash
# Ожидаемый результат: ListenOverflows=0, RetransSegs на низком уровне
nstat -az | grep -E "ListenOverflows|ListenDrops"
# → TcpExtTCPListenOverflows    0       0.0
# → TcpExtTCPListenDrops        0       0.0
```

**Best Practices:**
- Используйте `ss` вместо устаревшего `netstat`: `ss -tulpn` вместо `netstat -tulpn`, `nstat -az` вместо `netstat -s`.
- Для детального анализа конкретного соединения: `ss -tin dst <ip>`.

**Edge Cases:**
- **Контейнеры:** Используйте `nsenter -t <pid> -n ss -tin` для диагностики из namespace контейнера.
- **TIME_WAIT flood:** Много коротких соединений. Решение: `net.ipv4.tcp_tw_reuse=1`, connection pooling.
- **Close-Wait:** Приложение не закрывает соединения. `ss -tn state close-wait` → определить PID через `ss -tnp`.

### Сценарий 8: Мониторинг и алертинг (SRE/DevOps)

В операционных системах критически важно настроить proactive-мониторинг, а не реактивную диагностику.

#### Prometheus + node_exporter: правила алертинга

```yaml
# /etc/prometheus/rules/network_troubleshooting.yml
groups:
  - name: network_health
    rules:
      - alert: InterfaceDown
        expr: up{job="node"} == 0 or node_network_up{interface!="lo"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Интерфейс {{ $labels.instance }} {{ $labels.interface }} DOWN"
          description: "Интерфейс неактивен более 1 минуты"

      - alert: HighPacketLoss
        expr: rate(node_network_receive_drop_total[5m]) > 0 or rate(node_network_transmit_drop_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Потери пакетов на {{ $labels.instance }} {{ $labels.interface }}"
          description: "Rate дропов: rx={{ $value }} tx={{ $value }}"

      - alert: ConntrackTableFull
        expr: node_netfilter_nf_conntrack_count / node_netfilter_nf_conntrack_max > 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Таблица conntrack заполнена >90% на {{ $labels.instance }}"
          description: "Использовано {{ $value | humanizePercentage }}"

      - alert: ListenOverflows
        expr: rate(node_netstat_TcpExt_TCPListenOverflows[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Переполнение Accept backlog на {{ $labels.instance }}"
          description: "Rate переполнений: {{ $value }}"
```

#### Скрипт быстрой диагностики для SRE

```bash
#!/bin/bash
# network_health.sh — быстрая проверка здоровья сети
# Использование: ./network_health.sh [interface]

IFACE="${1:-eth0}"
EXIT_CODE=0

check() {
    local name="$1"
    local result="$2"
    local expected="$3"
    if [ "$result" != "$expected" ]; then
        echo "FAIL: $name = $result (ожидалось: $expected)"
        EXIT_CODE=1
    else
        echo "OK: $name = $result"
    fi
}

echo "=== Network Health Check: $IFACE ==="

# 1. Проверка состояния интерфейса
LINK_STATE=$(ip -br link show "$IFACE" | awk '{print $2}')
check "link_state" "$LINK_STATE" "UP"

# 2. Проверка ошибок интерфейса
RX_DROPPED=$(ip -s link show "$IFACE" | awk '/RX:/ {print $5}')
check "ip.rx_dropped" "$RX_DROPPED" "0"

# 3. Проверка softnet
SOFTNET_DROPPED=$(awk '{print $2}' /proc/net/softnet_stat | paste -sd+ | bc)
check "softnet.dropped" "$SOFTNET_DROPPED" "0"

# 4. Проверка ошибок NIC
RX_MISSED=$(ethtool -S "$IFACE" 2>/dev/null | grep rx_missed_errors | awk '{print $2}')
check "nic.rx_missed_errors" "${RX_MISSED:-0}" "0"

# 5. Проверка conntrack
CONNTRACK_COUNT=$(sysctl -n net.netfilter.nf_conntrack_count 2>/dev/null || echo "0")
CONNTRACK_MAX=$(sysctl -n net.netfilter.nf_conntrack_max 2>/dev/null || echo "1")
if [ "$CONNTRACK_COUNT" -gt "$((CONNTRACK_MAX * 90 / 100))" ]; then
    echo "WARN: conntrack usage = ${CONNTRACK_COUNT}/${CONNTRACK_MAX}"
    EXIT_CODE=1
else
    echo "OK: conntrack = ${CONNTRACK_COUNT}/${CONNTRACK_MAX}"
fi

# 6. Проверка ListenOverflows
LISTEN_OVERFLOWS=$(nstat -az | grep ListenOverflows | awk '{print $2}')
check "tcp.listen_overflows" "${LISTEN_OVERFLOWS:-0}" "0"

# 7. Проверка шлюза
GATEWAY=$(ip route show default | grep -oP 'via \K[0-9.]+')
if [ -n "$GATEWAY" ]; then
    if ping -c 1 -W 2 "$GATEWAY" >/dev/null 2>&1; then
        echo "OK: gateway $GATEWAY reachable"
    else
        echo "FAIL: gateway $GATEWAY unreachable"
        EXIT_CODE=1
    fi
else
    echo "WARN: no default gateway"
fi

exit $EXIT_CODE
```

**Валидация:**
```bash
chmod +x /etc/scripts/network_health.sh
/etc/scripts/network_health.sh eth0
# → OK: link_state = UP
# → OK: ip.rx_dropped = 0
# → OK: softnet.dropped = 0
# → OK: nic.rx_missed_errors = 0
# → OK: conntrack = 45000/1048576
# → OK: tcp.listen_overflows = 0
# → OK: gateway 192.168.1.1 reachable
```

**Автоматизация:**
```bash
# Добавление в cron для периодической проверки
(crontab -l 2>/dev/null; echo "*/5 * * * * /etc/scripts/network_health.sh eth0 || logger 'Network health check FAILED'") | crrontab -
```

## Дополнительная информация

### Чек-лист быстрого реагирования (TL;DR)

1.  **`ip a`** — Есть ли IP? Поднят ли линк?
2.  **`ip r`** — Куда идет трафик? Есть ли шлюз?
3.  **`ip n`** — Видит ли хост шлюз на уровне L2?
4.  **`ping -c 3 8.8.8.8`** — Есть ли внешняя связность по IP?
5.  **`resolvectl query google.com`** — Работает ли DNS?
6.  **`ss -ntlp`** — Слушает ли приложение нужный порт?
7.  **`nstat -az | grep -E "Drop|Overflow"`** — Есть ли дропы в стеке?
8.  **`dmesg | tail`** — Есть ли критические ошибки в логах ядра?
9.  **`ethtool -S eth0 | grep -E "drop|error"`** — Есть ли аппаратные ошибки?

### Таблица симптомов → уровень OSI

| Симптом | Вероятный уровень | Первые шаги |
| :--- | :--- | :--- |
| Interface DOWN | L1 | `ethtool eth0`, проверить кабель |
| crc errors, collisions | L1 | `ethtool -S eth0`, заменить кабель |
| ARP timeout | L2 | `ip neigh show`, `arp -a` |
| `Destination Host Unreachable` | L3 | `ip route get <dest>`, `ping <gateway>` |
| `Connection refused` | L4 | `ss -lntp`, проверить порт сервиса |
| `Connection timed out` | L3/L4 | `tcpdump`, проверить firewall/NAT |
| `No route to host` | L3 | `ip route get <dest>`, `traceroute` |
| `Name or service not known` | L7 (DNS) | `dig`, `resolvectl status` |
| HTTP 502/503 | L7 | `curl -v`, проверить бэкенд |
| TLS handshake failure | L6 | `openssl s_client`, сертификат |
| Slow response | L4/L7 | `ss -tn`, `tcpdump`, `curl -w` |

### Edge Cases

- **Асимметричная маршрутизация:** Значение `net.ipv4.conf.all.rp_filter = 1` (Strict) отбрасывает легитимные пакеты, приходящие через «неправильный» интерфейс. Решение: `rp_filter=2` (Loose).
- **VRF (Virtual Routing and Forwarding):** Каждый VRF имеет изолированный стек (маршруты, ARP, conntrack). Диагностика: `ip -n <vrf_name> addr show`, `ip -n <vrf_name> route show`.
- **Network Namespaces (контейнеры):** `ip netns exec <ns> ip addr` для входа в namespace. Для диагностики без входа: `nsenter -t <pid> -n ss -tin`.
- **Cgroups / systemd resource limits:** `MemoryMax` может вызывать Memory Pressure и дропы в сетевом стеке. Проверяйте `systemctl status` и `cat /proc/pressure/memory`.
- **Бондинг (bonding/LAG):** В bonded интерфейсах ARP-записи мигрируют между slave-интерфейсами. Проверяйте `cat /proc/net/bonding/bond0`.

### Best Practices

1.  **Постоянство настроек:** Изменения через `sysctl -w` теряются при перезагрузке. Сохраняйте в `/etc/sysctl.d/99-*.conf`.
2.  **Валидация после изменений:** После изменения любого параметра проверяйте счетчики (`nstat`, `softnet_stat`, `ethtool -S`) через 5-10 минут.
3.  **Постепенное изменение:** Увеличивайте параметры постепенно. Мониторьте `%si` в `mpstat` — рост SoftIRQ без роста пропускной способности указывает на неправильное направление тюнинга.
4.  **Изоляция проблем:** Используйте `pwru` или `bpftrace` для точного определения места дропа, а не перебирайте параметры наугад.
5.  **Документирование изменений:** Ведите changelog sysctl-параметров. Используйте `git` для `/etc/sysctl.d/`.
6.  **Откат:** Всегда имейте скрипт или команды для отката настроек перед применением изменений в production.

### Типичные ошибки при диагностике

- **Смешение аппаратных и программных потерь:** `rx_dropped` в `ip -s link` может расти из-за переполнения `netdev_max_backlog` (программный уровень), а не только из-за Ring Buffer NIC.
- **Игнорирование Memory Pressure:** Даже если `softnet_stat` нулевой, пакеты могут отбрасываться на уровне `sk_buff` allocation. Проверяйте `dmesg | grep -i napi` и slab-память.
- **Неучет cgroups/containers:** В Docker/Kubernetes параметры `sysctl` могут быть переопределены на уровне Pod security context. Проверяйте приоритет настроек.
- **Отключение offloading для диагностики:** При анализе через `tcpdump` отключайте TSO/GRO (`ethtool -K eth0 tso off gro off`), иначе пакеты отображаются в неразделанном виде.
- **Остановка на первом найденном симптоме:** Низкая скорость может быть вызвана как проблемами L1 (кабель), так и L7 (приложение). Проверяйте все уровни до изоляции проблемы.
- **Устаревший `netstat`:** `netstat` устарел. Используйте `ss` (сокеты) и `nstat` (глобальные счетчики).

### Связанные документы

*   **[Инструменты диагностики сети](./network_diagnostics_tools.md)** — подробный обзор команд.
*   **[Диагностика потерь пакетов в стеке](./network_stack_packet_loss.md)** — глубокий анализ дропов в ядре.
*   **[Анализ сокетов (ss)](../Diagnostics/Networking/ss.md)** — работа с TCP/UDP сессиями.
*   **[Диагностика DNS](../Diagnostics/Networking/dns/overview.md)** — уровни резолвинга в Linux.
*   **[Общая методология диагностики](../Diagnostics/Troubleshooting/general_troubleshooting_methodology.md)** — системный подход к поиску неисправностей.
*   **[Диагностика сокетов TCP](./Concepts/tcp_tuning/tcp_socket_diagnostics.md)** — метрики `ss -ti`, `nstat`, `bpftrace`.
*   **[Сетевой Troubleshooting: Flowchart](../../Networking/OSI_TCP_IP_Model/network_troubleshooting_flowchart.md)** — визуальная методология Bottom-Up.
*   **[Hardening сетевого стека Linux](./Security/network_hardening.md)** — sysctl для защиты от сетевых атак.
