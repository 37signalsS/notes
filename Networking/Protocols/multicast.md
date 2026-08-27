# Групповая рассылка (Multicast) и IGMP Snooping

## Определения

**Multicast (групповая рассылка)** — технология передачи данных от одного источника группе получателей одновременно. В отличие от **Unicast** (один к одному) и **Broadcast** (один ко всем), трафик доставляется только тем узлам, которые подписались на конкретную группу. Это радикально снижает нагрузку на сеть при трансляции потоковых данных (IPTV, видеоконференции).

**IGMP (Internet Group Management Protocol)** — протокол сетевого уровня (L3), используемый хостами и маршрутизаторами в сетях IPv4 для управления членством в мультикаст-группах.

**MLD (Multicast Listener Discovery)** — аналог IGMP для сетей IPv6, работающий на базе протокола ICMPv6.

**IGMP/MLD Snooping** — механизм канального уровня (L2), позволяющий коммутатору анализировать служебный трафик (Snooping) для ограничения рассылки мультикаста только на те порты, где есть активные подписчики.

## Основные концепции

### Адресация мультикаста

#### IP-адреса (L3)
- **IPv4:** Диапазон `224.0.0.0/4` (Класс D).
  - `224.0.0.1` — Все узлы в сегменте.
  - `224.0.0.2` — Все маршрутизаторы в сегменте.
  - `224.0.0.13` — Все PIM-маршрутизаторы.
  - `239.0.0.0/8` — Приватные (Administrative Scope) адреса, аналоги RFC 1918.
- **IPv6:** Диапазон `ff00::/8`.

#### MAC-адреса (L2) и маппинг
Для IPv4 мультикаст-адреса отображаются в MAC-адреса с префиксом **`01:00:5E`**.
- Механизм: Младшие 23 бита IP-адреса копируются в MAC-адрес.
- **Проблема коллизий:** Поскольку мультикаст-IP имеет 28 значимых бит, а в MAC копируется только 23, возникает ситуация, когда **32 разных IP-адреса** отображаются в один и тот же MAC-адрес. Коммутатор на L2 будет обрабатывать их как одну группу.

### Механизмы IGMP (IPv4)

| Версия | Ключевая особенность | Описание |
| :--- | :--- | :--- |
| **IGMPv1** | Базовый функционал | Только Join-запросы. Выход из группы происходит по таймауту. |
| **IGMPv2** | Leave Group | Добавлена команда Leave, позволяющая быстро прекратить поток трафика (Fast Leave). |
| **IGMPv3** | SSM (Source-Specific) | Позволяет хосту подписываться на поток от конкретного источника (Source-Specific Multicast), повышая безопасность. |

### Проблема Multicast-флуда и Snooping

Без IGMP Snooping коммутатор не знает, кто является получателем. Поскольку мультикаст-MAC никогда не бывает источником (Source MAC), коммутатор не может выучить его в CAM-таблицу и **флудит трафик на все порты VLAN**, как broadcast (широковещательный шторм).

**Механизм работы Snooping:**
1. **IGMP Join/Report:** Коммутатор перехватывает отчет о вступлении и добавляет порт в таблицу рассылки для группы.
2. **IGMP Leave:** Коммутатор удаляет порт (сразу в режиме Fast Leave или после проверки).
3. **Mrouter Ports:** Порты, на которых обнаружен мультикаст-маршрутизатор (через прием Query-пакетов или PIM-сообщений). На эти порты трафик отправляется всегда.

> **Связь с современными ЦОД:** В сетях VXLAN/EVPN мультикаст относится к категории **BUM-трафика** (Broadcast, Unknown Unicast, Multicast). Для его эффективного распределения используется Ingress Replication (копирование на уровне VTEP) или Multicast в Underlay-сети. IGMP Snooping работает поверх VNI для минимизации репликаций.

## Практические сценарии и диагностика

### Работа с мультикастом в Linux

Просмотр членства в группах на интерфейсе:
```bash
# Список всех мультикаст-групп (iproute2)
ip maddr show eth0

# Детальный просмотр сокетов, слушающих мультикаст
ss -ump

# Статистика пакетов
ip -s link show eth0
# Ищите поле "mcast"

# Просмотр IGMP-групп на интерфейсе
cat /proc/net/igmp

# Просмотр multicast routing таблицы (если включена маршрутизация)
ip mroute show
```

