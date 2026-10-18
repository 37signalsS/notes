# Сетевые технологии Proxmox

**Актуально для:** Proxmox VE 8.4 / 9.2 (SDN core fully supported; IPAM/DHCP и FRR-интеграция — tech preview; WireGuard/BGP fabrics — с 9.2)

## Определения

**Proxmox Networking** — подсистема управления сетью PVE: стек Linux (Bridge, VLAN, Bonding, ifupdown2) плюс SDN (зоны, VNet, IPAM, Fabrics).

**SDN (Software-Defined Networking)** — виртуализация сетевых топологий (зоны, VNets) поверх физической инфраструктуры без правки коммутаторов. Обзор теории: [SDN](../Networking/Concepts/sdn/sdn_overview.md).

**Linux Bridge** — программный коммутатор L2 для VM/LXC. Глубина: [Linux Bridge](../Linux/Networking/Concepts/linux_bridge.md).

**ifupdown2** — менеджер `/etc/network/interfaces` (по умолчанию с PVE 7). Понимает зависимости (мост поверх bond, VLAN-aware), умеет `ifreload` без перезагрузки узла. SSoT: [ifupdown2 / Debian interfaces](../Linux/Networking/Settings/Persistent_Network/debian_ubuntu_interfaces.md).

**pvesh** — CLI к REST API PVE; эквивалент GUI. Пути API — под `/cluster/sdn/...` и `/nodes/<node>/network`.

**FRR (Free Range Routing)** — BGP/OSPF/IS-IS, генерируемый PVE для SDN Fabrics и EVPN. Конфиги — в `/etc/frr/` (правка вручную конфликтует с SDN-apply).

**Open vSwitch (OVS)** — программный коммутатор L2/L3 (OpenFlow, VXLAN, Geneve). Backend для OVN/SDN и альтернатива Linux Bridge.

**OVN (Open Virtual Network)** — логический слой поверх OVS (адресация, ACL, NAT) в современных SDN-зонах PVE.

**dnsmasq** — backend автоматического DHCP для SDN (только Simple-зоны). Плагин создаёт `dnsmasq@<zone>`; штатный экземпляр отключают. SSoT: [dnsmasq](../Networking/Protocols/DNS/dnsmasq.md).

**VNet Firewall** — правила на уровне SDN VNet (`/etc/pve/sdn/firewall/<vnet>.fw`), направление `forward`; работают с nftables-based `proxmox-firewall`, не со старым `pve-firewall`. Подробнее: [Firewall](./proxmox_firewall_advanced.md).

**macvlan** — несколько MAC на одном NIC. Для VM в PVE используется реже bridge; для LXC — `link=` + `type=macvlan`. Не даёт L2-связь между такими интерфейсами на одном хосте.

**ipvlan** — общий MAC родителя, разделение по L2/L3 ID. Полезен, когда коммутатор режет MAC на порту.

**SR-IOV** — виртуальные функции NIC (VF) в VM как PCI-устройства near-native. Настройка — через `hostpci` / passthrough SSoT, не через virtio-net. См. [PCI passthrough](./proxmox_pci_passthrough.md), [SR-IOV](../Networking/Concepts/dpdk/sriov_setup.md).

**TUN/TAP / veth** — L3/L2-виртуальные устройства; LXC подключается veth-парами к мосту (`vethXXXi0` в контейнере, `vethXXXi1` на мосту).

**Conntrack** — отслеживание соединений (stateful firewall, NAT). При высоких нагрузках — тюнинг `nf_conntrack_*` (см. «Граничные случаи»).

**pvenetcommit** — systemd-сервис: при загрузке активирует `/etc/network/interfaces.new`, если GUI-изменения не были применены online.

**Fabrics (PVE 9+)** — автоматическая настройка underlay-маршрутизации между нодами (OpenFabric/OSPF/WireGuard/BGP). Статус: tech preview; WireGuard и BGP-протоколы — с PVE 9.2.

## Основные концепции

### Модели взаимодействия

