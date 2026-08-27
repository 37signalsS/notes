# Практические сценарии настройки GRE

## Определения и типы сценариев

В практической деятельности GRE используется в нескольких основных режимах, каждый из которых предназначен для решения специфических задач сетевой связности:

*   **Point-to-Point GRE (Точка-точка):** Классический L3-туннель между двумя узлами со статическими адресами. Используется для объединения офисов или подключения к провайдерам защиты от DDoS.
*   **Multipoint GRE (mGRE):** Позволяет одному интерфейсу терминировать множество туннелей. Является фундаментом для построения **DMVPN** (Dynamic Multipoint VPN).
*   **GRETAP (L2 GRE):** Инкапсулирует Ethernet-кадры вместо IP-пакетов. Позволяет «растягивать» L2-сегменты (VLAN) между удаленными площадками.
*   **ERSPAN (Encapsulated Remote SPAN):** Специализированная версия GRE для зеркалирования трафика L2 через маршрутизируемые IP-сети.

**Сводная таблица режимов:**

| Режим | Уровень OSI | Назначение | Особенности |
|-------|-------------|------------|-------------|
| **Point-to-Point** | L3 | Site-to-Site VPN | Требует статических эндпоинтов |
| **mGRE** | L3 | Hub-and-Spoke / Mesh | Требует протоколов разрешения (NHRP) |
| **GRETAP** | L2 | Растягивание VLAN | Высокий оверхед (~42 байта) |
| **ERSPAN** | L2 | Мониторинг трафика | Зависит от аппаратной поддержки |

---

## Настройка в Linux (iproute2)

Все настройки выполняются через утилиту `ip`. В современных системах рекомендуется использовать `ip link` вместо устаревшего `ip tunnel`.

### Базовая настройка Point-to-Point

**Полная настройка обоих узлов:**

```bash
# === Хост A (198.51.100.1) ===

# Включение IP forwarding (обязательно для маршрутизации)
sudo sysctl -w net.ipv4.ip_forward=1

# Создание GRE-туннеля
sudo ip link add dev gre0 type gre remote 203.0.113.2 local 198.51.100.1 ttl inherit key 100

# Установка MTU (рекомендуется 1400 для запаса под IPsec при необходимости)
sudo ip link set gre0 mtu 1400

# Назначение IP-адреса внутри туннеля
sudo ip address add 10.0.0.1/30 dev gre0

# Активация интерфейса
sudo ip link set gre0 up

# Добавление маршрута до удалённой подсети через туннель
sudo ip route add 172.16.0.0/24 via 10.0.0.2 dev gre0

# === Хост B (203.0.113.2) ===
sudo sysctl -w net.ipv4.ip_forward=1
sudo ip link add dev gre0 type gre remote 198.51.100.1 local 203.0.113.2 ttl inherit key 100
sudo ip link set gre0 mtu 1400
sudo ip address add 10.0.0.2/30 dev gre0
sudo ip link set gre0 up
sudo ip route add 192.168.0.0/24 via 10.0.0.1 dev gre0
```

**Параметры:**

| Параметр | Описание |
|----------|----------|
| `local` / `remote` | Внешние IP-адреса эндпоинтов туннеля |
| `key` | 32-битный идентификатор туннеля (должен совпадать на обоих концах) |
| `ttl inherit` | Наследование TTL от внутреннего пакета (рекомендуется для корректного `traceroute`) |
| `mtu` | Установка MTU для предотвращения фрагментации |

**Файрвол для GRE (обязательно на обоих узлах):**

```bash
# nftables (рекомендуется)
nft add rule inet filter input ip saddr 203.0.113.2 ip protocol 47 accept
nft add rule inet filter output ip daddr 203.0.113.2 ip protocol 47 accept

# iptables
sudo iptables -A INPUT -s 203.0.113.2 -p 47 -j ACCEPT
sudo iptables -A OUTPUT -d 203.0.113.2 -p 47 -j ACCEPT
```

