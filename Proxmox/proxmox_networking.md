# Сетевые технологии Proxmox

**Актуально для:** Proxmox VE 8.1 / 9.x

## Определения

**Proxmox Networking** — подсистема управления сетевыми ресурсами Proxmox Virtual Environment (PVE), построенная на базе стандартного стека Linux (Bridge, VLAN, Bonding) и расширенная возможностями программно-определяемых сетей (SDN).

**SDN (Software-Defined Networking)** — технология виртуализации сети, позволяющая создавать сложные топологии (зоны, виртуальные сети) поверх физической инфраструктуры без изменения конфигурации коммутаторов. Подробнее: **[Обзор SDN](../Networking/Concepts/sdn/sdn_overview.md)**.

**Linux Bridge** — программная реализация коммутатора (L2), позволяющая виртуальным машинам и контейнерам взаимодействовать друг с другом и с внешней сетью.

**ifupdown2** — менеджер сетевой конфигурации, работающий с файлом `/etc/network/interfaces`. Устанавливается по умолчанию с PVE 7.0, позволяет применять изменения сети без перезагрузки узла. Поддерживает сложные зависимости (мосты поверх бондов, VLAN-aware мосты) и вычисляет минимальный набор изменений при `ifreload -a`.

**pvesh** — CLI-инструмент для прямого вызова REST API Proxmox. Используется для управления SDN-зондами, контроллерами и другими объектами без GUI. Все операции, доступные через веб-интерфейс, имеют эквивалент в `pvesh`.

**FRR (Free Range Routing)** — набор демонов маршрутизации (BGP, OSPF, IS-IS, RIP), используемый PVE для автоматической настройки маршрутов в SDN Fabrics и Ceph. Конфигурация FRR генерируется автоматически из определения фабрики и хранится в `/etc/frr/`.

**Open vSwitch (OVS)** — программный коммутатор L2/L3 с поддержкой OpenFlow, GRE, VXLAN, Geneve. В PVE 9.x используется как backend для SDN-зон (OVN) и может заменять стандартный Linux Bridge в продвинутых сценариях. Управляется через `ovs-vsctl`, `ovs-ofctl`.

**OVN (Open Virtual Network)** — логический слой управления сетями поверх OVS. В PVE 9.x OVN отвечает за адресацию, ACL, NAT и маршрутизацию внутри SDN-зон. Конфигурация OVN хранится в `/etc/pve/sdn/` и применяется через `pvesh create /sdn/controllers/apply`.

**dnsmasq** — легковесный DNS/DHCP-сервер, используемый SDN как единственный backend автоматического DHCP (Simple-зоны). DHCP-плагин SDN создаёт отдельный сервис `dnsmasq@<zone>` для каждой зоны; стандартный экземпляр при этом отключается (`systemctl disable --now dnsmasq`). Подробнее: [dnsmasq](../Networking/Protocols/DNS/dnsmasq.md).

**VNet Firewall** — правила firewall на уровне SDN VNet (`/etc/pve/sdn/firewall/<vnet_name>.fw`), применяемые ко всему трафику, проходящему через VNet (guest↔guest, host↔guest). Так как это forwarded-трафик, правила создаются только с направлением `forward` и работают исключительно с новым nftables-based `proxmox-firewall` — стандартный `pve-firewall` игнорирует VNet-уровневые правила. Дополняет изоляцию портов VNet, которая действует только в пределах одной ноды.

**macvlan** — режим виртуального интерфейса, создающий несколько MAC-адресов на одном физическом интерфейсе. В Proxmox используется для подключения ВМ напрямую к физической сети без моста. Идеален для сценариев, где требуется максимальная производительность и прозрачность для физического коммутатора. Не поддерживает коммуникацию между ВМ на одном хосте через тот же физический NIC.

**ipvlan** — аналог macvlan, но с общим MAC-адресом родительского интерфейса. Режимы: `L2` (прозрачный L2-режим), `L3` (L3-разделение). В PVE применяется реже macvlan, но полезен в гетерогенных сетях, где коммутатор ограничивает количество MAC-адресов на порту.

**SR-IOV (Single Root I/O Virtualization)** — технология, позволяющая одному физическому NIC предоставить несколько виртуальных функций (VF, Virtual Functions). VF виден в ВМ как отдельный PCI-устройство с собственным MAC и IRQ. Обеспечивает производительность near-native, минуя гипервизор. В PVE настраивается через `qm set <vmid> --net0 virtio,bus=pci,....` или через PCI-пасsthrough. Поддержка SR-IOV зависит от драйвера NIC и BIOS (VT-d/AMD-Vi).

**TUN/TAP** — виртуальные сетевые устройства ядра Linux. `tun` работает с L3-пакетами (IP), `tap` — с L2-кадрами (Ethernet). В Proxmox используются для: VPN-туннелей (OpenVPN, WireGuard), контейнеров LXC (`veth`-пары), подключения к внешним сетям через `tap`-интерфейсы. Просмотр: `ls /dev/net/tun`.

**veth (Virtual Ethernet Pair)** — пара виртуальных интерфейсов, соединенных друг с другом внутри ядра. В LXC один end (`vethXXXi0`) находится в пространстве имен контейнера, другой (`vethXXXi1`) — в мосте хоста (`vmbr0`). Пара создается автоматически при старте контейнера. Просмотр: `ip link show type veth`.

**Conntrack (Connection Tracking)** — подсистема ядра Linux для отслеживания состояний сетевых соединений (NEW, ESTABLISHED, RELATED, INVALID). В PVE используется: (1) для stateful firewall (`pve-firewall`), (2) для NAT/Masquerading, (3) для SDN-зон с OVN. При включенном firewall и высоких нагрузках требуется увеличение `nf_conntrack_max` и `nf_conntrack_buckets`.

**pvenetcommit** — systemd-сервис, активирующий staging-файл `/etc/network/interfaces.new` при загрузке узла. Гарантирует, что изменения, примененные через GUI, вступят в силу после перезагрузки даже если сеть была временно недоступна во время редактирования.

## Основные концепции

### Модели сетевого взаимодействия

