# L2 Switching и VLAN: Практические сценарии

## Определения

*   **iproute2** — стандартный пакет утилит для управления сетевым стеком Linux (замена `net-tools`).
*   **Linux Bridge** — подсистема ядра, реализующая виртуальный L2-коммутатор.
*   **VLAN-aware Bridge** — современный режим работы моста, позволяющий управлять тегами на портах без создания множества виртуальных интерфейсов.
*   **Q-in-Q (IEEE 802.1ad)** — метод двойного тегирования (VLAN stacking), используемый для проброса клиентских VLAN через сеть провайдера.
*   **FDB (Forwarding Database)** — внутренняя таблица моста, сопоставляющая MAC-адреса устройств с портами моста. В Linux управляется утилитой `bridge fdb`.
*   **PVID (Port VLAN ID)** — идентификатор VLAN по умолчанию для нетегированных кадров, поступающих на порт. Управляется флагом `pvid` в `bridge vlan add`.
*   **Egress Untagged** — флаг, указывающий, что при выходе с порта тег данного VLAN должен быть удалён (аналог Native VLAN в Trunk или Access-порта).

Полный список терминов и теоретическая база — в **[Определения и концепции L2 Switching и VLAN](./definitions_and_concepts.md)**.

## Базовые концепции

Перед выполнением сценариев изучите теоретическую базу в **[Определения и концепции L2 Switching и VLAN](./definitions_and_concepts.md)**.

### Ключевые принципы настройки в Linux

1.  **Сабинтерфейсы:** Традиционный подход `eth0.10` создаёт виртуальное устройство для каждого тега. Удобно для малого количества VLAN.
2.  **Trunk-порт:** Физический интерфейс хоста должен быть подключён к порту коммутатора в режиме `trunk`.
3.  **MTU и Overhead:** Каждый тег 802.1Q добавляет 4 байта. Для Q-in-Q требуется увеличение MTU физического линка до 1508+ байт, чтобы избежать фрагментации IP-пакетов (стандарт 1500).
4.  **Promiscuous Mode:** Для работы мостов и некоторых конфигураций `macvlan` интерфейс должен принимать все кадры.
5.  **Hardware Offloading:** Linux может делегировать обработку 802.1Q-тегов сетевой карте. Проверяется через `ethtool -k <iface> | grep vlan`. Флаги `rx-vlan-offload` и `tx-vlan-offload` ускоряют обработку, но могут скрывать теги при захвате трафика (см. Edge Cases).
6.  **Персистентность:** Временные настройки `ip link` теряются при перезагрузке. Для постоянной конфигурации используйте systemd-networkd (`.netdev`/`.network` файлы), Netplan (`/etc/netplan/*.yaml`) или `/etc/network/interfaces` (ifupdown2). Выбор зависит от дистрибутива и среды.
7.  **Bonding + VLAN:** При использовании агрегированных каналов (Bonding/LACP) VLAN-интерфейсы создаются на логическом интерфейсе `bond0`, а не на физических (`eth0`/`eth1`). Это обеспечивает отказоустойчивость на уровне агрегата.
8.  **MACVLAN:** Позволяет создать виртуальный интерфейс с собственным MAC-адресом на базе физического, что даёт экстремальную изоляцию. Подробнее — в **[Сетевой драйвер macvlan](../../../Docker/Docker_network/drivers/macvlan.md)**.

## Практические сценарии

### Сценарий 1: Настройка VLAN на уровне хоста

#### Вариант A: iproute2 (Временная настройка)
```bash
# Создание интерфейса VLAN 10 поверх eth0
sudo ip link add link eth0 name eth0.10 type vlan id 10
sudo ip addr add 192.168.10.100/24 dev eth0.10
sudo ip link set eth0.10 up
```

#### Вариант B: systemd-networkd (Персистентная настройка)
Рекомендуется для Debian, Arch, Fedora. Требуется два файла в `/etc/systemd/network/`.

```ini
# 10-vlan10.netdev
[NetDev]
Name=eth0.10
Kind=vlan

[VLAN]
Id=10

# 20-eth0.network (привязка к физическому интерфейсу)
[Match]
Name=eth0

[Network]
VLAN=eth0.10
```

#### Вариант C: Netplan (Ubuntu)
```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  vlans:
    eth0.10:
      id: 10
      link: eth0
      addresses: [192.168.10.100/24]
```

#### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (kernel 3.8+) |
| **Утилиты** | iproute2 (`ip`, `bridge`), systemd-networkd или Netplan |
| **Права** | root (sudo) |
| **Интерфейс** | `eth0` — подключен к Trunk-порту коммутатора |
| **VLAN ID** | 10 (пример) |

#### Ожидаемый результат (Validation)
```bash
# Проверка созданного интерфейса
ip link show eth0.10
# → 3: eth0.10@eth0: <BROADCAST,MULTICAST,VLAN_LOCAL_FILTERS> mtu 1500 ...

# Проверка назначенного IP
ip addr show eth0.10
# → inet 192.168.10.100/24 scope global eth0.10

# Проверка наличия тега на физическом интерфейсе
sudo tcpdump -i eth0 -e -n vlan 10 -c 3
# → Должны появиться кадры с 802.1Q тегом VLAN 10

# Пинг шлюза
ping -c 3 192.168.10.1
# → 0% packet loss
```

#### Особые случаи (Edge Cases)
- **Отсутствие VLAN на коммутаторе:** если порт коммутатора настроен как Access в другой VLAN, трафик с тегом 10 будет отброшен. Проверьте `tcpdump` на `eth0` на наличие входящих тегированных кадров.
- **Hardware offload и tcpdump:** при включённом `rx-vlan-offload` ядро удаляет тег до передачи в пользовательское пространство. `tcpdump -i eth0 -e` может не отображать тег. Для диагностики: `sudo ethtool -K eth0 rx-vlan-offload off tx-vlan-offload off`.
- **Перезагрузка:** временная настройка (Вариант A) теряется при перезагрузке. Используйте Варианты B или C для постоянной конфигурации.

