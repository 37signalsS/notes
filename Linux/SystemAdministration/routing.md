# Маршрутизация в Linux

## Определения

- **Маршрутизация (Routing):** Процесс выбора пути для передачи IP-пакетов между сетевыми интерфейсами на основе таблиц маршрутизации.
- **Таблица маршрутизации (Routing Table):** База данных в ядре, содержащая маршруты. Linux поддерживает до 255 независимых таблиц (основные: `local`, `main`, `default`).
- **RIB (Routing Information Base):** Общая база данных маршрутов, собранных из всех источников (статические записи, демоны динамической маршрутизации, ядро). Решения принимаются в Control Plane.
- **FIB (Forwarding Information Base):** Структура данных в ядре, оптимизированная для сверхбыстрого поиска маршрутов. Является результатом компиляции RIB для Data Plane.
- **LPM (Longest Prefix Match):** Алгоритм выбора наиболее специфичного маршрута (с самой длинной маской подсети) при наличии нескольких совпадений.
- **RPDB (Routing Policy Database):** База данных правил (`ip rule`), определяющая, в какой таблице маршрутизации искать путь для конкретного пакета (**[PBR](../Networking/Policy_Based_Routing/index.md)**).
- **Nexthop Object:** Современный механизм (ядро 5.3+), позволяющий управлять параметрами следующего узла (шлюза) отдельно от самих маршрутов.
- **Метрика (Metric/Priority):** Числовое значение, определяющее предпочтительность маршрута. Чем ниже значение, тем выше приоритет.
- **Административная дистанция (Administrative Distance, AD):** Мера «доверия» к источнику маршрутной информации. При равных метриках из разных источников побеждает маршрут с наименьшим AD. В Linux: connected=0, static=1, динамические протоколы зависят от демона (eBGP=20, OSPF=110, iBGP=200).
- **Типы маршрутов:**
  - **Connected (c):** Прямо подключенная сеть. Ядро создаёт автоматически.
  - **Static (s):** Статический маршрут, добавленный администратором.
  - **Kernel (k):** Маршрут, созданный ядром (например, через policy routing).
  - **Dynamic (BGP/OSPF):** Маршруты от демонов динамической маршрутизации (FRRouting, Bird).
  - **Blackhole/Unreachable/Prohibit:** Специальные типы маршрутов, указывающие ядру отбросить пакет без отправки.

## Основные концепции

### Процесс принятия решений ядром (Routing Decision)

При обработке пакета сетевой стек Linux выполняет следующие шаги:

1. **Контекст (VRF):** Если интерфейс привязан к **[VRF](../Networking/vrf.md)**, поиск ограничивается таблицами этого VRF.
2. **Проверка RPDB (`ip rule`):** Ядро проходит по списку правил (от приоритета 0 до 32767). Каждое правило может направить пакет в конкретную таблицу или заставить прекратить поиск.
3. **Поиск по LPM:** В выбранной таблице ищется совпадение. Сначала проверяются самые узкие маски (например, `/32`), затем более широкие.
4. **Выбор шлюза и интерфейса:** Если найдено несколько маршрутов с одинаковой маской (например, два `default`), выбирается маршрут с наименьшей метрикой. При равных метриках может использоваться **ECMP**.
5. **Область видимости (Scope):** Ядро проверяет атрибут `scope` (host, link, global), чтобы убедиться, что цель достижима.

### Рекурсивный поиск маршрута

Если в таблице маршрутизации указан шлюз (Next-hop), который сам не является «соседом» по локальному сегменту, система выполняет рекурсивный поиск: она ищет маршрут к IP-адресу этого шлюза до тех пор, пока не найдет выходной интерфейс и MAC-адрес соседа.

```bash
# Пример: шлюз 192.168.1.1 доступен через локальную сеть 192.168.1.0/24
ip route get 8.8.8.8
# → 8.8.8.8 via 192.168.1.1 dev eth0 src 192.168.1.100 uid 1000
#     cache ...
```

### Выбор исходного IP (Source IP Selection)

Если приложение не привязано к конкретному адресу через `bind()`, ядро выбирает `Source IP` автоматически:

1. **Атрибут `src` маршрута:** Самый высокий приоритет. Задается при создании маршрута: `ip route add ... src 1.2.3.4`.
2. **Адрес на выходном интерфейсе:** Если `src` не задан, выбирается первый доступный адрес на интерфейсе, через который уходит пакет.
3. **IPv6 Privacy Extensions:** Для IPv6 могут выбираться временные (temporary) адреса для защиты приватности, если это включено в `sysctl`.

Проверка: `ip route get <destination_ip>`.

### Фильтрация обратного пути (rp_filter)

