# Диагностика маршрутизации в Linux

## Определения

**Маршрутизация** — процесс выбора пути для пересылки IP-пакетов от источника к назначению на основе таблицы маршрутизации (FIB — Forwarding Information Base).

**Policy-Based Routing (PBR)** — механизм маршрутизации, основанный на правилах (RPDB — Routing Policy Database), позволяющий выбирать маршрут не только по назначению, но и по другим критериям: источник, порт, метка (fwmark), входящий интерфейс.

**ECMP (Equal-Cost Multi-Path)** — механизм распределения трафика по нескольким равнозначным маршрутам для балансировки нагрузки.

**FIB (Forwarding Information Base)** — таблица маршрутизации ядра Linux, содержащая записи о том, куда направлять пакеты для каждого назначения.

## Основные концепции

### Алгоритм выбора маршрута

```
Пакет поступил
    │
    ▼
RPDB (Routing Policy Database)
    │  ← ip rule: какие таблицы проверять
    │  ← Приоритеты: чем меньше число, тем выше приоритет
    ▼
Таблица маршрутизации (main, local, custom)
    │  ← Longest Prefix Match (LPM)
    ▼
Выбор next-hop
    │
    ├── Прямое подключение → ARP → L2
    └── Через маршрутизатор → ARP для next-hop → L2
```

### Основные команды

```bash
# Просмотр таблицы маршрутизации
ip route show
ip route show table all      # все таблицы

# Просмотр правил PBR
ip rule show

# Проверка маршрута для конкретного IP
ip route get 8.8.8.8
ip route get 8.8.8.8 from 10.0.0.1   # с указанием источника

# Добавление маршрута
ip route add 10.0.0.0/24 via 192.168.1.1
ip route add default via 192.168.1.1

# Удаление маршрута
ip route del 10.0.0.0/24

# Добавление PBR правила
ip rule add from 10.0.1.0/24 table 100
ip rule add fwmark 1 table 100
```

### Таблицы маршрутизации

| Таблица | Номер | Назначение |
|:---|:---|:---|
| **local** | 255 | Локальные адреса (localhost, interface IP) |
| **main** | 256 | Основная таблица (по умолчанию) |
| **default** | 253 | Пустая таблица |
| **custom** | 100-999 | PBR, VPN, multi-ISP |

```bash
# Просмотр всех таблиц
cat /etc/iproute2/rt_tables
# → 255   local
# → 254   main
# → 253   default
# → 100   vpn
# → 200   isp2

# Просмотр конкретной таблицы
ip route show table 100
```

## Практические сценарии

### 1. Базовая диагностика маршрутизации

```bash
# Шаг 1: Проверка маршрута до цели
ip route get 8.8.8.8
# → 8.8.8.8 via 192.168.1.1 dev eth0 src 192.168.1.100 uid 0
#     cache

# Шаг 2: Проверка таблицы
ip route show
# → default via 192.168.1.1 dev eth0 proto static metric 100
# → 10.0.0.0/24 via 192.168.1.1 dev eth0 proto static metric 200

# Шаг 3: Проверка интерфейсов
ip -br addr show
# → eth0  UP  192.168.1.100/24
# → lo  UP  127.0.0.1/8

# Шаг 4: Проверка ARP (next-hop доступен?)
ip neigh show
# → 192.168.1.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
```

### 2. Диагностика ошибки «No route to host»

**Симптом:** приложение получает `No route to host` (или `connect: No route to host`). Ошибка часто ошибочно относят к проблемам самого сервера назначения, но причина может находиться на любом участке маршрута.

#### 2.1. Базовая проверка

```bash
# Шаг 1: Проверка маршрута до цели
ip route get <target_ip>
# → RTNETLINK answers: Network is unreachable

# Шаг 2: Проверка, есть ли default route
ip route show | grep default
# → пусто ← нет default gateway!
```

#### 2.2. Основные причины и диагностика

**1. На хосте нет маршрута**

Linux должен понимать, через какой интерфейс и gateway отправлять пакет. Если подходящего маршрута нет, пакет не будет отправлен.

```bash
ip route get 10.10.20.15
```

