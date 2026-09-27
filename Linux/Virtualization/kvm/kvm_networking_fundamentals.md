# Сетевые основы KVM: libvirt networks, dnsmasq, nwfilter, port forwarding

В данном файле описывается архитектура виртуальных сетей libvirt, внутренний стек dnsmasq для DHCP/DNS, сетевые фильтры (nwfilter) для изоляции ВМ и настройка проброса портов (port forwarding) из внешней сети в ВМ за NAT. Базовые сетевые архитектуры KVM (bridge, macvtap, SR-IOV) описаны в [KVM — Обзор и архитектура](./overview.md), а продвинутые топологии (OVS, VXLAN) — в [Продвинутая сеть KVM](./kvm_networking_advanced.md).

## Определения

**Virtual Network (Виртуальная сеть)** — программный коммутатор, создаваемый libvirt, обеспечивающий сетевую связность ВМ. Может работать в режимах NAT, bridge или isolated. Управляется через `virsh net-*` и XML-конфигурации.

**dnsmasq** — легковесный DNS/DHCP-сервер, используемый libvirt по умолчанию для предоставления IP-адресов и DNS-резолвинга внутри виртуальных NAT-сетей. Работает как отдельный процесс для каждой активной виртуальной сети.

**nwfilter (Network Filter)** — механизм libvirt для фильтрации сетевого трафика ВМ на уровне хоста. Позволяет создавать правила на основе MAC, IP, портов и протоколов, аналогично iptables, но привязанные к конкретным ВМ.

**Port Forwarding (Проброс портов)** — техника DNAT, позволяющая маршрутизировать трафик с определённого порта хоста на порт ВМ за NAT. Используется для доступа к сервисам внутри NAT-ВМ из внешней сети.

**dnsmasq lease file** — файл `/var/lib/libvirt/dnsmasq/<имя_сети>.leases`, хранящий текущие DHCP-аренды MAC→IP для ВМ в конкретной виртуальной сети.

**iptables/nftables libvirt chains** — автоматически создаваемые цепочки правил файрвола для каждой виртуальной сети: `LIBVIRT_FWI` (входящий), `LIBVIRT_FWO` (исходящий), `LIBVIRT_FWX` (forward).

**ARP/NDP Spoofing Protection** — механизм nwfilter для предотвращения атак подмены ARP/NDP-ответов между ВМ.

**MAC Spoofing** — атака, при которой ВМ отправляет фреймы с подменённым MAC-адресом, нарушая изоляцию. nwfilter предотвращает это через фильтр `no-mac-spoofing`.

**IP Spoofing** — атака, при которой ВМ отправляет пакеты с подменённым源 IP. nwfilter блокирует это через фильтр `no-ip-spoofing`.

## Базовые концепции

### Архитектура виртуальных сетей libvirt

Каждая виртуальная сеть libvirt — это независимый программный коммутатор с собственным DHCP/DNS и файрволом.

**Сетевые режимы:**

| Режим | Описание | DHCP | DNS | Firewall | Сценарий |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NAT** | ВМ в изолированной подсети, выход через NAT хоста | Да (dnsmasq) | Да (dnsmasq) | Да (iptables/nft) | Development, default |
| **Bridge** | ВМ напрямую в физической сети хоста | Нет (внешний DHCP) | Нет | Нет | Production, нужен IP из VLAN |
| **Isolated** | Нет выхода наружу, только между ВМ и хостом | Да (dnsmasq) | Да (dnsmasq) | Да | Тестовые сегменты, изолированные сервисы |
| **Routed** | Маршрутизация без NAT, ВМ доступны из сети хоста | Да (dnsmasq) | Да (dnsmasq) | Да | Многорежимные сети, VPN |

**XML-конфигурация NAT-сети:**
```xml
<network>
  <name>default</name>
  <forward mode='nat'/>
  <bridge name='virbr0' stp='on' delay='0'/>
  <ip address='192.168.122.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='192.168.122.2' end='192.168.122.254'/>
      <host mac='52:54:00:ab:cd:ef' ip='192.168.122.10'/>
    </dhcp>
  </ip>
</network>
```

### Стек dnsmasq в libvirt

Для каждой активной NAT-сети libvirt запускает отдельный процесс dnsmasq, который предоставляет DHCP и DNS для ВМ.