**Reverse Path Filtering** предотвращает спуфинг. Ядро проверяет, пришел ли пакет через тот же интерфейс, через который ушел бы ответ на него.

| Режим (`sysctl`) | Значение | Описание |
| :--- | :--- | :--- |
| **No Filtering** | `0` | Проверка отключена. Риск спуфинга, разрешена асимметричная маршрутизация. |
| **Strict Mode** | `1` | Пакет дропается, если входящий интерфейс не является оптимальным путем для ответа. |
| **Loose Mode** | `2` | Пакет принимается, если адрес источника достижим через *любой* интерфейс хоста. |

Настройка: `net.ipv4.conf.<interface>.rp_filter`.

### Пересылка трафика (IP Forwarding)

По умолчанию Linux не пересылает пакеты между интерфейсами (работает как Host). Для работы в режиме маршрутизатора (Router) необходимо включить `forwarding`.

- IPv4: `net.ipv4.ip_forward`
- IPv6: `net.ipv6.conf.all.forwarding`

### Атрибуты маршрута

При создании маршрута можно задавать дополнительные атрибуты, изменяющие поведение ядра:

| Атрибут | Пример | Описание |
| :--- | :--- | :--- |
| **scope** | `scope global` | Видимость маршрута: `host` (локальный), `link` (сегмент), `global` (внешний). |
| **onlink** | `onlink` | Принудительно использовать nexthop, даже если он не в локальной сети (без ARP). |
| **expires** | `expires 3600` | Время жизни маршрута в секундах (ядро 5.8+). |
| **table** | `table 100` | Номер таблицы маршрутизации. |
| **from** | `from 192.168.1.0/24` | Ограничить маршрут только для пакетов с указанным source prefix. |

Пример с `onlink`:
```bash
# Маршрут через шлюз, который НЕ в локальной сети, но доступен через L2
sudo ip route add 10.200.0.0/24 via 172.16.255.1 dev tun0 onlink
```

## Практические сценарии

### 1. Анализ и диагностика маршрутов

```bash
# Просмотр всех маршрутов в таблице main
ip route show

# Эмуляция выбора пути для конкретного адреса (с учетом всех таблиц и правил)
ip route get 8.8.8.8

# Глубокая проверка: маршрут может существовать в RIB, но пакет пойдет иначе
# из-за правил PBR (ip rule) или специфики source-ip.
ip route get 8.8.8.8 from 192.168.1.10
# → В выводе проверьте используемую таблицу (table) и исходящий интерфейс.

# Проверка правил маршрутизации (чтобы понять, почему пакет не попал в таблицу main)
ip rule show

# Проверка маршрута внутри конкретного VRF
ip route get 10.0.0.1 vrf vrf-blue
```

### 2. Управление маршрутами через Nexthop Objects (Kernel 5.3+)

Разделение маршрута и шлюза упрощает управление при наличии множества путей.

```bash
# Создание объекта nexthop
sudo ip nexthop add id 1 via 192.168.1.1 dev eth0

# Использование nexthop в маршруте
sudo ip route add 10.10.0.0/24 nhid 1
```

### 3. Настройка ECMP (Equal Cost Multi-Path)

Балансировка трафика между двумя провайдерами или линками.

```bash
# Старый синтаксис (multipath)
sudo ip route add default scope global \
    nexthop via 10.0.1.1 dev eth0 weight 1 \
    nexthop via 10.0.2.1 dev eth1 weight 1

# Современный синтаксис через nexthop group
sudo ip nexthop add id 10 via 10.0.1.1 dev eth0
sudo ip nexthop add id 20 via 10.0.2.1 dev eth1
sudo ip nexthop add id 100 group 10/20
sudo ip route add default nhid 100
```

**ECMP hash policy:** Распределение идет по хешу от 5-tuple (src IP, dst IP, src port, dst port, protocol). Для стабильности сессий используйте `fib_multipath_hash_policy=1` (5-tuple hash) или `fib_multipath_hash_policy=0` (3-tuple).

```bash
# Проверка текущей hash-политики
sysctl net.ipv4.fib_multipath_hash_policy

# Установка 5-tuple hash (рекомендуется для большинства случаев)
sudo sysctl -w net.ipv4.fib_multipath_hash_policy=1
```

### 4. Постоянная настройка (Persistence)

#### Netplan (Ubuntu/Debian)
```yaml
network:
  ethernets:
    enp0s3:
      routes:
        - to: 10.20.0.0/16
          via: 192.168.1.1
          metric: 100
          table: 100
          on-link: true
```

#### systemd-networkd (RHEL/Alma/Rocky, Debian)
```ini
# /etc/systemd/network/10-enp0s3.network
[Match]
Name=enp0s3

[Route]
Gateway=192.168.1.1
Destination=10.20.0.0/16
Metric=100
Table=100
```

