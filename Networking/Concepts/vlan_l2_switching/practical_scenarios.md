# L2 Switching и VLAN: Практические сценарии

## Определения

*   **iproute2** — основной набор утилит для управления сетевым стеком в Linux. См. **[iproute2: Обзор](../../../Linux/Networking/Tools/iproute2/overview.md)**.
*   **Linux Bridge** — программная реализация L2-коммутатора в ядре. См. **[Linux Bridge](../../../Linux/Networking/Concepts/linux_bridge.md)**.
*   **Open vSwitch (OVS)** — продвинутый виртуальный коммутатор для многоузловых сред. См. **[Open vSwitch (OVS)](../../ServicesAndTools/open_vswitch.md)**.
*   **Docker macvlan/ipvlan** — сетевые драйверы для прямого подключения контейнеров к L2-сегментам хоста.

## Базовые концепции

Перед выполнением сценариев изучите теоретическую базу в **[Определения и концепции L2 Switching и VLAN](./definitions_and_concepts.md)**.

### Ключевые принципы настройки в Linux

1.  **Сабинтерфейсы:** VLAN-интерфейсы создаются поверх физического адаптера (NIC) и имеют формат `имя.vlan_id` (например, `eth0.10`).
2.  **Trunk-порт:** Физический интерфейс хоста должен быть подключён к порту коммутатора, настроенному в режиме `trunk` с разрешёнными VLAN ID.
3.  **Forwarding:** Для реализации маршрутизации между VLAN на Linux-хосте должен быть включён параметр ядра `net.ipv4.ip_forward=1`.
4.  **MTU и тегирование:** При использовании 802.1Q к кадру добавляется 4 байта. Современные NIC поддерживают это автоматически, но в Q-in-Q или при использовании старого оборудования может потребоваться корректировка MTU.

## Практические сценарии

### Сценарий 1: Настройка VLAN в Linux (Host-уровень)

**Задача:** Настроить доступ к двум изолированным сетям (VLAN 10 и 20) через один физический интерфейс `eth0`.

#### Вариант A: Временная настройка (iproute2)
Используется для быстрой проверки или в скриптах автоматизации.

```bash
# Создание интерфейсов
sudo ip link add link eth0 name eth0.10 type vlan id 10
sudo ip link add link eth0 name eth0.20 type vlan id 20

# Назначение IP-адресов
sudo ip addr add 192.168.10.100/24 dev eth0.10
sudo ip addr add 192.168.20.100/24 dev eth0.20

# Активация
sudo ip link set eth0.10 up
sudo ip link set eth0.20 up
```

#### Вариант B: Постоянная настройка (Netplan / Ubuntu)
Рекомендуемый способ для современных дистрибутивов на базе Ubuntu/Debian. Подробности см. в **[Настройка Netplan](../../../Linux/Networking/Settings/Persistent_Network/ubuntu_netplan.md)**.

```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
  vlans:
    eth0.10:
      id: 10
      link: eth0
      addresses: [192.168.10.100/24]
    eth0.20:
      id: 20
      link: eth0
      addresses: [192.168.20.100/24]
```

#### Вариант C: Облачная инициализация (Cloud-init)
Используется при развертывании виртуальных машин в облаках (OpenStack, Proxmox, AWS).

```yaml
# cloud-config
network:
  version: 2
  vlans:
    vlan10:
      id: 10
      link: eth0
      addresses:
        - 192.168.10.50/24
```

---

### Сценарий 2: Контейнеризация (Docker macvlan)

**Задача:** Запустить контейнер, который будет виден в сети VLAN 10 как отдельное физическое устройство со своим MAC-адресом.

```bash
# Создание Docker-сети типа macvlan, привязанной к сабинтерфейсу хоста
docker network create -d macvlan \
  --subnet=192.168.10.0/24 \
  --gateway=192.168.10.1 \
  -o parent=eth0.10 \
  vlan10_net

# Запуск контейнера в этой сети
docker run -d --name web-vlan10 --network vlan10_net nginx
```

---

### Сценарий 3: Виртуализация (KVM/QEMU)

**Задача:** Изолировать трафик виртуальных машин с помощью Linux Bridge.

```bash
# Создание моста и привязка к нему VLAN-интерфейса
sudo ip link add name br-vlan10 type bridge
sudo ip link set eth0.10 master br-vlan10

# Поднятие интерфейсов
sudo ip link set br-vlan10 up

# В настройках VM (libvirt/virt-manager) указать Bridge 'br-vlan10'
```

---

### Сценарий 4: Меж-VLAN маршрутизация (Router-on-a-Stick)

**Задача:** Сделать Linux-хост маршрутизатором между VLAN 10 и 20.

```bash
# 1. Включение маршрутизации
sudo sysctl -w net.ipv4.ip_forward=1

# 2. Настройка IP на сабинтерфейсах (шлюзы для подсетей)
sudo ip addr add 192.168.10.1/24 dev eth0.10
sudo ip addr add 192.168.20.1/24 dev eth0.20

# 3. Настройка правил доступа (iptables/nftables)
# Разрешить трафик между VLAN
sudo iptables -A FORWARD -i eth0.10 -o eth0.20 -j ACCEPT
sudo iptables -A FORWARD -i eth0.20 -o eth0.10 -j ACCEPT
```

---

### Сценарий 5: Диагностика и поиск неисправностей

#### Проверка наличия тегов (tcpdump)
Критически важно убедиться, что коммутатор действительно присылает тегированный трафик.

```bash
# Просмотр Ethernet-заголовков на физическом интерфейсе
sudo tcpdump -i eth0 -e -n vlan
# Ожидаемый вывод: ... vlan 10, p 0, ethertype IPv4 ...
```

#### Проверка связности без IP (arping)
Позволяет проверить L2-связность, даже если IP-адреса настроены неверно.

```bash
sudo arping -I eth0.10 192.168.10.1
```

#### Типичные ошибки
- **Native VLAN Mismatch:** Если на одном конце транка Native VLAN 1, а на другом 99, трафик будет попадать в неверные сегменты.
- **VLAN Pruning:** Убедитесь, что нужный VLAN добавлен в список разрешённых на портах всех коммутаторов по пути следования трафика (`allowed vlan`).

## Дополнительная информация

### Маркировка кабелей и портов

Для поддержки сложных VLAN-структур обязательна физическая маркировка оборудования.

**Пример документирования порта:**
```text
Port: Gi0/24
Config: Mode=Trunk, Native=99, Allowed=10,20,30
Destination: SRV-PROD-01 (eth0)
```

**Связанные документы:**
- **[VLAN: Определения и концепции](./definitions_and_concepts.md)** — теоретическая база.
- **[Настройка Netplan](../../../Linux/Networking/Settings/Persistent_Network/ubuntu_netplan.md)** — полные примеры конфигурации.
- **[VLAN в Linux: Диагностика](../../Protocols/VLAN/vlan_linux_diagnostics.md)** — расширенный список команд для отладки.
