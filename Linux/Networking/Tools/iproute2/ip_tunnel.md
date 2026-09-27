# ip tunnel: Управление сетевыми туннелями

## Определения

* **Сетевой туннель** — технология инкапсуляции пакетов одного протокола в пакеты другого для их передачи через промежуточную сеть. Инкапсулированные пакеты маршрутизируются как обычный трафик по промежуточной инфраструктуре, оставаясь невидимыми для промежуточных маршрутизаторов.
* **`ip tunnel`** — специализированный объект утилиты `ip` (из пакета `iproute2`) для управления классическими туннелями (GRE, IPIP, SIT). В современной практике считается частично устаревшим и заменяется более универсальным объектом `ip link`, который поддерживает все протоколы туннелирования.
* **L3-туннели (Routing)** — туннелирование на сетевом уровне (IP-в-IP). Пакеты маршрутизируются ядром между туннельным и физическим интерфейсами. Трафик между конечными точками маршрутизируется, широковещательный трафик не передаётся.
* **L2-туннели (Bridging)** — передача Ethernet-кадров внутри IP-пакетов. Позволяют объединять удаленные сегменты сети в единый широковещательный домен (VXLAN, GRETAP, GENEVE). Охранивают multicast/broadcast трафик между сегментами.

## Предпосылки

### Требования

* **Пакет `iproute2`**: Установлен в системе (включает утилиту `ip`).
    ```bash
    # Debian/Ubuntu
    sudo apt install iproute2

    # RHEL/CentOS/Rocky
    sudo dnf install iproute
    ```
* **Права root**: Все команды `ip` требуют привилегий суперпользователя (`sudo`).
* **IP-форвардинг**: Для маршрутизации трафика между туннельным и физическим интерфейсами необходимо включить IP-форвардинг.
    ```bash
    sudo sysctl -w net.ipv4.ip_forward=1
    # Для постоянного эффекта:
    echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-ip-forwarding.conf
    sudo sysctl -p /etc/sysctl.d/99-ip-forwarding.conf
    ```
* **Модули ядра**: Различные протоколы туннелирования требуют загрузки соответствующих модулей.
    ```bash
    # Проверка и загрузка модулей
    sudo modprobe ip_gre      # GRE
    sudo modprobe ipip        # IPIP
    sudo modprobe sit         # SIT (6in4)
    sudo modprobe vxlan       # VXLAN
    sudo modprobe fou         # FOU (Foo Over UDP)
    sudo modprobe ip_vti      # VTI (Virtual Tunnel Interface)
    sudo modprobe geneve      # GENEVE

    # Проверка загруженных модулей
    lsmod | grep -E "^(ip_gre|ipip|sit|vxlan|fou|ip_vti|geneve)"
    ```

### Проверка доступных протоколов

```bash
# Просмотр поддерживаемых типов туннелей
ip link help | grep -E "type (gre|gretap|ipip|sit|vxlan|geneve|fou|vti|erspan)"
# → Выведет справку по параметрам каждого типа туннеля
```

## Основные концепции

### Эволюция управления: ip tunnel vs ip link

В современном сетевом стеке Linux существует два подхода к созданию туннельных интерфейсов:

| Критерий | `ip tunnel` (Legacy) | `ip link add type` (Modern) |
| :--- | :--- | :--- |
| **Протоколы** | IPIP, GRE, SIT | Все (GRE, IPIP, SIT, VXLAN, GENEVE, FOU, VTI, ERSPAN, GRETAP) |
| **IPv6-эндпоинты** | Ограничена (только IPv4) | Полная поддержка (local/remote на IPv6) |
| **Hardware Offload** | Нет | Поддержка TX/RX offload (checksum, GSO, GRO) |
| **Ключи/VNI** | Ограничены (32-bit key) | Полная поддержка (24-bit VNI для VXLAN/GENEVE) |
| **encap** | Нет | Поддержка FOU/GUE инкапсуляции |

**Рекомендация:** Используйте `ip link add type` как основной метод. `ip tunnel` может использоваться для обратной совместимости со старыми скриптами.

### Классификация протоколов туннелирования