1. **Bridged (Мостовая)**: Основная модель. Виртуальные интерфейсы подключаются к `vmbr0` (аналог виртуального коммутатора). VM получают IP-адреса из физической сети и ведут себя как устройства, напрямую подключенные к коммутатору — сеть видит уникальный MAC каждой VM, хотя физический кабель один.
2. **Routed (Маршрутизируемая)**: Хост выступает маршрутизатором (L3), весь трафик VM выходит через единственный MAC-адрес хоста. Позволяет обойти ограничения хостинг-провайдеров, блокирующих несколько MAC-адресов на одном порту.
3. **Masquerading (NAT)**: Внутренняя частная сеть для ресурсов PVE, скрытая за IP-адресом хоста. Используется при дефиците публичных адресов; для входящего доступа к VM требуется Port Forwarding.

### Практические схемы подключения VM

При установке PVE автоматически создаёт мост `vmbr0`, привязанный к первому физическому интерфейсу; IP-адрес, маска и gateway, заданные при установке, относятся именно к этому мосту. VM и LXC по умолчанию подключаются к `vmbr0` и получают адреса из физической сети (DHCP-сервер роутера).

**Изолированный мост без IP-адреса.** Для полной изоляции пары VM друг от друга и от внешнего мира создаётся отдельный мост (`vmbr1`) без IP-адреса и gateway — вся настройка сети выполняется внутри гостей:

1. Network → Create → Linux Bridge: имя `vmbr1`, IP/Gateway не указывать → Create → Apply Configuration.
2. Каждой VM добавить второй сетевой интерфейс (Hardware → Add → Network Device, Bridge `vmbr1`).
3. В гостях настроить новый интерфейс (Ubuntu — netplan, интерфейсы `ens18`/`ens19`):

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

4. Связность сохраняется даже при отключении внешнего интерфейса (`ens18`): изолированная сеть не зависит от маршрутов во внешний мир.
5. Доступ с рабочей станции — через jump host (VM с интерфейсами в обеих сетях), см. раздел «Доступ к изолированным ВМ через jump host» ниже.

**Второй физический интерфейс — вторая независимая сеть.** При двух и более NIC каждый интерфейс можно связать со своим мостом и своей сетью (свой роутер/DHCP): VM, подключённые к `vmbr1`, получают адреса из второй сети и не видят сеть `vmbr0`. Переключение VM между сетями — Hardware → Network Device → Bridge, занимает секунды; IP меняется после продления аренды DHCP.

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

**Создание Bond через GUI (безопасная последовательность).** Изменения сети на узле вступают в силу только кнопкой **Apply Configuration**, поэтому порядок действий критичен — промежуточный Apply с отвязанным портом приведёт к потере доступа к узлу:

1. Открыть настройки `vmbr0`, убрать физический порт из Bridge Ports (**не** нажимать Apply).
2. Network → Create → Linux Bond: имя `bond0`, указать slave-интерфейсы (оба подключены в один коммутатор), режим (таблица режимов — в [Агрегация каналов](../Networking/Concepts/link_aggregation.md)); для active-backup — Primary (приоритетный интерфейс). Create.
3. Вернуться в `vmbr0`, в Bridge Ports выбрать `bond0`.
4. Apply Configuration — вся конфигурация применяется разом.

**Проверка failover:** при отключении кабеля или порта коммутатора основного интерфейса трафик переключается на резервный — ping продолжает работать, в статусе интерфейсов (Nodes → Network) основной порт переходит в `Down`, резервный — в `Up`. Восстановление: сначала вернуть основной порт в Up, потом отключать резервный, чтобы не потерять связь.

### VLAN (IEEE 802.1q)

Два способа настройки:

1. **Традиционный (VLAN-под-интерфейсы)**: тег в имени устройства (`eno1.50`, `bond0.5`), на под-интерфейс ставится мост `vmbr0v5`.
2. **VLAN-aware мост** (`bridge-vlan-aware yes`): на физическом мосте включается VLAN-фильтрация, тег назначается отдельной VM/LXC (поле VLAN Tag в GUI). Позволяет использовать до 4094 VLAN на одном мосте.

Рекомендация: настраивать VLAN на интерфейсе с наименьшим числом абстракций до физической карты (NIC → Bond → Bridge).

**VLAN на стороне коммутатора и роутера.** Типовая топология: порт коммутатора, в который подключён Proxmox, настраивается как trunk (разрешены теги всех нужных VLAN); порт роутера/firewall — тоже trunk, на firewall создаются виртуальные под-интерфейсы для каждого VLAN, они выступают gateway и DHCP-серверами соответствующих подсетей. Порты коммутатора для конечных устройств настраиваются как access (один VLAN) или с PVID — нетегированные кадры маркируются тегом PVID. Теория trunk/native VLAN/PVID: **[Магистральные порты (Trunk) и Native VLAN](../Networking/Protocols/VLAN/vlan_trunk_native.md)**, практические сценарии: **[L2 Switching и VLAN: Практические сценарии](../Networking/Concepts/vlan_l2_switching/practical_scenarios.md)**.

**Перенос VM между VLAN через VLAN Tag.** При включённом VLAN-aware мосте (`bridge-vlan-aware yes`) VM переносится между сетями без перенастройки мостов: Hardware → Network Device → VLAN Tag (поле доступно и при создании VM: Create VM → Network). После смены тега VM получает IP из нового VLAN через DHCP — перезагрузка гостя не требуется, достаточно продления аренды. Важно: сеть управления узлом (`vmbr0` с IP хоста) не следует переносить в гостевой VLAN — доступ к узлу будет потерян; для управления используйте отдельный нетегированный VLAN или VLAN-под-интерфейс с адресом хоста (см. пример `vmbr0.5` в разделе «Настройка VLAN на мосте»).

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

Изменения SDN не применяются немедленно: сначала они записываются как отложенные (pending) и применяются одной атомарной операцией кнопкой **Apply** в панели SDN. Состояние применённой конфигурации отслеживается в файлах `.running-config` и `.version` в `/etc/pve/sdn`.

