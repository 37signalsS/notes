# ip route: Управление таблицей маршрутизации

## Определения

* **`ip route`** (синоним: `ip r`) — специализированный объект утилиты `ip` из пакета `iproute2` для управления таблицами маршрутизации в ядре Linux. Работает напрямую с **FIB (Forwarding Information Base)** — структурой данных ядра, оптимизированной для сверхбыстрого поиска маршрутов.
* **Таблица маршрутизации (Routing Table)** — база данных правил, используемых сетевым стеком ядра для принятия решения о выборе выходного интерфейса и следующего узла (Next Hop) для каждого IP-пакета. Linux поддерживает до 255 независимых таблиц.
* **FIB (Forwarding Information Base)** — компилированная ядром структура данных, в которой хранятся только «рабочие» маршруты. Команда `ip route` управляет именно FIB, а не таблицами маршрутизации напрямую.
* **RIB (Routing Information Base)** — внутреннее хранилище ядра, содержащее все маршруты (включая «кандидатов» из динамических протоколов, которые ещё не «converged»). Команда `ip route show protocol <proto>` показывает маршруты из RIB для указанного протокола.
* **Шлюз (Gateway / Next Hop)** — адрес сетевого устройства в локальном сегменте, выполняющего роль посредника для передачи трафика в другие сети.
* **Connected Route (связанный маршрут)** — маршрут, автоматически создаваемый ядром при назначении IP-адреса на интерфейс. Представляет собой прямую связь с подсетью. Невозможно удалить вручную — удаляется только при снятии IP-адреса.
* **Host Route (хостовый маршрут)** — маршрут с префиксом `/32` (IPv4) или `/128` (IPv6). Указывает путь к конкретному хосту, а не к подсети.

## Основные концепции

### Иерархия и типы таблиц

Linux поддерживает до 255 независимых таблиц маршрутизации. Маппинг имен таблиц на числовые ID хранится в `/etc/iproute2/rt_tables`.

| ID | Имя | Назначение |
|:---|:---|:---|
| **255** | **local** | Обслуживает локальные и широковещательные адреса хоста. Управляется ядром автоматически. |
| **254** | **main** | Основная таблица для статических и динамических маршрутов. Используется по умолчанию. |
| **253** | **default** | Историческая таблица для маршрутов по умолчанию (в современных ОС редко используется явно). |
| **1–252** | (custom) | Пользовательские таблицы для реализации **[Policy-Based Routing (PBR)](../../Policy_Based_Routing/index.md)**. |

### Типы маршрутов

Кроме стандартных маршрутных записей (unicast), ядро поддерживает специальные типы для нетривиальных сценариев:

| Тип | Поведение | Применение |
|:---|:---|:---|
| **unicast** | Стандартная маршрутизация (по умолчанию). | Основной тип для 99% маршрутов. |
| **blackhole** | Пакет молча отбрасывается (no log, no ICMP). | Защита от DDoS, изоляция compromised-хостов, предотвращение routing loops. |
| **unreachable** | Пакет отбрасывается + ICMP "Destination Unreachable" (type 3, code 0). | Диагностика, информирование хостов об отсутствии пути. |
| **prohibit** | Пакет отбрасывается + ICMP "Communication Administratively Prohibited" (type 3, code 13). | ACL-like блокировка трафика на уровне маршрутизации. |
| **throw** | Принудительный переход к следующей таблице в RPDB (аналог `ip rule` lookup, но на уровне таблицы). | Сложные PBR-схемы с несколькими таблицами. |
| **local** | Пакет доставляется локальному процессу (только для локальных адресов). | Управляется ядром; вручную создаётся только в особых случаях. |
| **broadcast** | Пакет рассылается всем хостам в подсети. | ARP, DHCP, сервисные протоколы. |
| **multicast** | Один-ко-многим через multicast-маршрутизацию. | multicast-ping, IPTV, кластерные heartbeats. |