**Сохранение IP forwarding (перезагрузка):**

```bash
#永久ное включение
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-gre.conf
sudo sysctl --system
```

**Проверка работоспособности:**
```bash
# Проверка статуса интерфейса
ip link show gre0

# Проверка обеих сторон туннеля
ping 10.0.0.2

# Проверка маршрута
ip route get 172.16.0.1
```

### Настройка GRETAP (L2 туннель)

Используется для объединения двух удаленных сегментов в один программный мост (Bridge):

```bash
# === Хост A (198.51.100.1) ===

# Создание моста (если ещё нет)
sudo ip link add br0 type bridge
sudo ip link set br0 up

# Создание GRETAP-туннеля
sudo ip link add dev tap0 type gretap remote 203.0.113.2 local 198.51.100.1

# Добавление интерфейса в мост
sudo ip link set tap0 master br0
sudo ip link set tap0 mtu 1450
sudo ip link set tap0 up

# Добавление физического интерфейса в мост (пример)
sudo ip link set eth1 master br0

# Назначение IP мосту (если нужен L3-доступ)
sudo ip address add 192.168.1.1/24 dev br0

# === Хост B (203.0.113.2) ===
sudo ip link add br0 type bridge
sudo ip link set br0 up
sudo ip link add dev tap0 type gretap remote 198.51.100.1 local 203.0.113.2
sudo ip link set tap0 master br0
sudo ip link set tap0 mtu 1450
sudo ip link set tap0 up
sudo ip link set eth1 master br0
sudo ip address add 192.168.1.2/24 dev br0
```

**GRETAP + VLAN:**

```bash
# Создание VLAN поверх GRETAP
sudo ip link add link tap0 name tap0.100 type vlan id 100
sudo ip link set tap0.100 up
sudo ip address add 10.10.100.1/24 dev tap0.100

# Добавление VLAN в мост (для прозрачной передачи)
sudo ip link set tap0.100 master br0
```

**Настройка STP (.Spanning Tree Protocol) для предотвращения петель):**
```bash
# Включение STP на мосту
sudo ip link set br0 type bridge stp_state 1

# Проверка состояния STP
bridge link show
brctl showstp br0
```

### Настройка ERSPAN

Зеркалирование трафика с удаленного коммутатора на сервер анализа:

```bash
# === Сервер анализа (198.51.100.1) ===

# erspan_ver 1 (совместимость с Cisco) или 2 (современный Linux)
# erspan 10 — идентификатор сессии зеркалирования
sudo ip link add dev erspan0 type erspan \
    local 198.51.100.1 remote 203.0.113.2 \
    erspan_ver 1 erspan 10
sudo ip link set erspan0 up
sudo ip address add 10.0.0.1/30 dev erspan0

# === Коммутатор (203.0.113.2) — источник трафика ===
sudo ip link add dev erspan0 type erspan \
    local 203.0.113.2 remote 198.51.100.1 \
    erspan_ver 1 erspan 10
sudo ip link set erspan0 up
```

**Проверка зеркалирования:**
```bash
# Анализ зеркалированного трафика
sudo tcpdump -i erspan0 -nn

# Проверка статистики ERSPAN
ip -s link show erspan0
```

---

## Настройка на сетевом оборудовании

### Cisco IOS/XE (Point-to-Point)

```cisco
! === Хост A (198.51.100.1) ===
interface Tunnel0
 ip address 10.0.0.1 255.255.255.252
 ip mtu 1400
 ip tcp adjust-mss 1360
 tunnel source 198.51.100.1
 tunnel destination 203.0.113.2
 tunnel key 100
 ! Рекомендуется для stateless туннелей
 keepalive 10 3

! Маршрутизация через туннель
ip route 172.16.0.0 255.255.255.0 10.0.0.2
```