#### Установка и статус поддержки SDN

Статус поддержки (PVE 9.x):

- Core SDN (управление VNet и интеграция со стеком PVE) — полностью поддерживается.
- IPAM, включая DHCP для гостевых систем — tech preview.
- Сложная маршрутизация через FRRouting и интеграция контроллеров — tech preview.

Установка:

- Начиная с PVE 8.1 пакеты core SDN установлены по умолчанию. При апгрейде со старых версий на каждой ноде: `apt install libpve-network-perl`.
- Для автоматического DHCP (опционально, opt-in) на каждой ноде:

```bash
apt update
apt install dnsmasq
# disable default instance
systemctl disable --now dnsmasq
```

Стандартный экземпляр dnsmasq отключается потому, что DHCP-плагин SDN создаёт собственный сервис `dnsmasq@<zone>` для каждой зоны и управляет его жизненным циклом. Конфигурация генерируется в `/etc/dnsmasq.d/<zone>/`, аренды хранятся в `/var/lib/misc/dnsmasq.<zone>.leases` — эти файлы управляются плагином и не подлежат ручной правке.

- Для расширенной маршрутизации (SDN Fabrics, EVPN-контроллеры; опционально) на всех нодах:

```bash
apt update
apt install frr frr-pythontools
systemctl enable frr.service
```

#### Типы зон SDN

Зона — виртуально изолированная сеть, ограниченная списком нод и правами доступа. После создания VNet в GUI он становится обычным Linux-мостом с тем же именем на каждой ноде — его назначают сетевым картам VM/LXC.

| Тип зоны | Механизм | Особенности |
|---|---|---|
| **Simple** | Изолированный мост; простой L3-мост с маршрутизацией (NAT) | Мост не связан с физическим интерфейсом, трафик VM локален на ноде. Поддерживает NAT- и routed-сценарии. Единственный тип зоны с поддержкой автоматического DHCP. |
| **VLAN** | Классическая сегментация 802.1Q | Использует существующий локальный Linux/OVS-мост; тег VLAN задаётся на уровне VNet. Обеспечивает связность VM между нодами. |
| **QinQ** | Stacked VLAN (IEEE 802.1ad) | Зона задаёт внешний тег (Service VLAN, S-Tag), VNet — внутренний (Customer VLAN, C-Tag). Физические коммутаторы должны поддерживать stacked VLAN. MTU — на 4 байта меньше физического интерфейса (1496 при MTU 1500). |
| **VXLAN** | L2-оверлей поверх UDP (порт 4789) | Инкапсулирует Ethernet-кадры в UDP-датаграммы; underlay нужно настроить самостоятельно. Идентификатор VNI — 24 бита, что дает до ~16 млн сегментов против 4096 у классических VLAN. Не шифрует трафик — при соединении площадок используйте site-to-site VPN. MTU — на 50 байт меньше исходящего физического интерфейса (по умолчанию 1450). |
| **EVPN (BGP EVPN)** | VXLAN с BGP для L3-маршрутизации | Маршрутизируемая L3-сеть, охватывающая несколько кластеров. Единственный тип зоны, требующий внешний контроллер (EVPN-контроллер настраивает FRR). Поддерживает anycast IP/MAC в качестве шлюза. |

Параметры зон:

- **Общие**: Nodes (ноды развёртывания), IPAM (по умолчанию `pve`), DNS, ReverseDNS, DNSZone (домен для регистрации `<hostname>.<domain>`; зона должна существовать на DNS-сервере).
- **VLAN**: Bridge — локальный мост или OVS, настроенный на каждой ноде.
- **QinQ**: Bridge (VLAN-aware), Service VLAN (основной тег зоны), Service VLAN Protocol (`802.1q` по умолчанию или `802.1ad`), MTU.
- **VXLAN**: Peers Address List (IP-адреса всех нод кластера, могут быть внешние ноды), SDN Fabric (автогенерация списка пиров), MTU.
- **EVPN**: VRF VXLAN ID, Primary Controller, Additional Controllers, VNet MAC Address, Exit Nodes, Primary Exit Node, Exit Nodes Local Routing, Advertise Subnets, Disable ARP ND Suppression, Route-target Import, MTU.

#### Параметры VNet, Subnet и сервисов SDN

**VNet** — после создания доступен как локальный интерфейс с тем же именем на каждой ноде:

- **ID** — идентификатор длиной до 8 символов.
- **Alias** — описательное имя, назначается как alias интерфейса.
- **Zone** — зона, к которой принадлежит VNet.
- **Tag** — уникальный VLAN- или VXLAN-ID.
- **VLAN Aware** — включает vlan-aware на интерфейсе, позволяя настраивать VLAN внутри гостя.
- **Isolate Ports** — флаг изоляции для всех гостевых портов VNet (не для самого интерфейса): гости могут слать трафик только на неизолированные порты моста, то есть на сам мост. Требует перезапуска гостя. Изоляция портов действует в пределах одной ноды — для изоляции между нодами используйте VNet Firewall.

**Subnet** — конкретный IP-диапазон (CIDR) внутри VNet; у VNet может быть несколько subnet'ов. Назначения: ограничение IP-адресов на VNet, назначение маршрутов/шлюзов в L3-зонах, включение SNAT в L3-зонах, автоматическое назначение IP через IPAM, регистрация DNS.

- **Gateway** — IP шлюза по умолчанию; в L3-зонах (Simple/EVPN) развёртывается на VNet.
- **SNAT** — Source NAT: позволяет VM из VNet выходить во внешнюю сеть, маскируя адреса адресом исходящего интерфейса ноды (в EVPN-зонах форвардинг выполняется на EVPN gateway-нодах).
- **DHCP range** — диапазон автоматической выдачи адресов. Поддерживается только в Simple-зонах и требует настроенного gateway на subnet, иначе автоматический DHCP не работает. CLI: `pvesh set /cluster/sdn/vnets/<vnet>/subnets/<subnet> -dhcp-range start-address=10.0.1.100,end-address=10.0.1.200`.
- **DNS Zone Prefix** — префикс домена для регистрации (`<hostname>.<prefix>.<domain>`).

