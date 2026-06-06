# Сетевые технологии Proxmox

## Определения

**Proxmox Networking** — это подсистема управления сетевыми ресурсами Proxmox Virtual Environment (PVE), построенная на базе стандартного стека Linux (Bridge, VLAN, Bonding) и расширенная возможностями программно-определяемых сетей (SDN).

**SDN (Software-Defined Networking)** — технология виртуализации сети, позволяющая создавать сложные сетевые топологии (зоны, виртуальные сети) поверх физической инфраструктуры.

**Linux Bridge (Мост)** — см. **[Linux Bridge](../../../Linux/Networking/Concepts/linux_bridge.md)**.

**MTU (Maximum Transmission Unit)** — максимальный размер полезного блока данных в одном пакете (кадре), передаваемого по сети без фрагментации.

## Основные концепции

### Модели сетевого взаимодействия

Proxmox VE (PVE) поддерживает три основные модели организации сети:

1. **Bridged (Мостовая)**: Самая распространенная модель. Виртуальные машины (VM) подключаются к виртуальному мосту (`vmbr0`), который привязан к физическому интерфейсу хоста. VM получают IP-адреса (Internet Protocol) из той же сети, что и хост.
2. **Routed (Маршрутизируемая)**: Хост выступает в роли маршрутизатора для VM. Позволяет экономить MAC-адреса (Media Access Control) и использовать несколько подсетей на одном интерфейсе.
3. **Masquerading (NAT — Network Address Translation)**: Внутренняя сеть для VM, скрытая за IP-адресом хоста. Используется для изоляции или при дефиците публичных IP-адресов.

### Виртуальные сети SDN (Software-Defined Networking)

Начиная с версии 8.1, SDN является встроенным функционалом Proxmox. Основные сущности:

- **Zones (Зоны)**: Определяют тип инкапсуляции и границы сети.
  - **Simple**: Изолированные мосты на уровне одной ноды.
  - **VLAN**: Поддержка стандартных тегированных сетей 802.1Q.
  - **VXLAN (Virtual Extensible LAN)**: Создание L2-сетей поверх L3-инфраструктуры (инкапсуляция в UDP-пакеты).
  - **EVPN (Ethernet Virtual Private Network)**: Продвинутая технология оверлейных сетей с использованием протокола BGP (Border Gateway Protocol) для синхронизации MAC-адресов между нодами.
- **VNET (Virtual Network)**: Логический коммутатор внутри зоны. Аналог `vmbr`, но управляемый через SDN-контроллер.
- **Subnets (Подсети)**: Диапазоны IP-адресов, привязанные к VNET, с поддержкой встроенного управления IPAM (IP Address Management).

### SDN Fabrics (Open Fabric)

Технология автоматической настройки маршрутизации внутри кластера Proxmox VE 9. Она позволяет строить высокоскоростные Mesh-сети между нодами (например, для трафика Ceph или миграции) без ручной настройки динамических протоколов маршрутизации.

## Практические сценарии

### Создание базового моста через CLI

Конфигурация сети в Proxmox хранится в файле `/etc/network/interfaces`. Для применения изменений рекомендуется использовать утилиту `ifupdown2`.

Пример добавления нового моста `vmbr1` через CLI:

```bash
# Добавить конфигурацию в файл
cat <<EOF >> /etc/network/interfaces

auto vmbr1
iface vmbr1 inet manual
    bridge-ports eth1
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-vids 2-4094
EOF

# Применить изменения без перезагрузки
ifreload -a
# → Exit code: 0
```

### Настройка VXLAN-зоны в SDN

Для работы VXLAN в кластере необходимо:

1. Перейти в `Datacenter -> SDN -> Zones -> Add -> VXLAN`.
2. Указать `ID` зоны и список `Peers` (IP-адреса всех нод кластера).
3. Создать `VNET` в этой зоне.
4. Создать `Subnet` внутри VNET (опционально для IPAM).
5. Нажать `Apply` в меню SDN для применения конфигурации на всех нодах кластера.

### Диагностика сетевых интерфейсов

Просмотр состояния мостов и подключенных к ним портов:

```bash
brctl show
# → bridge name     bridge id               STP enabled     interfaces
# → vmbr0           8000.a0369f4489a2       no              eth0
# →                                                         tap100i0
```

Просмотр таблицы MAC-адресов на мосту:

```bash
bridge fdb show dev vmbr0
# → 00:16:3e:00:01:01 vlan 1 master vmbr0 permanent
# → a0:36:9f:44:89:a2 master vmbr0 permanent
```

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [Кластеризация в Proxmox](./proxmox_cluster.md)
- [Архитектура SDN](../../Networking/Concepts/sdn/sdn_overview.md)
- [Технология VXLAN](../../Networking/Tunnels/vxlan.md)
- [Протокол UDP](../../Networking/Protocols/udp.md)
- [Linux Network Interfaces](../../Linux/Networking/Concepts/linux_network_interfaces.md)