**Процесс dnsmasq:**
```bash
# Просмотр процессов dnsmasq
ps aux | grep dnsmasq
# → dnsmasq --conf-file=/var/lib/libvirt/dnsmasq/default.conf
```

**Конфигурация dnsmasq (автогенерируемая):**
```bash
# /var/lib/libvirt/dnsmasq/default.conf
# Генерируется libvirt, не редактировать вручную!
listen-address=192.168.122.1,::1
bind-interfaces
pid-file=/var/run/libvirt/network/default.pid
except-interface=lo
dhcp-range=192.168.122.2,192.168.122.254,255.255.255.0,3600s
dhcp-option=option:router,192.168.122.1
dhcp-leasefile=/var/lib/libvirt/dnsmasq/default.leases
dns-hosts=/var/lib/libvirt/dnsmasq/default.hostsfile
addn-hosts=/var/lib/libvirt/dnsmasq/default.addnhosts
```

**DHCP-аренды:**
```bash
# Просмотр текущих DHCP-аренд
virsh net-dhcp-leases default
# → Expiry Time          MAC address           IP address       Hostname   Client ID or DUID
#   2026-09-17 12:00:00  52:54:00:ab:cd:ef    192.168.122.10   web-01     ff:ab:cd:ef:00:01:00:01:...
```

**Статические DHCP-записи (привязка MAC→IP):**
```bash
# Через XML виртуальной сети
virsh net-edit default
# Добавить в секцию <dhcp>:
# <host mac="52:54:00:ab:cd:ef" ip="192.168.122.10"/>

# Или через CLI:
virsh net-update default add ip-dhcp-host \
  "<host mac='52:54:00:ab:cd:ef' ip='192.168.122.10'/>" \
  --config --live
```

**DNS-резолвинг:**
```bash
# dnsmasq автоматически резолвит имена ВМ по DHCP-аренде
# Проверка из гостевой ОС:
ping web-server-01.local

# Просмотр DNS-записей:
cat /var/lib/libvirt/dnsmasq/default.hostsfile
# → 192.168.122.10 web-server-01
```

### Управление виртуальными сетями

```bash
# Список всех сетей
virsh net-list --all
# → Name      State      Autostart   Persistent
# → default   active   yes         yes

# Информация о сети
virsh net-info default

# XML-конфигурация
virsh net-dumpxml default

# Включение/отключение автозапуска
virsh net-autostart default
virsh net-autostart --disable default

# Запуск/остановка сети
virsh net-start default
virsh net-destroy default

# Удаление сети
virsh net-undefine default
```

**Создание изолированной сети:**
```bash
# Создание изолированной сети для тестов
cat > /tmp/isolated-net.xml << 'EOF'
<network>
  <name>isolated</name>
  <bridge name='virbr1'/>
  <ip address='10.0.0.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='10.0.0.100' end='10.0.0.200'/>
    </dhcp>
  </ip>
</network>
EOF

virsh net-define /tmp/isolated-net.xml
virsh net-start isolated
virsh net-autostart isolated
```

**Создание bridge-сети (без DHCP/libvirt):**
```bash
# Привязка к существующему Linux bridge
cat > /tmp/br-network.xml << 'EOF'
<network>
  <name>production</name>
  <forward mode='bridge'/>
  <bridge name='br0'/>
  <virtualport type='openvswitch'/>
</network>
EOF

virsh net-define /tmp/br-network.xml
virsh net-start production
virsh net-autostart production
```

### nwfilter: сетевые фильтры для изоляции ВМ

nwfilter позволяет создавать правила файрвола на уровне libvirt, привязанные к конкретным ВМ. Правила применяются к каждому виртуальному интерфейсу (vNIC) ВМ.

**Список стандартных фильтров:**
```bash
# Просмотр доступных фильтров
virsh nwfilter-list
# → UUID                                  Name
# → 00000000-0000-0000-0000-000000000001  clean-traffic
# → 00000000-0000-0000-0000-000000000002  no-mac-spoofing
# → 00000000-0000-0000-0000-000000000003  no-ip-spoofing
# → ...
```