Категория **Options** (Datacenter → SDN → Options) подключает внешние сервисы:

- **Controllers** — управление L3-маршрутизацией в сложных сценариях; на данный момент внешний контроллер требует только EVPN-зона (EVPN/BGP/ISIS-контроллеры настраивают FRR).
- **DHCP** — автоматический DHCP-сервер для зоны (единственный backend — dnsmasq).
- **IPAM** — внешнее управление IP-адресами (встроенный PVE IPAM, NetBox, phpIPAM).
- **DNS** — интеграция DNS-сервера для регистрации имён и IP гостевых систем.

#### Сценарии использования SDN

- **Изоляция и безопасность**: ресурсы, требующие дополнительного контроля (Firewall, ограничение доступа), выносятся в отдельную SDN-зону.
- **Разделение по отделам**: VM разных подразделений (разработка, веб-дизайн) размещаются в зонах своих отделов; сотрудники сами создают VM и назначают только разрешённые сети, без изменения конфигурации основной сети.
- **Хостинг (мультитенантность)**: клиенты разделяются по сетям и зонам — каждый видит и управляет только своими VM.
- **Изолированные частные сети** на отдельных нодах и сложные оверлеи между кластерами на разных площадках.

#### SNAT: поток пакетов

Зачем нужен SNAT: внешний шлюз ничего не знает о подсети SDN (например, `10.80.80.0/24`). При включённом SNAT адрес VM маскируется адресом самого Proxmox:

1. VM (`10.80.80.50`) → VNet-мост → мост ноды → внешний шлюз.
2. Ответ внешнего ресурса приходит на Proxmox: шлюз знает только, что пакет от Proxmox, с которым он напрямую подключён.
3. Proxmox по conntrack-записи NAT восстанавливает исходный адрес, видит, что пакет предназначен VM в SDN-зоне, и доставляет его ей.

Без SNAT на внешнем маршрутизаторе потребовался бы статический маршрут в подсеть SDN через Proxmox.

#### Практический сценарий: Simple-зона с SNAT и DHCP

Пример (иллюстративный): Simple-зона `simple`, VNet `vnet01`, subnet `10.80.80.0/24`, DHCP-диапазон `.50`–`.60`.

1. **Подготовка**: установка dnsmasq и отключение стандартного экземпляра (см. раздел «Установка»), проверка директивы `source /etc/network/interfaces.d/*` в `/etc/network/interfaces`.
2. **Создание зоны**: Datacenter → SDN → Zones → Add → Simple. Имя `simple`, выбрать ноды, в расширенных опциях включить автоматический DHCP.
3. **Создание VNet**: SDN → VNets → Create. ID `vnet01`, зона `simple`. Опционально — Isolate Ports и VLAN Aware.
4. **Создание Subnet**: выбрать VNet → Subnets → Create. Subnet `10.80.80.0/24`, Gateway `10.80.80.1` (первый адрес подсети), включить SNAT.
5. **DHCP Range**: вкладка DHCP Ranges → Create: start `10.80.80.50`, end `10.80.80.60`.
6. **Применение**: SDN → Apply. Без этого шага изменения остаются в статусе `new` и интерфейсы не создаются.
7. **Подключение VM**: VM → Hardware → Add → Network Device, Bridge = `vnet01`.
8. **Настройка гостя** (Ubuntu 24.04, netplan; новый интерфейс `ens19`):

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
# → ens19  UP  10.80.80.50/24  ...
ping -c 1 google.com
# → 1 packets transmitted, 1 received, 0% packet loss
```

9. **Проверка**: IP-адрес из настроенного DHCP-диапазона; доступ в интернет через SNAT.
10. **Просмотр IP-адресов**: Datacenter → SDN → IPAM — все IP-адреса и аренды по зонам, VNet и subnet'ам. При использовании DHCP через IPAM-панель можно создавать и редактировать аренды для конкретных VM (после изменения IP нужно форсировать обновление аренды в госте — перезагрузка сетевого стека или самого гостя).

#### Доступ к изолированным ВМ через jump host

Если VM в SDN-зоне не имеет маршрута во внешнюю сеть (или внешний маршрутизатор не знает подсеть SDN), доступ с рабочей станции возможен через jump host — VM/LXC с двумя интерфейсами: один в основной сети (например, `vmbr0`), второй в SDN-зоне (`vnet01`):

1. Создать LXC, добавить `eth0` (bridge `vmbr0`) и `eth1` (bridge `vnet01`, DHCP или статический IP из subnet).
2. Подключаться по SSH к `eth1` jump host из основной сети, затем с него — к VM в зоне.

Альтернатива — настроить маршрутизацию на внешнем роутере: статический маршрут подсети SDN (например, `10.80.80.0/24`) через IP Proxmox во внешней сети.

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

### Внутреннее устройство Linux Bridge

Linux Bridge — программный коммутатор уровня 2 в пространстве ядра. Ключевые механизмы:

- **FDB (Forwarding Database)**: таблица MAC-адресов, ассоциированных с портами моста. Заполняется автоматически при обучении (learning) на основе исходного MAC-адреса входящих кадров. Просмотр: `bridge fdb show dev vmbr0`.
- **Flooding**: неизвестный unicast, broadcast и multicast трафик рассылается на все порты моста, кроме входного. В VXLAN/SDN сетях flooding ограничивается туннелями.
- **STP (Spanning Tree Protocol)**: предотвращает петли в топологии. В PVE отключен по умолчанию (`bridge-stp off`), так как мосты обычно имеют единственный uplink. Включается только при сложных топологиях с несколькими путями.
- **VLAN filtering**: режим `bridge-vlan-aware yes` включает фильтрацию 802.1Q на уровне моста. Каждый порт имеет PVID (Port VLAN ID) — тег, добавляемый к нетегированным кадрам. Параметр `bridge-vids` определяет список разрешенных VLAN на порту.

### MTU и VXLAN overhead

VXLAN инкапсулирует исходный Ethernet-кадр в UDP-пакет. Overhead: 50 байт (VXLAN header 8 + outer IP 20 + outer UDP 8 + outer Ethernet 14). При стандартном underlay MTU 1500 максимальный MTU гостевой сети — 1450.

```bash
# Проверка MTU underlay
ip link show enp1s0 | grep mtu
# → 2: enp1s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...

