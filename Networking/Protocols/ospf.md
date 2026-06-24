# OSPF (Open Shortest Path First)

## Определения

**OSPF (Open Shortest Path First)** — протокол динамической маршрутизации, работающий внутри одной автономной системы (IGP). Использует алгоритм состояния каналов (Link State) для построения кратчайших путей. Быстро адаптируется к изменениям топологии сети.

> **См. также:** [BGP](./bgp.md), [Протоколы и оборудование](../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md)

## Основные концепции

### OSPF Passive Interface

**Passive Interface** — режим интерфейса в OSPF, при котором OSPF не отправляет hello-пакеты и не устанавливает соседства на этом интерфейсе. Маршруты из его подсети продолжают анонсироваться в OSPF-область.

**Назначение:** предотвращение лишних OSPF-соседств на интерфейсах, где подключены только конечные устройства (ПК, серверы).

**Настройка на Cisco:**

```cisco
router ospf 1
  passive-interface GigabitEthernet0/1
```

Если нужно оставить активным только один интерфейс:

```cisco
router ospf 1
  passive-interface default
  no passive-interface GigabitEthernet0/0
```

**Настройка на MikroTik:**

```
/routing ospf interface
set [ find interface="ether1" ] passive=yes
```

### OSPF Cost

**Cost** — метрика OSPF, используемая для выбора наилучшего пути. По умолчанию вычисляется как `10^8 / bandwidth` (в бит/с). Чем выше пропускная способность — тем ниже Cost, тем предпочтительнее маршрут.

Cost можно задать вручную для управления приоритетом линков.

**Настройка на Cisco:**

```cisco
interface GigabitEthernet0/1
  ip ospf cost 10

interface GigabitEthernet0/2
  ip ospf cost 20
```

**Настройка на MikroTik:**

```
/routing ospf interface
set [ find interface="ether1" ] cost=10
set [ find interface="ether2" ] cost=20
```

**Проверка:**

- Cisco: `show ip route ospf`, `show ip ospf neighbor`
- MikroTik: `/routing ospf route print`

## Практические сценарии

### OSPF single area на MikroTik

Базовая настройка OSPF для объединения нескольких подсетей в одну область (Area 0):

```bash
# Установка Router ID
/routing ospf instance set default router-id=1.1.1.1

# Добавление сетей в backbone area
/routing ospf network add network=192.168.10.0/24 area=backbone
/routing ospf network add network=192.168.20.0/24 area=backbone
```

**Проверка соседей и маршрутов:**

```bash
/routing ospf neighbor print
/ip route print
```

## Дополнительная информация

- [BGP](./bgp.md) — протокол внешней маршрутизации
- [Сетевой уровень](../OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md) — основы маршрутизации
- [Протоколы и оборудование](../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md) — обзор протоколов маршрутизации
