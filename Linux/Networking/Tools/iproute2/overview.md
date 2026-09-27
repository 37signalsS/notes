# iproute2: Обзор

## Определения

* **`iproute2`** — современный набор утилит командной строки для управления сетевым стеком в ядре Linux. Полностью заменяет устаревший пакет `net-tools` (утилиты `ifconfig`, `route`, `arp`, `netstat`, `brctl`). Является стандартом во всех современных дистрибутивах.
* **Netlink** — механизм (сокет-интерфейс), используемый `iproute2` для прямого взаимодействия с ядром. Обеспечивает атомарность операций, высокую скорость и доступ к функциям ядра, которые недоступны устаревшим инструментам через `ioctl`. Протокол Netlink также используется daemon-процессами (NetworkManager, systemd-networkd, FRRouting) для получения событий от ядра.
* **Объект** — логическая единица сетевой конфигурации в `iproute2`. Утилита `ip` оперирует такими объектами, как `link`, `address`, `route`, `neighbour` и другими. Каждый объект имеет набор действий (`add`, `del`, `show`, `replace`, `change`, `flush`) и атрибутов.
* **Действие (command)** — операция, выполняемая над объектом. Основные действия:
    * `show` (или `list`, `sh`, `l`) — просмотр текущего состояния.
    * `add` — добавление нового элемента.
    * `del` (или `delete`) — удаление элемента.
    * `replace` — атомарная замена (если существует — заменяет, если нет — добавляет). Предотвращает потерю связи при обновлении маршрутов.
    * `change` — изменение существующего элемента (вызов с ошибкой, если элемент не найден).
    * `flush` (или `clear`) — удаление всех элементов удовлетворяющих фильтру.
    * `help` — справка по объекту.

## Основные концепции

### Архитектура и компоненты

Пакет `iproute2` включает в себя ряд специализированных инструментов:

| Утилита | Назначение | Заменяет | Подробнее |
| :--- | :--- | :--- | :--- |
| **`ip`** | Управление сетевыми объектами (интерфейсы, адреса, маршруты, туннели, туннели, ACL). | `ifconfig`, `route`, `arp`, `ifup/ifdown` | — |
| **`ss`** | Диагностика сокетов и TCP-соединений. | `netstat` | [`ss`](../../../Diagnostics/Networking/ss.md) |
| **`tc`** | Управление трафиком, очередями (qdisc) и QoS (шейпинг, приоритизация). | `tc` (ventas) | [`tc`](./tc.md), [`tc netem`](./tc_netem.md) |
| **`bridge`** | Настройка и управление сетевыми мостами (L2). | `brctl` | — |
| **`devlink`** | Управление аппаратными ресурсами NIC (Offload, порты, драйверы). | — | — |
| **`mptcp`** | Управление путями и параметрами MultiPath TCP. | — | — |
| **`rdma`** | Настройка Remote Direct Memory Access. | — | — |
| **`nstat`** | Сбор и отображение SNMP-счётчиков ядра (TCP, UDP, ICMP). | `netstat -s` | — |
| **`lnstat`** | Отображение содержимого `/proc/net/stat/` (RT cache, nf_conntrack). | — | — |
| **`rtacct`** | Мониторинг сетевого трафика по policy-routing таблицам. | — | — |

### Синтаксис команд

Основной формат вызова утилиты `ip`:

```bash
ip [опции] объект команда [аргументы]
```

**Ключевые опции:**

| Опция | Описание | Пример |
| :--- | :--- | :--- |
| `-br` | Краткий (brief) однострочный вывод. | `ip -br a` |
| `-j` | Формирование вывода в формате JSON. | `ip -j link show` |
| `-p` | В сочетании с `-j` делает JSON читаемым (pretty print). | `ip -jp addr show` |
| `-s` | Отображение статистики. Повторное использование (`-s -s`) увеличивает детализацию. | `ip -s -s link show eth0` |
| `-d` | Детальная (detailed) информация о низкоуровневых параметрах. Повторное `-d -d` ещё подробнее. | `ip -d link show eth0` |
| `-4` / `-6` | Фильтрация по протоколам IPv4 или IPv6. | `ip -4 route show` |
| `-n` | Подавление обратного разрешения имён (DNS). Ускоряет вывод. | `ip -n neigh show` |
| `-o` | Однострочный вывод (для `ip monitor`). | `ip -o monitor link` |
| `-t` | Метка времени в выводе `ip monitor`. | `ip -t monitor route` |
| `-rc` | Режим с кодом возврата (return code): 0 — успех, 2 — частичная ошибка. | `ip -rc link set eth0 up` |

**Общая опция `-V` (capital V):** Отображает версию пакета.