| Протокол | Режим (mode) | Протокол/Порт | Назначение | Overhead |
| :--- | :--- | :--- | :--- | :--- |
| **GRE** | `gre` | IP 47 | Универсальная инкапсуляция L3 (любой протокол в IP). | 24-28 B |
| **GRETAP** | `gretap` | IP 47 | L2-туннель (Ethernet поверх GRE). | ~42 B |
| **ERSPAN** | `erspan` | IP 47 | Зеркалирование трафика L2 через GRE (версии v1 и v2). | ~42 B |
| **IPIP** | `ipip` | IP 4 | IPv4 внутри IPv4 (минимальные накладные расходы). | 20 B |
| **SIT (6in4)** | `sit` | IP 41 | IPv6 внутри IPv4, стандарт для миграции на IPv6. | 20 B |
| **VXLAN** | `vxlan` | UDP 4789 | L2-оверлей поверх UDP, стандарт для облаков и K8s. | 50 B |
| **GENEVE** | `geneve` | UDP 6081 | Современный расширяемый туннель (стандарт OVN/Cilium). | 50+ B |
| **VTI** | `vti` | IP 50 (ESP) | Виртуальный интерфейс для связки с политиками IPsec. | 20 B |
| **FOU / GUE** | `fou` / `gue` | UDP (любой) | Инкапсуляция в UDP для прохождения NAT и балансировки ECMP. | 32+ B |

### Ключевые технические параметры

*   **local** / **remote** — IP-адреса локальной и удаленной точек туннеля. Определяют внешний заголовок пакета.
*   **ttl** — Time To Live внешнего заголовка. Рекомендуется `inherit` (наследование от внутреннего пакета) для корректной работы `traceroute`.
*   **key** / **id** — Идентификатор туннеля (32-битный для GRE, 24-битный VNI для VXLAN/GENEVE). Используется для мультиплексирования множества туннелей на одном интерфейсе.
*   **nopmtudisc** — Отключение Path MTU Discovery. Крайне не рекомендуется — ведет к фрагментации и зависанию TCP-сессий при заблокированных ICMP.
*   **dev** — Явная привязка туннеля к конкретному физическому интерфейсу. Критично для multi-homed серверов.
*   **tos** — Type of Service (DSCP) внешнего заголовка. Используется для QoS-маркировки туннельного трафика.
*   **dfbit** — Don't Fragment Bit. По умолчанию установлен (DF=1). При фрагментации внешнего пакета отправляется ICMP Fragmentation Needed.
*   **flowbased** — Туннель без фиксированных local/remote (для использования с FIB rules и PBR).

### Принцип инкапсуляции и декапсуляции

1.  **Поступление пакета:** Пакет (IPv4, IPv6, Ethernet) поступает на туннельный интерфейс.
2.  **Инкапсуляция:** Добавляется заголовок протокола туннелирования (GRE: 4-12 байт, VXLAN: 8 байт, IPIP: 20 байт).
3.  **Внешний заголовок:** Добавляется внешний IP-заголовок (обычно IPv4, 20 байт) с адресами конечных точек туннеля (`local` и `remote`).
4.  **Маршрутизация:** Пакет маршрутизируется через транзитную сеть как обычный IP-трафик (протокол 47 для GRE, UDP для VXLAN/GENEVE). Промежуточные маршрутизаторы не видят инкапсулированный трафик.
5.  **Декапсуляция:** На удалённой стороне внешние заголовки снимаются, внутренний пакет передаётся во внутреннюю сеть или обрабатывается локально.

### Ограничения и особенности

*   **Безопасность:** GRE, IPIP, SIT, VXLAN, GENEVE передают трафик без шифрования. Для защиты используйте IPsec (VTI), WireGuard или шифрование поверх туннеля.
*   **MTU и фрагментация:** Каждый уровень инкапсуляции уменьшает доступный MTU. При MTU > 1500 на физическом интерфейсе может потребоваться увеличение MTU туннеля.
*   **CPU-нагрузка:** Инкапсуляция/декапсуляция выполняется в ядре. На высокоскоростных каналах (>10 Gbps) используйте hardware offload (checksum, GSO) или DPDK/XDP.
*   **Keepalive:** GRE и IPIP поддерживают механизм keepalive для обнаружения обрыва туннеля. VXLAN и GENEVE не имеют нативного keepalive — используйте BFD или ECMP health checks.
*   **Namespace:** Туннельные интерфейсы можно перемещать в network namespaces для изоляции (routes, ARP tables).