Если команда возвращает `Network is unreachable` или `unreachable`, маршрут отсутствует.

**2. Неправильная маска или gateway**

Сервер может считать адрес назначения локальным из-за неправильной маски и пытаться найти его через ARP вместо отправки на маршрутизатор.

```bash
ip addr
ip route
```

Проверьте, что маска подсети корректна, а gateway назначен на правильном интерфейсе.

**3. Проблема с ARP**

Маршрут может существовать, но следующий hop не отвечает на ARP-запросы.

```bash
ip neigh
```

Если рядом с адресом появляется `FAILED` или `INCOMPLETE`, хост не смог разрешить IP в MAC-адрес.

**4. Firewall возвращает ICMP unreachable**

`No route to host` не всегда означает, что маршрута действительно нет. Firewall может отправить ICMP Destination Host Unreachable, после чего приложение получит именно такую ошибку.

```bash
sudo nft list ruleset
```

Проверьте, нет ли правил, возвращающих `icmp host-unreachable` или `icmp port-unreachable`.

**5. Маршрутизатор не знает путь дальше**

Сервер может иметь правильный default route, но следующий маршрутизатор не обязан знать, где находится сеть назначения.

```bash
traceroute -n 10.10.20.15
```

Если трассировка обрывается на определённом хопе — проблема на стороне маршрутизатора.

**6. Обратный маршрут сломан**

Пакет может успешно дойти до сервера, но ответ пойдёт через другой маршрут или вообще не найдёт пути обратно.

```bash
# На сервере назначения:
ip route get <IP-клиента>
```

Эта ситуация часто проявляется при нескольких интерфейсах, VRF или policy routing.

**7. Маршрут есть, но интерфейс фактически не работает**

В таблице может быть запись `10.10.20.0/24 dev eth1`, но сам `eth1` находится в `DOWN` или физический линк не поднят.

```bash
ip link show eth1
```

#### 2.3. Пошаговый алгоритм диагностики

```bash
# Шаг 1: Проверка таблиц
ip route show table all | grep -c default
# → 0 = нет default ни в одной таблице

# Шаг 2: Проверка правил PBR
ip rule show
# → 0:    from all lookup local
# → 32766: from all lookup main
# → 32767: from all lookup default

# Шаг 3: Проверка ARP
ip neigh show

# Шаг 4: Проверка firewall
sudo nft list ruleset

# Шаг 5: Добавление default route при необходимости
sudo ip route add default via 192.168.1.1
```

#### 2.4. Интерпретация

`No route to host` лучше читать не как «сервер недоступен», а как «на этом этапе сеть не смогла доставить пакет дальше». Сначала смотрим маршрут, затем next-hop, ARP и уже после этого разбираемся с firewall и удалённым хостом.

### 4. Диагностика Policy-Based Routing

**Симптом:** Трафик идёт не через тот интерфейс/ISP.

```bash
# Шаг 1: Просмотр всех правил
ip rule show
# → 0:	from all lookup local
# → 100:	from 10.0.1.0/24 lookup 100
# → 200:	fwmark 1 lookup 200
# → 32766:	from all lookup main
# → 32767:	from all lookup default

# Шаг 2: Проверка конкретной таблицы
ip route show table 100
# → default via 10.0.1.1 dev eth1

# Шаг 3: Проверка, какой маршрут会选择
ip route get 8.8.8.8 from 10.0.1.50
# → 8.8.8.8 via 10.0.1.1 dev eth1 src 10.0.1.50 uid 0
#     cache lookup fib

# Шаг 4: Проверка fwmark (для iptables MARK)
ip rule show | grep fwmark
# → 200:	fwmark 1 lookup 200
```

### 5. Диагностика ECMP (Multi-Path)

```bash
# Шаг 1: Проверка ECMP маршрутов
ip route show
# → default
#     nexthop via 10.0.1.1 dev eth0 weight 1
#     nexthop via 10.0.2.1 dev eth1 weight 1

# Шаг 2: Проверка распределения
ip route get 8.8.8.8
# → 8.8.8.8 via 10.0.1.1 dev eth0 ...  ← выбор зависит от хеша

# Шаг 3: Мониторинг распределения
for i in {1..100}; do
  ip route get 8.8.8.8 | grep -oP 'dev \K\w+'
done | sort | uniq -c
# → 52 eth0
# → 48 eth1  ← примерно равномерно

# Шаг 4: Проверка hash-политики
ip -d route show default
# → ... proto static ... hash l4
```