#### Очистка (Cleanup)
```bash
# Удаление временного VLAN-интерфейса
sudo ip link set eth0.10 down
sudo ip link delete eth0.10 type vlan id 10

# Отмена Netplan конфигурации
sudo rm /etc/netplan/01-netcfg.yaml
sudo netplan apply

# Отмена systemd-networkd конфигурации
sudo rm /etc/systemd/network/10-vlan10.netdev /etc/systemd/network/20-eth0.network
sudo systemctl restart systemd-networkd
```

---

### Сценарий 2: Виртуализация (VLAN-aware Bridge)

**Задача:** Создать один мост, который будет работать как Trunk-порт для виртуальных машин, распределяя их по разным VLAN.

```bash
# 1. Создание моста с включенной фильтрацией VLAN
sudo ip link add name br0 type bridge vlan_filtering 1
sudo ip link set eth0 master br0
sudo ip link set br0 up

# 2. Настройка портов моста (eth0 как Trunk для VLAN 10, 20)
sudo bridge vlan add dev eth0 vid 10
sudo bridge vlan add dev eth0 vid 20

# 3. Назначение VLAN для виртуального интерфейса VM (vnet0) как Access-порт
# Трафик от VM (без тега) будет помечаться ID 10 при входе в мост
sudo bridge vlan add dev vnet0 vid 10 pvid untagged
```

#### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (kernel 3.8+ для `vlan_filtering`) |
| **Утилиты** | iproute2 (`ip`, `bridge`) |
| **Права** | root (sudo) |
| **Интерфейсы** | `eth0` — физический uplink; `vnet0` — интерфейс ВМ (создаётся гипервизором, напр. KVM/QEMU) |
| **VLAN IDs** | 10, 20 — Trunk VLAN |

#### Персистентная конфигурация (systemd-networkd)
```ini
# /etc/systemd/network/30-br0.netdev
[NetDev]
Name=br0
Kind=bridge

[Bridge]
STP=yes
VLANFiltering=yes

# /etc/systemd/network/30-br0-bind.network (привязка eth0 к мосту)
[Match]
Name=eth0

[Network]
Bridge=br0

# /etc/systemd/network/30-br0.network (настройка моста)
[Match]
Name=br0

[Network]
Address=192.168.100.1/24
```
Применение: `sudo networkctl reload && sudo networkctl reconfigure br0`

#### STP на VLAN-aware Bridge

Linux Bridge поддерживает STP для предотвращения петеле. В ЦОД-топологиях Leaf-Spine STP часто отключают.

```bash
# Включение STP на мосте
sudo ip link set br0 type bridge stp_state 1

# Установка приоритета (кратно 4096)
sudo ip link set br0 type bridge priority 4096

# Настройка порта как Edge (аналог PortFast)
sudo bridge link set dev eth0 edgeport on

# Просмотр состояния STP
bridge link show
# → 2: eth0 state forwarding priority 32 cost 100
```

#### Ожидаемый результат (Validation)
```bash
# Просмотр VLAN на всех портах моста
bridge vlan show
# → port    vlan ids
# → eth0    10
# →         20
# → vnet0   10 PVID Egress Untagged

# Проверка состояния моста
ip link show br0
# → bridge vlan_filtering 1 stp_state 1 ...

# Проверка FDB (MAC-адреса устройств за портами)
bridge fdb show dev br0
# → 52:54:00:12:34:56 vlan 10 master br0

# Проверка STP
bridge link show
# → 2: eth0 state forwarding ...
# → 3: vnet0 state forwarding ...
```

#### Особые случаи (Edge Cases)
- **VLAN Filtering и перезагрузка:** при включённом `vlan_filtering` все порты по умолчанию наследуют VLAN 1. Если VLAN 1 не используется, она создаёт broadcast-домен. Удалите её: `bridge vlan del dev eth0 vid 1`.
- **MAC-адреса ВМ в FDB:** в VLAN-aware Bridge MAC-адреса ВМ создаются в FDB с привязкой к VLAN ID. Дублирование MAC между VLAN на одном мосту приводит к конфликту. Проверяйте: `bridge fdb show | grep <MAC>`.
- **Promiscuous Mode ВМ:** если ВМ отправляет нетегированный трафик на access-порт, тег добавляется автоматически (PVID). Если ВМ посылает тегированный трафик на access-порт — кадр будет отброшен.
- **STP и задержки:** STP добавляет задержку при перестроении топологии (30–50 сек для 802.1D, 1–10 сек для RSTP). Для критичных к задержкам средств используйте RSTP (`ip link set br0 type bridge forward_delay 4`).

#### Очистка (Cleanup)
```bash
# Удаление VLAN с портов
sudo bridge vlan del dev eth0 vid 10
sudo bridge vlan del dev eth0 vid 20
sudo bridge vlan del dev vnet0 vid 10 pvid untagged

# Отключение STP
sudo ip link set br0 type bridge stp_state 0

# Удаление портов из моста и удаление моста
sudo ip link set eth0 nomaster
sudo ip link set vnet0 nomaster
sudo ip link delete br0 type bridge
```

---

### Сценарий 3: Q-in-Q (VLAN Stacking)

**Задача:** Пробросить трафик клиента (с его собственными тегами) через VLAN 1000 провайдера.