**XML-конфигурация фильтра `clean-traffic`:**
```xml
<filter name="clean-traffic" chain="root">
  <!-- Запрет подмены MAC -->
  <filterref filter="no-mac-spoofing"/>
  <!-- Запрет подмены IP -->
  <filterref filter="no-ip-spoofing"/>
  <!-- Запрет подмены ARP -->
  <filterref filter="no-arp-spoofing"/>
  <!-- Запрет IP multicast -->
  <filterref filter="no-ip-multicast"/>
  <!-- Разрешить только IPv4 -->
  <filterref filter="allow-arp"/>
  <filterref filter="allow-ipv4"/>
</filter>
```

**Применение фильтра к интерфейсу ВМ (XML):**
```xml
<interface type='network'>
  <source network='default'/>
  <mac address='52:54:00:ab:cd:ef'/>
  <filterref filter='clean-traffic'/>
  <model type='virtio'/>
</interface>
```

**Применение фильтра к работающей ВМ:**
```bash
# Добавление фильтра к интерфейсу ВМ
virsh nwfilter-binding-list
# → UUID                                  PortDev   Filter-Name-UUID              Filter-Name   Links
```

**Создание кастомного фильтра:**
```xml
<!-- /tmp/custom-filter.xml -->
<filter name="web-server-filter" chain="root">
  <!-- Базовая очистка трафика -->
  <filterref filter="clean-traffic"/>
  <!-- Разрешить HTTP/HTTPS -->
  <rule action="accept" direction="in" priority="100">
    <ip protocol="tcp" dstportstart="80" dstportend="443"/>
  </rule>
  <!-- Разрешить SSH только с конкретного IP -->
  <rule action="accept" direction="in" priority="200">
    <ip protocol="tcp" srcipaddr="10.0.0.1" dstportstart="22" dstportend="22"/>
  </rule>
  <!-- Запретить весь остальной входящий трафик -->
  <rule action="drop" direction="in" priority="500">
    <all/>
  </rule>
</filter>
```

```bash
# Определение фильтра
virsh nwfilter-define /tmp/custom-filter.xml

# Привязка к ВМ
virsh nwfilter-binding-add web-server-01.0 web-server-filter
```

**Проверка Applied Filters:**
```bash
# Просмотр активных фильтров
virsh nwfilter-binding-list

# Просмотр фильтра для конкретного интерфейса
virsh nwfilter-binding-info web-server-01.0
```

### NAT Port Forwarding (Проброс портов)

Для доступа к сервисам внутри NAT-ВМ из внешней сети используется DNAT через правила iptables/libvirt.

**Способ 1: Ручная настройка iptables (рекомендуется):**
```bash
# Проброс порта 8080 хоста → порт 80 ВМ (192.168.122.10)
sudo iptables -t nat -A LIBVIRT_FWI \
  -d 192.168.122.1 -p tcp --dport 8080 \
  -j DNAT --to-destination 192.168.122.10:80

sudo iptables -A LIBVIRT_FWI \
  -d 192.168.122.10 -p tcp --dport 80 \
  -j ACCEPT

# Проверка
sudo iptables -t nat -L LIBVIRT_FWI -n -v
```

**Способ 2: Полная конфигурация (port forwarding + firewall):**
```bash
#!/bin/bash
# kvm-port-forward.sh — проброс порта для ВМ

VM_IP="192.168.122.10"
HOST_PORT="8080"
VM_PORT="80"
PROTOCOL="tcp"

# Проброс через DNAT
sudo iptables -t nat -A PREROUTING -p $PROTOCOL --dport $HOST_PORT \
  -j DNAT --to-destination ${VM_IP}:${VM_PORT}

# Разрешение forwarded трафика
sudo iptables -A FORWARD -p $PROTOCOL -d $VM_IP --dport $VM_PORT \
  -m state --state NEW,ESTABLISHED,RELATED -j ACCEPT

# Маскарадинг для исходящего трафика (если нужно)
sudo iptables -t nat -A POSTROUTING -s 192.168.122.0/24 \
  -o eth0 -j MASQUERADE

# Включение forwarding
sudo sysctl -w net.ipv4.ip_forward=1
```

**Способ 3: Через firewalld (RHEL/Fedora):**
```bash
# Добавление rich rule для проброса порта
sudo firewall-cmd --permanent --add-rich-rule='
  rule family="ipv4"
  forward-port
  to-addr="192.168.122.10"
  port port="8080" protocol="tcp"
  to-port="80" protocol="tcp"'

sudo firewall-cmd --reload
```