## Практические сценарии

### Основные команды управления

| Действие | Команда |
| :--- | :--- |
| **Создание туннеля** | `sudo ip link add name <имя> type <тип> local <IP> remote <IP> [параметры]` |
| **Активация** | `sudo ip link set <имя> up` |
| **Добавление IP** | `sudo ip address add <CIDR> dev <имя>` |
| **Просмотр туннелей** | `ip -d link show type <тип>` |
| **Просмотр статистики** | `ip -s link show dev <имя>` |
| **Удаление туннеля** | `sudo ip link del <имя>` |

### Сценарий 1: Классический GRE-туннель (L3)

Создание point-to-point GRE-туннеля между двумя хостами для маршрутизации между сетями.

```bash
# На хосте A (198.51.100.1):
sudo ip link add name gre1 type gre \
    local 198.51.100.1 remote 203.0.113.2 \
    ttl inherit key 100
sudo ip link set gre1 up
sudo ip address add 10.0.0.1/30 dev gre1

# Добавление маршрута к удаленной сети
sudo ip route add 192.168.2.0/24 via 10.0.0.2 dev gre1

# На хосте B (203.0.113.2):
sudo ip link add name gre1 type gre \
    local 203.0.113.2 remote 198.51.100.1 \
    ttl inherit key 100
sudo ip link set gre1 up
sudo ip address add 10.0.0.2/30 dev gre1

sudo ip route add 192.168.1.0/24 via 10.0.0.1 dev gre1

# Валидация
ping 10.0.0.2    # → Reply from 10.0.0.2 (gre1)
ip -d link show gre1   # → Детали: type gre, key 100, local/remote IP
```

### Сценарий 2: Настройка L2-мостика через GRETAP

Объединение двух удаленных офисов в одну L2-сеть (один broadcast-домен).

```bash
# На хосте A:
sudo ip link add tap0 type gretap remote 203.0.113.2 local 198.51.100.1
sudo ip link set tap0 master br0
sudo ip link set tap0 up

# На хосте B:
sudo ip link add tap0 type gretap remote 198.51.100.1 local 203.0.113.2
sudo ip link set tap0 master br0
sudo ip link set tap0 up

# Проверка моста
bridge link show
# → tap0: <BROADCAST,MULTICAST,UP> master br0 state forwarding
```

### Сценарий 3: Настройка VXLAN (L2-оверлей)

Создание виртуального L2-сегмента поверх IP-сети (стандарт для виртуализации и Kubernetes).

```bash
# На хосте A (VTEP 192.168.1.10):
sudo ip link add vxlan10 type vxlan \
    id 1000 dev eth0 \
    local 192.168.1.10 remote 192.168.1.20 \
    dstport 4789
sudo ip link set vxlan10 up
sudo ip address add 10.10.10.1/24 dev vxlan10

# Добавление в мост (опционально, для L2-режима)
sudo ip link set vxlan10 master br0

# На хосте B (VTEP 192.168.1.20):
sudo ip link add vxlan10 type vxlan \
    id 1000 dev eth0 \
    local 192.168.1.20 remote 192.168.1.10 \
    dstport 4789
sudo ip link set vxlan10 up
sudo ip address add 10.10.10.2/24 dev vxlan10

# Валидация
ip -d link show vxlan10
# → type vxlan, id 1000, dstport 4789, local 192.168.1.10, remote 192.168.1.20

ping 10.10.10.2
# → Reply from 10.10.10.2 (vxlan10)
```

### Сценарий 3.1: VXLAN multi-host (Multicast Flood-and-Learn)

В продакшене VXLAN обычно работает между **3+ хостами** (VTEP). Multicast-группа используется для unknown unicast flood и broadcast.