```bash
# 1. Увеличение MTU на физическом интерфейсе
sudo ip link set dev eth0 mtu 1508

# 2. Создание внешнего (Service) тега
sudo ip link add link eth0 name eth0.1000 type vlan protocol 802.1ad id 1000

# 3. Создание внутреннего (Customer) тега поверх сервисного
sudo ip link add link eth0.1000 name eth0.1000.10 type vlan protocol 802.1Q id 10
sudo ip addr add 10.0.0.1/24 dev eth0.1000.10
```

#### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (kernel 3.8+ для `protocol 802.1ad`) |
| **Утилиты** | iproute2 (`ip`, `bridge`, `tcpdump`) |
| **Права** | root (sudo) |
| **MTU** | физический интерфейс должен поддерживать jumbo frames (≥1508 байт) |
| **Вендор** | сетевой коммутатель провайдера должен поддерживать Q-in-Q (802.1ad) |

#### Ожидаемый результат (Validation)
```bash
# Проверка созданных интерфейсов
ip link show eth0.1000.10
# → eth0.1000.10@eth0.1000: <BROADCAST,MULTICAST,VLAN_LOCAL_FILTERS> mtu 1500 ...

# Проверка вложенности тегов
sudo tcpdump -i eth0 -e -nn vlan 1000
# → Должен отображаться сервисный тег 1000
# → Внутри него — клиентский тег 10

# Проверка IP-адреса
ip addr show eth0.1000.10
# → inet 10.0.0.1/24 scope global eth0.1000.10
```

#### Особые случаи (Edge Cases)
- **MTU и фрагментация:** каждый тег добавляет 4 байта. Стандартный IP-пакет (1500 байт) + 2 тега = 1508 байт. Если MTU физического интерфейса не изменён, IP-пакеты фрагментируются. Решение: `sudo ip link set dev eth0 mtu 1508` (или 9000 для jumbo frames).
- **Поддержка драйвером:** не все сетевые карты поддерживают `protocol 802.1ad`. Проверьте через `ethtool -k eth0 | grep tx-vlan-offload`. При отсутствии аппаратной поддержки теги обрабатываются в программном режиме (более высокая нагрузка на CPU).
- **Контрольный кадр Ethernet:** при работе с Q-in-Q важно, чтобы коммутатор провайдера не изменял сервисный тег. Настройка `vlan dot1q tag native` на коммутаторе предотвращает снятие тега.

#### Очистка (Cleanup)
```bash
# Удаление внутреннего (клиентского) тега
sudo ip link set eth0.1000.10 down
sudo ip link delete eth0.1000.10 type vlan id 10

# Удаление внешнего (сервисного) тега
sudo ip link set eth0.1000 down
sudo ip link delete eth0.1000 type vlan protocol 802.1ad id 1000

# Восстановление стандартного MTU
sudo ip link set dev eth0 mtu 1500
```

---

### Сценарий 4: Меж-VLAN маршрутизация (Router-on-a-Stick)

**Задача:** Настроить Linux как шлюз для двух подсетей.

```bash
# Включение пересылки пакетов
sudo sysctl -w net.ipv4.ip_forward=1

# Настройка адресов-шлюзов
sudo ip addr add 192.168.10.1/24 dev eth0.10
sudo ip addr add 192.168.20.1/24 dev eth0.20

# Маскировка трафика (NAT), если нужен выход в интернет через eth1
sudo iptables -t nat -A POSTROUTING -o eth1 -j MASQUERADE
```

#### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (любой современный дистрибутив) |
| **Утилиты** | iproute2 (`ip`), iptables (`iptables-nft` или `iptables-legacy`) |
| **Права** | root (sudo) |
| **Интерфейсы** | `eth0` — подключен к Trunk-порту; `eth1` — uplink в Интернет (опционально) |
| **VLAN IDs** | 10, 20 — маршрутизируемые сегменты |

#### Персистентная конфигурация
Для постоянного включения пересылки пакетов используйте `/etc/sysctl.d/`:

```bash
# /etc/sysctl.d/99-ip-forward.conf
net.ipv4.ip_forward=1
```

Применить: `sudo sysctl -p /etc/sysctl.d/99-ip-forward.conf`

#### Ожидаемый результат (Validation)
```bash
# Проверка включения пересылки
cat /proc/sys/net/ipv4/ip_forward
# → 1

# Проверка маршрутов
ip route show
# → 192.168.10.0/24 dev eth0.10 proto kernel ...
# → 192.168.20.0/24 dev eth0.20 proto kernel ...

# Пинг из VLAN 10 до VLAN 20 (с хоста в VLAN 10)
ping -c 3 192.168.20.100
# → 0% packet loss

# Проверка NAT (если включена)
sudo iptables -t nat -L POSTROUTING -n -v
# → Правило MASQUERADE для eth1
```

#### Особые случаи (Edge Cases)
- **Аппаратная vs программная маршрутизация:** в этом сценарии маршрутизация выполняется в программном режиме (CPU). Для высоких скоростей используйте L3-коммутатор с SVI (аппаратная маршрутизация через ASIC). См. **[Меж-VLAN маршрутизация](../../Protocols/VLAN/vlan_inter_vlan_routing.md)**.
- **ICMP Redirect:** при использовании Linux-шлюза в сети с другим маршрутизатором могут появляться ICMP Redirect. Отключить: `sysctl -w net.ipv4.conf.all.send_redirects=0`.
- **Firewall (nftables/iptables):** если включены правила фаервола, убедитесь, что FORWARD-цепочка разрешает трафик между VLAN: `iptables -A FORWARD -i eth0.10 -j ACCEPT`.
- **MTU в ROAS:** каждый 802.1Q тег добавляет 4 байта. При использовании поверх туннеля (GRE, IPsec) требуется дополнительная корректировка MTU.