**Важные моменты Cisco:**
*   `ip mtu 1400` + `ip tcp adjust-mss 1360` — предотвращают фрагментацию и зависание TCP.
*   `keepalive 10 3` — проверка связности каждые 10 сек, 3 попытки до объявления DOWN.
*   `tunnel key 100` — идентификатор туннеля (должен совпадать на обоих концах).

### MikroTik (RouterOS)

```routeros
# === Хост A (198.51.100.1) ===

# Создание GRE-туннеля
/interface gre
add local-address=198.51.100.1 remote-address=203.0.113.2 name=gre-tunnel1 \
    dscp=inherit mtu=1400 tunnel-id=100

# Назначение адреса
/ip address
add address=10.0.0.1/30 interface=gre-tunnel1

# Маршрутизация
/ip route
add dst-address=172.16.0.0/24 gateway=10.0.0.2

# Файрвол (разрешение GRE)
/ip firewall filter
add chain=input protocol=gre src-address=203.0.113.2 action=accept \
    comment="Allow GRE from remote"
add chain=output protocol=gre dst-address=203.0.113.2 action=accept \
    comment="Allow GRE to remote"
```

**Проверка MikroTik:**
```routeros
/interface gre print detail
/ip route print where gateway=10.0.0.2
/tool ping 10.0.0.2
```

---

## Постоянная конфигурация (Persistence)

### Netplan (Ubuntu/Debian)

Файл `/etc/netplan/60-tunnel.yaml`:

```yaml
network:
  version: 2
  tunnels:
    gre0:
      mode: gre
      local: 198.51.100.1
      remote: 203.0.113.2
      addresses:
        - 10.0.0.1/30
      keys:
        input: 100
        output: 100
      routes:
        - to: 172.16.0.0/24
          via: 10.0.0.2
      mtu: 1400
```

### systemd-networkd

Файл `/etc/systemd/network/25-gre.netdev`:
```ini
[NetDev]
Name=gre0
Kind=gre

[Tunnel]
Local=198.51.100.1
Remote=203.0.113.2
Key=100
TTL=inherit
```

Файл `/etc/systemd/network/25-gre.network`:
```ini
[Match]
Name=gre0

[Network]
Address=10.0.0.1/30

[Route]
Destination=172.16.0.0/24
Gateway=10.0.0.2
```

**Примечание:** Для `Key` в systemd-networkd используется десятичный формат, не hex.

### NetworkManager (nmcli)

```bash
# Создание туннеля с ключом
sudo nmcli connection add type ip-tunnel ifname gre0 con-name gre0-tunnel \
    mode gre remote 203.0.113.2 local 198.51.100.1 \
    ip-tunnel.input-key 100 ip-tunnel.output-key 100

# Настройка адресации
sudo nmcli connection modify gre0-tunnel ipv4.addresses 10.0.0.1/30 ipv4.method manual
sudo nmcli connection modify gre0-tunnel +ipv4.routes "172.16.0.0/24 10.0.0.2"

# Установка MTU
sudo nmcli connection modify gre-tunnel 802-3-ethernet.mtu 1400

# Активация
sudo nmcli connection up gre0-tunnel

# Проверка
nmcli connection show gre0-tunnel
```

---

## Решение проблем MTU и MSS

Самая частая причина проблем в GRE — превышение размера пакета, так как заголовок GRE (4-12 байт) + внешний IP (20 байт) уменьшают полезную нагрузку.

**Расчёт MSS:**
*   Для MTU 1400: MSS = 1400 - 40 (TCP+IP) = **1360**
*   Для MTU 1476: MSS = 1476 - 40 = **1436**

### MSS Clamping (iptables/nftables)

Применяется на шлюзах для предотвращения зависания сессий (PMTUD Black Hole).

**Через iptables (autoclamp):**
```bash
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre0 -j TCPMSS --clamp-mss-to-pmtu
```