```bash
# Хост A (VTEP1): 192.168.1.10
sudo ip link add vxlan10 type vxlan \
    id 1000 dev eth0 \
    dstport 4789 \
    group 239.1.1.1 \
    ttl 64 \
    nolearning
sudo ip link set vxlan10 up

# Хост B (VTEP2): 192.168.1.20
sudo ip link add vxlan10 type vxlan \
    id 1000 dev eth0 \
    dstport 4789 \
    group 239.1.1.1 \
    ttl 64 \
    nolearning

# Хост C (VTEP3): 192.168.1.30
sudo ip link add vxlan10 type vxlan \
    id 1000 dev eth0 \
    dstport 4789 \
    group 239.1.1.1 \
    ttl 64 \
    nolearning

# Привязка к bridge (каждый хост)
sudo ip link add br0 type bridge
sudo ip link set vxlan10 master br0
sudo ip link set br0 up

# Пример: подключение локальной ВМ к bridge
sudo ip link set veth-vm0 master br0
```

**Параметр `nolearning`:** Отключает автоматическое обучение FDB через data-plane (frame flooding). MAC-адреса добавляются статически или через control-plane (BGP EVPN). Снижает ненужный flood-трафик.

**Просмотр FDB (Forwarding Database):**
```bash
# Статические записи (的学习된 MAC)
bridge fdb show dev vxlan10
# → 00:11:22:33:44:55 dev vxlan10 self permanent
# → aa:bb:cc:dd:ee:ff dev vxlan10 self dst 192.168.1.20

# Добавление статической FDB-записи (для known remote host)
sudo bridge fdb add aa:bb:cc:dd:ee:ff dev vxlan10 self dst 192.168.1.20

# Удаление FDB-записи
sudo bridge fdb del aa:bb:cc:dd:ee:ff dev vxlan10 self
```

**Troubleshooting:**
```bash
# Проверка multicast-группы
ip maddr show | grep 239.1.1.1

# Проверка, что VXLAN-трафик доходит (UDP 4789)
sudo tcpdump -i eth0 udp port 4789 -n

# Просмотр всех VXLAN-интерфейсов
ip -d link show type vxlan
```

### Сценарий 3.2: VXLAN multi-host с bridge VLAN filtering

Комбинирование VXLAN и VLAN-aware bridge позволяет передавать несколько VLAN через один overlay.

```bash
# Хост A (VTEP1)
sudo ip link add br0 type bridge vlan_filtering 1
sudo ip link add vxlan10 type vxlan id 1000 dev eth0 dstport 4789 group 239.1.1.1
sudo ip link set vxlan10 master br0

# VLAN 100 на bridge → VXLAN
sudo bridge vlan add dev vxlan10 vid 100

# Локальные порты bridge для VLAN 100
sudo bridge vlan add dev veth-vm0 vid 100 pvid untagged

sudo ip link set br0 up
```

### Сценарий 3.3: VXLAN с BGP EVPN (control-plane learning)

BGP EVPN заменяет multicast-флудинг: MAC-адреса обмениваются через BGP route-type 2 (MAC/IP Advertisement). Используется в DC (Data Center) для масштабируемых overlay-сетей.

```bash
# На каждом VTEP: VXLAN без multicast, с learning через BGP
sudo ip link add vxlan10 type vxlan \
    id 1000 dev eth0 \
    dstport 4789 \
    nolearning \
    local 192.168.1.10

sudo ip link set vxlan10 up
sudo ip link add br0 type bridge
sudo ip link set vxlan10 master br0

# FRRouting: настройка BGP EVPN (через vtysh)
# router bgp 65001
#   bgp router-id 192.168.1.10
#   address-family l2vpn evpn
#     advertise-all-vni
#     advertise-svi-ip
#   exit-address-family
#   neighbor 192.168.1.20 remote-as 65001
```

**Ключевые моменты:**
- `advertise-all-vni` — анонсировать все VNI через BGP
- Route-type 2 (MAC/IP) — learning MAC без flood
- Route-type 5 (IP Prefix) — L3-маршрутизация между VNI (symmetric IRB)
- **Детали:** [BGP EVPN](../../../../Networking/Concepts/sdn/bgp_evpn.md)

### Сценарий 4: Настройка GENEVE (современный L2-оверлей)

GENEVE — расширяемый туннель с поддержкой TLV-опций. Стандарт для OVN/Cilium.

```bash
# На хосте A:
sudo ip link add geneve1 type geneve \
    id 100 dev eth0 \
    remote 192.168.1.20 local 192.168.1.10 \
    dstport 6081
sudo ip link set geneve1 up
sudo ip address add 10.20.20.1/24 dev geneve1

# На хосте B:
sudo ip link add geneve1 type geneve \
    id 100 dev eth0 \
    remote 192.168.1.10 local 192.168.1.20 \
    dstport 6081
sudo ip link set geneve1 up
sudo ip address add 10.20.20.2/24 dev geneve1

# Валидация
ip -d link show geneve1
# → type geneve, id 100, dstport 6081, remote 192.168.1.20
```