```bash
# Создание blackhole-маршрута (все пакеты в 10.0.0.0/8 молча отбрасываются)
sudo ip route add blackhole 10.0.0.0/8

# Создание unreachable-маршрута
sudo ip route add unreachable 10.0.0.5/32

# Создание prohibit-маршрута
sudo ip route add prohibit 10.0.0.100/32

# Удаление специального маршрута
sudo ip route del blackhole 10.0.0.0/8
```

### FIB и RIB: разница между实际控制ом и отображением

Это ключевое понимание для диагностики маршрутизации в Linux:

*   **FIB** — то, что реально используется для пересылки пакетов. Команда `ip route show` (без флагов) показывает именно FIB.
*   **RIB** — внутреннее хранилище ядра со всеми кандидатами. Динамические протоколы (BGP, OSPF) загружают маршруты в RIB; ядро «компилирует» лучшие из них в FIB.

```bash
# Просмотр FIB (только «рабочие» маршруты)
ip route show

# Просмотр маршрутов определённого протокола из RIB
ip route show protocol static
ip route show protocol bgp
ip route show protocol ospf

# Просмотр ВСЕХ таблиц (включая локальную, custom и пр.)
ip route show table all

# Эмуляция FIB-поиска для конкретного пакета (включая все таблицы и правила)
ip route get 8.8.8.8
# → 8.8.8.8 via 192.168.1.1 dev eth0 src 192.168.1.10 uid 0
#   table local ← ядро сначала проверяет таблицу local

# Глубокая проверка с учётом source-ip и входящего интерфейса
ip route get 8.8.8.8 from 192.168.1.10
# → покажет, какую таблицу выбрало ядро для этого конкретного pairing

# Флаг fibmatch: показать не эмуляцию, а реальный FIB-запрос (полезно при проблемах с кэшем)
ip route get 8.8.8.8 fibmatch
```

> **Важно:** Если `ip route get` показывает маршрут через интерфейс, который отличается от ожидаемого — проблема скорее всего в `ip rule` (RPDB), а не в `ip route`.

### Connected routes и host routes

**Connected routes** создаются ядром автоматически при назначении IP-адреса на интерфейс. Их нельзя удалить через `ip route del` — они исчезнут только при снятии IP-адреса.

```bash
# Пример connected-маршрута (автоматически после назначения IP)
sudo ip addr add 192.168.1.10/24 dev eth0
ip route show
# → 192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.10
#                          ^^^^^^^^^^^^ proto kernel = connected route

# Host route (/32) — путь к конкретному хосту через шлюз
sudo ip route add 10.0.0.5/32 via 192.168.1.1
# Используется для: отказоустойчивых кластеров (VIP), Anycast, static host routing

# Просмотр только хостовых маршрутов
ip route show | grep '/32'
```

### Атрибуты маршрутов

* **via** — IP-адрес шлюза (Next Hop).
* **dev** — сетевой интерфейс, через который осуществляется передача.
* **proto** — источник маршрута:
    * `kernel` — connected route (создан ядром при назначении IP).
    * `static` — добавлен вручную через `ip route add`.
    * `dhcp` — получен от DHCP-сервера.
    * `bgp`, `ospf`, `zebra` и др. — от динамических протоколов маршрутизации.
* **metric** — приоритет маршрута (при наличии нескольких путей к одной цели выбирается маршрут с наименьшим значением). Если metric не задан, ядро использует значение по умолчанию (обычно 0).
* **scope** — область видимости маршрута:
    * `global` — для внешнего трафика (основной тип).
    * `link` — только для локального сегмента (connected routes).
    * `host` — только для локального хоста (loopback, local).