**Через iptables (жёсткая установка):**
```bash
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre0 -j TCPMSS --set-mss 1360
```

**Через nftables (autoclamp):**
```bash
nft add rule inet filter forward oifname "gre0" tcp flags syn \
    tcp option maxseg size set rt mtu
```

**Через nftables (жёсткая установка):**
```bash
nft add rule inet filter forward oifname "gre0" tcp flags syn \
    tcp option maxseg size set 1360
```

**Проверка MSS:**
```bash
# Просмотр MSS-правил
sudo iptables -t mangle -L FORWARD -v -n | grep TCPMSS
nft list chain inet filter forward | grep mss

# Проверка текущего MSS соединения
ss -ti | grep mss
```

---

## Продвинутые сценарии

### OSPF over GRE (FRRouting)

Настройка динамической маршрутизации OSPF поверх GRE-туннеля с использованием FRRouting.

**Установка FRRouting:**
```bash
# Debian/Ubuntu
sudo apt install frr

# Включение OSPF-демона
sudo sed -i 's/ospfd=no/ospfd=yes/' /etc/frr/daemons
sudo systemctl restart frr
```

**Конфигурация (Hub — 198.51.100.1):**
```bash
sudo vtysh
conf t

# Интерфейс GRE
interface gre0
 ip address 10.0.0.1/30
 ip ospf area 0
 ip ospf hello-interval 10
 ip ospf dead-interval 40
exit

# OSPF
router ospf
 ospf router-id 1.1.1.1
 network 192.168.1.0/24 area 0
 network 10.0.0.0/30 area 0
 passive-interface eth0
 log-adjacency-changes
exit

write
```

**Конфигурация (Spoke — 203.0.113.2):**
```bash
sudo vtysh
conf t

interface gre0
 ip address 10.0.0.2/30
 ip ospf area 0
 ip ospf hello-interval 10
 ip ospf dead-interval 40
exit

router ospf
 ospf router-id 2.2.2.2
 network 192.168.2.0/24 area 0
 network 10.0.0.0/30 area 0
 passive-interface eth0
 log-adjacency-changes
exit

write
```

**Проверка OSPF:**
```bash
# Соседство
sudo vtysh -c "show ip ospf neighbor"

# База данных LSA
sudo vtysh -c "show ip ospf database"

# Таблица маршрутизации OSPF
sudo vtysh -c "show ip route ospf"

# Статус интерфейсов OSPF
sudo vtysh -c "show ip ospf interface gre0"
```

### BGP Peering over GRE

Настройка BGP-сессии между двумя Autonomous Systems поверх GRE-туннеля.

**Конфигурация (AS 65001 — 198.51.100.1):**
```bash
sudo vtysh
conf t

router bgp 65001
 bgp router-id 1.1.1.1
 bgp log-neighbor-changes
 neighbor 10.0.0.2 remote-as 65002
 neighbor 10.0.0.2 description AS65002-Peer
 neighbor 10.0.0.2 timers 10 30

 address-family ipv4 unicast
  network 192.168.1.0/24
  neighbor 10.0.0.2 activate
  neighbor 10.0.0.2 soft-reconfiguration inbound
  maximum-paths 2
 exit-address-family
exit

write
```

**Конфигурация (AS 65002 — 203.0.113.2):**
```bash
sudo vtysh
conf t

router bgp 65002
 bgp router-id 2.2.2.2
 bgp log-neighbor-changes
 neighbor 10.0.0.1 remote-as 65001
 neighbor 10.0.0.1 description AS65001-Peer
 neighbor 10.0.0.1 timers 10 30

 address-family ipv4 unicast
  network 192.168.2.0/24
  neighbor 10.0.0.1 activate
  neighbor 10.0.0.1 soft-reconfiguration inbound
  maximum-paths 2
 exit-address-family
exit

write
```