#### Очистка (Cleanup)
```bash
# Отключение пересылки
sudo sysctl -w net.ipv4.ip_forward=0
sudo rm /etc/sysctl.d/99-ip-forward.conf && sudo sysctl -p

# Удаление правил NAT
sudo iptables -t nat -D POSTROUTING -o eth1 -j MASQUERADE

# Удаление VLAN-интерфейсов
sudo ip link set eth0.10 down
sudo ip link set eth0.20 down
```

---

### Сценарий 5: Диагностика и поиск неисправностей

#### Анализ таблицы MAC-адресов (FDB)
Позволяет увидеть, на каких портах моста находятся конкретные устройства.
```bash
# Просмотр базы данных пересылки (Forwarding Database)
bridge fdb show dev br0
# → 52:54:00:12:34:56 vlan 10 master br0
```

#### Проверка тегов в реальном времени
```bash
# Захват кадров с выводом L2-заголовков (флаг -e)
sudo tcpdump -i eth0 -e -n vlan 10
```

#### Просмотр статистики VLAN-интерфейсов
```bash
# Детальная информация и счетчики ошибок
ip -s -d link show eth0.10
# → eth0.10@eth0: <BROADCAST,MULTICAST,VLAN_LOCAL_FILTERS> ...
#     vlan protocol 802.1Q id 10 <REORDER_HDR>
```

#### Проверка hardware offloading
```bash
# Проверка offload-флагов для VLAN
ethtool -k eth0 | grep -i vlan
# → tx-vlan-offload: on
# → rx-vlan-offload: on

# Отключение для диагностики (если tcpdump не видит теги)
sudo ethtool -K eth0 rx-vlan-offload off tx-vlan-offload off
```

#### Просмотр конфигурации VLAN через /proc
```bash
# Список всех VLAN и их физических устройств
cat /proc/net/vlan/config
# → Доступно, если созданы VLAN-интерфейсы через 802.1Q

# Статистика и флаги для конкретного интерфейса
cat /proc/net/vlan/eth0.10
# → eth0.10  VID 10  TYPE 802.1Q  FLAGS 0x0000  REORDER_HDR

# Просмотр фильтров VLAN на мосте (альтернатива bridge vlan show)
ls /sys/class/net/br0/bridge/vlan/
```

#### Анализ ARP-таблицы для VLAN
```bash
# Просмотр соседей (ARP) для проверки доступности шлюзов
ip neigh show
# → 192.168.10.1 dev eth0.10 REACHABLE ...

# Принудительный ARP-запрос
sudo arping -c 3 -I eth0.10 192.168.10.1
```

#### Мониторинг в реальном времени
```bash
# Непрерывный просмотр статистики на физическом интерфейсе
watch -n 1 'ip -s link show eth0'

# Захват broadcast-трафика (поиск broadcast storm / петле)
sudo tcpdump -i eth0 -n broadcast -c 100
```

#### Таблица типичных проблем и решений

| Проблема | Признак | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Нет пинга между устройствами в одной VLAN** | `ping` таймаутит | `bridge fdb show` — MAC на старом порту | Проверить физическую связь; `sudo bridge fdb flush dev br0` |
| **One-way traffic (трафик только в одну сторону)** | Ping from A→B работает, B→A нет | CDP/LLDP: `Native VLAN mismatch` | Установить одинаковый Native VLAN на обоих концах |
| **VLAN-интерфейс в DOWN** | `ip link show eth0.10` — состояние DOWN | `ip link show eth0` — физический DOWN | Поднять физический интерфейс: `sudo ip link set eth0 up` |
| **Весь трафик затапливается (коммутатор как хаб)** | Высокая нагрузка, broadcast storm | `bridge fdb show \| wc -l` — рост MAC | Включить Port Security, очистить FDB |
| **Ошибки MTU / packet drops** | `ip -s link show` — рост `dropped` | `ip link show eth0` — MTU < 1508 при Q-in-Q | Увеличить MTU: `sudo ip link set dev eth0 mtu 1508` |
| **Теги не видны в tcpdump** | `tcpdump -i eth0 -e` не показывает 802.1Q | `ethtool -k eth0 | grep vlan` — offload on | Отключить: `sudo ethtool -K eth0 rx-vlan-offload off` |
| **MAC flapping в FDB** | Один MAC на разных портах | `bridge fdb show` — MAC перемещается | Проверить наличие петли; включить STP `stp_state 1` |

---

### Сценарий 6: Агрегация каналов и VLAN (Bonding + 802.1Q)

**Задача:** Настроить LACP-агрегат с VLAN-интерфейсами поверх логического канала для отказоустойчивости и сегментации трафика.

#### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (kernel 3.10+ для bonding) |
| **Утилиты** | iproute2 (`ip`, `bridge`), ethtool |
| **Права** | root (sudo) |
| **Аппарат** | 2+ физические сетевые карты, коммутатор с поддержкой LACP (IEEE 802.3ad) |
| **VLAN IDs** | 10, 20 — сегменты для создания |

#### Конфигурация (iproute2 — временная)
```bash
# 1. Создание логического интерфейса Bonding в режиме LACP (mode 4)
sudo modprobe bonding
sudo ip link add name bond0 type bond mode 802.3ad
sudo ip link set eth1 down
sudo ip link set eth2 down
sudo ip link set eth1 master bond0
sudo ip link set eth2 master bond0
sudo ip link set bond0 up

# 2. Создание VLAN-интерфейсов на агрегате
sudo ip link add link bond0 name bond0.10 type vlan id 10
sudo ip link add link bond0 name bond0.20 type vlan id 20
sudo ip addr add 192.168.10.1/24 dev bond0.10
sudo ip addr add 192.168.20.1/24 dev bond0.20
sudo ip link set bond0.10 up
sudo ip link set bond0.20 up

# 3. Проверка статуса агрегата
cat /proc/net/bonding/bond0
# → Bonding Mode: IEEE 802.3ad Dynamic link aggregation
# → MII Status: up
# → Active Agg: ...
```