```bash
# Применение
sudo networkctl reload
sudo networkctl reconfigure enp0s3
```

#### ifupdown (legacy Debian/Ubuntu)
```bash
# /etc/network/interfaces
auto enp0s3
iface enp0s3 inet static
    address 192.168.1.100/24
    up ip route add 10.20.0.0/16 via 192.168.1.1 table 100
    down ip route del 10.20.0.0/16 via 192.168.1.1 table 100
```

### 5. Маршрутизация в изолированных окружениях (ip netns)

Linux Network Namespaces создают отдельные экземпляры сетевого стека. Каждый namespace имеет свои таблицы маршрутизации.

```bash
# Создание namespace
sudo ip netns add ns-blue

# Создание veth-пары
sudo ip link add veth-blue type veth peer name veth-host

# Привязка одного конца к namespace
sudo ip link set veth-blue netns ns-blue

# Настройка адресов
sudo ip netns exec ns-blue ip addr add 10.200.1.1/24 dev veth-blue
sudo ip netns exec ns-blue ip link set veth-blue up
sudo ip addr add 10.200.1.2/24 dev veth-host
sudo ip link set veth-host up

# Маршрут по умолчанию внутри namespace
sudo ip netns exec ns-blue ip route add default via 10.200.1.2 dev veth-blue

# Проверка таблицы маршрутизации внутри namespace
sudo ip netns exec ns-blue ip route show

# SNAT для выхода в интернет
sudo iptables -t nat -A POSTROUTING -s 10.200.1.0/24 -o eth0 -j MASQUERADE
```

**Важно:** `iptables`/`nftables` не разделяются между namespace по умолчанию. Каждый namespace имеет свои правила файрвола.

### 6. Kill Switch и фильтрация трафика

Создание маршрутов, которые отбрасывают трафик, — стандартная практика для изоляции несанкционированных подсетей или реализации kill switch для VPN.

```bash
# Запрет трафика в подсеть 10.0.0.0/8 (кроме исключений)
sudo ip route add blackhole 10.0.0.0/8

# Маршрут "недостижимо" — отправка ICMP unreachable
sudo ip route add prohibit 203.0.113.0/24

# Проверка
ip route show table all | grep -E "blackhole|unreachable|prohibit"
```

### 7. Мониторинг и observability

```bash
# Мониторинг изменений маршрутов в реальном времени
sudo ip monitor route

# Детальный просмотр маршрутов (FIB-компиляция, nexthop group)
ip -d route show

# Счетчики по интерфейсам
ip -s link show

# Статистика ядра сети
nstat -az | grep -E "IpForwarding|IpInReceives|IpOutRequests|IpForward|ReasmTimeout"

# Проверка ARP/NDP кэша (соседи nexthop)
ip neigh show

# Мониторинг через /proc
cat /proc/net/route
cat /proc/net/fib_trie
```

### 8. Sysctl-параметры, влияющие на маршрутизацию

```bash
# Основные параметры
net.ipv4.ip_forward = 1                    # Включение forwarding
net.ipv6.conf.all.forwarding = 1           # IPv6 forwarding

# rp_filter
net.ipv4.conf.all.rp_filter = 2            # Loose mode по умолчанию (безопаснее)
net.ipv4.conf.all.accept_redirects = 0     # Блокировка ICMP redirect (защита от MITM)
net.ipv4.conf.all.send_redirects = 0       # Не отправлять redirect

# ECMP
net.ipv4.fib_multipath_hash_policy = 1     # 5-tuple hash для ECMP
net.ipv4.fib_sync_mem = 0                  # Ограничение памяти для FIB sync

# Маршрутизация в namespace
net.ipv4.conf.all.promote_secondaries = 1  # Не удалять secondary адреса при удалении primary

# Применение
sudo sysctl -p
```

### 9. Типичные проблемы и устранение неполадок

#### Проблема: Маршрут добавлен, но пакеты не идут

**Диагностика:**
```bash
# 1. Проверьте таблицу, в которую попал пакет (может быть PBR)
ip rule show
ip route get <destination> from <source_if_needed>

# 2. Проверьте FIB (не RIB!)
ip route show table all

# 3. Проверьте reachability nexthop
ip neigh show

# 4. Проверьте фаервол
sudo iptables -L -n -v | grep -i drop
sudo nft list ruleset
```

#### Проблема: Асимметричная маршрутизация

Трафик входит через один интерфейс, а уходит через другой. Частая причина — rp_filter=1 в сочетании с PBR.

```bash
# Проверка
ip route get <dst> from <src>
# Сравните in_iface с out_iface в выводе

# Решение: либо отключить rp_filter (осторожно), либо настроить rp_filter=2 (loose)
sudo sysctl -w net.ipv4.conf.eth0.rp_filter=2
```