**Проверка BGP:**
```bash
# Соседство
sudo vtysh -c "show bgp ipv4 unicast summary"

# Таблица маршрутизации BGP
sudo vtysh -c "show bgp ipv4 unicast"

# Детали конкретного соседа
sudo vtysh -c "show bgp ipv4 unicast neighbors 10.0.0.2"

# Проверка advertised routes
sudo vtysh -c "show bgp ipv4 unicast neighbors 10.0.0.2 advertised-routes"
```

### mGRE и DMVPN

В режиме mGRE интерфейс не имеет фиксированного `remote`. Для работы требуется протокол **NHRP** (Next Hop Resolution Protocol). В Linux это реализуется через **FRRouting (FRR)**.

**Конфигурация интерфейса (Hub):**
```bash
# Создание mGRE интерфейса
sudo ip link add dev mgre0 type gre local 198.51.100.1 key 1 ttl 64
sudo ip addr add 10.255.255.1/24 dev mgre0
sudo ip link set mgre0 up
sudo sysctl -w net.ipv4.ip_forward=1
```

**Конфигурация NHRP (Hub — FRR):**

Файл `/etc/frr/frr.conf`:
```
frr defaults traditional
hostname hub.example.com
log syslog warning
!
ip nhrp event watching
!
interface mgre0
 ip nhrp network-id 1
 ip nhrp map multicast dynamic
 ip nhrp redirect timeout 600
 ip address 10.255.255.1/24
 ip ospf area 0
!
router ospf
 ospf router-id 1.1.1.1
 log-adjacency-changes
!
line vty
!
```

**Конфигурация Spoke (203.0.113.2):**

```bash
# Создание mGRE интерфейса
sudo ip link add dev mgre0 type gre local 203.0.113.2 key 1 ttl 64
sudo ip addr add 10.255.255.2/24 dev mgre0
sudo ip link set mgre0 up
```

Файл `/etc/frr/frr.conf`:
```
frr defaults traditional
hostname spoke.example.com
log syslog warning
!
interface mgre0
 ip nhrp network-id 1
 ip nhrp nhs 10.255.255.1
 ip nhrp map 10.255.255.1 198.51.100.1
 ip nhrp map multicast 198.51.100.1
 ip nhrp shortcut
 ip address 10.255.255.2/24
 ip ospf area 0
!
router ospf
 ospf router-id 2.2.2.2
 log-adjacency-changes
!
line vty
!
```

**Проверка DMVPN:**
```bash
# Просмотр NHRP кеша
sudo vtysh -c "show ip nhrp"

# Просмотр NHRP-сведений
sudo vtysh -c "show ip nhrp brief"

# Проверка OSPF-соседства
sudo vtysh -c "show ip ospf neighbor"

# Проверка туннелей mGRE
ip -d link show mgre0
```

### Keepalive для Linux

GRE — **stateless-протокол**. Интерфейс остаётся в состоянии `UP`, даже если удалённая точка недоступна. Это приводит к «чёрной дыре» маршрутизации.

**Проблема:** Ядро Linux (`ip_gre`) **не поддерживает** нативные Cisco-style keepalives. Команда `ip tunnel change gre1 keepalive 10 3` молча игнорируется.

**Решения:**

**Вариант 1 — Фоновый скрипт (простой):**
```bash
#!/bin/bash
REMOTE="10.0.0.2"
IFACE="gre0"

while true; do
    if ! ping -c 1 -W 2 $REMOTE > /dev/null 2>&1; then
        ip link set $IFACE down
        sleep 5
        ip link set $IFACE up
        logger "GRE tunnel to $REMOTE is DOWN — restarting"
    fi
    sleep 10
done
```

**Вариант 2 — BFD через FRRouting (production):**
```bash
sudo vtysh -c "configure terminal" \
  -c "interface gre0" \
  -c "bfd profile gre-bfd" \
  -c "  transmit-interval 300" \
  -c "  receive-interval 300" \
  -c "  detect-multiplier 3" \
  -c "exit" \
  -c "router ospf" \
  -c "  bfd" \
  -c "exit"
```

