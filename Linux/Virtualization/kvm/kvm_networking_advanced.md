# Продвинутая сеть KVM: Open vSwitch, VXLAN, GRE

В данном файле описывается использование Open vSwitch (OVS) для построения высокопроизводительных сетевых топологий в среде KVM: VLAN-тегирование, VXLAN/GRE-туннели, DPDK-ускорение и интеграция с libvirt. Базовые сетевые модели KVM описаны в [KVM — Обзор и архитектура](./overview.md), а Linux Bridge — в [Linux Bridge: Концепции](../../Networking/Concepts/linux_bridge.md).

## Определения

**Open vSwitch (OVS)** — программный L2-коммутатор с поддержкой OpenFlow, работающий в ядре Linux. Предоставляет функциональность аппаратного коммутатора: VLAN-тегирование, GRE/VXLAN-туннели, зеркалирование, ACL.

**OpenFlow** — протокол управления потоками, позволяющий контроллеру (ONOS, OpenDaylight) или администратору определять правила маршрутизации пакетов.

**OVS-DPDK** — режим OVS, использующий DPDK (Data Plane Development Kit) для обработки пакетов в userspace. Достигает производительности 10-40 Gbps на одном ядре.

**VXLAN (Virtual Extensible LAN)** — протокол инкапсуляции L2-трафика в UDP-пакеты (порт 4789). Позволяет объединять L2-сегменты через L3-сеть (overlay network). VNI (VXLAN Network Identifier) — 24-bit идентификатор (до 16M сегментов).

**GRE (Generic Routing Encapsulation)** — протокол туннелирования L3-трафика. Поддерживает multicast и أكثر эффективный overhead (4 байта) по сравнению с VXLAN (50 байт).

**VLAN (Virtual LAN)** — стандарт IEEE 802.1Q для сегментации L2-сети. OVS поддерживает до 4094 VLAN-тегов на одном мосте.

**Mirror Port (Зеркалирование)** — функция OVS для копирования трафика с одного порта на другой. Используется для анализа трафика (tcpdump, IDS).

**ACL (Access Control List)** — правила фильтрации трафика на уровне L2-L4 в OVS. Аналог iptables, но для виртуальных коммутаторов.

**Hardware Offload (TC Flower)** — перенос правил OVS/OpenFlow в аппаратуру NIC (SmartNIC) для снижения нагрузки на CPU.

## Базовые концепции

### Архитектура OVS

OVS состоит из нескольких компонентов, работающих в разных пространствах.

**Компоненты:**
- **ovs-vswitchd:** Демон пользовательского уровня. Обрабатывает пакеты, не обработанные ядром. Управляет OpenFlow-потоками.
- **ovsdb-server:** Сервер базы данных OVSDB. Хранит конфигурацию мостов, портов, VLAN, туннелей.
- **Datapath (ядро):** Модуль ядра `openvswitch.ko`. Обрабатывает fast-path пакеты ( 패턴 match-action в ядре).
- **ovs-vsctl:** CLI-утилита для управления конфигурацией (через ovsdb-server).
- **ovs-ofctl:** Утилита для управления OpenFlow-правилами.
- **ovs-appctl:** Утилита для диагностики и управления внутренним состоянием OVS.

**Поток пакета:**
1. Пакет поступает на порт OVS.
2. Datapath проверяет кэш potokov (microflow cache).
3. При промахе — пакет отправляется в ovs-vswitchd (userspace) для обработки по OpenFlow-правилам.
4. Результат записывается в кэш ядра для последующих пакетов.

### Типы портов OVS

| Тип порта | Описание | Использование |
| :--- | :--- | :--- |
| **Access** | Порт без тега. Один VLAN. | Подключение ВМ к сети. |
| **Trunk** | Порт с тегами VLAN. Несколько VLAN. | Связь между коммутаторами. |
| **Tunnel** | GRE/VXLAN-туннел. | Multi-host overlay networking. |
| **Patch** | Виртуальный кабель между мостами OVS. | Соединение мостов внутри хоста. |
| **Internal** | Внутренний порт (аналог loopback). | Маршрутизация на хосте. |
| **Mirror** | Зеркалирование трафика. | Анализ трафика (tcpdump). |