**Проверка:**
```bash
# С хоста:
curl http://localhost:8080
# → Должен вернуть ответ от сервиса в ВМ

# Мониторинг соединений:
ss -tlnp | grep 8080
# → LISTEN  0  128  0.0.0.0:8080  0.0.0.0:*  users:(("iptables",...))
```

### Отключение дефолтной NAT-сети

В production дефолтная сеть `default` часто отключается, если ВМ используют bridge-режим.

```bash
# Отключение автозапуска
virsh net-autostart --disable default

# Остановка (если не используется)
virsh net-destroy default

# Удаление (если не нужна)
virsh net-undefine default

# Проверка
virsh net-list --all
# → Name      State    Autostart   Persistent
# → (пусто)
```

**Отключение автозапуска dnsmasq (если сеть bridge):**
При использовании bridge-сети libvirt не запускает dnsmasq для неё, так как DHCP предоставляется внешним сервером.

### Диагностика сетевых проблем ВМ

**Алгоритм диагностики:**
1. **ВМ не получает IP:** Проверить `virsh net-dhcp-leases default`, статус dnsmasq, XML ВМ
2. **ВМ пингуется из хоста, но не снаружи:** Проверить NAT, forwarding, файрвол
3. **ВМ не пингуется:** Проверить bridge, MAC-адрес, ARP-таблицу
4. **DNS не работает:** Проверить `/etc/resolv.conf` в госте, dnsmasq hostsfile

```bash
# Проверка ARP-таблицы хоста
arp -n | grep 192.168.122
# → 192.168.122.10   dev virbr0 lladdr 52:54:00:ab:cd:ef REACHABLE

# Проверка bridge-таблицы (FDB)
bridge fdb show dev virbr0
# → 52:54:00:ab:cd:ef master virbr0

# Проверка conntrack для NAT
conntrack -L -p tcp --dport 80 2>/dev/null | head -5
# → tcp  6 117 TIME_WAIT src=10.0.0.1 dst=192.168.122.10 sport=xxxx dport=80 ...

# Проверка iptables chains
sudo iptables -t nat -L LIBVIRT_FWI -n -v
sudo iptables -L LIBVIRT_FWI -n -v
```

## Практические сценарии

### Сценарий 1: Полная настройка NAT-сети с port forwarding

Настройка сети для development-среды с доступом к ВМ снаружи.

**1. Создание сети:**
```bash
cat > /tmp/dev-network.xml << 'EOF'
<network>
  <name>dev-net</name>
  <forward mode='nat'>
    <nat>
      <port start='10000' end='10100'/>
    </nat>
  </forward>
  <bridge name='virbr100' stp='on' delay='0'/>
  <ip address='192.168.100.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='192.168.100.10' end='192.168.100.200'/>
    </dhcp>
  </ip>
</network>
EOF

virsh net-define /tmp/dev-network.xml
virsh net-start dev-net
virsh net-autostart dev-net
```

**2. Проброс портов (HTTP + SSH):**
```bash
# HTTP: 8080 → 80
sudo iptables -t nat -A LIBVIRT_FWI \
  -d 192.168.100.1 -p tcp --dport 8080 \
  -j DNAT --to-destination 192.168.100.10:80
sudo iptables -A LIBVIRT_FWI \
  -d 192.168.100.10 -p tcp --dport 80 -j ACCEPT

# SSH: 2222 → 22
sudo iptables -t nat -A LIBVIRT_FWI \
  -d 192.168.100.1 -p tcp --dport 2222 \
  -j DNAT --to-destination 192.168.100.10:22
sudo iptables -A LIBVIRT_FWI \
  -d 192.168.100.10 -p tcp --dport 22 -j ACCEPT

# Сохранение правил
sudo iptables-save > /etc/iptables/rules.v4
```

**3. Создание ВМ с привязкой к dev-net:**
```bash
virt-install \
  --name dev-server \
  --memory 2048 \
  --vcpus 2 \
  --disk path=/var/lib/libvirt/images/dev-server.qcow2,size=20 \
  --network network=dev-net,model=virtio \
  --graphics none \
  --import
```

**4. Проверка:**
```bash
# С хоста:
ssh -p 2222 user@localhost
curl http://localhost:8080

# Просмотр DHCP-аренд
virsh net-dhcp-leases dev-net
```