Диагностика трафика через `tcpdump`:
```bash
# Перехват только IGMP трафика
sudo tcpdump -i eth0 igmp

# Перехват мультикаст данных (например, на порт 5000)
sudo tcpdump -i eth0 -n net 224.0.0.0/4 and udp port 5000

# Перехват IGMP Join/Leave сообщений
sudo tcpdump -i eth0 -n 'igmp and (igmp type 0x12 or igmp type 0x17)'

# Перехват IGMP Query (от маршрутизатора)
sudo tcpdump -i eth0 -n 'igmp and igmp type 0x11'

# Сохранение мультикаст-трафика для анализа
sudo tcpdump -i eth0 -w /tmp/multicast.pcap 'net 239.0.0.0/8'
```

### Вступление в мультикаст-группу в Linux

```bash
# Вступление в группу 239.0.0.1 на интерфейсе eth0
sudo ip maddr add 239.0.0.1 dev eth0

# Проверка
ip maddr show dev eth0

# Использование socat для приема мультикаст-трафика
socat UDP-LISTEN:1234,bind=0.0.0.0,reuseaddr STDOUT

# Отправка мультикаст-пакета
echo "stream" | socat - UDP4-DATAGRAM:239.0.0.1:1234,bind=:1234

# Настройка интерфейса для мулькаста
ip link set eth0 multicast on
ip route add 239.0.0.0/8 dev eth0
```

### Конфигурация multicast routing в Linux

```bash
# Включение IP-маршрутизации (если не включена)
sysctl -w net.ipv4.ip_forward=1

# Включение multicast routing
sysctl -w net.ipv4.conf.all.mc_forwarding=1

# Настройка PIM (через frrouting или bird)
# Пример для FRRouting:
# router pim
#  ip pim
#  ip pim send-join 239.0.0.1 eth0

# Проверка multicast routing таблицы
ip mroute show
# → (192.168.1.100, 239.0.0.1) Iif: eth0 Oifs: eth1 eth2
```

### Настройка на коммутаторах (Cisco)

```cisco
# Включение IGMP Snooping глобально
ip igmp snooping

# Настройка Querier (если нет мультикаст-роутера)
ip igmp snooping querier
ip igmp snooping querier address 192.168.1.1

# Включение Fast Leave (Immediate Leave) для ускорения переключения каналов IPTV
ip igmp snooping vlan 10 immediate-leave

# Ограничение мультикаста только на определенные порты
ip igmp snooping vlan 10 static 239.0.0.1 interface Gi0/1

# Настройка мультикаст-в rays (VLAN)
interface Vlan10
 ip pim sparse-mode
 ip igmp version 3

# Просмотр IGMP Snooping таблицы
show ip igmp snooping
show ip igmp snooping groups
show ip igmp snooping mrouter
```

### Настройка на маршрутизаторах (Cisco — PIM)

```cisco
# Включение PIM Sparse Mode на интерфейсах
interface GigabitEthernet0/0
 ip pim sparse-mode
 ip igmp version 3

# Настройка RP (Rendezvous Point)
ip pim rp-address 10.0.0.1

# Или Bootstrap Router (BSR) для автоматического выбора RP
ip pim bsr-candidate Loopback0
ip pim rp-candidate Loopback0

# Просмотр PIM-соседей
show ip pim neighbor

# Просмотр multicast routing таблицы
show ip mroute

# Просмотр активных IGMP-групп
show ip igmp groups
```

### Настройка на маршрутизаторах (Linux — FRRouting)

```bash
# Включение PIM в FRRouting
vtysh
configure terminal
router pim
 ip pim
 ip pim rp-address 10.0.0.1
exit

# Настройка интерфейсов
interface eth0
 ip pim
exit

interface eth1
 ip pim
exit

# Проверка
show ip pim neighbor
show ip mroute
show ip igmp groups
```

### Сценарий: IPTV-вещание в корпоративной сети

**Архитектура:**
1. IPTV-сервер (источник) → Multicast 239.10.1.1:5000
2. Маршрутизатор (PIM-SM RP) → межсетевая маршрутизация
3. Коммутаторы (IGMP Snooping) → доставка только подписчикам
4. IPTV-приемники (IGMPv3 Join) → получение потока