### Сценарий 5: Настройка FOU (Foo Over UDP)

Инкапсуляция протоколов без портов (как GRE) в UDP для обхода "тупых" NAT и улучшения балансировки трафика провайдерами (ECMP).

```bash
# 1. Настройка UDP-приемника для протокола 47 (GRE)
sudo ip fou add port 6666 ipproto 47

# 2. Создание туннеля, упакованного в UDP
sudo ip link add name gre_fou type gre \
    remote 203.0.113.2 local 198.51.100.1 \
    encap fou encap-sport auto encap-dport 6666

sudo ip link set gre_fou up
sudo ip address add 10.0.1.1/30 dev gre_fou

# Валидация
ip -d link show gre_fou
# → type gre, encap fou, encap-sport auto, encap-dport 6666

# Проверка UDP-соединения
ss -ulnp | grep 6666
# → UNCONN  0  0  0.0.0.0:6666  0.0.0.0:*
```

### Сценарий 6: Зеркалирование трафика через ERSPAN

Копирование трафика с удаленного коммутатора для анализа (не требует физического подключения кSPAN-порту).

```bash
# На хосте-получателе (192.168.1.1):
sudo ip link add name erspan0 type erspan \
    local 192.168.1.1 remote 192.168.1.100 \
    erspan_ver 2 erspan 10
sudo ip link set erspan0 up
sudo ip address add 10.30.30.1/24 dev erspan0

# На хосте-источнике (192.168.1.100) — настройка ERSPAN-источника
# (обычно через ethtool или TC mirred)

# Валидация
ip -d link show erspan0
# → type erspan, erspan_ver 2, erspan 10, local 192.168.1.1, remote 192.168.1.100

# Захват зеркалированного трафика
sudo tcpdump -i erspan0 -n -c 10
# → Показывает зеркалированные пакеты
```

### Сценарий 7: Настройка IPIP (минимальный overhead)

IPIP — простейшая инкапсуляция IPv4-в-IPv4 с минимальными накладными расходами (20 байт).

```bash
# На хосте A:
sudo ip link add name ipip1 type ipip \
    local 198.51.100.1 remote 203.0.113.2 \
    ttl inherit
sudo ip link set ipip1 up
sudo ip address add 10.0.0.1/30 dev ipip1

# На хосте B:
sudo ip link add name ipip1 type ipip \
    local 203.0.113.2 remote 198.51.100.1 \
    ttl inherit
sudo ip link set ipip1 up
sudo ip address add 10.0.0.2/30 dev ipip1

# Валидация
ping 10.0.0.2
ip -d link show ipip1
# → type ipip, local 198.51.100.1, remote 203.0.113.2
```

### Сценарий 8: Настройка SIT (6in4 — туннелирование IPv6)

Инкапсуляция IPv6-пакетов в IPv4 для передачи через IPv4-инфраструктуру.

```bash
# На хосте A (IPv6: 2001:db8:1::1):
sudo ip link add name sit1 type sit \
    local 198.51.100.1 remote 203.0.113.2 \
    ttl inherit
sudo ip link set sit1 up
sudo ip address add 2001:db8:1::1/64 dev sit1

# На хосте B (IPv6: 2001:db8:1::2):
sudo ip link add name sit1 type sit \
    local 203.0.113.2 remote 198.51.100.1 \
    ttl inherit
sudo ip link set sit1 up
sudo ip address add 2001:db8:1::2/64 dev sit1

# Валидация
ping6 2001:db8:1::2
ip -d link show sit1
# → type sit, local 198.51.100.1, remote 203.0.113.2
```

### Сценарий 9: Настройка VTI (Virtual Tunnel Interface для IPsec)

VTI — виртуальный интерфейс для связки с политиками IPsec. Позволяет создавать "чистый" туннель, который ведёт себя как GRE.