#### Проблема: Martian packets

Пакеты с недопустимыми адресами или пришедшие с "неправильного" интерфейса.

```bash
# Включение логирования
sudo sysctl -w net.ipv4.conf.all.log_martians=1

# Проверка логов
dmesg | grep -i martian

# Типичные причины:
# - Неправильный rp_filter
# - Spoofed IP
# - Ошибочная маршрутизация
```

#### Проблема: MTU Black Hole

Пакеты большого размера не проходят через туннель или VPN.

```bash
# Проверка MTU на пути
tracepath 8.8.8.8

# Проверка PMTU кэша
ip route show cache | grep mtu

# Временное решение: уменьшение MSS
sudo iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu

# Или статическое значение
sudo iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --set-mss 1360
```

## Диагностика и устранение неполадок

### Основные инструменты

| Задача | Инструмент | Описание |
| :--- | :--- | :--- |
| **Путь пакета** | `mtr` / `traceroute` | Поиск узла, на котором обрывается связь. |
| **Эмуляция FIB** | `ip route get` | Показывает, какой nexthop выберет ядро для конкретного IP. |
| **Детальный FIB** | `ip -d route show` | Показывает nexthop group, hash policy, параметры ECMP. |
| **Счетчики сбросов** | `nstat -az` | Проверка `IpReversePathFilter` (сбросы из-за rp_filter). |
| **Мониторинг** | `ip monitor route` | Отслеживание изменений в таблице маршрутизации в реальном времени. |
| **Проверка правил** | `ip rule show` | Анализ приоритетов таблиц (особенно при наличии VPN). |
| **Соседи** | `ip neigh show` | ARP/NDP кэш, статус nexthop. |
| **Статистика** | `nstat -az` | Счетчики ядерного сетевого стека. |
| **Журналы** | `dmesg | grep martian` | Логи подозрительных пакетов. |

### Типичные проблемы

1. **Martian packets:** Пакеты с недопустимыми адресами или пришедшие с "неправильного" интерфейса. Логируются при `net.ipv4.conf.all.log_martians = 1`.
2. **ICMP Redirects:** Ядро получает уведомление от другого маршрутизатора, что есть более короткий путь. Может быть вектором атаки. Отключается через `net.ipv4.conf.all.accept_redirects = 0`.
3. **PMTU Discovery:** Проблемы с прохождением пакетов большого размера через туннели. Лечится настройкой `TCPMSS` в iptables/nftables или уменьшением MTU на маршруте.
4. **Асимметричная маршрутизация:** Ответный трафик уходит через другой интерфейс. Решается через `rp_filter=2` (loose) или корректировкой правил PBR.
5. **ECMP Out-of-Order:** При распределении по нескольким путям пакеты одного потока могут приходить в разном порядке. Решается использованием 5-tuple hash (`fib_multipath_hash_policy=1`) и исключением критического трафика из ECMP.

## Дополнительная информация

### Сравнение инструментов маршрутизации

| Инструмент | Статус | Пример | Примечание |
| :--- | :--- | :--- | :--- |
| **iproute2** | Актуальный | `ip route add ...` | Рекомендуемый. Поддерживает все современные функции. |
| **route** | Устаревший | `route add ...` | Удален в некоторых дистрибутивах. Не поддерживает VRF, nexthop. |
| **netstat -rn** | Устаревший | `netstat -rn` | Показывает только основную таблицу. Используйте `ip route`. |

### Смежные темы

- **[Policy-Based Routing (PBR)](../Networking/Policy_Based_Routing/index.md):** Маршрутизация на основе источника, портов или меток.
- **[VRF (Virtual Routing and Forwarding)](../Networking/vrf.md):** Создание изолированных сетевых контекстов.
- **[iproute2: Обзор](../Networking/Tools/iproute2/overview.md):** Основной пакет утилит для управления сетью (`ip`, `ss`, `tc`).
- **[ip route](../Networking/Tools/iproute2/ip_route.md):** Управление таблицами маршрутизации.
- **[ip rule](../Networking/Tools/iproute2/ip_rule_pbr.md):** Правила маршрутизации (PBR).
- **[BGP/OSPF (FRRouting)](../../Networking/Tools/frr.md):** Динамическая маршрутизация в Linux.
- **[NetworkManager / nmcli](../Networking/Settings/Persistent_Network/centos_rhel_networkmanager.md):** Управление сетевыми подключениями в RHEL/CentOS/Fedora.
- **[Диагностика сети](../Diagnostics/Networking/network_cli_tools.md):** Утилиты диагностики: `ping`, `traceroute`, `mtr`, `ss`, `ip`.