# Проверка MTU VXLAN-интерфейса
ip -d link show type vxlan | grep -A2 'mtu'
# → vxlan_sdn: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 ...
#     vxlan id 100 local 10.0.0.1 dev enp1s0 remote 10.0.0.2 dstport 4789
```

Для использования jumbo frames в underlay (MTU 9000) необходимо поднять MTU VXLAN-интерфейса до 8950 и согласовать MTU на всех коммутаторах между узлами.

### Альтернативные модели сетевого доступа

Помимо стандартного Linux Bridge, PVE поддерживает:

- **macvlan bridge mode**: каждый интерфейс получает уникальный MAC, ВМ видимы как отдельные устройства на физической сети. Подходит для хостов, где несколько MAC на одном порту разрешены. Не требует моста, но ВМ на одном хосте не могут общаться друг с другом через этот интерфейс.
- **ipvlan L3 mode**: разделение на основе VLAN-подобных ID. Все интерфейсы имеют общий MAC родителя. Подходит для провайдерских сред и хостеров с ограничением MAC-портов.
- **SR-IOV VF**: прямой доступ к PCI-функции NIC с минимальным overhead. Настройка через `qm set <vmid> --net0 virtio,....` или через `hostpci`. Требует поддержки SR-IOV в драйвере (`lspci -vvv | grep -i "sr-iov"`).

### Архитектура сетевого firewall Proxmox

PVE включает распределенный firewall с несколькими уровнями:

1. **Datacenter-уровень**: глобальные опции (`datacenter.cfg`), макросы, группы.
2. **Уровень узла**: `node.fw` — правила, применяемые ко всем интерфейсам узла (включая корпоративные сети).
3. **Уровень VM/CT**: `vm/<vmid>.fw` или `ct/<ctid>.fw` — правила для конкретного гостя. Включают `netX` (для каждой сетевой карты) и `options` (включение/отключение firewall для гостя).
4. **Уровень VNet (SDN)**: `/etc/pve/sdn/firewall/<vnet_name>.fw` — правила для всего трафика, проходящего через SDN VNet (guest↔guest, host↔guest). Так как это forwarded-трафик, правила создаются только с направлением `forward` и работают исключительно с новым nftables-based `proxmox-firewall` — стандартный `pve-firewall` игнорирует VNet-уровневые правила.
5. **Security Groups**: наборы правил, назначаемые нескольким VM одновременно.

SDN интегрируется с firewall автоматической генерацией IPSets для VNet и IPAM-записей (например, `vnet0-all`, `vnet-no-gateway`, `vnet-dhcp`), которые можно использовать в полях source/destination правил. IPSets обновляются автоматически при изменении конфигурации subnet'ов.

Firewall работает на уровне `netfilter` (iptables/nftables) и применяется к виртуальным интерфейсам (`fwbr+`, `fwln+`). При включенном firewall для исходящих соединений VM может потребоваться конфигурация conntrack-зон (см. пример NAT выше).

### OVS как альтернативный backend

Для продвинутых сценариев (интеграция с OVN, DPDK, контроль трафика) можно использовать Open vSwitch вместо Linux Bridge:

```bash
# Установка OVS
apt install openvswitch-switch

# Создание моста OVS
ovs-vsctl add-br ovsbr0

# Добавление физического порта
ovs-vsctl add-port ovsbr0 enp1s0

# Назначение VLAN tag порту
ovs-vsctl set port enp1s0 tag=100

# Просмотр конфигурации
ovs-vsctl show
```

OVS требует переключения конфигурации с `ifupdown2` на OVS-native management (через `ovs-vsctl`). Несовместим с VLAN-aware Linux Bridge на том же узле без разделения интерфейсов.

## Управление сетью через CLI

### Основные команды управления сетью

```bash
# Статус всех интерфейсов
ip -br link show
# → lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP>
# → eno1             UP             86:0a:aa:bb:cc:dd <BROADCAST,MULTICAST,UP,LOWER_UP>
# → bond0            UP             86:0a:aa:bb:cc:ee <BROADCAST,MULTICAST,UP,LOWER_UP>
# → vmbr0            UP             86:0a:aa:bb:cc:ff <BROADCAST,MULTICAST,PROMISC,UP,LOWER_UP>

# Подробная информация о мосте
bridge link show
# → 2: eno1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
# → 15: veth101i0@if2 state UP @vmbr0 ...

# Таблица MAC-адресов моста
bridge fdb show dev vmbr0
# → 00:16:3e:a1:b2:c3 vlan 1 master vmbr0 permanent
# → 00:16:3e:d4:e5:f6 vlan 10 master vmbr0

# Статистика по bond-интерфейсу
cat /proc/net/bonding/bond0
# → Bond Mode: IEEE 802.3ad Dynamic link aggregation
# → MII Status: up
# → MII Polling Interval: 100
# → Up Delay: 0
# → Down Delay: 0
# → Slave Interface: enp1s0
# → MII Status: up
# → Speed: 10000 Mbps
# → Slave Interface: enp2s0
# → MII Status: up
# → Speed: 10000 Mbps
```

### Управление SDN через pvesh

```bash
# Список зон SDN
pvesh get /sdn/zones
# → zones: [{"zone": "prod", "type": "vxlan", ...}, {"zone": "mgmt", "type": "simple", ...}]

# Создание VXLAN-зоны (эквивалент GUI)
pvesh create /sdn/zones/vxlan/prod \
  --zone prod \
  --peers "10.0.0.1,10.0.0.2,10.0.0.3" \
  --vnet prod-vxlan

# Создание VNET в зоне
pvesh create /sdn/vnets/prod-vnet \
  --zone prod \
  --subnet 10.100.0.0/24

# Применение конфигурации (распространяет на все узлы)
pvesh create /sdn/controllers/apply