### 6. Диагностика асимметричной маршрутизации

**Симптом:** ping работает в одну сторону, но не в другую; или `rp_filter` ошибки.

```bash
# Шаг 1: Проверка rp_filter
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.eth0.rp_filter
# → 1 = строгий (отклоняет асимметричный трафик)
# → 0 = отключен (принимает всё)
# → 2 = мягкий (проверяет только основную таблицу)

# Шаг 2: Определение асимметрии
traceroute -n <target>           # путь "туда"
ssh <target> traceroute -n <your_ip>  # путь "обратно"

# Шаг 3: Решение (временно)
sudo sysctl -w net.ipv4.conf.all.rp_filter=0
sudo sysctl -w net.ipv4.conf.eth0.rp_filter=0

# Шаг 4: PBR для симметрии
sudo ip rule add from <source_ip> table 100
sudo ip route add default via <gateway> table 100
```

### 7. Диагностика blackhole/unreachable маршрутов

```bash
# Проверка наличия blackhole маршрутов
ip route show | grep -E "blackhole|unreachable|prohibit"
# → blackhole 10.99.99.0/24 dev lo proto static

# Проверка, попадает ли трафик в blackhole
ip route get 10.99.99.1
# → 10.99.99.1 dev lo table local ... blackhole

# Удаление blackhole маршрута
sudo ip route del blackhole 10.99.99.0/24
```

### 8. Сохранение маршрутов (постоянная настройка)

```bash
# ⚠️ Команды ip route - временные (до перезагрузки!)

# Для systemd-networkd:
# /etc/systemd/network/10-eth0.network
[Route]
Gateway=192.168.1.1
Destination=0.0.0.0/0

[Route]
Gateway=10.0.1.1
Destination=10.0.0.0/24
Metric=200

# Для Netplan (Ubuntu):
# /etc/netplan/01-config.yaml
network:
  version: 2
  ethernets:
    eth0:
      routes:
        - to: default
          via: 192.168.1.1
        - to: 10.0.0.0/24
          via: 10.0.1.1
          metric: 200

# Для PBR (ip rule) через systemd-networkd:
# /etc/systemd/network/10-vpn.network
[RoutingPolicyRule]
From=10.0.1.0/24
Table=100
Priority=100
```

## Дополнительная информация

### Интеграция с Prometheus

```yaml
# node_exporter экспортирует:
# node_netstat_Ip_ForwardingEnabled  — IP forwarding включен
# node_netstat_Ip_OutNoRoutes        — пакеты без маршрута

groups:
  - name: routing_alerts
    rules:
      - alert: NoRoutesDetected
        expr: rate(node_netstat_Ip_OutNoRoutes[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High no-route packets on {{ $labels.instance }}"

      - alert: IPForwardingDisabled
        expr: node_netstat_Ip_ForwardingEnabled == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "IP forwarding disabled on router {{ $labels.instance }}"
```

### Связанные инструменты

- **[ip route](../../Linux/Networking/Tools/iproute2/ip_route.md)** — полная справка по ip route (SSoT).
- **[ip rule / PBR](../../Linux/Networking/Tools/iproute2/ip_rule_pbr.md)** — Policy-Based Routing (SSoT).
- **[ip neighbour](../../Linux/Networking/Tools/iproute2/ip_neighbour.md)** — ARP/NDP диагностика.
- **[routing.md](../../Linux/SystemAdministration/routing.md)** — комплексное руководство по маршрутизации.
- **[PBR scenarios](../../Linux/Networking/Policy_Based_Routing/scenarios.md)** — сценарии PBR.
- **[traceroute/mtr](./traceroute_mtr.md)** — трассировка сетевого пути.
- **[asymmetric routing](../../../Networking/Concepts/asymmetric_routing.md)** — асимметричная маршрутизация.