### OVS vs Linux Bridge

| Критерий | Linux Bridge | Open vSwitch |
| :--- | :--- | :--- |
| VLAN | Ограничено (4094) | Полная поддержка trunk/access |
| Туннели | Geneve/VXLAN (ограниченно) | GRE, VXLAN, Geneve, LISP |
| OpenFlow | Нет | Полная поддержка |
| DPDK | Нет | Да (OVS-DPDK) |
| Hardware Offload | Ограничен (TC) | TC Flower, SmartNIC |
| Производительность | Высокая (ядро) | Средняя (userspace), высокая (DPDK) |
| Диагностика | brctl, bridge | ovs-vsctl, ovs-ofctl, ovs-appctl |

### VLAN-тегирование в OVS

OVS поддерживает два режима работы с VLAN: access (один VLAN) и trunk (несколько VLAN).

**Настройка OVS-моста с VLAN:**
```bash
# Создание моста
sudo ovs-vsctl add-br br-int

# Access-порт (один VLAN, тег добавляется автоматически)
sudo ovs-vsctl add-port br-int tap0 -- set port tag=100

# Trunk-порт (несколько VLAN, теги проходят как есть)
sudo ovs-vsctl add-port br-int eth0 -- set port eth0 trunk=100,200,300

# Access + trunk на одном порту (hybrid)
sudo ovs-vsctl add-port br-int hybrid0 \
  -- set port hybrid0 trunk=100,200 tag=300
```

**OpenFlow для VLAN:**
```bash
# Добавление VLAN к пакетам с определенного порта
sudo ovs-ofctl add-flow br-int "in_port=tap0,actions=mod_vlan_vid:100,output:eth0"

# Удаление VLAN при входе
sudo ovs-ofctl add-flow br-int "in_port=eth0,vlan_vid=100,actions=strip_vlan,output:tap0"

# Маршрутизация по VLAN
sudo ovs-ofctl add-flow br-int "in_port=eth0,vlan_vid=100,actions=output:tap0"
sudo ovs-ofctl add-flow br-int "in_port=eth0,vlan_vid=200,actions=output:tap1"
```

### VXLAN и GRE туннели

Туннели позволяют объединять L2-сегменты ВМ на разных физических хостах.

**VXLAN через OVS:**
```bash
# На Host A (Local IP: 192.168.1.10)
sudo ovs-vsctl add-br br-int
sudo ovs-vsctl add-port br-int vxlan0 \
  -- set interface vxlan0 type=vxlan \
     options:remote_ip=192.168.1.20 \
     options:key=100

# На Host B (Local IP: 192.168.1.20)
sudo ovs-vsctl add-br br-int
sudo ovs-vsctl add-port br-int vxlan0 \
  -- set interface vxlan0 type=vxlan \
     options:remote_ip=192.168.1.10 \
     options:key=100
```

**GRE через OVS:**
```bash
# На Host A
sudo ovs-vsctl add-br br-int
sudo ovs-vsctl add-port br-int gre0 \
  -- set interface gre0 type=gre \
     options:remote_ip=192.168.1.20

# На Host B
sudo ovs-vsctl add-br br-int
sudo ovs-vsctl add-port br-int gre0 \
  -- set interface gre0 type=gre \
     options:remote_ip=192.168.1.10
```

### OVS-DPDK

Режим OVS с DPDK для обработки пакетов в userspace с минимальными задержками.

**Требования:**
- HugePages (1GB) выделены для DPDK.
- EAL (Environment Abstraction Layer) настроен.
- NIC поддерживает DPDK (Intel, Mellanox).