```bash
$ ip -V
ip utility, iproute2-5.15.0, PDMA Suite
```

### Версии и совместимость

| Пакет | Минимальное ядро | Ключевые возможности |
| :--- | :--- | :--- |
| iproute2 4.x | 3.x | Базовые: link, addr, route, neigh, tunnel. |
| iproute2 5.x | 4.x+ | Nexthop-объекты,/MPLS, SRv6, большинство modern features. |
| iproute2 5.15+ | 5.10+ |/ip addr add ... nodad, улучшенная IPv6-поддержка. |
| iproute2 6.x | 5.15+ | Расширенная поддержка MPTCP, BPF, hardware offload. |

> **Совет:** Для серверных дистрибутивов (RHEL 8+, Ubuntu 22.04+, Debian 11+) всегда доступна достаточно новая версия. Для встраиваемых систем проверяйте `ip -V`.

### Ключевые объекты и их назначение

| Объект | Сокращение | Назначение | Описание |
| :--- | :--- | :--- | :--- |
| **link** | `ip l` | Управление L1-L2 (MTU, MAC, состояние). | [`ip link`](./ip_link.md) |
| **address** | `ip a` | Управление IP-адресами (L3). | [`ip address`](./ip_address.md) |
| **route** | `ip r` | Таблицы и метрики маршрутизации (FIB). | [`ip route`](./ip_route.md) |
| **neighbour** | `ip n` | ARP-кэш и таблица соседей NDP. | [`ip neighbour`](./ip_neighbour.md) |
| **rule** | `ip rule` | Правила выбора таблиц (Policy-Based Routing). | [`ip rule`](./ip_rule_pbr.md) |
| **vrf** | `ip vrf` | Виртуальная маршрутизация (VRF). | [VRF](../../vrf.md) |
| **netns** | `ip netns` | Изоляция сетевых пространств имен. | [`ip netns`](./ip_netns.md) |
| **tunnel** | `ip tunnel` | Настройка туннелей (GRE, IPIP, SIT). | [`ip tunnel`](./ip_tunnel.md) |
| **tcp_metrics** | `ip tcp_m` | Просмотр и сброс закэшированных параметров TCP. | — |
| **ntable** | `ip nt` | Управление параметрами таблиц ARP/NDP. | — |
| **xfrm** | `ip x` | Настройка IPsec (SA/SP). | [IPsec](../../../../Networking/Tunnels/ipsec/ipsec.md) |
| **maddress** | `ip m` | Управление групповыми (multicast) адресами. | — |
| **monitor** | `ip monitor` | Мониторинг событий в реальном времени (ссылки, адреса, маршруты). | — |
| **netconf** | `ip netc` | Просмотр/настройка параметров ядра (sysctl через netlink). | — |
| **ila** | `ip ila` | Управление IPv6 Locally-Routed ILA (Identifier Locator Addressing). | — |

### Привилегии и безопасность

Для выполнения большинства операций `iproute2` требуются права root. Существует несколько способов получения привилегий:

```bash
# Способ 1: sudo (наиболее распространённый)
sudo ip link set eth0 up

# Способ 2: capabilities (для скриптов и systemd-юнитов)
sudo setcap cap_net_admin+ep /usr/sbin/ip
# Теперь ip может выполнять операции без root (ограниченно)

# Способ 3: systemd-run (для одноразовых операций)
sudo systemd-run --property=CapabilityBoundingSet=CAP_NET_ADMIN ip link set eth0 up
```

**Ключевые capabilities:**
* `CAP_NET_ADMIN` — управление интерфейсами, адресами, маршрутами, правилами, туннелями, qdisc.
* `CAP_NET_RAW` — raw-сокеты (некоторые операции `ip xfrm`).
* `CAP_SYS_ADMIN` — управление namespaces (`ip netns`), some devlink operations.

> **Важно:** В контейнерах (Docker, Kubernetes) по умолчанию контейнер не имеет `CAP_NET_ADMIN`. Для настройки сети контейнера необходимо передавать capability или использовать privileged mode.

### Диагностика и отладка

Пакет `iproute2` предоставляет встроенные средства для отладки проблем:

```bash
# Просмотр всех интерфейсов с подробной статистикой
ip -s -s link show

# Просмотр маршрута с указанием всех атрибутов (metric, advmss, window)
ip route get 8.8.8.8

# Просмотр содержимого всех таблиц маршрутизации (включая local, main, custom)
ip route show table all

# Просмотр кэша TCP-метрик
ip tcp_metrics show

# Просмотр параметров ядра через netlink (sysctl-подобный)
ip netconf show
ip netconf show dev eth0

# Просмотр состояния IPsec
ip xfrm state
ip xfrm policy
```