**Конфигурация:**
```bash
# На IPTV-сервере (Linux)
# Запуск VLC-сервера с multicast-выходом
cvlc --sout '#std{access=udp,mux=ts,dst=239.10.1.1:5000}' video.mp4

# Или через ffmpeg
ffmpeg -i input.mp4 -f mpegts udp://239.10.1.1:5000

# На IPTV-приемнике (Linux)
# Присоединение к группе
sudo ip maddr add 239.10.1.1 dev eth0

# Запуск VLC-клиента
vlc udp://@239.10.1.1:5000
```

**Настройка VLAN для IPTV:**
```cisco
# VLAN 100 для IPTV-трафика
vlan 100
 name IPTV

# Access-порты для IPTV-приемников
interface range GigabitEthernet0/1-24
 switchport mode access
 switchport access vlan 100
 spanning-tree portfast
 spanning-tree bpduguard enable

# Trunk-порты к маршрутизатору
interface GigabitEthernet0/48
 switchport mode trunk
 switchport trunk allowed vlan 100
```

### Сценарий: видеоконференции (WebRTC, SIP)

**Проблема:** Мультикаст-трафик видеоконференции (RTP) должен доставляться только активным участникам, но без IGMP Snooping он флудится на все порты.

**Решение:**
```cisco
# Включение Fast Leave для VLAN с видеоконференциями
ip igmp snooping vlan 50 immediate-leave

# Ограничение querier интервала для быстрого обнаружения
ip igmp snooping querier
ip igmp snooping query-interval 30
ip igmp snooping query-max-response-time 5
```

### Диагностика проблем (Troubleshooting)

#### Диагностический скрипт

```bash
#!/bin/bash
# Multicast Diagnostics Script
IFACE="${1:-eth0}"

echo "=== Multicast Diagnostics for $IFACE ==="

# 1. Проверка multicast на интерфейсе
echo ""
echo "--- Interface Multicast Status ---"
ip link show $IFACE | grep -i multicast
ip maddr show dev $IFACE

# 2. Проверка IGMP
echo ""
echo "--- IGMP Groups ---"
cat /proc/net/igmp | head -20

# 3. Проверка multicast routing
echo ""
echo "--- Multicast Routing Table ---"
ip mroute show 2>/dev/null || echo "  Multicast routing not enabled"

# 4. Проверка PIM (если настроен)
echo ""
echo "--- PIM Status ---"
if command -v vtysh &>/dev/null; then
    vtysh -c "show ip pim neighbor" 2>/dev/null || echo "  PIM not configured"
else
    echo "  FRRouting not installed"
fi

# 5. Проверка firewall для multicast
echo ""
echo "--- Firewall Rules (multicast) ---"
iptables -L -n -v | grep -i "224\.\|239\.\|multicast" || echo "  No multicast-specific rules"

# 6. Проверка IGMP Snooping (если bridge)
echo ""
echo "--- Bridge IGMP Snooping ---"
if ip link show type bridge &>/dev/null; then
    bridge link show | head -5
    cat /sys/class/net/br0/bridge/multicast_router 2>/dev/null || echo "  No bridge found"
fi

echo ""
echo "=== Diagnostics Complete ==="
```

#### Типичные ошибки и решения

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Мультикаст-трафик идет на все порты** | IGMP Snooping отключен или нет Querier | `show ip igmp snooping` — проверить статус | Включить IGMP Snooping; настроить Querier |
| **Трафик не идет вообще** | Нет подписчиков или RPF fail | `show ip igmp groups` — проверить группы | Проверить IGMP Join на хостах; проверить RPF |
| **Задержка при переключении канала** | IGMPv1/v2 без Fast Leave | `show ip igmp version` — проверить версию | Перейти на IGMPv3; включить Fast Leave |
| **Маршрутизатор не пересылает мультикаст** | PIM не настроен на интерфейсах | `show ip pim interface` — проверить PIM | Включить `ip pim sparse-mode` на интерфейсах |
| **Нет RP (Rendezvous Point)** | RP не настроен или недоступен | `show ip pim rp mapping` — проверить RP | Настроить статический RP или BSR |
| **Высокий CPU на коммутаторе** | Мультикаст-шторм (нет Snooping) | `show process cpu` — проверить нагрузку | Включить IGMP Snooping; ограничить multicast |
| **IPTV-приемник не получает поток** | VLAN не настроен или нет Trunk | `show vlan brief` — проверить VLAN | Настроить VLAN 100; проверить Trunk |
| **Мультикаст не проходит через VPN** | GRE/IPSec не поддерживает multicast | Проверить MTU и encapsulation | Настроить PIM over GRE; увеличить MTU |