# Проверка статуса
pvesh get /sdn/zones/prod/status
# → {"nodes": {"pve1": {"state": "active"}, "pve2": {"state": "active"}}}

# Удаление VNET
pvesh delete /sdn/vnets/prod-vnet

# Dry-run (PVE 9.2+)
pvesh create /sdn/controllers/apply --dry-run 1
```

### Валидация конфигурации

```bash
# Проверка синтаксиса interfaces
ifreload -a --dry-run
# → ifupdown2: dry-run, no changes applied

# Проверка наличия необходимых директив
grep -E '^source /etc/network/interfaces.d' /etc/network/interfaces
# → source /etc/network/interfaces.d/*

# Проверка статуса SDN-контроллера
pvesh get /cluster/ha/status
# → {"nodename": "pve1", "state": "online", ...}

# Проверка маршрутов после применения SDN
ip route show table main
# → default via 192.168.1.1 dev vmbr0
# → 10.100.0.0/24 dev vxlan_sdn proto kernel scope link src 10.0.0.1
```

### Резервное копирование и восстановление конфигурации

```bash
# Создание бэкапа конфигурации сети
tar czf /var/backups/network-config-$(date +%Y%m%d).tar.gz \
  /etc/network/interfaces \
  /etc/network/interfaces.d \
  /etc/pve/sdn/ \
  /etc/frr/

# Включение конфигурации в резервное копирование через PBS/VZDump
# Добавить в /etc/vzdump.conf:
# script: /usr/local/sbin/network-backup.sh

# Восстановление из бэкапа
tar xzf /var/backups/network-config-20260101.tar.gz -C /
ifreload -a
```

### Мониторинг сетевого здоровья

```bash
# Мониторинг ошибок на интерфейсах
ip -s link show eno1 | grep -E 'RX|TX'
# → RX: bytes packets errors dropped overrun mcast
# → RX: 123456789 123456 0 0 0 0

# Мониторинг ошибок bond
cat /proc/net/bonding/bond0 | grep -E 'MII|Error'
# → MII Status: up
# → Error packets: 0

# Мониторинг VXLAN
ip -s link show type vxlan | grep -E 'RX|TX'
# → RX: bytes packets errors dropped overrun mcast
# → TX: bytes packets errors dropped carrier collsns

# Проверка firewall правил
iptables-save | grep -E 'vmbr|fwbr|vnet'
# → -A FORWARD -i fwbr+ -j DROP
# → -A FORWARD -i fwln+ -j DROP

# Журналы firewall
journalctl -u pve-firewall -f
# → ... rule added: IN=vmbr0 OUT= MAC=... SRC=10.0.0.10 DST=10.0.0.1 ...

# Prometheus метрики (node_exporter)
# node_network_transmit_bytes_total{device="vmbr0"}
# node_network_receive_bytes_total{device="enp1s0"}
# node_network_receive_err_total{device="bond0"}
```

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

### Управление сетевыми картами VM/LXC через CLI

Добавление сети к работающей ВМ (hot-add):

```bash
# Добавление сети virtio на vmbr0
qm set 100 --net1 virtio,bridge=vmbr0,firewall=1
# → net1: virtio=76:32:...:E2, bridge=vmbr0, firewall=1

# Удаление сети
qm set 100 --delete net1
# → deleted net1

# Изменение модели сетевой карты (требует выключенной ВМ)
qm set 100 --net0 virtio,bridge=vmbr0,queues=4
```

Для LXC:

```bash
# Добавление сети
pct set 101 --net0 name=eth0,bridge=vmbr0,ip=10.0.0.10/24,gw=10.0.0.1
# → net0: name=eth0,bridge=vmbr0,ip=10.0.0.10/24,gw=10.0.0.1

# Проверка конфигурации
pct config 101 | grep net
# → net0: name=eth0,bridge=vmbr0,ip=10.0.0.10/24,gw=10.0.0.1,tag=5
```

### Валидация изменений перед применением

Создание staging-файла и проверка через `ifreload --dry-run`:

```bash
# Создание staging-файла (аналог GUI Apply)
cat <<EOF > /etc/network/interfaces.new
auto vmbr10
iface vmbr10 inet static
    address 10.200.0.1/24
    bridge-ports bond0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-vids 100-200
EOF

# Dry-run
ifreload -a --dry-run
# → ifupdown2: dry-run, no changes applied
# → [OK] No changes to apply

# Если dry-run успешен — применение
ifreload -a
# → ifupdown2: applying changes
# → [OK] Applied 1 interfaces
```

### Откат изменений сети

При потере доступа к узлу после изменения сети:

```bash
# Через физическую консоль/IPMI/iDRAC
# Откат staging-файла
mv /etc/network/interfaces.new /etc/network/interfaces.new.bak
ifreload -a

# Или принудительная перезагрузка с восстановлением
# (pvenetcommit активирует interfaces.new при загрузке)
# Если interfaces.new содержит ошибки — переименовать его
mv /etc/network/interfaces.new /etc/network/interfaces.new.broken
reboot
```

### Проверка связности VM с внешней сетью

```bash
# Внутри VM (Linux)
ip route show
# → default via 10.0.0.1 dev eth0

ping -c 3 10.0.0.1
# → 3 packets transmitted, 3 received, 0% packet loss

# Проверка ARP-таблицы хоста
ip neigh show dev vmbr0
# → 10.0.0.10 dev vmbr0 lladdr 00:16:3e:a1:b2:c3 REACHABLE

# Проверка FDB моста
bridge fdb show dev vmbr0 | grep 00:16:3e:a1:b2:c3
# → 00:16:3e:a1:b2:c3 vlan 1 master vmbr0 permanent
```

### Настройка SDN Fabrics через CLI (WireGuard underlay)

Пример настройки WireGuard-фабрики для защищенного underlay между узлами:

```bash
# На узле 1 (pve1)
wg genkey | tee privatekey | wg pubkey > publickey

# /etc/wireguard/pve1.conf
[Interface]
Address = 10.200.1.1/24
ListenPort = 51820
PrivateKey = <содержимое privatekey>

