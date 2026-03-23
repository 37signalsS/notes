# L2 Switching и VLAN: Практические сценарии

## Сценарий 1: Настройка VLAN в Linux

**Задача:** Сервер подключён к trunk-порту, нужны интерфейсы для VLAN 10 и 20.

### Вариант A: Временная настройка (iproute2)

```bash
# Создать VLAN-интерфейсы
ip link add link eth0 name eth0.10 type vlan id 10
ip link add link eth0 name eth0.20 type vlan id 20

# Назначить IP
ip addr add 192.168.10.100/24 dev eth0.10
ip addr add 192.168.20.100/24 dev eth0.20

# Поднять интерфейсы
ip link set eth0.10 up
ip link set eth0.20 up

# Проверка
ip -d link show eth0.10
ip -d link show eth0.20
```

### Вариант B: NetworkManager (nmtui/nmcli)

```bash
# Создать VLAN через nmcli
nmcli connection add type vlan ifname enp0s3.10 \
  dev enp0s3 id 10 con-name "vlan10-users"

nmcli connection modify vlan10-users \
  ipv4.addresses 192.168.10.100/24 \
  ipv4.gateway 192.168.10.1 \
  ipv4.dns "8.8.8.8 8.8.4.4" \
  ipv4.method manual

nmcli connection up vlan10-users
```

### Вариант C: Netplan (Ubuntu 18.04+)

**Подробная документация:** **[Настройка Netplan](../../../Linux/Networking/Settings/Persistent_Network/index.md#3-ubuntu-1710-netplan)** — полные примеры конфигураций (статические IP, bonding, VLAN, маршруты).

```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: no
      optional: true
  vlans:
    eth0.10:
      id: 10
      link: eth0
      addresses: [192.168.10.100/24]
      gateway4: 192.168.10.1
      nameservers:
        addresses: [8.8.8.8, 8.8.4.4]
    eth0.20:
      id: 20
      link: eth0
      addresses: [192.168.20.100/24]

# Применить
sudo netplan apply
```

---

## Сценарий 2: VLAN на гипервизоре (KVM/QEMU)

**Задача:** Виртуальные машины на одном гипервизоре должны быть в разных VLAN.

### Решение с Linux Bridge

```bash
# Создать мосты для каждого VLAN
ip link add name br-vlan10 type bridge
ip link add name br-vlan20 type bridge

# Создать VLAN-интерфейсы
ip link add link eth0 name eth0.10 type vlan id 10
ip link add link eth0 name eth0.20 type vlan id 20

# Привязать VLAN к мостам
ip link set eth0.10 master br-vlan10
ip link set eth0.20 master br-vlan20

# Поднять всё
ip link set eth0.10 up
ip link set eth0.20 up
ip link set br-vlan10 up
ip link set br-vlan20 up

# Виртуальные машины подключаются к соответствующему мосту
# VM1 → br-vlan10, VM2 → br-vlan20
```

### Решение с Open vSwitch

```bash
# Создать OVS мост
ovs-vsctl add-br ovs-br0

# Добавить физический интерфейс как trunk
ovs-vsctl add-port ovs-br0 eth0

# Создать внутренние порты для VLAN
ovs-vsctl add-port ovs-br0 vlan10 -- set interface vlan10 type=internal
ovs-vsctl set interface vlan10 options:tag=10

ovs-vsctl add-port ovs-br0 vlan20 -- set interface vlan20 type=internal
ovs-vsctl set interface vlan20 options:tag=20

# Назначить IP
ip addr add 192.168.10.1/24 dev vlan10
ip addr add 192.168.20.1/24 dev vlan20
```

---

## Сценарий 3: Меж-VLAN маршрутизация

**Задача:** Обеспечить связь между VLAN 10 и 20.

**SSoT:** Полная информация о маршрутизации между VLAN, включая схемы Router-on-a-Stick и сабинтерфейсы, доступна в **[VLAN (протокол)](../../Protocols/vlan.md#меж-vlan-маршрутизация-router-on-a-stick)**.

**Краткая настройка в Linux:**

```bash
# Включить IP forwarding
sysctl -w net.ipv4.ip_forward=1

# Создать VLAN-интерфейсы с IP
ip link add link eth0 name eth0.10 type vlan id 10
ip link add link eth0 name eth0.20 type vlan id 20

ip addr add 192.168.10.1/24 dev eth0.10
ip addr add 192.168.20.1/24 dev eth0.20

ip link set eth0.10 up
ip link set eth0.20 up
```

---

## Сценарий 4: Диагностика проблем VLAN

### Проблема 1: Нет связи между устройствами в одном VLAN

```bash
# Проверить VLAN на интерфейсе
ip -d link show eth0.10
# Ожидается: vlan id 10 ...

# Проверить таблицу ARP
ip neigh show dev eth0.10

# Проверить counters
ip -s link show eth0.10

# tcpdump для проверки тегов
tcpdump -i eth0 -e -n vlan
```

### Проблема 2: Трафик не проходит через trunk

```bash
# На коммутаторе проверить разрешённые VLAN
show interfaces trunk
show running-config interface Gi0/8

# Проверить native VLAN
show interfaces Gi0/8 switchport

# На Linux проверить получение тегов
tcpdump -i eth0 -e 'vlan[0:2] & 0x0fff = 10'
```

### Проблема 3: Медленная работа сети

```bash
# Проверить broadcast-трафик
tcpdump -i eth0 -c 1000 | grep -i broadcast | wc -l

# Проверить ошибки на интерфейсе
ip -s link show eth0
ethtool -S eth0 | grep -i error
```

---

## Ссылки

- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
- **[Дополнительная информация](./additional_info.md)** — маркировка и стандарты