#### Пошаговый алгоритм диагностики

```
1. Мультикаст-трафик не работает
   ├── Проверьте IGMP на хосте: ip maddr show dev eth0
   │   ├── Группа есть → проблема в сети/маршрутизации
   │   └── Группы нет → отправьте IGMP Join вручную
   ├── Проверьте IGMP Snooping на коммутаторе
   │   ├── Snooping включен → проверьте Querier
   │   └── Snooping выключен → включите
   ├── Проверьте PIM на маршрутизаторе
   │   ├── PIM neighbor есть → проверьте RP
   │   └── PIM neighbor нет → проверьте интерфейсы
   └── Проверьте RPF
       ├── RPF OK → проблема в ACL/fabric
       └── RPF fail → исправьте маршрутизацию
```

#### Мониторинг мультикаст-трафика

```bash
# Статистика мультикаст-пакетов на интерфейсе
ip -s link show eth0 | grep -A2 "RX:"
# → RX:  bytes=... packets=... errors=... dropped=... overrun=... mcast=...

# Мониторинг IGMP в реальном времени
watch -n 1 'cat /proc/net/igmp | grep -A1 "eth0"'

# Мониторинг multicast routing таблицы
watch -n 1 'ip mroute show'

# Проверка счетчиков multicast в ядре
cat /proc/net/snmp | grep -i "multicast\|igmp"
```

### Интеграция с Prometheus (мониторинг мультикаста)

```bash
# Экспорт метрик multicast через node_exporter
# Добавить в collector: --collector.systemd

# Примеры метрик:
# node_netstat_Igmp_InMsgs — входящие IGMP-сообщения
# node_netstat_Igmp_OutMsgs — исходящие IGMP-сообщения
# node_netstat_Igmp_InErrors — ошибки IGMP

# Алерты в Prometheus:
# - ALERT: MulticastFloodDetected
#   expr: rate(node_netstat_Igmp_InMsgs[5m]) > 1000
#   for: 2m
#   labels:
#     severity: warning
#   annotations:
#     summary: "High IGMP activity on {{ $labels.instance }}"
```

## Дополнительная информация

### Маршрутизация: PIM (Protocol Independent Multicast)

Для передачи мультикаста между IP-сетями (L3) используются протоколы маршрутизации, которые строят деревья распространения трафика на основе данных Unicast-маршрутизации (OSPF, BGP).

1. **PIM Dense Mode (DM):**
   - **Принцип:** Сначала флудит трафик во все интерфейсы, затем маршрутизаторы без подписчиков отправляют Prune-сообщения (обрезают ветки).
   - **Применение:** Устарел. Плохо масштабируется, создает огромный оверхед.

2. **PIM Sparse Mode (SM):**
   - **Принцип:** Трафик идет только туда, где его явно запросили. Использует **Rendezvous Point (RP)** — центральную точку встречи источника и получателей.
   - **Anycast-RP и MSDP:** В крупных сетях для отказоустойчивости RP настраивают несколько роутеров с одинаковым IP-адресом (Anycast). Протокол **MSDP (Multicast Source Discovery Protocol)** синхронизирует списки активных источников между этими RP.

3. **PIM Source-Specific Multicast (SSM):**
   - **Принцип:** Получатель (через IGMPv3) сразу запрашивает трафик от конкретного источника (IP-адреса).
   - **Преимущество:** Исключает необходимость в RP, строит кратчайшее дерево (SPT) сразу от получателя к источнику. Стандарт де-факто для IPTV.

### Связанные документы

- **[MAC-адрес: Принципы адресации](../Concepts/mac_address.md)** — детальный разбор физической адресации.
- **[RPF и uRPF — проверка пути](./rpf_urpf.md)** — предотвращение петель в мультикасте.
- **[VLAN — виртуальные сети](./vlan.md)** — границы широковещательных и мультикаст доменов.
- **[UDP — транспортный уровень](./udp.md)** — основной протокол для мультикаст-данных.
- **[IPv6 и MLD](./ipv6_overview.md)** — особенности мультикаста в IPv6.
- **[VXLAN](../Tunnels/vxlan.md)** — мультикаст в оверлейных сетях (BUM-трафик).
- **[GRE-туннели](../Tunnels/gre/gre.md)** — туннелирование мультикаста между сетями.
- **[IPSec](../Tunnels/ipsec/ipsec.md)** — защита мультикаст-трафика через шифрование.