### Сценарий 2: nwfilter для изоляции ВМ в multi-tenant среде

Настройка фильтров для изоляции ВМ разных tenants.

**1. Создание фильтра для Tenant A:**
```xml
<!-- /tmp/tenant-a-filter.xml -->
<filter name="tenant-a-filter" chain="root">
  <filterref filter="clean-traffic"/>
  <!-- Разрешить трафик только внутри tenant (192.168.100.0/24) -->
  <rule action="accept" direction="in" priority="100">
    <ip srcipaddr="192.168.100.0" srcipmask="24"/>
  </rule>
  <rule action="accept" direction="out" priority="100">
    <ip dstipaddr="192.168.100.0" dstipmask="24"/>
  </rule>
  <!-- Разрешить DNS -->
  <rule action="accept" direction="inout" priority="200">
    <ip protocol="udp" dstportstart="53" dstportend="53"/>
  </rule>
  <!-- Запретить всё остальное -->
  <rule action="drop" direction="inout" priority="1000">
    <all/>
  </rule>
</filter>
```

**2. Применение к ВМ Tenant A:**
```bash
virsh nwfilter-define /tmp/tenant-a-filter.xml

# Привязка к интерфейсу ВМ (XML)
# <interface type='network'>
#   <source network='dev-net'/>
#   <filterref filter='tenant-a-filter'/>
# </interface>
```

**3. Проверка:**
```bash
# Просмотр активных фильтров
virsh nwfilter-binding-list
# → PortDev                Filter-Name
# → virbr100-0             tenant-a-filter
```

### Сценарий 3: Настройка DNS через libvirt с кастомными записями

Добавление статических DNS-записей для ВМ через libvirt.

```bash
# Добавление DNS-хоста через virsh
virsh net-update default add dns-host \
  "<host ip='192.168.122.10'>
    <hostname>web-server-01</hostname>
    <hostname>web01.local</hostname>
  </host>" \
  --config --live

# Добавление CNAME-записи (requires手动 редактирование XML)
virsh net-edit default
# В секцию <dns> добавить:
# <host ip='192.168.122.10'>
#   <hostname>web</hostname>
# </host>

# Проверка из гостевой ОС:
# nslookup web-server-01
# → 192.168.122.10
```

### Сценарий 4: Отключение dnsmasq для bridge-сети

При использовании внешнего DHCP-сервера (Kea, ISC DHCP) dnsmasq не нужен.

```bash
# Создание bridge-сети без dnsmasq
cat > /tmp/br-prod.xml << 'EOF'
<network>
  <name>prod-bridge</name>
  <forward mode='bridge'/>
  <bridge name='br0'/>
</network>
EOF

virsh net-define /tmp/br-prod.xml
virsh net-start prod-bridge
virsh net-autostart prod-bridge

# Проверка: dnsmasq НЕ запускается для bridge-сетей
ps aux | grep dnsmasq | grep prod-bridge
# → (пусто)
```

## Сетевое программирование: Bonding, VLAN, IPv6, DNS

### Network Bonding (LACP, active-backup, balance-rr)

**Bonding** — агрегация нескольких физических сетевых интерфейсов в один логический для увеличения пропускной способности или отказоустойчивости.

**Режимы bonding:**

| Режим | Alias | Линк-агрегация | Отказоустойчивость | Балансировка | Требования |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **balance-rr** | mode=0 | Да | Да | По round-robin | Поддержка LACP на switch |
| **active-backup** | mode=1 | Нет | Да (failover) | Нет | Нет |
| **balance-xor** | mode=2 | Да | Да | По XOR хешу | Поддержка LACP |
| **broadcast** | mode=3 | Да | Да | Нет | Нет |
| **802.3ad (LACP)** | mode=4 | Да | Да | По LACP | LACP на switch |
| **balance-tlb** | mode=5 | Да | Да | По TX | Нет |
| **balance-alb** | mode=6 | Да | Да | По TX+RX | Нет |

