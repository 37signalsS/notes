# L2 Switching и VLAN: Практическое руководство

## Определения

**Коммутатор (Switch)** — устройство канального уровня (L2), пересылающее кадры между устройствами на основе [MAC-адресов](./mac_address.md).

**Broadcast-домен** — сегмент сети, где все устройства получают широковещательные пакеты друг друга. По умолчанию один коммутатор = один broadcast-домен.

**VLAN** — технология логического разделения broadcast-доменов. Подробное описание протокола 802.1Q см. в **[VLAN (протокол)](../Protocols/vlan.md)**.

## Базовые концепции

### Принцип работы коммутатора

Коммутатор работает с **таблицей MAC-адресов** (MAC address table, CAM table):

**Процесс коммутации:**
```
1. Кадр поступает на порт → коммутатор запоминает:
   Source MAC → Port X (запись в таблицу)

2. Коммутатор смотрит Destination MAC:
   ├─ Известен (есть в таблице) → унитарная отправка на конкретный порт
   ├─ Неизвестен → flooding на все порты (кроме входного)
   └─ Broadcast/Multicast → flooding на все порты
```

**Пример таблицы MAC-адресов:**
```
MAC Address       VLAN    Port
--------------    ----    ----
00:1A:2B:3C:4D:5E 10      Gi0/1
00:1A:2B:3C:4D:5F 10      Gi0/2
00:1A:2B:3C:4D:60 20      Gi0/3
```

### Сегментация сети с помощью VLAN

**Зачем делить сеть на VLAN:**

| Причина | Описание |
|---------|----------|
| **Изоляция** | Устройства в разных VLAN не видят друг друга на L2 |
| **Безопасность** | Критичные сервисы (серверы, управление) в отдельном VLAN |
| **Производительность** | Broadcast-трафик не распространяется за пределы VLAN |
| **Гибкость** | Группировка по отделам/проектам, а не физическому расположению |

**Пример сегментации:**
```
                    [Core Switch]
                         |
        +----------------+----------------+
        |                |                |
   [VLAN 10]        [VLAN 20]        [VLAN 30]
   Users            Servers          Management
   192.168.10.0/24  192.168.20.0/24  192.168.30.0/24
```

## Практические сценарии

### Сценарий 2: Настройка VLAN в Linux

**Задача:** Сервер подключён к trunk-порту, нужны интерфейсы для VLAN 10 и 20.

**Вариант A: Временная настройка (iproute2)**
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

**Вариант B: NetworkManager (nmtui/nmcli)**
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

**Вариант C: Netplan (Ubuntu 18.04+)**
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

### Сценарий 3: VLAN на гипервизоре (KVM/QEMU)

**Задача:** Виртуальные машины на одном гипервизоре должны быть в разных VLAN.

**Решение с Linux Bridge:**
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

**Решение с Open vSwitch:**
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

### Сценарий 4: Меж-VLAN маршрутизация (Router-on-a-Stick)

**Задача:** Обеспечить связь между VLAN 10 и 20 через маршрутизатор.

**Топология:**
```
[Users VLAN 10] ----+
                    |
              [Router]
                    |
[Servers VLAN 20] --+
```

**Конфигурация роутера (Cisco):**
```cisco
interface GigabitEthernet0/0.10
 encapsulation dot1Q 10
 ip address 192.168.10.1 255.255.255.0

interface GigabitEthernet0/0.20
 encapsulation dot1Q 20
 ip address 192.168.20.1 255.255.255.0
```

**Конфигурация Linux (iproute2):**
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

# Настроить NAT (если нужен выход в интернет)
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
```

### Сценарий 5: Диагностика проблем VLAN

**Проблема 1: Нет связи между устройствами в одном VLAN**

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

**Проблема 2: Трафик не проходит через trunk**

```bash
# На коммутаторе проверить разрешённые VLAN
show interfaces trunk
show running-config interface Gi0/8

# Проверить native VLAN
show interfaces Gi0/8 switchport

# На Linux проверить получение тегов
tcpdump -i eth0 -e 'vlan[0:2] & 0x0fff = 10'
```

**Проблема 3: Медленная работа сети**

```bash
# Проверить broadcast-трафик
tcpdump -i eth0 -c 1000 | grep -i broadcast | wc -l

# Проверить ошибки на интерфейсе
ip -s link show eth0
ethtool -S eth0 | grep -i error
```

## Дополнительная информация

### Маркировка кабелей и портов

**Правильная маркировка критична для поддержки VLAN:**

**Стандарты:**
- **Двусторонняя маркировка:** Оба конца кабеля маркируются
- **Формат:** `Откуда → Куда` (например, `SW1-P24 → SRV3-eth0`)
- **VLAN информация:** На коммутаторе указать VLAN ID на порту

**Пример маркировки:**
```
Порт коммутатора:
  Gi0/1  [VLAN 10]  →  SRV1-eth0  (Users)
  Gi0/2  [VLAN 20]  →  SRV1-eth1  (Servers)
  Gi0/24 [TRUNK]    →  SW2-Gi0/1

Кабель:
  [SW1-P24] ====== [SW2-P1]
  CAT6A, 2024-03-15
```

### Связанные документы

**Протоколы:**
- **[VLAN 802.1Q](../Protocols/vlan.md)** — детальное описание протокола
- **[STP](../Protocols/stp.md)** — предотвращение петель
- **[Ethernet](../Protocols/ethernet.md)** — формат кадров

**Концепции:**
- **[MAC-адреса](./mac_address.md)** — адресация L2
- **[Сетевая сегментация](./network_segmentation_and_microsegmentation.md)** — стратегии
- **[NAT](./nat.md)** — трансляция адресов