**Настройка OVS-DPDK:**
```bash
# 1. Резервирование HugePages
echo 4 | sudo tee /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages

# 2. Загрузка модулей
sudo modprobe uio_pci_generic
sudo modprobe vfio-pci

# 3. Привязка NIC к DPDK (vfio-pci)
sudo dpdk-devbind.py --bind=vfio-pci 0000:01:00.0

# 4. Инициализация OVS с DPDK
sudo ovs-vsctl --no-wait init
sudo ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
sudo ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem=1024
sudo systemctl restart openvswitch-switch

# 5. Создание DPDK-моста
sudo ovs-vsctl add-br br-dpdk -- set bridge br-dpdk datapath_type=netdev
sudo ovs-vsctl add-port br-dpdk dpdk0 -- set Interface dpdk0 type=dpdk \
  options:dpdk-devargs=0000:01:00.0

# 6. Подключение VHOST-USER порта для ВМ
sudo ovs-vsctl add-port br-dpdk vhost-user-0 \
  -- set Interface vhost-user-0 type=dpdkvhostuserclient \
     options:vhost-server-path=/var/run/openvswitch/vhost-user-0
```

**XML-конфигурация ВМ для OVS-DPDK:**
```xml
<interface type='vhostuser'>
  <mac address='52:54:00:xx:xx:xx'/>
  <source type='unix' path='/var/run/openvswitch/vhost-user-0' mode='client'/>
  <model type='virtio'/>
  <driver name='vhostuser' queues='4'/>
</interface>
```

## Практические сценарии

### Сценарий 1: Интеграция OVS с libvirt

Подключение ВМ к OVS-мосту через XML-конфигурацию.

**1. Создание OVS-моста:**
```bash
sudo ovs-vsctl add-br br-ovs
sudo ovs-vsctl add-port br-ovs eth0  # Физический интерфейс
```

**2. XML-конфигурация ВМ:**
```xml
<interface type='bridge'>
  <mac address='52:54:00:ab:cd:ef'/>
  <source bridge='br-ovs'/>
  <virtualport type='openvswitch'>
    <parameters interfaceid='vm-web-01'/>
  </virtualport>
  <model type='virtio'/>
  <driver name='vhost' queues='4'/>
</interface>
```

**3. CLI-управление (virsh):**
```bash
# Добавление интерфейса к работающей ВМ
virsh attach-interface web-server-01 bridge br-ovs \
  --virtualport type=openvswitch \
  --model virtio \
  --persistent

# Проверка
virsh dumpxml web-server-01 | grep -A10 interface
```

### Сценарий 2: Multi-tenant изоляция через VLAN

Изоляция ВМ разных tenants через VLAN в OVS.

**Архитектура:**
```
Tenant A (VLAN 100):  VM-A1 (192.168.100.10)  VM-A2 (192.168.100.20)
Tenant B (VLAN 200):  VM-B1 (192.168.200.10)  VM-B2 (192.168.200.20)
```

**Настройка:**
```bash
# Создание моста
sudo ovs-vsctl add-br br-multi-tenant

# Tenant A (VLAN 100)
sudo ovs-vsctl add-port br-multi-tenant tap-a1 \
  -- set port tag=100
sudo ovs-vsctl add-port br-multi-tenant tap-a2 \
  -- set port tag=100

# Tenant B (VLAN 200)
sudo ovs-vsctl add-port br-multi-tenant tap-b1 \
  -- set port tag=200
sudo ovs-vsctl add-port br-multi-tenant tap-b2 \
  -- set port tag=200

# Trunk-порт для uplink (все VLAN)
sudo ovs-vsctl add-port br-multi-tenant eth0 \
  -- set port eth0 trunk=100,200
```

**Проверка:**
```bash
# Проверка портов
sudo ovs-vsctl show
# → Port "tap-a1"
#     tag: 100
# → Port "tap-b1"
#     tag: 200

# Проверка трафика
sudo ovs-ofctl dump-flows br-multi-tenant
```

### Сценарий 3: VXLAN-overlay для миграции ВМ

Объединение L2-сегментов ВМ на разных хостах через VXLAN.

**На Host A (192.168.1.10):**
```bash
sudo ovs-vsctl add-br br-ovs
sudo ovs-vsctl add-port br-ovs vxlan-overlay \
  -- set interface vxlan-overlay type=vxlan \
     options:remote_ip=192.168.1.20 \
     options:key=5000
sudo ovs-vsctl add-port br-ovs tap-vm-a
```

