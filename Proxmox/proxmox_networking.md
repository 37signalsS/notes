# Сетевые технологии Proxmox

## Определения

**Proxmox Networking** — подсистема управления сетевыми ресурсами Proxmox Virtual Environment (PVE), построенная на базе стандартного стека Linux (Bridge, VLAN, Bonding) и расширенная возможностями программно-определяемых сетей (SDN).

**SDN (Software-Defined Networking)** — технология виртуализации сети, позволяющая создавать сложные топологии (зоны, виртуальные сети) поверх физической инфраструктуры без изменения конфигурации коммутаторов. Подробнее: **[Обзор SDN](../Networking/Concepts/sdn/sdn_overview.md)**.

**Linux Bridge** — программная реализация коммутатора (L2), позволяющая виртуальным машинам и контейнерам взаимодействовать друг с другом и с внешней сетью.

**ifupdown2** — менеджер сетевой конфигурации, работающий с файлом `/etc/network/interfaces`. Устанавливается по умолчанию с PVE 7.0, позволяет применять изменения сети без перезагрузки узла.

## Основные концепции

### Модели сетевого взаимодействия

1. **Bridged (Мостовая)**: Основная модель. Виртуальные интерфейсы подключаются к `vmbr0` (аналог виртуального коммутатора). VM получают IP-адреса из физической сети и ведут себя как устройства, напрямую подключенные к коммутатору — сеть видит уникальный MAC каждой VM, хотя физический кабель один.
2. **Routed (Маршрутизируемая)**: Хост выступает маршрутизатором (L3), весь трафик VM выходит через единственный MAC-адрес хоста. Позволяет обойти ограничения хостинг-провайдеров, блокирующих несколько MAC-адресов на одном порту.
3. **Masquerading (NAT)**: Внутренняя частная сеть для ресурсов PVE, скрытая за IP-адресом хоста. Используется при дефиците публичных адресов; для входящего доступа к VM требуется Port Forwarding.

### Файл конфигурации сети и применение изменений

Вся сетевая конфигурация узла хранится в `/etc/network/interfaces` (формат `interfaces(5)`), применяется стеком `ifupdown2`.

- **Staging-файл**: PVE не пишет напрямую в `/etc/network/interfaces`. GUI создает промежуточный файл `/etc/network/interfaces.new`, изменения применяются кнопкой **Apply Configuration** — это защищает от потери доступа к узлу при ошибке.
- **Live-Reload**: ручные правки применяются командой `ifreload -a` — вычисляется разница между текущим состоянием и файлом, применяются только изменения (безопаснее, чем `ifup`/`ifdown`).
- **pvenetcommit**: при перезагрузке узла systemd-сервис активирует staging-файл `interfaces.new` до поднятия сети.
- **Осторожно с ifup/ifdown**: классические команды при `ifdown vmbrX` прерывают трафик всех гостей, а при повторном `ifup` они не переподключаются.

**Именование интерфейсов** — systemd Predictable Network Interface Names: `eno1` (on-board), `enp3s0f1` (PCI bus 3, slot 0, function 1). VLAN-под-интерфейсы обозначаются точкой: `eno1.50`, `bond1.30`. Типы интерфейсов Linux: **[Сетевые интерфейсы в Linux](../Linux/Networking/Concepts/linux_network_interfaces.md)**.

### Агрегация каналов (Bonding)

Объединение нескольких физических интерфейсов в один логический (`bond0`) для отказоустойчивости и повышения пропускной способности.
- **802.3ad (LACP)**: Рекомендуемый режим для продакшена. Требует поддержки со стороны физического коммутатора.
- **Active-Backup**: Простейший режим отказоустойчивости, не требующий настройки коммутатора. Активный интерфейс задается через `bond-primary`.
- **Прочие режимы**: `balance-rr`, `balance-xor`, `broadcast`, `balance-tlb`, `balance-alb`.

Полное описание режимов и тюнинга: **[Агрегация каналов (Bonding)](../Networking/Concepts/link_aggregation.md)**.

### VLAN (IEEE 802.1q)

Два способа настройки:

1. **Традиционный (VLAN-под-интерфейсы)**: тег в имени устройства (`eno1.50`, `bond0.5`), на под-интерфейс ставится мост `vmbr0v5`.
2. **VLAN-aware мост** (`bridge-vlan-aware yes`): на физическом мосте включается VLAN-фильтрация, тег назначается отдельной VM/LXC (поле VLAN Tag в GUI). Позволяет использовать до 4094 VLAN на одном мосте.

Рекомендация: настраивать VLAN на интерфейсе с наименьшим числом абстракций до физической карты (NIC → Bond → Bridge).

### Программно-определяемые сети (SDN)

В PVE 8.x/9.x SDN является встроенным функционалом, позволяющим автоматизировать настройку сетей в кластере. Начиная с PVE 8.1 SDN входит в основной пакет `pve-manager`.

- **Zones (Зоны)**: Границы вещания (L2 сегментация).
  - **Simple**: Локальные сети в рамках одной ноды.
  - **VLAN**: Стандартная сегментация 802.1Q.
  - **QinQ**: Двойная инкапсуляция 802.1ad (операторский + клиентский VLAN).
  - **VXLAN**: Создание L2 оверлея поверх L3 сети. Идеально для растянутых кластеров.
  - **EVPN**: Использование протокола BGP для управления MAC-адресами в VXLAN сетях.
- **VNET (Virtual Network)**: Виртуальный коммутатор, к которому подключаются сетевые карты VM/LXC.
- **IPAM (IP Address Management)**: Встроенное управление диапазонами адресов (поддержка внутренних PVE-диапазонов, Netbox, phpIPAM).

**Расположение конфигурации**: SDN хранится в `/etc/pve/sdn/` (общий для кластера каталог, синхронизируется через pmxcfs) и транслируется в конфигурации `ifupdown2` и FRR. В конце `/etc/network/interfaces` на всех нодах должна присутствовать директива:

```text
source /etc/network/interfaces.d/*
```

### SDN Fabrics (Open Fabric)

Технология автоматической настройки Mesh-сетей: маршруты между нодами для трафика Ceph, миграции и SDN прокладываются автоматически без ручной настройки BGP.

**Протоколы фабрик (PVE 9.x):**

- **OpenFabric**: протокол фабрики на основе **OpenFabric** (упрощенный IS-IS).
- **OSPF**: маршрутизация между нодами; в PVE 9.2 добавлена route redistribution.
- **WireGuard** (PVE 9.2): зашифрованные туннели node-to-node; безопасный underlay для VXLAN, миграций и кросс-кластерных соединений.
- **BGP** (PVE 9.2): eBGP unnumbered underlay — каждая нода получает уникальный ASN и пирится по физическим интерфейсам без IP-адресов.

**Фильтрация и контроль маршрутов (PVE 9.2):**

- **Route maps и prefix lists** для BGP/EVPN: контроль того, какие префиксы принимаются и анонсируются.
- **IPv6 underlay** для EVPN и поддержка нескольких EVPN-контроллеров на кластер.
- **Dry-run**: проверка SDN-конфигурации до применения.

**Статус**: фабрики появились в PVE 9.0 как техническое превью, в PVE 9.1 — бета, в PVE 9.2 протоколы WireGuard/BGP стали стабильными.

## Практические сценарии

### Создание LACP-бонда и моста через CLI

Конфигурация в `/etc/network/interfaces` с использованием `ifupdown2`.

```bash
# Пример конфигурации Bonding + Bridge
cat <<EOF >> /etc/network/interfaces

auto bond0
iface bond0 inet manual
    bond-slaves enp1s0 enp2s0
    bond-miimon 100
    bond-mode 802.3ad
    bond-xmit-hash-policy layer3+4

auto vmbr0
iface vmbr0 inet static
    address 192.168.1.10/24
    gateway 192.168.1.1
    bridge-ports bond0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
EOF

# Применение конфигурации
ifreload -a
# → Exit code: 0
```

### Настройка VLAN на мосте

Пример из официального руководства: адрес управления узла в VLAN 5, гости — в нетеганом VLAN по умолчанию.