**Вариант 3 — eBPF/XDP (ядро 5.10+, проект linux-gre-keepalive):**
```bash
# Установка из исходников (https://github.com/jamesits/linux-gre-keepalive)
git clone https://github.com/jamesits/linux-gre-keepalive.git
cd linux-gre-keepalive
make
sudo ./gre_keepalive --local 198.51.100.1 --remote 203.0.113.2 --interval 10 --interface eth0
```

### GRE через UDP (FOU — Foo Over UDP)

Используется для обхода проблемных NAT и брандмауэров, а также для балансировки трафика (ECMP) на основе UDP-портов.

```bash
# 1. Создание UDP-слушателя для GRE (порт 6666)
sudo ip fou add port 6666 ipproto 47

# 2. Создание туннеля, упакованного в UDP
sudo ip link add name gre_fou type gre \
    remote 203.0.113.2 local 198.51.100.1 \
    encap fou encap-sport auto encap-dport 6666

# 3. Назначение адреса и активация
sudo ip addr add 10.0.0.1/30 dev gre_fou
sudo ip link set gre_fou up
sudo ip link set gre_fou mtu 1400
```

**Проверка FOU:**
```bash
# Проверка UDP-слушателя
ip fou show

# Проверка интерфейса
ip link show gre_fou

# Анализ UDP-трафика (port 6666)
sudo tcpdump -i any udp port 6666 -nn
```

### TC/Traffic Shaping для GRE

GRE-трафик конкурирует с остальным за полосу пропускания. TC (Traffic Control) позволяет приоритизировать и ограничивать GRE.

#### Приоритизация GRE перед остальным трафиком

```bash
# Очистка существующих правил
sudo tc qdisc del dev eth0 root 2>/dev/null

# HTB qdisc (Hierarchical Token Bucket)
sudo tc qdisc add dev eth0 root handle 1: htb default 30

# Корневой класс (вся пропускная способность)
sudo tc class add dev eth0 parent 1: classid 1:1 htb rate 1gbit ceil 1gbit

# Класс для GRE (высокий приоритет)
sudo tc class add dev eth0 parent 1:1 classid 1:10 htb rate 500mbit ceil 1gbit prio 1

# Класс для остального трафика (низкий приоритет)
sudo tc class add dev eth0 parent 1:1 classid 1:30 htb rate 300mbit ceil 500mbit prio 2

# Фильтр: GRE (protocol 47) → класс 1:10
sudo tc filter add dev eth0 parent 1: protocol ip prio 1 u32 \
    match ip protocol 47 0xff flowid 1:10
```

#### Ограничение пропускной способности GRE-туннеля

```bash
# Ограничение GRE до 100 Мбит/с
sudo tc qdisc add dev gre0 root handle 1: htb default 1
sudo tc class add dev gre0 parent 1: classid 1:1 htb rate 100mbit ceil 100mbit
```

#### QoS для VOIP через GRE

```bash
# Дифференцированное обслуживание
sudo tc qdisc add dev eth0 root handle 1: htb default 20
sudo tc class add dev eth0 parent 1: classid 1:1 htb rate 1gbit

# VOIP (DSCP EF) → максимальный приоритет
sudo tc class add dev eth0 parent 1:1 classid 1:10 htb rate 100mbit ceil 1gbit prio 1
sudo tc filter add dev eth0 parent 1: protocol ip prio 1 u32 \
    match ip dport 5060 0xffff flowid 1:10

# GRE → средний приоритет
sudo tc class add dev eth0 parent 1:1 classid 1:20 htb rate 500mbit ceil 1gbit prio 2
sudo tc filter add dev eth0 parent 1: protocol ip prio 2 u32 \
    match ip protocol 47 0xff flowid 1:20

# Остальное → низкий приоритет
sudo tc class add dev eth0 parent 1:1 classid 1:30 htb rate 200mbit ceil 500mbit prio 3
```