```bash
# 1. Создание IPsec-policy (SPD)
sudo ip xfrm policy add dir out \
    src 198.51.100.1 dst 203.0.113.2 \
    tmpl proto esp mode tunnel \
    reqid 1

sudo ip xfrm policy add dir in \
    src 203.0.113.2 dst 198.51.100.1 \
    tmpl proto esp mode tunnel \
    reqid 1

# 2. Создание VTI-интерфейса
sudo ip link add vti1 type vti \
    local 198.51.100.1 remote 203.0.113.2 \
    key 1

sudo ip link set vti1 up
sudo ip address add 10.0.0.1/30 dev vti1

# Валидация
ip -d link show vti1
# → type vti, local 198.51.100.1, remote 203.0.113.2
```

## Диагностика и мониторинг

### Просмотр конфигурации туннелей

```bash
# Просмотр всех туннельных интерфейсов
ip -d link show | grep -E "(gre|tunl|ipip|sit|vxlan|geneve|fou|vti|erspan)" -A2

# Детальный просмотр конкретного туннеля
ip -d link show dev gre1
# → type gre, local 198.51.100.1, remote 203.0.113.2, key 100, ttl inherit

# Просмотр всех туннелей определенного типа
ip -d link show type gre
ip -d link show type vxlan
```

### Мониторинг статистики

```bash
# Статистика ошибок и дропов
ip -s link show dev gre1
# → RX: bytes, packets, errors, dropped, overruns
# → TX: bytes, packets, errors, dropped, overruns

# Мониторинг в реальном времени
watch -n 1 'ip -s link show dev gre1'
```

### Проверка маршрутизации через туннель

```bash
# Проверка маршрута к удаленной сети
ip route get 192.168.2.1
# → 192.168.2.1 via 10.0.0.2 dev gre1 src 198.51.100.1

# Проверка ARP/NDP на туннельном интерфейсе
ip neigh show dev gre1
```

### Отладка туннельного трафика

```bash
# Захват трафика на туннельном интерфейсе
sudo tcpdump -i gre1 -n -c 10
# → Показывает инкапсулированные пакеты

# Захват трафика на физическом интерфейсе (внешний заголовок)
sudo tcpdump -i eth0 proto 47 -n -c 10
# → Показывает GRE-пакеты (протокол 47) с внешними заголовками

# Просмотр IPsec SA (для VTI)
sudo ip xfrm state
```

## Траблшутинг

### Проблема: "RTNETLINK answers: No such file or directory"

**Причина:** Модуль ядра для протокола туннелирования не загружен.

**Решение:**
```bash
# Загрузка модуля
sudo modprobe ip_gre       # Для GRE
sudo modprobe vxlan        # Для VXLAN
sudo modprobe geneve       # Для GENEVE

# Проверка загрузки
lsmod | grep -E "^(ip_gre|vxlan|geneve)"

# Автоматическая загрузка при старте
echo "ip_gre" | sudo tee -a /etc/modules-load.d/tunnel.conf
```

### Проблема: "RTNETLINK answers: File exists"

**Причина:** Туннель с таким именем уже существует или конфликтует с другим интерфейсом.

**Решение:**
```bash
# Просмотр существующих интерфейсов
ip link show | grep gre

# Удаление существующего туннеля
sudo ip link del gre1

# Или использование другого имени
sudo ip link add name gre2 type gre ...
```

### Проблема: "RTNETLINK answers: No such process"

**Причина:** Удалённый IP-адрес недоступен или не маршрутизируется.

**Решение:**
```bash
# Проверка доступности удаленного IP
ping -c 3 <remote_ip>

# Проверка маршрута к удаленному IP
ip route get <remote_ip>

# Если удаленный IP находится за NAT/防火墙
# → Разрешить протокол 47 (GRE), UDP 4789 (VXLAN), UDP 6081 (GENEVE)
```

### Проблема: Нет связи по туннелю (ping не проходит)

**Причины и диагностика:**

| Проверка | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| Интерфейс активен | `ip link show dev gre1` | `state UP` |
| IP назначен | `ip addr show dev gre1` | Адрес в сети туннеля |
| Маршрут существует | `ip route get <tunnel_IP>` | Маршрут через туннельный интерфейс |
| Файервол разрешает | `sudo iptables -L -n -v \| grep -E "(47\|4789\|6081)"` | Нет DROP/REJECT правил |
| Ключи совпадают | `ip -d link show dev gre1` | `key 100` на обоих концах |