* **src** — предпочитаемый исходный IP (`Source IP`) для пакетов, генерируемых хостом. Подробнее: **[Маршрутизация в Linux — выбор Source IP](../../SystemAdministration/routing.md#выбор-исходного-ip-source-ip-selection)**.
* **mtu** — Maximum Transmission Unit для маршрута. Перезаписывает MTU интерфейса для данного пути.
* **advmss** — Explicit MSS (Maximum Segment Size) для TCP-соединений через данный маршрут. Критично для туннелей (GRE, WireGuard, IPsec), где реальный MTU меньше стандарта 1500.
* **window** — Максимальный размер TCP window для маршрута (в байтах).
* **initcwnd** — Начальное окно перегрузки (Initial Congestion Window). Увеличение до 10–30 сегментов ускоряет старт HTTP-соединений.
* **initrwnd** — Начальное окно приёма (Initial Receive Window).
* **quickack** — Включение немедленного подтверждения пакетов (минимизация задержек Delayed ACK).
* **rto_min** — Минимальный Retransmission Timeout (в мс). Позволяет увеличить таймаут для маршрутов с высокой задержкой (спутниковые каналы).
* **congctl** — Алгоритм управления перегрузкой TCP для данного маршрута (например, `bbr`, `cubic`, `dctcp`).
* **nospace** — Стратегия обработки ICMP "Fragmentation Needed" (can set blackhole/unreachable для маршрутов с PMTU-проблемами).
* **encap** — Параметры инкапсуляции (MPLS, IPsec, BAREUDP и др.).

### Nexthop-объекты (ядро 5.3+)

Современный механизм, позволяющий управлять параметрами следующего узла отдельно от маршрутов. Упрощает управление ECMP и уменьшает дублирование конфигурации.

```bash
# Создание nexthop-объекта
sudo ip nexthop add id 1 via 192.168.1.1 dev eth0
sudo ip nexthop add id 2 via 192.168.1.2 dev eth1

# Группа nexthop (для ECMP) — трафик распределяется между ID 1 и 2
sudo ip nexthop add id 100 group 1/2

# Использование nexthop в маршруте
sudo ip route add 10.10.0.0/24 nhid 100

# Просмотр nexthop-объектов
ip nexthop show

# Удаление nexthop (невозможно, если он используется в маршруте)
sudo ip nexthop del id 100
```

> **Преимущество:** При изменении IP шлюза достаточно обновить nexthop-объект (`ip nexthop replace`), а не каждый маршрут отдельно. Это критично при наличии сотен маршрутов через один шлюз.

## Справочник команд

### Анализ

| Команда | Описание |
|:---|:---|
| `ip route show` | Просмотр FIB (таблица main по умолчанию). |
| `ip route show table <ID/имя>` | Просмотр конкретной таблицы. |
| `ip route show table all` | Просмотр всех таблиц (включая local, main, custom). |
| `ip route show protocol <proto>` | Маршруты из RIB для указанного протокола (static, bgp, ospf и др.). |
| `ip route show proto <proto>` | То же, короткая форма. |
| `ip route show type <тип>` | Фильтрация по типу (unicast, blackhole, unreachable, prohibit, throw, local, broadcast). |
| `ip route get <dst>` | Эмуляция FIB-поиска для конкретного назначения. |
| `ip route get <dst> from <src>` | Эмуляция с учётом source-ip. |
| `ip route get <dst> iif <iface>` | Эмуляция с учётом входящего интерфейса. |
| `ip route get <dst> fibmatch` | Показать реальный FIB-запрос вместо эмуляции. |
| `ip route get <dst> vrf <name>` | Эмуляция в контексте VRF. |
| `ip monitor route` | Мониторинг изменений в таблице маршрутизации в реальном времени. |

### Модификация

| Команда | Описание |
|:---|:---|
| `ip route add <dst> via <gw> dev <iface>` | Добавление маршрута. |
| `ip route add default via <gw>` | Установка маршрута по умолчанию. |
| `ip route add <dst> blackhole/unreachable/prohibit` | Добавление специального маршрута. |
| `ip route replace <dst> via <gw>` | Атомарная замена маршрута (add или replace). |
| `ip route change <dst> via <gw>` | Изменение существующего маршрута (только если он уже есть). |
| `ip route del <dst>` | Удаление маршрута. |
| `ip route del <dst> via <gw>` | Удаление конкретного маршрута (если их несколько на одну цель). |
| `ip route flush` | Очистка таблицы main. **Осторожно!** |
| `ip route flush table <ID>` | Очистка конкретной таблицы. |
| `ip route save > file.txt` | Сохранение всех маршрутов в файл (для бэкапа или анализа). |
| `ip route restore < file.txt` | Восстановление маршрутов из файла. |

## Практические сценарии

### Анализ и просмотр маршрутов

```bash
# Просмотр основной таблицы маршрутизации
ip route show

# Просмотр конкретной таблицы (например, для отладки PBR)
ip route show table 100

# Детальный анализ выбора пути для конкретного назначения
ip route get 8.8.8.8
# → 8.8.8.8 via 192.168.1.1 dev eth0 src 192.168.1.10 uid 1000
#   (src указывает IP, который ядро подставит в пакет)

# Проверка маршрута с учётом source-ip (важно при PBR)
ip route get 8.8.8.8 from 192.168.1.50
# → покажет, какую таблицу RPDB выбрала для данного pairing

# Просмотр всех таблиц (включая custom и local)
ip route show table all | head -50

# Просмотр только статических маршрутов
ip route show protocol static

# Просмотр только маршрутов от BGP/OSPF (требует запущенного протокола)
ip route show protocol bgp
ip route show protocol ospf

# Просмотр только хостовых маршрутов (/32)
ip route show | grep '/32'

# Просмотр маршрутов с определённым типом
ip route show type blackhole
ip route show type unreachable
```

### Модификация маршрутов

```bash
# Добавление маршрута к подсети через шлюз
sudo ip route add 10.0.0.0/8 via 192.168.1.1 dev eth0

# Установка маршрута по умолчанию
sudo ip route add default via 192.168.1.1

# Замена маршрута (атомарная операция, предотвращающая потерю связи)
sudo ip route replace default via 192.168.1.254

# Удаление маршрута
sudo ip route del 10.0.0.0/8

# Удаление маршрута по умолчанию (если есть несколько default)
sudo ip route del default via 192.168.1.1

# Очистка ТОЛЬКО пользовательских маршрутов (оставляя connected и local)
sudo ip route flush table main
# ⚠️ ВНИМАНИЕ: Это удалит все маршруты в main, включая default. Соединение будет потеряно!

# Безопасная очистка: удаление только определённого типа
sudo ip route flush table 100

# Сохранение всех маршрутов в файл (для бэкапа перед изменениями)
ip route save > /tmp/routes_backup.txt

# Восстановление маршрутов из файла
sudo ip route restore < /tmp/routes_backup.txt
```

### Специальные маршруты (blackhole, unreachable, prohibit)

```bash
# Blackhole: молчаливое отбрасывание трафика (без ICMP, без логов)
# Используется для: изоляции compromised-хостов, предотвращения routing loops
sudo ip route add blackhole 10.0.0.0/8

# Unreachable: отбрасывание + ICMP "Network Unreachable"
# Используется для: информирования отправителя, диагностики
sudo ip route add unreachable 10.0.0.5/32

# Prohibit: отбрасывание + ICMP "Administratively Prohibited"
# Используется для: ACL-подобной блокировки на уровне маршрутизации
sudo ip route add prohibit 10.0.0.100/32

# Пример: VPN kill-switch — весь трафик идёт через VPN, а при обрыве — blackhole
sudo ip route add default dev tun0
sudo ip route add blackhole default metric 10000

# Удаление blackhole-маршрута
sudo ip route del blackhole 10.0.0.0/8
```

### Тюнинг TCP через маршруты

Настройка параметров стека для конкретных направлений позволяет оптимизировать производительность без глобальных изменений в `sysctl`.

```bash
# initcwnd — Начальное окно перегрузки (Initial Congestion Window)
# Увеличение до 10–30 сегментов ускоряет старт HTTP-соединений (особенно для CDN/VPS)
sudo ip route change default via 192.168.1.1 initcwnd 15

# initrwnd — Начальное окно приёма (Initial Receive Window)
sudo ip route change default via 192.168.1.1 initrwnd 15

# advmss — Явное указание MSS (Maximum Segment Size)
# Критично для туннелей (GRE, WireGuard), где реальный MTU < 1500
sudo ip route add default via 10.0.0.1 dev tun0 advmss 1400

# quickack — Немедленные ACK (минимизация задержек Delayed ACK)
sudo ip route change default via 192.168.1.1 quickack 1

# rto_min — Минимальный Retransmission Timeout
# Увеличение для маршрутов с высокой задержкой (спутник, long-distance WAN)
sudo ip route change default via 192.168.1.1 rto_min 3000

# congctl — Алгоритм управления перегрузкой для маршрута
sudo ip route change default via 192.168.1.1 congctl bbr

# Комбинированный тюнинг (максимальная производительность для CDN)
sudo ip route change default via 192.168.1.1 initcwnd 30 initrwnd 30 quickack 1 rto_min 200

# Проверка применённых параметров
ip route get 8.8.8.8
# → в выводе будут указаны все применённые параметры
```

### ECMP (Equal-Cost Multi-Path)

Метод распределения трафика между несколькими шлюзами с одинаковым приоритетом.

```bash
# Старый синтаксис (multipath)
sudo ip route add default scope global \
    nexthop via 192.168.1.1 dev eth0 weight 1 \
    nexthop via 192.168.1.2 dev eth1 weight 1

# Современный синтаксис через nexthop group (ядро 5.3+)
sudo ip nexthop add id 1 via 192.168.1.1 dev eth0
sudo ip nexthop add id 2 via 192.168.1.2 dev eth1
sudo ip nexthop add id 100 group 1/2
sudo ip route add default nhid 100

# ECMP с весами (70/30)
sudo ip route add default scope global \
    nexthop via 192.168.1.1 dev eth0 weight 7 \
    nexthop via 192.168.1.2 dev eth1 weight 3

# Просмотр ECMP-маршрутов
ip route show
# → default
#         nexthop via 192.168.1.1 dev eth0 weight 1
#         nexthop via 192.168.1.2 dev eth1 weight 1

# Просмотр nexthop-объектов
ip nexthop show
```

### Мониторинг изменений в реальном времени

```bash
# Мониторинг всех изменений в таблице маршрутизации
sudo ip monitor route
# → [10.0.0.0/8] dev eth0 proto kernel scope link src 192.168.1.10
# → deleted 10.0.0.0/8 via 192.168.1.1

# Фильтрация: только добавления/удаления
sudo ip monitor route | grep -E "^(Broadcast|Deleted|[0-9])"

# Мониторинг в фоне (для логирования)
sudo ip monitor route >> /var/log/route_changes.log 2>&1 &

# Сохранение текущего состояния для сравнения
ip route show > /tmp/routes_before.txt
# ... внести изменения ...
ip route show > /tmp/routes_after.txt
diff /tmp/routes_before.txt /tmp/routes_after.txt
```

### Сохранение настроек (Persistence)

Методы персистентной настройки зависят от используемого сетевого менеджера:

*   **Netplan (Ubuntu/Debian)**: Секция `routes:` в файлах `/etc/netplan/*.yaml`.
*   **NetworkManager (RHEL/CentOS/Fedora)**: Через команду `nmcli connection modify <NAME> +ipv4.routes "10.0.0.0/8 192.168.1.1"`.
*   **systemd-networkd**: Секция `[Route]` в файлах `.network`.
*   **Временное (с ethers)**: `/etc/ethers` + `arp -f` + скрипт в `/etc/rc.local` (устаревший метод).

```yaml
# Пример: Netplan — статический маршрут с metric
network:
  ethernets:
    enp0s3:
      routes:
        - to: 10.20.0.0/16
          via: 192.168.1.1
          metric: 100
```

```bash
# Пример: NetworkManager — добавление маршрута
nmcli connection modify "System eth0" +ipv4.routes "10.20.0.0/16 192.168.1.1 100"
nmcli connection up "System eth0"
```

Подробные инструкции: **[Постоянная настройка сети](../../Settings/Persistent_Network/index.md)**.

## Диагностика и устранение неполадок

### Методология

1. **Проверить FIB:** `ip route show` — есть ли маршрут к цели?
2. **Эмулировать FIB:** `ip route get <dst>` — какой путь выберет ядро?
3. **Проверить RPDB:** `ip rule show` — не перенаправляет ли правило пакет в другую таблицу?
4. **Проверить source-ip:** `ip route get <dst> from <src>` — влияет ли исходный адрес?
5. **Проверить интерфейс:** `ip link show` — UP ли интерфейс?
6. **Проверить ARP:** `ip neighbour show` — разрешён ли MAC-адрес шлюза?

### Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **RTNETLINK answers: File exists** | Маршрут уже прописан в таблице. | Используйте `replace` вместо `add`. |
| **RTNETLINK answers: No such device** | Указанный интерфейс не существует или DOWN. | `ip link show <dev>` — проверьте состояние интерфейса. |
| **Network is unreachable** | Отсутствует маршрут к сети шлюза или интерфейс DOWN. | Проверьте `ip address` и `ip link`. Добавьте connected route или default gateway. |
| **Invalid prefix for "..."** | Некорректный формат CIDR (например, лишние биты в маске). | 192.168.1.1/24 — неверно, 192.168.1.0/24 — верно. |
| **RTNETLINK answers: No route to host** | Шлюз недоступен (ARP не резолвится). | Проверьте `ip neighbour show` и `ping <gw>`. |
| **RTNETLINK answers: Permission denied** | Команда выполнена без root. | Используйте `sudo`. |
| **Маршрут есть, но пакеты не идут** | Проблема с `ip rule` (RPDB) — пакет уходит в другую таблицу. | `ip route get <dst> from <src>` покажет, какую таблицу выбрало ядро. |
| **ECMP не балансирует** | Все пакеты идут через один шлюз (хеш-алгоритм ядра). | Используйте `ip route get` для проверки; балансировка работает на уровне потоков, а не пакетов. |
| **ip route flush удаляет default gateway** | Очистка таблицы main удаляет все маршруты, включая default. | Перед очисткой сохраните маршруты: `ip route save > /tmp/routes.txt`. |

## Дополнительная информация

### Сравнение с альтернативными инструментами

| Инструмент | Уровень | Сценарий |
|:---|:---|:---|
| **ip route** | Ядро (FIB) | Основной инструмент управления маршрутизацией в Linux. |
| **route** (net-tools) | Ядро | Устаревший; не поддерживает nexthop-объекты, PBR, advanced metrics. |
| **NetworkManager** | Пользователь | Автоматическое управление маршрутами; для ручного контроля используйте `ip route`. |
| **FRRouting** | Динамическая маршрутизация | BGP, OSPF, IS-IS — маршруты загружаются в RIB и компилируются в FIB. |
| **nftables** | Трансляция адресов | DNAT/SNAT — не маршрутизация, но влияет на путь пакета. |

### Связанные темы

*   **[ip rule & PBR](./ip_rule_pbr.md)** — управление правилами выбора таблиц маршрутизации.
*   **[Маршрутизация в Linux](../../SystemAdministration/routing.md)** — концептуальный обзор, FIB vs RIB, IP Forwarding и выбор Source IP.
*   **[Сценарии маршрутизации](../../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/routing_scenarios.md)** — ECMP, multipath, hash-политики, маршрутизация по source IP.
*   **[Настройка initcwnd](../../Concepts/tcp_tuning/tcp_initcwnd.md)** — детальный разбор начального окна перегрузки и его влияние на производительность.
*   **[Оптимизация TCP](../../Concepts/tcp_tuning/tcp_tuning_overview.md)** — детальный разбор параметров `initcwnd` и `advmss`.