#### Проверка TC-правил

```bash
# Просмотр qdisc
tc -s qdisc show dev eth0

# Просмотр классов
tc -s class show dev eth0

# Просмотр фильтров
tc filter show dev eth0

# Мониторинг в реальном времени
tc -s -d qdisc show dev eth0
```

### LACP/Bonding и Failover для GRE

#### Bonding двух GRE-туннелей (LACP failover)

```bash
# Создание двух GRE-туннелей через разные physical интерфейсы
sudo ip link add dev gre_primary type gre \
    remote 203.0.113.2 local 198.51.100.1 key 100
sudo ip link add dev gre_backup type gre \
    remote 203.0.113.3 local 198.51.100.1 key 200

# Создание bonding-интерфейса
sudo ip link add dev bond0 type bond mode active-backup
sudo ip link set gre_primary master bond0
sudo ip link set gre_backup master bond0

# Адресация
sudo ip addr add 10.0.0.1/30 dev bond0
sudo ip link set bond0 up
sudo ip link set gre_primary up
sudo ip link set gre_backup up
```

**Проверка failover:**
```bash
# Просмотр состояния bonding
cat /proc/net/bonding/bond0

# Имитация отказа primary
sudo ip link set gre_primary down
# Проверка: bond0 работает через gre_backup
```

#### ECMP через GRE-over-UDP (FOU)

```bash
# Два GRE-over-UDP туннеля с разными портами
sudo ip fou add port 6666 ipproto 47
sudo ip fou add port 6667 ipproto 47

sudo ip link add name gre_ecmp1 type gre \
    remote 203.0.113.2 local 198.51.100.1 \
    encap fou encap-sport auto encap-dport 6666
sudo ip link add name gre_ecmp2 type gre \
    remote 203.0.113.2 local 198.51.100.1 \
    encap fou encap-sport auto encap-dport 6667

# Одинаковые address для обоих интерфейсов
sudo ip addr add 10.0.0.1/30 dev gre_ecmp1
sudo ip addr add 10.0.0.1/30 dev gre_ecmp2
sudo ip link set gre_ecmp1 up
sudo ip link set gre_ecmp2 up

# ECMP маршрут (ядро распределит нагрузку)
sudo ip route add 172.16.0.0/24 \
    nexthop via 10.0.0.2 dev gre_ecmp1 weight 1 \
    nexthop via 10.0.0.2 dev gre_ecmp2 weight 1

# Проверка ECMP
ip route get 172.16.0.1
ip route show | grep 172.16
```

---

## Диагностика и отладка

### Пошаговый чек-лист при неисправности

**Этап 1 — Связанность Underlay:**
```bash
# Пинг эндпоинта (внешний IP)
ping -c 3 203.0.113.2

# Трассировка маршрута
traceroute 203.0.113.2

# Проверка маршрута к эндпоинту
ip route get 203.0.113.2
```

**Этап 2 — GRE-интерфейс:**
```bash
# Статус и детали интерфейса
ip -d link show gre0

# Статистика пакетов (входящие/исходящие, ошибки)
ip -s link show gre0

# Проверка MTU
ip link show gre0 | grep mtu

# Проверка параметров туннеля (key, ttl)
ip -d link show gre0 | grep -E "key|ttl|pmtudisc"
```

**Этап 3 — Маршрутизация:**
```bash
# Таблица маршрутизации (только GRE-маршруты)
ip route show | grep via

# Проверка конкретного маршрута
ip route get 172.16.0.1

# Проверка IP forwarding
sysctl net.ipv4.ip_forward
```