1. **Bridged** — основная модель: гости на `vmbr0`, MAC видны коммутатору.
2. **Routed (L3)** — хост-маршрутизатор, единый MAC хоста наружу; обход «один MAC на порту» у хостеров.
3. **Masquerading (NAT)** — частная сеть за IP хоста; вход — port forward или SDN SNAT.

### Файл сети и применение изменений

Конфигурация узла — `/etc/network/interfaces` (interfaces(5)), применяется ifupdown2.

- **Staging**: GUI пишет `/etc/network/interfaces.new`; **Apply Configuration** — атомарное применение (защита от потери SSH).
- **Live-reload**: ручные правки — `ifreload -a` (diff-based; безопаснее, чем `ifup`/`ifdown`).
- **Dry-run**: `ifreload -a -n` (или `ifreload -dn`) — показать, что изменится, без применения.
- **Осторожно**: `ifdown vmbrX` рвёт трафик всех гостей на мосте; последующий `ifup` не «вернёт» их автоматически. Для одного порта: `ifreload -i <iface>`.
- **pvenetcommit** — страховка при перезагрузке, если Apply не был нажат.

Именование — Predictable Network Interface Names: `eno1`, `enp3s0f1`; VLAN-поды: `eno1.50`. Типы интерфейсов: [Linux interfaces](../Linux/Networking/Concepts/linux_network_interfaces.md). В PVE 9+ есть `pve-network-interface-pinning` (фиксация интерфейсов к слотам) — при смене NIC/слотов порядка.

### Bonding (LACP)

Объединение NIC в `bond0`: отказоустойчивость + пропускная способность. Режимы и теория: [Link aggregation](../Networking/Concepts/link_aggregation.md).

- **802.3ad (LACP)** — продакшен; коммутатор должен поддерживать LACP.
- **Active-backup** — без настройки коммутатора; `bond-primary` задаёт активный слейв.

**Безопасное создание bond в GUI** (Apply только один, в конце):

1. Открыть `vmbr0`, убрать физический порт из Bridge Ports (**не** Apply).
2. Network → Create → Linux Bond: `bond0`, slave-порты (один коммутатор), режим, для active-backup — Primary.
3. В `vmbr0` вернуть в Bridge Ports `bond0`.
4. Apply Configuration.

**CLI-эквивалент** (`/etc/network/interfaces`):

```text
auto bond0
iface bond0 inet manual
    bond-slaves enp1s0 enp2s0
    bond-miimon 100
    bond-mode 802.3ad
    bond-xmit-hash-policy layer3+4
    bond-lacp-rate 1

auto vmbr0
iface vmbr0 inet static
    address 192.168.1.10/24
    gateway 192.168.1.1
    bridge-ports bond0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
```

```bash
ifreload -a -n   # dry-run
ifreload -a
# → exit 0
```

**Проверка failover:** отключить основной кабель → ping идёт, порт Down/Up меняются местами. Восстанавливать в обратном порядке (сначала вернуть основной, затем гасить резерв), чтобы не остаться без связи.

### VLAN (802.1Q)

Два способа:

1. **VLAN-под-интерфейсы** — тег в имени (`eno1.50` → мост `vmbr0v5`).
2. **VLAN-aware мост** — `bridge-vlan-aware yes` на физическом мосте; тег на VM/LXC (поле VLAN Tag). До 4094 VLAN на одном мосте. Рекомендуется.

Правило: настраивайте VLAN на самом «низком» интерфейсе до NIC (NIC → Bond → Bridge).

**Коммутатор/роутер:** порт Proxmox — trunk (нужные теги); gateway/firewall — trunk + поды; access-порты — один VLAN/PVID. Теория: [Trunk / Native VLAN](../Networking/Protocols/VLAN/vlan_trunk_native.md), практика: [L2 switching](../Networking/Concepts/vlan_l2_switching/practical_scenarios.md).

**Менеджмент-сеть узла — отдельно от гостевых VLAN.** Не переносите IP хоста в гостевой VLAN. Типичный паттерн — адрес хоста на `vmbr0.5` (VLAN management), гости на нетегированном или других тегах:

```text
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

Традиционный эквивалент:

```text
auto vmbr0v5
iface vmbr0v5 inet static
    address 10.10.10.2/24
    gateway 10.10.10.1
    bridge-ports eno1.5
    bridge-stp off
    bridge-fd 0
```

**Перенос гостя между VLAN** при VLAN-aware: сменить VLAN Tag (Hardware → Network Device). DHCP-аренда обновится без перезагрузки гостя (release/renew). Перенос management-IP моста — нет.

### Отдельные сети: management / cluster / storage / guest

SRE-требование к кластеру: **не смешивать** corosync, live-migration, Ceph/NFS и гостевой трафик на одном NIC/VLAN, если это возможно.

| Сеть | Что идёт | Порты/протоколы | Рекомендация |
|------|----------|-----------------|--------------|
| Management | SSH, 8006, API, PVE-прокси | TCP 22, 8006 | Изолированный VLAN |
| Cluster | corosync | UDP 5404–5405 (и кольца) | Отдельный VLAN или выделенный bond; latency/jitter критичны — [Cluster](./proxmox_cluster.md) |
| Migration | live-migration | TCP 60000–60050 | Отдельный VLAN; иногда — dedicated `migrate` bridge |
| Storage | NFS/iSCSI/Ceph public+cluster | TCP/UDP по типу | MTU согласован; jumbo — только end-to-end |
| Guest | VM/LXC | — | VLAN-aware bridge или SDN VNet |

Пример выделенного bridge для миграций (второй NIC):

```text
iface enp2s0 inet manual

auto vmbr2
iface vmbr2 inet static
    address 10.0.2.10/24
    bridge-ports enp2s0
    bridge-stp off
    bridge-fd 0