#### Персистентная конфигурация (Netplan/Ubuntu)
```yaml
# /etc/netplan/01-bond-vlan.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0: {}
    enp3s1: {}
  bonds:
    bond0:
      interfaces: [enp3s0, enp3s1]
      parameters:
        mode: 802.3ad
        mii-monitor-interval: 100
        transmit-hash-policy: layer3+4
        lacp-rate: fast
  vlans:
    bond0.10:
      id: 10
      link: bond0
      addresses: [192.168.10.1/24]
    bond0.20:
      id: 20
      link: bond0
      addresses: [192.168.20.1/24]
```
Применить: `sudo netplan apply`

#### Персистентная конфигурация (systemd-networkd)
```ini
# /etc/systemd/network/10-bond0.netdev
[NetDev]
Name=bond0
Kind=bond

[Bond]
Mode=802.3ad
MIIMonitorSec=100
LACPTransmitRate=fast
TransmitHashPolicy=layer3+4

# /etc/systemd/network/10-bond0-slave-eth1.network
[Match]
Name=eth1

[Network]
Bond=bond0

# /etc/systemd/network/10-bond0-slave-eth2.network
[Match]
Name=eth2

[Network]
Bond=bond0

# /etc/systemd/network/11-bond0.network
[Match]
Name=bond0

[Network]
DHCP=no

# /etc/systemd/network/12-bond0.10.netdev
[NetDev]
Name=bond0.10
Kind=vlan

[VLAN]
Id=10

# /etc/systemd/network/12-bond0.10.network
[Match]
Name=bond0.10

[Network]
Address=192.168.10.1/24
```

#### Ожидаемый результат (Validation)
```bash
# Проверка статуса агрегата
cat /proc/net/bonding/bond0 | head -10
# → Bonding Mode: IEEE 802.3ad
# → MII Status: up
# → MII Polling Interval: 100
# → Down-to-up failures: 0

# Проверка VLAN-интерфейсов
ip addr show bond0.10
# → inet 192.168.10.1/24

# Пинг между VLAN
ping -c 3 192.168.20.100
# → 0% packet loss
```

#### Особые случаи (Edge Cases)
- **Одиночный поток не использует все линки:** один TCP-соединение ограничено скоростью одного физического порта (см. **[Агрегация каналов](../link_aggregation.md)**). Для параллельных потоков трафик распределяется по хешу.
- **LACP и STP конфликт:** при включённом STP на коммутаторе LACP-агрегат может работать нестабильно. Убедитесь, что STP настроен на всех участниках LACP-группы.
- **MTU на bond0:** при использовании jumbo frames установите одинаковый MTU на всех участниках: `ip link set bond0 mtu 9000`.

#### Очистка (Cleanup)
```bash
# Удаление VLAN-интерфейсов
sudo ip link set bond0.10 down
sudo ip link set bond0.20 down
sudo ip link delete bond0.10
sudo ip link delete bond0.20

# Распрыгивание bond0
sudo ip link set bond0 down
sudo ip link set eth1 nomaster
sudo ip link set eth2 nomaster
sudo ip link delete bond0
sudo rmmod bonding
```

---

### Сценарий 7: MACVLAN — изоляция на уровне хоста

**Задача:** Создать изолированный виртуальный сетевой интерфейс с собственным MAC-адресом для запуска контейнеров или ВМ с прямой видимостью в физической сети.

#### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (kernel 3.10+ для macvlan) |
| **Утилиты** | iproute2 (`ip`) |
| **Права** | root (sudo) |
| **Интерфейс** | `eth0` — физический или виртуальный uplink |
| **Порт коммутатора** | должен разрешать несколько MAC-адресов на порт (иначе — Port Security блокирует) |

#### Конфигурация (iproute2)
```bash
# 1. Создание macvlan-интерфейса в режиме bridge
#    Режимы: bridge (по умолчанию), vepa, private, passthru
sudo ip link add link eth0 name macv-eth0 type macvlan mode bridge

# 2. Назначение IP-адреса и активация
sudo ip addr add 192.168.1.201/24 dev macv-eth0
sudo ip link set macv-eth0 up

# 3. Проверка созданного интерфейса
ip link show macv-eth0
# → macv-eth0@eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
# → link/bridge 00:11:22:33:44:55 brd
```

#### Docker macvlan (кросс-домен с Docker)
Для контейнеров Docker используйте встроенный драйвер macvlan:

```bash
# 1. Создание сети macvlan в Docker
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  my_macvlan_net

# 2. Запуск контейнера с собственным IP в физической сети
docker run -d --name app \
  --network my_macvlan_net \
  --ip 192.168.1.55 \
  nginx:alpine
```

Подробнее: **[Сетевой драйвер macvlan](../../../Docker/Docker_network/drivers/macvlan.md)**

#### Host-to-Container communication (Shim Interface)
Ядро Linux запрещает родительскому интерфейсу (`eth0`) общаться с дочерними `macvlan`-интерфейсами. Для решения создают shim-интерфейс:

```bash
# 1. Создание shim-интерфейса
sudo ip link add macv-shim link eth0 type macvlan mode bridge

# 2. Настройка IP и маршрутов
sudo ip addr add 192.168.1.200/32 dev macv-shim
sudo ip link set macv-shim up
sudo ip route add 192.168.1.55/32 dev macv-shim
```