[Peer]
# pve2
PublicKey = <публичный ключ pve2>
AllowedIPs = 10.200.1.0/24, 10.0.0.0/24
Endpoint = 192.168.1.2:51820

[Peer]
# pve3
PublicKey = <публичный ключ pve3>
AllowedIPs = 10.200.1.0/24, 10.0.0.0/24
Endpoint = 192.168.1.3:51820

# Активация
systemctl enable --now wg-quick@pve1

# Проверка
wg show
# → interface: pve1
# → public key: ...
# → endpoint: 192.168.1.2:51820
# → allowed ips: 10.200.1.0/24, 10.0.0.0/24
# → transfer: 1.23 GiB received, 456.78 MiB sent
```

### Настройка OVS backend для SDN

```bash
# Установка OVS
apt update && apt install -y openvswitch-switch

# Создание интеграционного моста (аналог vmbr0)
ovs-vsctl add-br ovsbr0 -- set bridge ovsbr0 protocols=OpenFlow10,OpenFlow13

# Добавление физического порта
ovs-vsctl add-port ovsbr0 enp1s0 -- set interface enp1s0 type=system

# Настройка VLAN-aware порта
ovs-vsctl set port enp1s0 tag=100
ovs-vsctl set port enp1s0 trunks=100,200

# Создание внутреннего порта для управления хостом
ovs-vsctl add-port ovsbr0 mgmt0 -- set interface mgmt0 type=internal
ip addr add 10.200.1.1/24 dev mgmt0
ip link set mgmt0 up

# Просмотр конфигурации
ovs-vsctl show
# → Bridge ovsbr0
# →     Port ovsbr0
# →         Interface ovsbr0
# →             type: internal
# →     Port enp1s0
# →         Interface enp1s0
# →             type: system
# →     Port mgmt0
# →         Interface mgmt0
# →             type: internal

# Добавление OpenFlow правила (пример)
ovs-ofctl add-flow ovsbr0 "in_port=enp1s0,dl_vlan=100,actions=output:mgmt0"
ovs-ofctl dump-flows ovsbr0
```

## Диагностика и устранение неполадок

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

### Типичные проблемы

#### VM не имеет сети

| Причина | Диагностика | Решение |
|---------|-------------|---------|
| Виртуальная карта отключена | `qm config 100 \| grep net0` | `qm set 100 --net0 virtio,bridge=vmbr0` |
| Bridge не существует | `ip link show vmbr0` | Создать bridge или исправить имя в конфигурации VM |
| VLAN mismatch | `bridge vlan show dev vmbr0` | Проверить PVID на порту и tag в конфигурации VM |
| Firewall блокирует трафик | `iptables-save \| grep vmbr0` | Проверить `vm/<vmid>.fw` и `node.fw` |
| Bond без LACP на коммутаторе | `cat /proc/net/bonding/bond0` | Переключиться на active-backup или настроить LACP на коммутаторе |

#### VXLAN-туннель не поднимается

```bash
# Проверка доступности пиров
ping -c 3 10.0.0.2
# → 3 packets transmitted, 3 received, 0% packet loss

# Проверка UDP-порта 4789
nc -zvu 10.0.0.2 4789
# → Connection to 10.0.0.2 4789 port [udp/*] succeeded!

# Проверка iptables для VXLAN
iptables-save | grep 4789
# → -A INPUT -p udp --dport 4789 -j ACCEPT

# Проверка MTU
ip -d link show type vxlan | grep mtu
# → mtu 1450
# Если underlay MTU 1500 — требуется поднять MTU на физических интерфейсах или снизить MTU VM
```

#### Bond-интерфейс не агрегируется (LACP)

```bash
# Проверка режима bonding
cat /proc/net/bonding/bond0
# → Bond Mode: IEEE 802.3ad Dynamic link aggregation

# Проверка negotiated LACP
ethtool bond0 | grep -i "speed\|link"
# → Speed: 20000Mb/s (если оба линка активны)

# Проверка на коммутаторе (если есть доступ)
show lacp neighbor
# Должен отображаться aggregator для bond0 с обоими линками

# Если коммутатор не поддерживает LACP — переключиться на active-backup
```

#### MAC-адрес conflict

```bash
# Поиск дублирующихся MAC
for mac in $(bridge fdb show dev vmbr0 | awk '{print $2}'); do
  count=$(bridge fdb show dev vmbr0 | grep -c "$mac")
  if [ "$count" -gt 1 ]; then
    echo "Duplicate MAC: $mac"
  fi
done
# → Duplicate MAC: 00:16:3e:a1:b2:c3

# Проверка, какой VM использует MAC
qm config 100 | grep net0
# → net0: virtio=86:0a:aa:bb:cc:dd,bridge=vmbr0,firewall=1

# Исправление: назначить новый MAC или удалить дубликат
qm set 100 --net0 virtio,bridge=vmbr0,firewall=1,macaddr=AA:BB:CC:DD:EE:FF
```

#### SDN apply fails

```bash
# Проверка статуса SDN-контроллера
pvesh get /sdn/controllers/status
# → {"nodes": {"pve1": {"state": "error", "message": "MTU mismatch on vxlan_sdn"}}}

# Проверка логов FRR
journalctl -u frr -n 50
# → FRR: VXLAN interface vxlan_sdn MTU 1450 is smaller than underlay MTU 1500

# Проверка конфигурации SDN
cat /etc/pve/sdn/zones.cfg
# → vnet prod-vxlan {
# →     zone prod;
# → }

# Проверка интерфейсов на всех нодах
for node in pve1 pve2 pve3; do
  echo "=== $node ==="
  ssh $node "ip -d link show type vxlan"
done
```

#### Bridge port flapping

```bash
# Проверка состояния порта
bridge link show | grep veth101i0
# → 15: veth101i0@if2: <BROADCAST,MULTICAST,PROMISC,UP,LOWER_UP> ...

# Проверка счетчика ошибок
ip -s link show eno1 | grep -A2 'RX\|TX'
# → RX: bytes packets errors dropped overrun mcast
# → RX: 123456789 123456 123 0 0 0
# →     errors > 0 — проблема с кабелем/портом

