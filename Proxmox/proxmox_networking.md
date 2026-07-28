---
Надёжность: 10 (SSoT + Проектный контекст 2026)
Свежесть: Актуально на июль 2026
---

# Сетевые технологии Proxmox

## Определения

**Proxmox Networking** — подсистема управления сетевыми ресурсами Proxmox Virtual Environment (PVE), построенная на базе стандартного стека Linux (Bridge, VLAN, Bonding) и расширенная возможностями программно-определяемых сетей (SDN).

**SDN (Software-Defined Networking)** — технология виртуализации сети, позволяющая создавать сложные топологии (зоны, виртуальные сети) поверх физической инфраструктуры без изменения конфигурации коммутаторов. Подробнее: **[Обзор SDN](../Networking/Concepts/sdn/sdn_overview.md)**.

**Linux Bridge** — программная реализация коммутатора (L2), позволяющая виртуальным машинам и контейнерам взаимодействовать друг с другом и с внешней сетью.

## Основные концепции

### Модели сетевого взаимодействия

1. **Bridged (Мостовая)**: Основная модель. Виртуальные интерфейсы подключаются к `vmbr0` (аналог виртуального коммутатора). VM получают IP-адреса из физической сети.
2. **Routed (Маршрутизируемая)**: Хост выступает маршрутизатором (L3). Позволяет избежать проблем с безопасностью MAC-адресов в публичных облаках.
3. **Masquerading (NAT)**: Внутренняя частная сеть для ресурсов PVE, скрытая за IP-адресом хоста. Используется при дефиците публичных адресов.

### Агрегация каналов (Bonding)

Объединение нескольких физических интерфейсов в один логический (`bond0`) для отказоустойчивости и повышения пропускной способности.
- **802.3ad (LACP)**: Рекомендуемый режим для продакшена. Требует поддержки со стороны физического коммутатора.
- **Active-Backup**: Простейший режим отказоустойчивости, не требующий настройки коммутатора.
- **SSoT:** Подробное описание режимов см. в **[Агрегация каналов](../../Networking/Concepts/link_aggregation.md)**.

### Программно-определяемые сети (SDN)

В PVE 8.x/9 SDN является встроенным функционалом, позволяющим автоматизировать настройку сетей в кластере.

- **Zones (Зоны)**: Границы вещания (L2 сегментация).
  - **Simple**: Локальные сети в рамках одной ноды.
  - **VLAN**: Стандартная сегментация 802.1Q.
  - **VXLAN**: Создание L2 оверлея поверх L3 сети. Идеально для растянутых кластеров.
  - **EVPN**: Использование протокола BGP для управления MAC-адресами в VXLAN сетях.
- **VNET (Virtual Network)**: Виртуальный коммутатор, к которому подключаются сетевые карты VM/LXC.
- **IPAM (IP Address Management)**: Встроенное управление диапазонами адресов (поддержка внутренних PVE-диапазонов, Netbox, phpIPAM).

### SDN Fabrics (Open Fabric)

Технология автоматической настройки Mesh-сетей в PVE 9. Основана на протоколе **OpenFabric** (упрощенный IS-IS).
- **Назначение**: Автоматическая прокладка маршрутов между нодами для трафика Ceph, миграции и SDN без ручной настройки BGP.

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

### Настройка VXLAN в SDN

1. **Создание зоны**: `Datacenter -> SDN -> Zones -> Add -> VXLAN`. Указать ID и список IP-адресов нод-пиров.
2. **Создание VNET**: Привязать VNET к созданной VXLAN зоне.
3. **Применение**: Нажать кнопку **Apply** в разделе SDN. Это создаст необходимые интерфейсы на всех нодах кластера.

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

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [Кластеризация в Proxmox](./proxmox_cluster.md)
- [Архитектура SDN](../Networking/Concepts/sdn/sdn_overview.md)
- [Технология VXLAN](../Networking/Tunnels/vxlan.md)
- [Linux Network Interfaces](../Linux/Networking/Concepts/linux_network_interfaces.md)
- [Агрегация каналов (Bonding)](../../Networking/Concepts/link_aggregation.md)