**Настройка active-backup (отказоустойчивость):**
```bash
# /etc/network/interfaces.d/bond0
auto bond0
iface bond0 inet static
    address 192.168.1.100
    netmask 255.255.255.0
    gateway 192.168.1.1
    bond-slaves eth0 eth1
    bond-mode active-backup
    bond-miimon 100
    bond-primary eth0

# Проверка
cat /proc/net/bonding/bond0
# → MII Status: up
# → Active Slave: eth0
# → Slave Interface: eth0  MII Status: up  Speed: 1000 Mbps
# → Slave Interface: eth1  MII Status: up  Speed: 1000 Mbps  (standby)
```

**Настройка LACP (mode=4):**
```bash
# /etc/network/interfaces.d/bond0
auto bond0
iface bond0 inet static
    address 192.168.1.100
    netmask 255.255.255.0
    bond-slaves eth0 eth1
    bond-mode 802.3ad
    bond-xmit-hash-policy layer3+4
    bond-lacp-rate fast
    bond-miimon 100
```

**Привязка bond0 к bridge (KVM):**
```bash
# /etc/network/interfaces.d/br0
auto br0
iface br0 inet static
    address 192.168.1.100
    netmask 255.255.255.0
    gateway 192.168.1.1
    bridge-ports bond0
    bridge-stp off
    bridge-fd 0
```

**Привязка bond к ВМ через libvirt:**
```xml
<interface type='bridge'>
  <source bridge='br0'/>
  <model type='virtio'/>
  <driver name='vhost' queues='4'/>
</interface>
```

### VLAN Tagging (802.1Q)

**VLAN** — виртуальная локальная сеть, позволяющая изолировать трафик на уровне L2. В KVM используется для multi-tenant сред и сегментации сетей.

**Настройка VLAN на хосте:**
```bash
# Установка vlan
sudo apt install -y vlan

# Создание VLAN на bond0
cat <<EOF | sudo tee /etc/network/interfaces.d/bond0.100
auto bond0.100
iface bond0.100 inet static
    address 192.168.100.1
    netmask 255.255.255.0
    vlan-raw-device bond0
EOF

# Или через ip link
sudo ip link add link bond0 name bond0.100 type vlan id 100
sudo ip addr add 192.168.100.1/24 dev bond0.100
sudo ip link set bond0.100 up
```

**VLAN-aware bridge (libvirt):**
```bash
# Создание VLAN-aware bridge
cat <<EOF | sudo tee /etc/network/interfaces.d/br0
auto br0
iface br0 inet manual
    bridge-ports bond0
    bridge-vlan-aware yes
    bridge-vids 100 200 300
    bridge-pvid 1
EOF
```

**XML-конфигурация ВМ с VLAN:**
```xml
<interface type='bridge'>
  <source bridge='br0'/>
  <model type='virtio'/>
  <virtualport type='bridge'>
    <parameters interfaceid='vm-web-01' vlanid='100'/>
  </virtualport>
</interface>
```

**Создание libvirt-сети с VLAN:**
```bash
# VLAN 100 для production
cat > /tmp/vlan100-net.xml << 'EOF'
<network>
  <name>prod-vlan100</name>
  <forward mode='bridge'/>
  <bridge name='br0'/>
  <virtualport type='bridge'>
    <parameters vlanid='100'/>
  </virtualport>
</network>
EOF

virsh net-define /tmp/vlan100-net.xml
virsh net-start prod-vlan100
virsh net-autostart prod-vlan100
```

### IPv6 в KVM

**IPv6** — интернет-протокол нового поколения с адресным пространством 128 бит, автоматической конфигурацией (SLAAC) и встроенным IPsec.

**Настройка IPv6 на bridge:**
```bash
# Включение IPv6 forwarding
sysctl -w net.ipv6.conf.all.forwarding=1

# Добавление IPv6-адреса на bridge
ip -6 addr add 2001:db8:1::1/64 dev br0

# Router Advertisement для SLAAC
sudo apt install -y radvd
cat <<EOF | sudo tee /etc/radvd.conf
interface br0 {
    AdvSendAdvert on;
    prefix 2001:db8:1::/64 {
        AdvOnLink on;
        AdvAutonomous on;
        AdvRouterAddr on;
    };
};
EOF
sudo systemctl enable --now radvd
```