```

В Datacenter → Migration → Network выбрать `vmbr2` (или default). Ceph public network — в [Storage](./proxmox_storage.md)/Ceph; mesh — удобно через SDN Fabrics (PVE 9+).

### MTU: underlay, VXLAN, гости

| Контекст | MTU | Комментарий |
|----------|-----|-------------|
| Физический NIC / underlay | 1500 или 9000 | Jumbo — только если **весь** путь (коммутаторы) согласован |
| QinQ | underlay − 4 | 1496 при 1500 |
| VXLAN | underlay − 50 | 1450 при 1500; overhead: VXLAN 8 + IP 20 + UDP 8 + Eth 14 |
| WireGuard (underlay для VXLAN) | underlay − 50 − 60/80 | 1370 при 1500 (IPsec-like overhead WG + VXLAN) — см. PVE SDN docs |
| VirtIO MTU в VM (PVE 9) | по умолчанию = MTU моста | Пустое поле / `mtu=1` = inherit; явно 1500 — только если нужно |

В PVE 9 VirtIO-устройства **наследуют MTU моста**, если поле пустое (как LXC). Это важно для VXLAN-VNet (мост 1450) и jumbo-мостов: проверяйте MTU внутри гостя после создания NIC.

```bash
ip link show enp1s0 | awk '{print $1,$4,$5}'
# → 2: enp1s0: ... mtu 1500 ...
ip -d link show type vxlan
# → ... mtu 1450 ... vxlan id 100 local 10.0.0.1 remote 10.0.0.2 dstport 4789
```

### Внутреннее устройство Linux Bridge (кратко)

- **FDB** — таблица MAC: `bridge fdb show dev vmbr0`.
- **Flooding** — unknown unicast/broadcast на все порты; в VXLAN ограничивается туннелями.
- **STP** — в PVE off по умолчанию (`bridge-stp off`); включать только при реальных петлях.
- **VLAN filtering** — `bridge-vlan-aware yes`; PVID порта + `bridge-vids`.

### SDN в PVE

С PVE 8.1 core SDN входит в `pve-manager`. Конфиги — `/etc/pve/sdn/` (pmxcfs, общий на кластер); транслируются в ifupdown2/FRR. В конце `/etc/network/interfaces` **обязателен**:

```text
source /etc/network/interfaces.d/*
```

Изменения — pending → атомарный **Apply** в Datacenter → SDN. Состояние — `.running-config`, `.version` в `/etc/pve/sdn`.

**Статус поддержки (актуально для PVE 9.2):**

| Слой | Статус |
|------|--------|
| Core SDN (VNet, интеграция со стеком) | fully supported |
| IPAM + DHCP для гостей | tech preview |
| Сложная маршрутизация FRR / контроллеры | tech preview |
| Fabrics (OpenFabric, OSPF, WireGuard, BGP) | tech preview; WireGuard/BGP — с 9.2 |

**Установка (opt-in):**

```bash
# апгрейд со старых версий — core
apt update && apt install libpve-network-perl

# автоматический DHCP (Simple-зоны)
apt install dnsmasq
systemctl disable --now dnsmasq

# Fabrics / EVPN / продвинутая маршрутизация
apt install frr frr-pythontools
systemctl enable frr.service
```

dnsmasq: плагин SDN управляет `dnsmasq@<zone>`, конфиги — `/etc/dnsmasq.d/<zone>/`, leases — `/var/lib/misc/dnsmasq.<zone>.leases` (не редактировать вручную).

#### Типы зон

| Тип | Механизм | Особенности |
|-----|----------|-------------|
| **Simple** | Изолированный мост; NAT/routed | Трафик локален на ноде; **единственный** тип с автоматическим DHCP |
| **VLAN** | 802.1Q поверх локального bridge/OVS | Связность гостей между нодами |
| **QinQ** | Stacked VLAN (802.1ad) | S-Tag зоны + C-Tag VNet; MTU − 4 |
| **VXLAN** | L2-оверлей UDP 4789 | VNI 24 бита; underlay своими руками; **не шифрует** — между площадками VPN |
| **EVPN** | VXLAN + BGP EVPN | L3, anycast gateway, exit-nodes; требует EVPN-контроллер (FRR) |

**Параметры зон (общие):** Nodes, IPAM (`pve` по умолчанию), DNS/ReverseDNS, DNSZone (зона должна существовать на DNS-сервере).

- **VLAN:** Bridge — существующий локальный bridge/OVS **на каждой** ноде.
- **QinQ:** Bridge VLAN-aware, Service VLAN, protocol 802.1q/802.1ad, MTU.
- **VXLAN:** Peers Address List (все ноды) или SDN Fabric; MTU.
- **EVPN:** VRF VXLAN ID, controllers, anycast MAC, exit nodes, advertise subnets, route-target import, MTU (default 1450).

#### VNet, Subnet, Options

**VNet** — после Apply становится локальным интерфейсом с тем же именем на нодах зоны:

- **ID** — до 8 символов; **Alias** — описание; **Zone**; **Tag** — VLAN/VXLAN ID.
- **VLAN Aware** — vlan-aware на VNet (гость может тегировать).
- **Isolate Ports** — гости ходят только «в мост», не гость↔гость; действует **в пределах одной ноды**; для межнодовой изоляции — VNet Firewall; требуется перезапуск гостя.

**Subnet** — CIDR внутри VNet: ограничение адресов, gateway/SNAT в L3-зонах, DHCP range, IPAM, DNS-регистрация.

- **Gateway** — в Simple/EVPN развивается на VNet.
- **SNAT** — выход наружу адресом ноды (EVPN — на exit-node’ах).
- **DHCP range** — только при настроенном gateway; только Simple + dnsmasq.
- **DNS Zone Prefix** — префикс домена при регистрации.

**Options** (Datacenter → SDN): Controllers (EVPN), DHCP (dnsmasq), IPAM (pve / NetBox / phpIPAM), DNS.

#### SNAT: поток

Внешний шлюз не знает подсеть SDN (например, `10.80.80.0/24`):

1. VM `10.80.80.50` → VNet → мост ноды → шлюз.
2. Ответ идёт на IP Proxmox (к нему подключён шлюз).
3. Conntrack раскрывает SNAT, пакет уходит VM.

Альтернатива без SNAT — статический маршрут `10.80.80.0/24` через IP Proxmox.

### SDN Fabrics

Автоматизация underlay между нодами (Ceph, миграции, EVPN/VXLAN peers) без ручного mesh-BGP.

| Протокол | Суть | Версия |
|----------|------|--------|
| OpenFabric | IS-IS для DC-фабрик | 9.0+ (tech preview) |
| OSPF | link-state; redistribution — с 9.2 | 9.0+ |
| WireGuard | шифрованные туннели n↔n и с внешними пирами; keys генерируются PVE; `/etc/wireguard/proxmox/` | 9.2 |
| BGP | eBGP unnumbered: ASN на ноду, пиринг по link-local без IP на линках | 9.2 |

Также в 9.2: route maps / prefix lists, IPv6 underlay для EVPN, dry-run SDN, несколько EVPN-контроллеров. Разрешения: `SDN.Audit` / `SDN.Allocate`; для записи в interfaces при обновлении fabric — `Sys.Modify` на ноде.

WireGuard fabric **не заменяет** site-to-site VPN между площадками — для «PVE ↔ интернет/другой DC» используйте [VPN](./proxmox_vpn_tunnels.md); fabric — secure underlay внутри/между нодами кластера.

### Firewall (уровни)

Полный SSoT — [Firewall Proxmox](./proxmox_firewall_advanced.md). Здесь — только архитектура уровней:

1. **Datacenter** — опции, макросы, группы, security groups.
2. **Node** (`host.fw`) — все интерфейсы узла.
3. **VM/CT** (`vm/<id>.fw`, `ct/<id>.fw`) — `netX`, options.
4. **VNet (SDN)** — forwarded-трафик; только `forward`; nftables `proxmox-firewall`.
5. **Security Groups** — переиспользуемые наборы правил.

SDN генерирует IPSets (`vnet0-all`, `vnet-no-gateway`, `vnet-dhcp`) для source/destination. Трафик гостей идёт через `fwbr+`/`fwln+` (netfilter). Старый `pve-firewall` (iptables) VNet-уровень игнорирует.

### OVS (кратко)

Для OVN/SDN и продвинутых сценариев; на одном NIC с Linux Bridge без разделения — нестабильно. Практика:

```bash
apt install openvswitch-switch
ovs-vsctl add-br ovsbr0
ovs-vsctl add-port ovsbr0 enp1s0
ovs-vsctl set port enp1s0 tag=100
ovs-vsctl show
```

В PVE-конфигурации узла OVS-мосты описываются через `ovs_type`/`ovs_ports` в `/etc/network/interfaces`; смешение «живой» ovs-vsctl и ifupdown2 без понимания порядка применения — источник инцидентов.

## Практические сценарии

### Изолированный мост без IP (пара VM)

1. Создать `vmbr1` без адреса и gateway → Apply.
2. Добавить гостям NIC на `vmbr1`.
3. В госте (Ubuntu netplan):

```yaml
# /etc/netplan/01-isolated.yaml
network:
  version: 2
  ethernets:
    ens19:
      addresses: [10.0.0.1/24]
```

```bash
sudo netplan apply
ping -c 1 10.0.0.2
# → 1 packets transmitted, 1 received, 0% packet loss
```

Связность не зависит от `ens18`. Доступ с рабочей станции — jump host (см. ниже).

### Второй физический NIC — вторая сеть

Каждый NIC → свой bridge/IP/DHCP. Переключение гостя: Hardware → Network Device → Bridge.

### Routed (хостинг, свой блок адресов)

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

Адрес моста — первый usable блока для VM, не сетевой адрес.

### NAT (masquerading) вручную

```text
auto eno1
iface eno1 inet static
    address 198.51.100.5/24
    gateway 198.51.100.1

auto vmbr0
iface vmbr0 inet static
    address 10.10.10.1/24
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    post-up echo 1 > /proc/sys/net/ipv4/ip_forward
    post-up iptables -t nat -A POSTROUTING -s 10.10.10.0/24 -o eno1 -j MASQUERADE
    post-down iptables -t nat -D POSTROUTING -s 10.10.10.0/24 -o eno1 -j MASQUERADE
```

При включённом PVE firewall гостям может понадобиться conntrack-зона:

```text
post-up iptables -t raw -I PREROUTING -i fwbr+ -j CT --zone 1
post-down iptables -t raw -D PREROUTING -i fwbr+ -j CT --zone 1
```

Предпочтительнее для новых проектов — SDN Simple + SNAT (ниже), а не голый iptables post-up.

### SDN Simple: зона + SNAT + DHCP

Пример: зона `simple`, VNet `vnet01`, subnet `10.80.80.0/24`, DHCP `.50`–`.60`.

1. Установить dnsmasq, отключить default-инстанс; проверить `source /etc/network/interfaces.d/*`.
2. Zones → Add → Simple (ноды, включить DHCP в расширенных).
3. VNets → Create: ID `vnet01`, zone `simple`.
4. Subnets → Create: `10.80.80.0/24`, gateway `10.80.80.1`, SNAT.
5. DHCP Ranges: `.50`–`.60`.
6. **SDN → Apply** (иначе status `new`).
7. Гостю: bridge `vnet01`; в госте dhcp4.

```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  ethernets:
    ens19:
      dhcp4: true
```

```bash
sudo netplan apply
ip -br a show ens19
# → ens19  UP  10.80.80.50/24 ...
ping -c 1 google.com
# → 0% packet loss
```

8. Просмотр аренд — Datacenter → SDN → IPAM; правка IP в IPAM требует renew в госте.

### Jump host к изолированным гостям

LXC с `eth0` → `vmbr0` (или management) и `eth1` → `vnet01`. SSH на jump, затем внутрь зоны. Или статик на внешнем роутере в подсеть SDN через IP Proxmox.

### VXLAN-зона (GUI)

1. Zones → Add → VXLAN: ID, Peers (все ноды) или Fabric.
2. VNet → к зоне.
3. Apply — интерфейсы на всех нодах. В PVE 9.2 — dry-run перед Apply.

### SDN через pvesh (эквивалент GUI)

```bash
# Список зон
pvesh get /cluster/sdn/zones

# Создать VXLAN-зону
pvesh create /cluster/sdn/zones \
  --type vxlan --id prod \
  --peers "10.0.0.1,10.0.0.2,10.0.0.3"

# VNet в зоне
pvesh create /cluster/sdn/vnets --vnet prod-vnet --zone prod

# Subnet (путь vnet/вложенный объект — через секцию vnets)
pvesh create /cluster/sdn/vnets/prod-vnet/subnets \
  --subnet 10.100.0.0/24 --gateway 10.100.0.1 --snat 1

# Применить pending на весь кластер (PUT /cluster/sdn)
pvesh set /cluster/sdn

# Список / удаление
pvesh get /cluster/sdn/vnets
pvesh delete /cluster/sdn/vnets/prod-vnet
```

Статус применения отслеживается в GUI SDN и через `/etc/pve/sdn/.running-config`; endpoint’ы статуса зон/фабрик развёрнуты в 9.1+ (resource tree). Не путать `PUT /cluster/sdn` (apply) с `GET /cluster/ha/status` (HA, не SDN).

### NIC гостей через CLI

```bash
# VM: hot-add NIC (если поддерживается модель/шина)
qm set 100 --net1 virtio,bridge=vmbr0,firewall=1
qm set 100 --delete net1

# multiqueue (виртуальные очереди; guest driver + queues=) — см. Performance
qm set 100 --net0 virtio,bridge=vmbr0,queues=4

# LXC
pct set 101 --net0 name=eth0,bridge=vmbr0,ip=10.0.0.10/24,gw=10.0.0.1,tag=5
pct config 101 | grep net
```

### SR-IOV NIC в VM

VF пробрасывается как PCI, не как virtio-мост:

```bash
# после включения SR-IOV на PF / в ядре — см. SSoT
qm set 101 --hostpci1 03:10.0,sriov=1
```

Детали и проверки: [PCI passthrough](./proxmox_pci_passthrough.md).

### Резерв копирования сетевой конфигурации

```bash
tar czf /var/backups/network-config-$(date +%Y%m%d).tar.gz \
  /etc/network/interfaces \
  /etc/network/interfaces.d \
  /etc/pve/sdn/ \
  /etc/frr/
```

Восстановление: распаковать, `ifreload -a`. `/etc/pve/sdn` и `/etc/pve/corosync.conf` уже реплицируются pmxcfs — бэкап нужен для cold-recovery узла.

### Откат при потере доступа

```bash
# через IPMI/console
mv /etc/network/interfaces.new /etc/network/interfaces.new.bak
ifreload -a
# если interfaces.new битый и мешает загрузке сети:
mv /etc/network/interfaces.new /etc/network/interfaces.new.broken
reboot
```

## Диагностика и устранение неполадок

### Быстрая проверка состояния

```bash
ip -br link show
bridge link show
bridge fdb show dev vmbr0
cat /proc/net/bonding/bond0
ip -d link show type vxlan
ip route show
ifreload -a -n
```

Мониторинг (Prometheus/node_exporter) — [Monitoring](./proxmox_monitoring.md): `node_network_*`, ошибки bond, alerты на flapping.

### VM без сети

| Причина | Проверка | Действие |
|---------|----------|----------|
| NIC отключён/нет в конфиге | `qm config 100 \| grep net` | `qm set 100 --net0 virtio,bridge=vmbr0` |
| Bridge не существует | `ip link show vmbr0` | Создать bridge / исправить имя |
| VLAN mismatch | `bridge vlan show`; tag в конфиге гостя | Согласовать PVID/теги |
| Firewall | `iptables-save` / nftables; `vm/<id>.fw` | [Firewall](./proxmox_firewall_advanced.md) |
| Bond без LACP на коммутаторе | `/proc/net/bonding/bond0` | LACP или active-backup |
| MTU гость ≠ мост (PVE 9 / jumbo) | `ip link` в госте и на мосте | Выставить mtu или пустое поле (inherit) |

### VXLAN не поднимается

```bash
ping -c 3 <peer>
nc -zvu <peer> 4789
iptables-save | grep 4789   # или nft list ruleset
ip -d link show type vxlan   # mtu, local/remote, state
```

MTU: underlay 1500 → VXLAN 1450; фрагментация «висит» scp/curl при завышенном MTU.

### Bond не агрегирует (LACP)

```bash
cat /proc/net/bonding/bond0
ethtool bond0 | grep -i "speed\|link"
# на коммутаторе: show lacp neighbor
```

### Дубли MAC

```bash
bridge fdb show dev vmbr0 | awk '{print $2}' | sort | uniq -d
qm config 100 | grep net0
qm set 100 --net0 virtio,bridge=vmbr0,macaddr=AA:BB:CC:DD:EE:FF
```

Клон без regen MAC → ARP flux; в PVE клон обычно меняет MAC, но проверяйте.

### SDN Apply / FRR

```bash
pvesh get /cluster/sdn/zones
cat /etc/pve/sdn/zones.cfg   # pending vs running
journalctl -u frr -n 50
for n in pve1 pve2 pve3; do ssh $n "ip -d link show type vxlan"; done
```

### Flapping / ошибки порта

```bash
ip -s link show eno1
ethtool eno1 | grep -i "speed\|duplex"
```

CRC/errors > 0 — кабель/оптика/порты; Half duplex — настройка или неавтосогласование.

### DNS узла/гостя

На Debian 12+ / PVE 8+ (systemd 252+):

```bash
resolvectl status
# устаревший systemd-resolve на этих версиях не используется
```

## Лучшие практики

1. **Сегментация**: management, cluster (corosync), migration, storage, guest — раздельные VLAN/NIC, где возможно.
2. **Имена**: `vmbr0` mgmt, `vmbr10` guest VLAN 10, `bond0`, `eno1`; без generic `br0`.
3. **Изменения по одному** + `ifreload -a -n` перед Apply; GUI Apply — только когда конфиг согласован.
4. **Бэкап** `/etc/network/interfaces`, `/etc/pve/sdn`, `/etc/frr` перед изменениями.
5. **VLAN-aware bridge** вместо леса VLAN-подов.
6. **MTU согласован** end-to-end; для PVE 9 проверяйте наследование MTU у VirtIO в гостях.
7. **Лучший wireguard/VXLAN-underlay** — SDN Fabrics (9.2), не ручной wg-quick на узлах без need.
8. **Firewall по умолчанию** для гостей; security groups; VNet firewall между сегментами SDN.
9. **Мониторинг**: dropped/CRC на bond, flapping, VXLAN, quorum/latency corosync — [Monitoring](./proxmox_monitoring.md).
10. **Change management**: maintenance mode; в PVE 9.2 — `disarm-ha` / `arm-ha` перед сменой cluster-сети без fencing ([Cluster](./proxmox_cluster.md)).

## Граничные случаи

1. **MTU mismatch VXLAN**: симптом — small packets OK, big transfers hang; лечится MTU 1450 у гостя/наследованием или PMTUD.
2. **Смешанные скорости в LACP** (1G+10G) — перегрузка медленного линка; раздельные bond’ы или active-backup.
3. **Клон VM без нового MAC** — ARP conflicts; проверять `qm config`.
4. **Старые гости без 802.1Q** — VLAN-aware + tag в NIC не работает; VLAN-под на хосте (`eno1.50`).
5. **SDN + maintenance**: сначала мигрировать гостей, потом узел; туннели к узлу рвутся.
6. **Разные ревизии NIC в bond** — разные offload; выравнивать `ethtool`.
7. **Conntrack exhaustion**: `CT table full` → `nf_conntrack_max`/`buckets` (см. [conntrack](../Linux/Networking/Concepts/conntrack_production_tuning.md)).
8. **OVS + Linux Bridge на одном NIC** — нестабильно; отдельные порты или один backend.
9. **DHCP только в Simple** и **только с gateway** на subnet — иначе `dnsmasq@zone` не отдаёт адреса.
10. **QinQ untagged VNet + jumbo**: MTU зоны может не примениться к veth-парам нетегированных VNet (Proxmox Bugzilla #8005) — проверять MTU на `ln_*`/`pr_*`.
11. **VXLAN без шифрования** — между площадками обязателен VPN; overhead WireGuard+VXLAN ≈ 110–130 байт.
12. **Jumbo на storage + VirtIO**: в PVE 9 NIC наследует MTU моста; после миграций/клонов проверять MTU в госте — иначе iSCSI/NFS «дёргается».
13. **IPv6 fabrics (OpenFabric)**: для не-full-mesh нужен глобальный `net.ipv6.conf.all.forwarding=1` (см. PVE SDN docs) — влияет на SLAAC/RA.
14. **Правка `/etc/frr` вручную** перетирается SDN-apply — все параметры — через Controllers/Fabrics GUI/API.

## Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [SDN — теория](../Networking/Concepts/sdn/sdn_overview.md)
- [Linux Bridge](../Linux/Networking/Concepts/linux_bridge.md)
- [ifupdown2 / interfaces](../Linux/Networking/Settings/Persistent_Network/debian_ubuntu_interfaces.md)
- [Bonding / LACP](../Networking/Concepts/link_aggregation.md)
- [Trunk / Native VLAN](../Networking/Protocols/VLAN/vlan_trunk_native.md) · [L2 switching](../Networking/Concepts/vlan_l2_switching/practical_scenarios.md)
- [dnsmasq](../Networking/Protocols/DNS/dnsmasq.md) · [BGP/FRR](../Networking/Protocols/bgp.md)
- [SR-IOV](../Networking/Concepts/dpdk/sriov_setup.md)
- [Firewall](./proxmox_firewall_advanced.md) · [VPN](./proxmox_vpn_tunnels.md)
- [Cluster (corosync, сети)](./proxmox_cluster.md) · [Storage / Ceph](./proxmox_storage.md)
- [Performance (multiqueue, offload)](./proxmox_performance.md) · [PCI passthrough](./proxmox_pci_passthrough.md)
- [Monitoring](./proxmox_monitoring.md) · [Security](./proxmox_security.md)