```text
# VLAN-aware мост (рекомендуемый способ)
auto lo
iface lo inet loopback
iface eno1 inet manual

auto vmbr0.5
iface vmbr0.5 inet static
    address 10.10.10.2/24
    gateway 10.10.10.1

auto vmbr0
iface vmbr0 inet manual
    bridge-ports eno1
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-vids 2-4094
```

Традиционный способ — через VLAN-под-интерфейс и отдельный мост:

```text
auto vmbr0v5
iface vmbr0v5 inet static
    address 10.10.10.2/24
    gateway 10.10.10.1
    bridge-ports eno1.5
    bridge-stp off
    bridge-fd 0
```

### Настройка VXLAN в SDN

1. **Создание зоны**: `Datacenter -> SDN -> Zones -> Add -> VXLAN`. Указать ID и список IP-адресов нод-пиров.
2. **Создание VNET**: Привязать VNET к созданной VXLAN зоне.
3. **Применение**: Нажать кнопку **Apply** в разделе SDN. Это создаст необходимые интерфейсы на всех нодах кластера.

В PVE 9.2 перед применением доступна проверка **dry-run**, позволяющая увидеть изменения конфигурации до их применения.

### Маршрутизируемая модель (Routed)

Сценарий хостинга: публичный IP хоста (198.51.100.5/29) и отдельный блок адресов для VM (203.0.113.16/28). Мост `vmbr0` без физических портов, адрес — первый usable адрес блока (сетевой адрес блока присваивать нельзя).

```text
auto eno0
iface eno0 inet static
    address 198.51.100.5/29
    gateway 198.51.100.1
    post-up echo 1 > /proc/sys/net/ipv4/ip_forward
    post-up echo 1 > /proc/sys/net/ipv4/conf/eno0/proxy_arp

auto vmbr0
iface vmbr0 inet static
    address 203.0.113.17/28
    bridge-ports none
    bridge-stp off
    bridge-fd 0
```

### NAT (Masquerading)

Внутренняя сеть `10.10.10.0/24` скрывается за публичным IP хоста через iptables.

```text
auto eno1
# реальный IP-адрес
iface eno1 inet static
    address 198.51.100.5/24
    gateway 198.51.100.1

auto vmbr0
# частная подсеть
iface vmbr0 inet static
    address 10.10.10.1/24
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    post-up echo 1 > /proc/sys/net/ipv4/ip_forward
    post-up iptables -t nat -A POSTROUTING -s '10.10.10.0/24' -o eno1 -j MASQUERADE
    post-down iptables -t nat -D POSTROUTING -s '10.10.10.0/24' -o eno1 -j MASQUERADE
```

*Примечание: при включенном сетевом firewall PVE могут потребоваться conntrack-зоны для исходящих соединений VM:*

```text
post-up iptables -t raw -I PREROUTING -i fwbr+ -j CT --zone 1
post-down iptables -t raw -D PREROUTING -i fwbr+ -j CT --zone 1
```

## Диагностика

### Проверка состояния SDN и портов

Просмотр туннелей VXLAN:

```bash
ip -d link show type vxlan
# → 12: vxlan_sdn: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 ...
# → vxlan id 100 local 10.0.0.1 dev enp1s0 remote 10.0.0.2 dstport 4789
```

Просмотр мостов и портов:

```bash
bridge link show
# → 15: veth101i0@if2 state UP @vmbr0 ...
# → 12: vxlan_sdn state UP @vmbr0 ...
```

Проверка таблицы MAC-адресов:

```bash
bridge fdb show dev vmbr0
# → 00:16:3e:a1:b2:c3 vlan 1 master vmbr0 permanent
# → a0:b1:c2:d3:e4:f5 self master vmbr0
```

### Общая диагностика сети

```bash
ip link show
# → 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 ...
# → 2: eno1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...

ip -s link show bond0
# → показывает статистику передач/ошибок по линкам бонда

ip route show
# → default via 192.168.1.1 dev vmbr0
# → 192.168.1.0/24 dev vmbr0 proto kernel scope link src 192.168.1.10
```

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [Архитектура SDN](../Networking/Concepts/sdn/sdn_overview.md)
- [Технология VXLAN](../Networking/Tunnels/vxlan.md)
- [Proxmox Service Discovery](./proxmox_service_discovery.md) — автоматическое обнаружение VM через DNS