#### Ожидаемый результат (Validation)
```bash
# Проверка выделенного MAC-адреса
ip link show macv-eth0
# → link/bridge 00:11:22:33:44:55

# Пинг с хоста через macvlan
ping -I macv-eth0 -c 3 192.168.1.1
# → 0% packet loss

# Проверка ARP-записей
arp -a | grep 192.168.1.55
# → (192.168.1.55) at 00:11:22:33:44:55 [ether] on macv-eth0
```

#### Особые случаи (Edge Cases)
- **Wi-Fi ограничения:** macvlan почти не работает с Wi-Fi-адаптерами (IEEE 802.11 ограничивает количество MAC на одну ассоциацию).
- **Port Security на коммутаторе:** если включена Port Security с лимитом 1 MAC на порт, macvlan-интерфейсы будут заблокированы. Отключите Port Security или увеличьте лимит.
- **Режим private:** контейнеры на одном хосте в режиме `private` не могут напрямую общаться. Используйте режим `bridge` для межконтейнерного взаимодействия.
- **VEPA режим:** все трафик (даже между контейнерами одного хоста) отправляется на физический коммутатор. Требует поддержки режима hairpin на коммутаторе.

#### Очистка (Cleanup)
```bash
# Удаление macvlan-интерфейса
sudo ip link set macv-eth0 down
sudo ip link delete macv-eth0 type macvlan

# Удаление shim-интерфейса
sudo ip link set macv-shim down
sudo ip link delete macv-shim type macvlan

# Удаление маршрута
sudo ip route del 192.168.1.55/32 dev macv-shim
```

---

### Сценарий 8: VLAN-aware Bridge с STP и оптимизацией

**Задача:** Создать VLAN-aware Bridge с включённым STP, настроить trunk и access порты, и оптимизировать параметры для production-среды.

#### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (kernel 3.8+) |
| **Утилиты** | iproute2 (`ip`, `bridge`) |
| **Права** | root (sudo) |
| **Интерфейсы** | `eth0` — uplink (trunk); `vnet0`, `vnet1` — интерфейсы ВМ |

#### Конфигурация
```bash
# 1. Создание моста с VLAN filtering и STP
sudo ip link add name br0 type bridge vlan_filtering 1
sudo ip link set br0 type bridge stp_state 1
sudo ip link set br0 type bridge priority 4096
sudo ip link set eth0 master br0

# 2. Настройка eth0 как Trunk (VLAN 10, 20, 999 Native)
sudo bridge vlan add dev eth0 vid 10
sudo bridge vlan add dev eth0 vid 20
sudo bridge vlan add dev eth0 vid 999
# Удаление VLAN 1 (по умолчанию) для безопасности
sudo bridge vlan del dev eth0 vid 1
sudo bridge vlan add dev eth0 vid 999 pvid untagged  # Native VLAN

# 3. Настройка vnet0 как Access-порт в VLAN 10
sudo bridge vlan add dev vnet0 vid 10 pvid untagged

# 4. Настройка vnet1 как Access-порт в VLAN 20
sudo bridge vlan add dev vnet1 vid 20 pvid untagged

# 5. Настройка портов как Edge (аналог PortFast для мгновенного перехода в Forwarding)
sudo bridge link set dev eth0 edgeport off   # Uplink не Edge
sudo bridge link set dev vnet0 edgeport on   # VM-порты Edge
sudo bridge link set dev vnet1 edgeport on

# 6. Активация моста
sudo ip link set br0 up
```

#### Ожидаемый результат (Validation)
```bash
# Проверка конфигурации VLAN на портах
bridge vlan show
# → port    vlan ids
# → eth0    10 20 999 pvid untagged
# → vnet0   10 PVID Egress Untagged
# → vnet1   20 PVID Egress Untagged

# Проверка STP
bridge link show
# → 1: eth0 state forwarding priority 32 cost 4
# → 2: vnet0 state forwarding priority 32 cost 50
# → 3: vnet1 state forwarding priority 32 cost 50

# Проверка маршрута моста
ip link show br0
# → bridge vlan_filtering 1 stp_state 1 priority 4096
```

#### Особые случаи (Edge Cases)
- **Bridge Priority и выбор Root Bridge:** в топологии из нескольких мостов выбирайте наименьший приоритет на том узле, который должен быть Root Bridge: `sudo ip link set br0 type bridge priority 0`.
- **Forward Delay:** стандартное значение 1500 (сек * 100) может быть слишком длинным. Уменьшите для более быстрой сходимости: `sudo ip link set br0 type bridge forward_delay 400`.
- **Max Age:** время жизни BPDU (по умолчанию 20 сек). При нестабильном линке уменьшите: `sudo ip link set br0 type bridge max_age 600`.
- **VLAN 1 по умолчанию:** всегда удаляйте VLAN 1 с trunk-портов для предотвращения утечки сервисного трафика.

#### Очистка (Cleanup)
```bash
# Отключение STP и удаление VLAN
sudo bridge vlan del dev eth0 vid 10
sudo bridge vlan del dev eth0 vid 20
sudo bridge vlan del dev eth0 vid 999 pvid untagged
sudo bridge vlan del dev vnet0 vid 10 pvid untagged
sudo bridge vlan del dev vnet1 vid 20 pvid untagged

# Отключение Edge портов
sudo bridge link set dev vnet0 edgeport off
sudo bridge link set dev vnet1 edgeport off

# Удаление портов из моста
sudo ip link set eth0 nomaster
sudo ip link set vnet0 nomaster
sudo ip link set vnet1 nomaster

# Удаление моста
sudo ip link set br0 down
sudo ip link delete br0 type bridge
```

---

### Сценарий 9: Production incident response — MAC flapping, broadcast storm, native VLAN mismatch

**Задача:** Диагностика и устранение типовых production-инцидентов на уровне L2 без доступа к коммутатору (только с хоста Linux).

#### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (любой современный дистрибутив) |
| **Утилиты** | iproute2, tcpdump, ethtool, arpwatch |
| **Права** | root (sudo) |
| **Сеть** | Хост подключён к trunk-порту (доступен tagged трафик нескольких VLAN) |

#### Инцедент 1: MAC flapping (MAC перемещается между портами)

**Симптомы:** Пинги падают на 5–30%, логи коммутатора содержат `MAC_MOVE` или `Host flapping`.

```bash
# 1. Непрерывный мониторинг FDB на мосте (Linux)
watch -n 2 'bridge fdb show | grep "00:11:22:33:44:55"'

# 2. Если доступен только trunk-интерфейс (без моста) — захват в реальном времени
sudo tcpdump -i eth0 -e -n 'ether host 00:11:22:33:44:55' &
# Подождите 30 секунд, остановите Ctrl+C
# Если MAC виден на разных ingress портах — потенциальная петля

# 3. Проверка на Linux-хосте: MAC в локальном ARP
ip neigh show | grep "00:11:22:33:44:55"
# → Если MAC есть на нескольких интерфейсах — это проблема

# 4. Решение (Linux-side): принудительная очистка FDB
sudo bridge fdb flush dev br0
```

**Root cause:** петля L2, неправильный LACP (один линк в агрегате), VM с жёстко заданным MAC на разных VN, или switch spoofing.

#### Инцедент 2: Broadcast storm

**Симптомы:** CPU нагружен на 100%, `ping` таймаутит, интерфер сети растягивается на 10-20 секунд.

```bash
# 1. Быстрая диагностика: подсчёт broadcast-кадров в секунду
sudo timeout 10 tcpdump -i eth0 -n 'ether broadcast' -w /tmp/storm.pcap &
sleep 10
pkill tcpdump
mergecap /tmp/storm.pcap | head -20 | wc -l
# → Если >1000 кадров за 10 сек — broadcast storm

# 2. Определение источника по MAC
sudo tcpdump -i eth0 -e 'ether broadcast' -c 100 | \
  awk '{print $2}' | sort | uniq -c | sort -rn | head -5

# 3. Storm Control на Linux (аналог Cisco)
sudo tc qdisc replace dev eth0 clsact
sudo tc filter add dev eth0 ingress \
  protocol all flower dst_mac ff:ff:ff:ff:ff:ff \
  police rate 20mbit burst 50k drop

# 4. Проверка результата
tc -s filter show dev eth0 ingress
# → Должен виден счётчик drop
```

#### Инцедент 3: Native VLAN mismatch

**Симптомы:** Нет доступа к шлюзу, ping работает только в одну сторону, `show interfaces trunk` показывает mismatch.

```bash
# 1. Проверка нетегированного трафика на trunk-интерфейсе
sudo tcpdump -i eth0 -e -n 'not vlan' | head -10
# → Если виден нетегированный трафик, а на коммутаторе Native VLAN != 1 — mismatch

# 2. Проверка tagged трафика для Native VLAN
sudo tcpdump -i eth0 -e -n 'vlan 999' | head -10
# → Если Native VLAN = 999, нетегированный трафик должен приходить без тега

# 3. Решение: если коммутатор недоступен, на Linux можно добавить PVID
sudo bridge vlan add dev eth0 vid 999 pvid untagged
```

#### Ожидаемый результат (Validation)

| Инцедент | Диагностика | Результат |
| :--- | :--- | :--- |
| MAC flapping | `bridge fdb monitor` показывает перемещение | FDB flush решает временно; root cause → LACP/stp |
| Broadcast storm | `tcpdump broadcast` > 100 фреймов/сек | `tc police` ограничивает до 20mbit |
| Native VLAN mismatch | Трафик без тега не соответствует Native VLAN | Добавление `pvid untagged` или согласование на коммутаторе |

#### Особые случаи (Edge Cases)

- **Linux + коммутатор без доступа:** `tcpdump` на физическом интерфейсе — единственный способ увидеть теги, если `rx-vlan-offload` включён (выключайте через `ethtool -K`).
- **MAC flapping и OVS:** в Open vSwitch MAC flapping часто вызван дублирующим BR0/Bond0 (loopback через OVS бридж); проверяйте `ovs-vsctl show` на наличие двойника.
- **Storm Control и CPU:** если хост — не коммутатор, а конечный сервер, `tc police` работает на уровне ядра и может не успеть при 100G+; используйте hardware-коммутатор для rate-limiting.

#### Очистка (Cleanup)

```bash
# 1. Снятие Storm Control (tc filter)
sudo tc filter del dev eth0 ingress
sudo tc qdisc del dev eth0 clsact

# 2. Очистка FDB
sudo bridge fdb flush dev br0

# 3. Удаление PVID untagged (если был добавлен)
sudo bridge vlan del dev eth0 vid 999 pvid untagged
```

---

## Дополнительная информация

### Сравнение технологий виртуализации L2

| Технология | Изоляция | Сложность | Масштабируемость | Применение |
| :--- | :--- | :--- | :--- | :--- |
| **VLAN (802.1Q)** | Высокая | Низкая | Лимит 4094 ID | Корпоративные сети, дата-центры |
| **MACVLAN** | Экстремальная | Средняя | Требует поддержки моста в NIC | Контейнеры (Docker), legacy-приложения |
| **VXLAN** | Экстремальная | Высокая | 16 млн ID (через L3 сеть) | Облачные среды, ЦОД масштабирование |
| **Bonding (LACP)** | Нет (агрегат) | Средняя | Зависит от количества портов | Отказоустойчивость каналов |
| **Q-in-Q (802.1ad)** | Высокая | Средняя | 4094 × 4094 комбинаций | Провайдеры, мультитенантность |