**Этап 4 — Трафик и MSS:**
```bash
# Анализ GRE-трафика (протокол 47)
sudo tcpdump -i any proto 47 -nn

# Проверка MSS соединений через туннель
ss -ti | grep mss

# Тест MTU (пакет должен пройти без фрагментации)
ping -M do -s 1372 10.0.0.2

# Тест пропускной способности
iperf3 -s  # на одном узле
iperf3 -c 10.0.0.2 -t 30  # на другом
```

**Этап 5 — Firewall:**
```bash
# Просмотр правил (nftables)
nft list ruleset | grep -E "47|gre"

# Просмотр правил (iptables)
sudo iptables -L INPUT -v -n | grep 47
sudo iptables -L FORWARD -v -n
```

### Инструментарий

| Задача | Команда |
|--------|---------|
| Просмотр параметров и счетчиков | `ip -d -s link show gre0` |
| Анализ прохождения протокола 47 | `tcpdump -i any proto 47 -nn` |
| Проверка маршрута к эндпоинту | `ip route get 203.0.113.2` |
| Просмотр NHRP кеша (для mGRE) | `vtysh -c "show ip nhrp"` |
| Проверка MSS соединения | `ss -ti \| grep mss` |
| Тест MTU через туннель | `ping -M do -s <size> <tunnel_ip>` |
| Тест пропускной способности | `iperf3 -c <tunnel_ip> -t 30` |
| Просмотр статистики ошибок | `ip -s -s link show gre0` |

### Таблица устранения неисправностей

| Симптом | Вероятная причина | Решение |
|---------|-------------------|---------|
| **Интерфейс UP, пинга нет** | Firewall блокирует ICMP внутри туннеля или сам GRE снаружи | Проверить правила `iptables/nftables` для IP 47 |
| **Мелкие пакеты проходят, крупные — нет** | Проблема MTU/MSS | Настроить MSS Clamping до 1360-1400 байт |
| **Трафик идет только в одну сторону** | NAT/PAT без поддержки GRE | Использовать FOU (GRE-over-UDP) |
| **Intermittent packet loss** | Keepalive не работает (Linux) | Настроить BFD через FRRouting или фоновый скрипт |
| **OSPF-соседство не устанавливается** | Multicast не проходит через GRE | Проверить `ip maddr show`, добавить `ip ospf network point-to-point` |
| **BGP-сессия flapping** | Нестабильный Underlay или MTU | Проверить `bgp log-neighbor-changes`, уменьшить MTU |
| **GRETAP: кадры не проходят** | Bridge не настроен или STP блокирует | Проверить `bridge link show`, отключить STP для теста |
| **ERSPAN: нет трафика** | Несовпадение erspan ID | Проверить `ip -d link show erspan0`, совпадение `erspan` на обоих концах |
| **mGRE: Spoke не видит Hub** | NHRP NHS не настроен | Проверить `vtysh -c "show ip nhrp"`, IP-адрес NHS |
| **Высокая задержка (jitter)** | Маршрутизация меняет путь | Проверить `traceroute`, статические маршруты или BFD |

---

## Дополнительная информация

### Связанные документы

*   [Протокол GRE](./gre.md) — фундаментальный обзор архитектуры и заголовков.
*   [Интеграция с IPsec](./gre_ipsec_integration.md) — настройка защищённых каналов (GRE-over-IPsec).
*   [GRE vs WireGuard](./gre_vs_wireguard.md) — сравнение протоколов, критерии выбора.
*   [Мониторинг GRE](./gre_monitoring.md) — наблюдаемость, Prometheus, алертинг.
*   [ip tunnel vs ip link](../../../Linux/Networking/Tools/iproute2/ip_tunnel.md) — детальное сравнение методов управления в Linux.
*   [MTU и VPN](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) — глубокая теория фрагментации и диагностики.
*   [OSPF (FRRouting)](../../Protocols/ospf.md) — настройка OSPF на FRRouting (Linux).
*   [BGP (FRRouting)](../../Protocols/bgp.md) — настройка BGP на FRRouting (Linux).