**На Host B (192.168.1.20):**
```bash
sudo ovs-vsctl add-br br-ovs
sudo ovs-vsctl add-port br-ovs vxlan-overlay \
  -- set interface vxlan-overlay type=vxlan \
     options:remote_ip=192.168.1.10 \
     options:key=5000
sudo ovs-vsctl add-port br-ovs tap-vm-b
```

**Результат:** VM-A и VM-B находятся в одном L2-сегменте (VNI=5000) и могут общаться напрямую по MAC, хотя физически находятся на разных хостах.

### Сценарий 4: Зеркалирование трафика (Mirror Port)

Анализ трафика ВМ без влияния на производительность.

```bash
# Создание mirror-порта для анализа
sudo ovs-vsctl add-port br-ovs mirror-tap

# Настройка зеркалирования
sudo ovs-vsctl set bridge br-ovs mirrors=@m \
  -- --id=@m create mirror name=m0 \
    select-dst-port=tap-web-01 \
    select-src-port=tap-web-01 \
    output-port=mirror-tap

# Проверка
sudo ovs-vsctl list mirror

# Захват трафика на mirror-tap
sudo tcpdump -i mirror-tap -w /tmp/vm-web-01-traffic.pcap
```

### Сценарий 5: OVS с OpenFlow для микросегментации

Контроль доступа между ВМ на уровне L2-L4 через OpenFlow.

```bash
# Запретить трафик между VM-A и VM-B (tenant isolation)
sudo ovs-ofctl add-flow br-ovs \
  "in_port=tap-a,dl_src=52:54:00:aa:bb:01,dl_dst=52:54:00:aa:bb:02,actions=drop"

# Разрешить HTTP-трафик только на порт 80
sudo ovs-ofctl add-flow br-ovs \
  "in_port=tap-a,tcp,tp_dst=80,actions=normal"
sudo ovs-ofctl add-flow br-ovs \
  "in_port=tap-a,tcp,tp_dst!=80,actions=drop"

# Логирование ICMP-пакетов
sudo ovs-ofctl add-flow br-ovs \
  "in_port=tap-a,icmp,actions=normal,controller"

# Просмотр правил
sudo ovs-ofctl dump-flows br-ovs
```

### Сценарий 6: Диагностика OVS

Команды для выявления проблем с OVS.

```bash
# Проверка состояния OVS
sudo ovs-vsctl show
sudo ovs-vsctl list bridge
sudo ovs-vsctl list port

# Проверка потоков
sudo ovs-ofctl dump-flows br-ovs
sudo ovs-ofctl dump-flows br-ovs -O OpenFlow13

# Диагностика пакета (traceroute для L2)
sudo ovs-appctl ofproto/trace br-ovs \
  in_port=tap-a,dl_src=52:54:00:aa:bb:01,dl_dst=52:54:00:aa:bb:02,ip,nw_src=192.168.100.10,nw_dst=192.168.100.20

# Статистика портов
sudo ovs-vsctl list interface
# Или:
sudo ovs-vsctl list port | grep -E 'name|statistics'

# Мониторинг событий
sudo ovs-appctl monitor
```

## Дополнительная информация

- [Open vSwitch: Полное руководство](../../Networking/ServicesAndTools/open_vswitch.md) — архитектура, порты, OpenFlow, диагностика.
- [Linux Bridge: Концепции](../../Networking/Concepts/linux_bridge.md) — архитектура L2-сетей.
- [Сетевая диагностика ВМ](./vm_network_troubleshooting.md) — MTU, conntrack, macvtap, packet loss.
- [VXLAN](../../Networking/Tunnels/vxlan.md) — RFC, заголовок, режимы, диагностика.
- [GRE](../../Networking/Tunnels/gre/gre.md) — протокол, туннели, IPSec-интеграция.
- [DPDK](../../Networking/Concepts/dpdk/dpdk_overview.md) — ускорение сетевого стека.
- [SR-IOV](../../Networking/Concepts/dpdk/sriov.md) — прямой проброс NIC в ВМ.
- [eBPF и XDP](../../Networking/Concepts/sdn/ebpf_xdp.md) — программирование сетевого стека.
- [Microsegmentation](../../Networking/Concepts/network_segmentation_and_microsegmentation.md) — сегментация и изоляция.