### Лучшие практики (Best Practices)

1.  **Принцип «один VLAN = одна подсеть»:** упрощает маршрутизацию, настройку фаервола и диагностику (трафик всегда идёт через шлюз).
2.  **VLAN Pruning:** на trunk-портах разрешайте только необходимые VLAN (`bridge vlan add ... vid 10,20`), чтобы ограничить broadcast-трафик.
3.  **Изоляция Native VLAN:** смещайте Native VLAN с ID 1 на неиспользуемый (например, 999), используйте принудительное тегирование.
4.  **Отключение DTP:** на всех портах используйте `switchport nonegotiate` для предотвращения атаки типа Switch Spoofing.
5.  **Port Security:** на access-портах ограничивайте количество MAC-адресов.
6.  **Black Hole VLAN:** неиспользуемые порты переводите в `shutdown` и назначайте в немаршрутизируемую VLAN (например, ID 999).
7.  **BPDU Guard:** обязательная функция на access-портах для предотвращения подключения посторонних коммутаторов.
8.  **STP:** включайте на мостах с избыточной топологией, используйте RSTP/MSTP вместо классического STP.
9.  **Аппаратный offload:** при высокой нагрузке используйте `tx-vlan-offload`/`rx-vlan-offload` для снижения нагрузки на CPU.
10. **Storm Control:** на access-портах ограничивайте broadcast/multicast до 1–2% для предотвращения broadcast storm (см. **[Жёсткая защита L2](../../Protocols/VLAN/vlan_security_hardening.md)**).
11. **DHCP Snooping + DAI:** на access-портах всегда включайте DHCP Snooping (untrusted) и DAI для предотвращения ARP-спуфинга и Rogue DHCP (см. **[Безопасность портов](../../Protocols/VLAN/vlan_dtp_security.md)**).
12. **VLAN Design Matrix:** все VLAN должны быть зарегистрированы в едином реестре (NetBox/IPAM) с указанием subnet, назначения и security policy (см. **[Проектирование VLAN](../../Concepts/vlan_l2_switching/vlan_design_patterns.md)**).

### Очистка всей конфигурации (Cleanup Summary)

При удалении всех настроек VLAN и мостов выполните в порядке:

```bash
# 1. Удаление всех VLAN-интерфейсов
for iface in $(ip -o link show | grep -oP '\S+\.\K\d+' | sort -u); do
  sudo ip link set "eth0.$iface" down
  sudo ip link delete "eth0.$iface" type vlan id "$iface"
done

# 2. Отключение STP и удаление портов из моста
sudo ip link set br0 type bridge stp_state 0
for port in $(ip -o link show master br0 | awk '{print $2}' | sed 's/://'); do
  sudo ip link set "$port" nomaster
done

# 3. Удаление моста и bond-интерфейсов
sudo ip link set br0 down
sudo ip link delete br0 type bridge
sudo ip link set bond0 down
sudo ip link delete bond0
sudo rmmod bonding
```

### Связанные документы

- **[VLAN: Определения и концепции](./definitions_and_concepts.md)** — теоретическая база, термины и алгоритм работы коммутатора.
- **[VLAN — обзор](../../Protocols/vlan.md)** — типы портов, диапазоны VLAN ID, VTP.
- **[Формат кадра 802.1Q](../../Protocols/VLAN/vlan_8021q_frame.md)** — структура и поля тега.
- **[Безопасность портов и VLAN Hopping](../../Protocols/VLAN/vlan_dtp_security.md)** — DTP, Port Security, MAC Flooding.
- **[VLAN в Linux: механизмы и диагностика](../../Protocols/VLAN/vlan_linux_diagnostics.md)** — SSoT по инструментам отладки и типовым проблемам.
- **[Меж-VLAN маршрутизация](../../Protocols/VLAN/vlan_inter_vlan_routing.md)** — Router-on-a-Stick, SVI, Routed Port.
- **[Trunk и Native VLAN](../../Protocols/VLAN/vlan_trunk_native.md)** — работа магистральных портов, Native VLAN.
- **[STP (Spanning Tree Protocol)](../../Protocols/stp.md)** — предотвращение петел, роли портов, диагностика.
- **[Агрегация каналов (Link Aggregation)](../link_aggregation.md)** — LACP, Bonding, политики хеширования.
- **[Linux Bridge](../../../Linux/Networking/Concepts/linux_bridge.md)** — архитектура и возможности мостов в Linux.
- **[Сетевой драйвер macvlan](../../../Docker/Docker_network/drivers/macvlan.md)** — использование в контейнерах.
- **[QoS и приоритизация L2](../qos.md#уровень-l2-data-link)** — управление очередями и PCP-метки.
- **[MAC-адрес](../mac_address.md)** — структура, типы адресации, управление в Linux.
- **[Наблюдаемость VLAN](../../Protocols/VLAN/vlan_monitoring.md)** — SNMP, NetFlow, Prometheus, Linux-мониторинг.
- **[Жёсткая защита L2](../../Protocols/VLAN/vlan_security_hardening.md)** — DHCP Snooping, DAI, IPSG, BPDU Guard, Storm Control.
- **[Проектирование VLAN: production-ready топологии](./vlan_design_patterns.md)** — Enterprise Campus, PVLAN, Leaf-Spine, QoS marking, production checklist.

### См. также

- **[Канальный уровень (L2) — OSI модель](../../OSI_TCP_IP_Model/data_link_layer.md)** — основы Ethernet, MAC-адреса, методы коммутации.
- **[VLAN — обзор](../../Protocols/vlan.md)** — общие принципы сегментации и типы расширений (QinQ, PVLAN).