### Мониторинг событий в реальном времени

Команда `ip monitor` позволяет отслеживать изменения в сетевой конфигурации без опроса (pull). Ядро отправляет уведомления (push) при каждом изменении:

```bash
# Мониторинг всех событий
sudo ip monitor all

# Мониторинг только изменений ссылок (UP/DOWN)
sudo ip monitor link

# Мониторинг только маршрутов
sudo ip monitor route

# Мониторинг ARP/NDP
sudo ip monitor neigh

# Мониторинг с меткой времени и однострочным форматом
sudo ip -ot monitor all

# Логирование в файл (для анализа позже)
sudo ip monitor all >> /var/log/network_events.log 2>&1 &
```

> **Совет:** Используйте `ip monitor` вместо постоянного `watch ip route show` — это потребляет меньше ресурсов и не пропускает события.

### Автоматизация и скрипты

**JSON-вывод для парсинга:**

```bash
# Получить список всех интерфейсов и их IP-адресов
ip -j -4 addr show | jq -r '.[] | .ifname as $dev | .addr_info[] | select(.family == "inet") | "\($dev) \(.local)"'

# Проверить, UP ли интерфейс
ip -j link show eth0 | jq -r '.[0].operstate'

# Извлечь все default-шлюзы
ip -j route show | jq -r '.[] | select(.dst == "default") | .gateway'

# Получить список всех MAC-адресов
ip -j link show | jq -r '.[] | select(.address != null) | "\(.ifname) \(.address)"'
```

**Циклы по интерфейсам:**

```bash
# Перезапуск всех интерфейсов (кроме loopback)
for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep -v lo); do
    sudo ip link set "$iface" down && sudo ip link set "$iface" up
done

# Сбор статистики по всем интерфейсам
for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep -v lo); do
    echo "=== $iface ==="
    ip -s link show "$iface"
done
```

**Сохранение и восстановление:**

```bash
# Сохранение всех маршрутов (для бэкапа)
ip route save > /tmp/routes_backup.txt

# Восстановление маршрутов
sudo ip route restore < /tmp/routes_backup.txt

# Сохранение всех адресов
ip -o -4 addr show | awk '{print $2, $4}' > /tmp/addresses_backup.txt
```

## Практические сценарии

### Оперативная диагностика

```bash
# Просмотр статуса интерфейсов и адресов (кратко)
ip -br a

# Определение выбранного маршрута для конкретного IP
ip route get 8.8.8.8

# Просмотр активных соединений и процессов (аналог netstat -tunlp)
ss -tunlp

# Мониторинг всех сетевых событий в реальном времени
ip monitor all

# Проверка ARP-кэша
ip -br neigh show

# Просмотр всех таблиц маршрутизации
ip route show table all
```

### Анализ производительности и ошибок

```bash
# Детальная статистика ошибок и дропов на интерфейсе
ip -s -s link show eth0

# Просмотр SNMP-статистики TCP стека (через nstat)
nstat -az | grep Tcp

# Просмотр кэша TCP-метрик (RTT, cwnd, MSS для последних соединений)
ip tcp_metrics show

# Просмотр содержимого всех таблиц маршрутизации (поиск нестандартных маршрутов)
ip route show table all | grep -v "table local"
```

### Автоматизация через JSON и jq

```bash
# Получить операционное состояние интерфейса eth0
ip -j link show eth0 | jq -r '.[0].operstate'

# Извлечь все IPv4 адреса в виде списка
ip -j -4 addr show | jq -r '.[].addr_info[].local'

# Найти интерфейс по MAC-адресу
ip -j link show | jq -r '.[] | select(.address == "00:11:22:33:44:55") | .ifname'

# Получить MTU всех интерфейсов
ip -j link show | jq -r '.[] | "\(.ifname) \(.mtu)"'

# Проверить, есть ли IP-адрес на интерфейсе
ip -j addr show dev eth0 | jq '.[0].addr_info | length' | grep -q '^0$' && echo "No IP" || echo "Has IP"
```

### Миграция с net-tools

Для администраторов, привыкших к `net-tools`, вот ключевые соответствия:

| net-tools (legacy) | iproute2 (современный) | Файл |
| :--- | :--- | :--- |
| `ifconfig` | `ip addr`, `ip link` | [ip_link.md](./ip_link.md), [ip_address.md](./ip_address.md) |
| `ifconfig eth0 up/down` | `ip link set eth0 up/down` | [ip_link.md](./ip_link.md) |
| `ifconfig eth0 mtu 1500` | `ip link set eth0 mtu 1500` | [ip_link.md](./ip_link.md) |
| `ifconfig eth0:0 192.168.1.2/24` | `ip addr add 192.168.1.2/24 dev eth0` | [ip_address.md](./ip_address.md) |
| `route -n` | `ip route` | [ip_route.md](./ip_route.md) |
| `route add default gw 192.168.1.1` | `ip route add default via 192.168.1.1` | [ip_route.md](./ip_route.md) |
| `arp -n` | `ip neigh` | [ip_neighbour.md](./ip_neighbour.md) |
| `arp -s 192.168.1.1 aa:bb:cc:dd:ee:ff` | `ip neigh add 192.168.1.1 lladdr aa:bb:cc:dd:ee:ff dev eth0 nud permanent` | [ip_neighbour.md](./ip_neighbour.md) |
| `netstat -tanp` | `ss -tanp` | [ss.md](../../../Diagnostics/Networking/ss.md) |
| `netstat -rn` | `ip route` | [ip_route.md](./ip_route.md) |
| `netstat -i` | `ip -s link` | — |
| `netstat -s` | `nstat -az` | — |
| `netstat -g` | `ip maddr` | — |
| `brctl show` | `bridge link show` | — |
| `brctl addbr br0` | `ip link add br0 type bridge` | — |
| `ifup/ifdown` | `ip link set up/down` | — |

> **Подробнее:** Сравнение характеристик и причин миграции см. в [netstat.md](../../../Diagnostics/Networking/netstat.md).

## Дополнительная информация

### Сохранение конфигурации (Persistence)

Изменения через `iproute2` применяются немедленно в ядре, но **исчезают** после перезагрузки. Для постоянной настройки используйте системные конфигураторы:

| Менеджер | Дистрибутивы | Конфигурация |
| :--- | :--- | :--- |
| **Netplan** | Ubuntu, Debian | Файлы `/etc/netplan/*.yaml` |
| **NetworkManager** | RHEL, CentOS, Fedora, Desktop | `nmcli connection modify` |
| **systemd-networkd** | Минималистичные, контейнеры | Файлы `.network` и `.link` |
| **ifupdown2** | Debian (устаревший) | `/etc/network/interfaces` |

Подробнее: **[Постоянная настройка сети](../../Settings/Persistent_Network/index.md)**.

### Установка пакета

| Дистрибутив | Команда установки |
| :--- | :--- |
| **Debian / Ubuntu** | `sudo apt install iproute2` |
| **RHEL / Fedora** | `sudo dnf install iproute` |
| **Arch Linux** | `sudo pacman -S iproute2` |
| **Alpine** | `apk add iproute2` |
| **openSUSE** | `sudo zypper install iproute2` |
| **Gentoo** | `sudo emerge sys-apps/iproute2` |

### Сравнение с альтернативами

| Инструмент | Уровень | Сценарий |
| :--- | :--- | :--- |
| **iproute2** | Ядро (netlink) | Основной инструмент для управления сетевым стеком Linux. |
| **NetworkManager** | Пользователь | Автоматическое управление; для ручного контроля используйте `iproute2`. |
| **systemd-networkd** | Пользователь | Минималистичные системы; настройка через `.network` файлы. |
| **FRRouting** | Динамическая маршрутизация | BGP, OSPF, IS-IS — маршруты загружаются в RIB и компилируются в FIB. |
| **ethtool** | Драйвер NIC | Управление аппаратными параметрами NIC (offload, ring buffer, coalescing). |

### Связанные темы

* **[ip link](./ip_link.md)** — управление сетевыми интерфейсами (L1-L2).
* **[ip address](./ip_address.md)** — управление IP-адресами (L3).
* **[ip route](./ip_route.md)** — таблицы маршрутизации и статические маршруты.
* **[ip neighbour](./ip_neighbour.md)** — ARP/NDP-таблицы и кэш соседей.
* **[ip rule & PBR](./ip_rule_pbr.md)** — policy-based routing и правила выбора таблиц.
* **[ip netns](./ip_netns.md)** — изоляция сетевых пространств имен.
* **[ip tunnel](./ip_tunnel.md)** — настройка туннелей (GRE, IPIP, SIT).
* **[tc](./tc.md)** — управление трафиком и QoS.
* **[tc netem](./tc_netem.md)** — эмуляция сетевых условий (задержки, потери, джиттер).
* **[Диагностика сокетов (ss)](../../../Diagnostics/Networking/ss.md)** — глубокий разбор `ss`.
* **[Сетевая диагностика](../../network_diagnostics_tools.md)** — сравнительный обзор всех инструментов.
* **[Сетевые интерфейсы](../../Concepts/linux_network_interfaces.md)** — типы (Bridge, Bond, VLAN).