### Проблема: ICMP (ping) проходит, TCP виснет

**Причина:** Проблема MTU/MSS. TCP-пакеты больше MTU туннеля, но PMTUD не работает (заблокированы ICMP).

**Решение:**
```bash
# 1. Определение MTU туннеля
ip link show dev gre1 | grep mtu
# → mtu 1476 (GRE) или 1480 (IPIP)

# 2. Применение MSS Clamping
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre1 -j TCPMSS --clamp-mss-to-pmtu

# 3. Или ручная установка MSS
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre1 -j TCPMSS --set-mss 1436
```

### Проблема: Высокие потери на интерфейсе

**Причины:**
1. Файервол блокирует туннельный трафик.
2. Физическая сеть перегружена.
3. Несовпадение ключей (key) между концами туннеля.

**Диагностика:**
```bash
# Статистика ошибок
ip -s link show dev gre1
# → errors, dropped, overruns

# Проверка правил файервола
sudo iptables -L -n -v | grep -E "(DROP|REJECT)" | grep -E "(47|4789|6081)"

# Проверка ключей на обоих концах
ip -d link show dev gre1 | grep key
```

### Проблема: Высокое потребление CPU при большом трафике

**Решение:**
```bash
# Включение аппаратных offload
sudo ethtool -K eth0 tx-checksum-ipv4 on
sudo ethtool -K eth0 tx-checksum-ipv6 on
sudo ethtool -K eth0 scatter-gather on
sudo ethtool -K eth0 generic-segmentation-offload on

# Проверка offload
ethtool -k eth0 | grep -E "(checksum|scatter|segmentation)"
```

## Оптимизация MTU и MSS

Инкапсуляция неизбежно увеличивает размер пакета, что уменьшает полезную нагрузку.

### Таблица оверхеда протоколов

| Комбинация | Накладные расходы (B) | Эффективный MTU (физика 1500) |
| :--- | :--- | :--- |
| **IPIP / SIT** | 20 | 1480 |
| **GRE (без ключа)** | 24 | 1476 |
| **GRE (с ключом)** | 28 | 1472 |
| **VXLAN** | 50 | 1450 |
| **GENEVE** | 50+ | 1450 |
| **WireGuard** | 60-80 | 1420 |
| **FOU + GRE** | 32 (20+8+4) | 1468 |
| **GRETAP** | 42 | 1458 |

### Решение проблемы "зависших" соединений (MSS Clamping)

Если на пути туннеля блокируются ICMP (PMTUD сломан), TCP-сессии будут обрываться. Необходимо принудительно ограничивать MSS:

```bash
# Подстройка MSS под MTU туннельного интерфейса
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
     -o gre1 -j TCPMSS --clamp-mss-to-pmtu
```

## Очистка среды

**Важно:** Всегда удаляйте туннельные интерфейсы после завершения тестов.

```bash
# Удаление туннеля
sudo ip link del gre1

# Проверка удаления
ip link show | grep gre
# → Не должно быть вывода

# Удаление FOU
sudo ip fou del port 6666 ipproto 47

# Проверка
ip fou show
# → Не должно быть портов
```

## Связанные темы

*   **[ip link](./ip_link.md)** — базовое управление сетевыми интерфейсами.
*   **[ip route](./ip_route.md)** — управление таблицами маршрутизации.
*   **[GRE — подробное руководство](../../../Networking/Tunnels/gre/gre.md)** — архитектура, заголовки, мультикаст, DMVPN.
*   **[IPIP и SIT](../../../Networking/Tunnels/ipip_and_sit.md)** — инкапсуляция IPv4/IPv6, FOU, offload.
*   **[VXLAN](../../../Networking/Tunnels/vxlan.md)** — виртуальные L2-сегменты, VTEP, control plane.
*   **[BGP EVPN](../../../Networking/Concepts/sdn/bgp_evpn.md)** — control-plane learning для VXLAN (замена flood-and-learn), symmetric IRB, multi-homing.
*   **[MTU и VPN](../../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — overhead туннелей, MSS Clamping, PMTUD.
*   **[Туннелирование IPv6](../../Settings/ipv6_configuration/tunneling.md)** — специфика SIT и 6in4.