**Двойной стек (IPv4 + IPv6) для ВМ:**
```bash
# Создание сети с двойным стеком
cat > /tmp/dualstack-net.xml << 'EOF'
<network>
  <name>dualstack</name>
  <forward mode='nat'/>
  <bridge name='virbr2'/>
  <ip address='192.168.122.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='192.168.122.10' end='192.168.122.200'/>
    </dhcp>
  </ip>
  <ip family='ipv6' address='2001:db8:cafe::1/64'>
    <dhcp>
      <range start='2001:db8:cafe::10' end='2001:db8:cafe::ff'/>
    </dhcp>
  </ip>
</network>
EOF

virsh net-define /tmp/dualstack-net.xml
virsh net-start dualstack
```

**Проверка IPv6 из гостевой ОС:**
```bash
# Проверка адреса
ip -6 addr show
# → inet6 2001:db8:cafe::10/64 scope global dynamic

# Проверка conectivity
ping6 2001:db8:cafe::1
ping6 2606:4700:4700::1111  # Cloudflare DNS

# DNS-резолвинг
dig AAAA example.com
```

### DNS-инфраструктура для KVM

**dnsmasq** — основной DNS/DHCP для NAT-сетей libvirt. Для bridge-сетей используется внешний DNS.

**Настройка кастомного DNS через libvirt:**
```bash
# Добавление статических DNS-записей
virsh net-update default add dns-host \
  "<host ip='192.168.122.10'>
    <hostname>web-server-01</hostname>
    <hostname>web01.internal</hostname>
  </host>" \
  --config --live

# Проверка
cat /var/lib/libvirt/dnsmasq/default.hostsfile
# → 192.168.122.10 web-server-01 web01.internal
```

**Настройка DNS через systemd-resolved (на хосте):**
```bash
# /etc/systemd/resolved.conf
[Resolve]
DNS=1.1.1.1 8.8.8.8
FallbackDNS=9.9.9.9
Domains=~internal
DNSSEC=allow-downgrade
DNSOverTLS=opportunistic

# /etc/resolv.conf → symlink
sudo ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf

# Проверка
resolvectl status
# → Global: DNS Servers: 1.1.1.1 8.8.8.8
```

**DNS для bridge-сети (BIND/Unbound на хосте):**
```bash
# Установка BIND (authoritative DNS)
sudo apt install -y bind9

# /etc/bind/named.conf.local
zone "internal" {
    type master;
    file "/etc/bind/zones/internal.db";
};

# /etc/bind/zones/internal.db
$TTL 604800
@   IN  SOA ns1.internal. admin.internal. (
        2026091701  ; Serial
        604800      ; Refresh
        86400       ; Retry
        2419200     ; Expire
        604800 )    ; Negative Cache TTL

@   IN  NS  ns1.internal.
ns1 IN  A   192.168.122.1
web IN  A   192.168.122.10
db  IN  A   192.168.122.20
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — базовые сетевые архитектуры (bridge, macvtap, SR-IOV).
- [Продвинутая сеть KVM: OVS, VXLAN](./kvm_networking_advanced.md) — Open vSwitch, DPDK, tunneling.
- [Управление виртуальными машинами](./management.md) — `virsh net-*`, XML-конфигурации.
- [Установка и настройка KVM](./installation.md) — файрвол и сетевые порты.
- [Решение проблем (Troubleshooting)](./troubleshooting.md) — сетевая диагностика (сценарий 9).
- [Сетевая диагностика ВМ](./vm_network_troubleshooting.md) — MTU, conntrack, macvtap, packet loss.
- [dnsmasq: Полное руководство](../../Networking/Protocols/DNS/dnsmasq.md) — архитектура, кэширование, PXE.
- [DHCP в Docker и виртуализации](../../Networking/Protocols/DHCP/dhcp_docker_virtualization.md) — libvirt DHCP vs Kea.
- [Linux Bridge: Концепции](../../Linux/Networking/Concepts/linux_bridge.md) — L2-мост, VLAN filtering, FDB.
- [I/O планировщики и ФС](./io_scheduler_and_fs.md) — выбор scheduler и файловой системы для KVM.
- [Open vSwitch](../../Networking/ServicesAndTools/open_vswitch.md) — OVS, OpenFlow, DPDK.
- [iptables](../../Networking/Protocols/iptables/iptables_overview.md) — таблицы, цепочки, DNAT/MASQUERADE.
- [nftables](../../Networking/Protocols/nftables/nftables_overview.md) — замена iptables.