# Проверка duplex
ethtool eno1 | grep -i "speed\|duplex"
# → Speed: 1000Mb/s
# → Duplex: Full
# → Если Half — проблема с настройкой или кабелем
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

# Проверка DNS (если VM не резолвит имена)
systemd-resolve --status
# → DNS Servers: 192.168.1.1
# → DNS Domain: cluster.local

# Проверка firewall правил
iptables-save | grep -E "DROP|REJECT"
# → -A FORWARD -i fwbr+ -j DROP
# → -A FORWARD -o fwbr+ -j DROP
```

## Лучшие практики

1. **Сегментация сетей**: Разделяйте management, guest и storage трафик на разные VLAN или физические интерфейсы. Management сеть должна быть изолирована от гостевой.
2. **Именование**: Используйте осмысленные имена: `vmbr0` (management), `vmbr10` (guest VLAN 10), `bond0` (LAG), `eno1` (физический порт). Избегайте generic-имён вроде `br0`.
3. **Изменения по одному**: Вносите изменения сети по одному параметру с валидацией через `ifreload --dry-run`. Не объединяйте несколько изменений в одном окне.
4. **Резервное копирование конфигурации**: Автоматически бэкапьте `/etc/network/interfaces`, `/etc/pve/sdn/` и `/etc/frr/` перед изменениями.
5. **VLAN-aware bridge**: Используйте `bridge-vlan-aware yes` вместо множества VLAN-под-интерфейсов. Это упрощает управление и масштабирование.
6. **MTU согласованность**: При VXLAN/SDN убедитесь, что MTU underlay (обычно 1450) согласован на всех узлах и коммутаторах. Используйте jumbo frames только если поддерживаются на всем пути.
7. **Документирование**: Ведите документацию по топологии сети (какой VLAN к какой зоне/ВМ), используйте комментарии в конфигурации.
8. **Change Management**: Используйте maintenance mode для узлов при изменении сети. Оповещайте команду о planned downtime.
9. **Firewall по умолчанию**: Включайте firewall для всех VM/LXC. Используйте security groups для стандартных политик (web, db, mgmt).
10. **Мониторинг**: Настройте алерты на: dropped packets на bond, ошибки CRC, flapping портов, недоступность VXLAN-туннелей.

## Граничные случаи

1. **MTU mismatch в VXLAN**: Если underlay MTU 1500, а VXLAN MTU оставлен 1500, фрагментация пакетов приведет к потере пакетов или снижению производительности. Симптом: `ping` работает, но `scp`/`curl` зависают. Решение: установить MTU 1450 на VM или настроить Path MTU Discovery.
2. **Смешанные скорости в bonding**: При использовании NIC разной скорости (1G + 10G) в LACP-бонде трафик хешируется только по скоростям. Может привести к перегрузке медленного линка. Решение: использовать separate bonds или active-backup.
3. **MAC-адрес conflict при клонировании VM**: При клонировании без Cloud-Init MAC может дублироваться. Симптом: ARP flux, потери пакетов. Решение: `qm set <newid> --net0 virtio,bridge=vmbr0,firewall=1` — назначает новый MAC.
4. **VLAN-aware bridge + legacy VM**: Некоторые старые ОС (Windows Server 2012, старые Linux ядра) не корректно обрабатывают VLAN tagging на уровне guest. Симптом: VM не получает DHCP или нет связи. Решение: использовать традиционные VLAN-под-интерфейсы (`eno1.50` → `vmbr0v5`) или VLAN trunk в VM.
5. **SDN во время обслуживания узла**: При переводе узла в maintenance mode SDN-туннели к этому узлу разрываются. Миграция VM в это время может завершиться ошибкой сети. Решение: сначала мигрировать VM, потом вводить maintenance mode.
6. **Bonding с разными драйверами NIC**: NIC одного производителя, но разные revision могут иметь несовместимые offload параметры, вызывающие падение bond. Решение: единообразная конфигурация `ethtool` на всех slave-интерфейсах.
7. **Conntrack exhaustion при высоких нагрузках**: При >100K соединений в секунду на узел может произойти исчерпание `nf_conntrack_max`. Симптом: `CT table full, dropping packet`. Решение: `sysctl -w net.netfilter.nf_conntrack_max=1048576`.
8. **OVS + Linux Bridge на одном узле**: OVS и Linux Bridge не могут совместно использовать один физический NIC без VFIO passthrough или macvlan. Приводит к нестабильной работе. Решение: выделить отдельные NIC под OVS и Linux Bridge, или использовать только один backend.
9. **Автоматический DHCP только в Simple-зонах**: VLAN-, VXLAN- и EVPN-зоны не поддерживают автоматический DHCP — адреса назначаются вручную или через внешний DHCP-сервер в этой сети. Симптом: VM не получает IP, хотя DHCP-диапазон настроен.
10. **DHCP без gateway**: автоматический DHCP не работает, если на subnet не настроен gateway.
11. **QinQ: untagged VNet и MTU**: при jumbo-frame underlay MTU зоны не применяется к veth-паре `ln_<zone>`/`pr_<zone>` для нетегированных VNet (Proxmox Bugzilla #8005) — они остаются на 1500. Тегированные VNet не затронуты.
12. **VXLAN без шифрования**: VXLAN сам по себе не шифрует трафик; при соединении площадок через интернет организуйте site-to-site VPN.

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md) — архитектура и взаимодействие сетевых компонентов PVE
- [Архитектура SDN](../Networking/Concepts/sdn/sdn_overview.md) — теория SDN, OVS/OVN и VXLAN
- [Linux Bridge — архитектура и настройка](../Linux/Networking/Concepts/linux_bridge.md) — глубинное понимание программного коммутатора в Linux
- [dnsmasq — локальный DNS/DHCP-сервер](../Networking/Protocols/DNS/dnsmasq.md) — backend автоматического DHCP в SDN-зонах
- [BGP и FRRouting](../Networking/Protocols/bgp.md) — маршрутизация для EVPN-контроллеров и SDN Fabrics
