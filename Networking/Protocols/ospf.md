# OSPF (Open Shortest Path First)

## Определения

**OSPF (Open Shortest Path First)** — протокол динамической маршрутизации на основе состояния каналов (Link-State), работающий внутри одной автономной системы (IGP). Стандартизирован IETF (RFC 2328 для IPv4, RFC 5340 для IPv6). В отличие от дистанционно-векторных протоколов, OSPF строит полное математическое дерево (карту) всей сети с помощью алгоритма Дейкстры (SPF — Shortest Path First), обеспечивая маршрутизацию без петель и сверхбыструю сходимость.

**Ключевая особенность:** Каждый маршрутизатор в OSPF-домене обладает одинаковой и полной базой данных о топологии сети (LSDB) и самостоятельно вычисляет кратчайшие пути до всех подсетей назначения.

> **См. также:** [BGP](./bgp.md), [Протоколы и оборудование](../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md)

## Основные концепции

### Иерархическая структура и Зоны (Areas)

OSPF использует концепцию зон (Areas) для разделения большой сети на логические сегменты. Это снижает размер таблиц маршрутизации, уменьшает нагрузку на CPU (пересчет SPF происходит реже) и локализует влияние нестабильных линков (flapping).

*   **Area 0 (Backbone Area):** Магистральная зона. Центр OSPF-сети. Все остальные зоны обязаны иметь физическое или логическое (Virtual Link) подключение к Area 0.
*   **Standard Area:** Обычная зона, обменивающаяся всеми маршрутами.
*   **Stub Area (Тупиковая зона):** Не принимает внешние маршруты (от других протоколов, например, BGP). Вместо них использует маршрут по умолчанию (0.0.0.0/0).
*   **Totally Stubby Area:** Не принимает ни внешние маршруты, ни маршруты из других зон OSPF (Inter-area). Использует только default route.
*   **NSSA (Not-So-Stubby Area):** Тупиковая зона, которой разрешено импортировать небольшое количество внешних маршрутов через специальный тип LSA.

### Типы маршрутизаторов

*   **Internal Router (Внутренний):** Все интерфейсы находятся в одной зоне.
*   **Backbone Router:** Хотя бы один интерфейс находится в Area 0.
*   **ABR (Area Border Router):** Пограничный маршрутизатор между зонами. Имеет интерфейсы в Area 0 и одной или нескольких других зонах.
*   **ASBR (Autonomous System Boundary Router):** Маршрутизатор, импортирующий (redistribute) маршруты из других протоколов (BGP, EIGRP, статика) в домен OSPF.

### Выборы DR и BDR

В сетях со множественным доступом (Broadcast, например Ethernet) OSPF не устанавливает соседство "каждый с каждым" (full mesh), чтобы избежать шторма пакетов. Вместо этого выбираются:
*   **DR (Designated Router):** Главный маршрутизатор в сегменте, который собирает и рассылает информацию всем остальным (DROther).
*   **BDR (Backup Designated Router):** Резервный главный маршрутизатор.

**Принцип выборов:**
1.  Высший OSPF Priority (по умолчанию 1, значение 0 означает отказ от участия в выборах).
2.  Высший Router ID (Loopback-адрес, если есть, иначе старший активный физический IP).

### LSA (Link State Advertisement) и LSDB

**LSA** — объявления о состоянии каналов, которыми обмениваются OSPF-маршрутизаторы. Совокупность всех LSA образует **LSDB** (Link State Database).

**Основные типы LSA:**
*   **Type 1 (Router LSA):** Генерируется каждым роутером, описывает его линки. Не выходит за пределы зоны.
*   **Type 2 (Network LSA):** Генерируется DR в broadcast-сети, содержит список подключенных к нему соседей.
*   **Type 3 (Summary LSA):** Генерируется ABR для передачи информации о сетях между зонами.
*   **Type 4 (ASBR Summary LSA):** Генерируется ABR для указания пути к ASBR.
*   **Type 5 (External LSA):** Генерируется ASBR для анонсирования маршрутов, импортированных извне (например, BGP или статика).
*   **Type 7 (NSSA External LSA):** Генерируется ASBR внутри NSSA-зоны (преобразуется в Type 5 на ABR).

### OSPF Cost

**Cost** — метрика OSPF, используемая алгоритмом Дейкстры для выбора наилучшего пути. Вычисляется как `Reference Bandwidth / Interface Bandwidth` (по умолчанию `10^8 / bandwidth` в бит/с, то есть 100 Мбит/с имеет Cost 1).
Чем выше пропускная способность — тем ниже Cost. Путь с наименьшей суммой Cost до цели становится активным в таблице маршрутизации.

**Проблема:** В современных сетях интерфейсы 100 Мбит/с, 1 Гбит/с и 10 Гбит/с будут иметь одинаковый Cost = 1 (так как значение не может быть меньше 1).
**Решение:** Требуется изменение `auto-cost reference-bandwidth` на всех роутерах домена (например, до 100000 для 100G) или ручная установка стоимости.

### OSPF Passive Interface

**Passive Interface** — режим, при котором OSPF не отправляет hello-пакеты и не устанавливает соседства на интерфейсе, но при этом анонсирует префикс этого интерфейса в OSPF-область.

**Назначение:** Защита от спуфинга и лишней нагрузки. Применяется на интерфейсах, направленных к конечным пользователям или серверам, где нет других OSPF-маршрутизаторов.

## Практические сценарии

### Настройка OSPF Cost

**Cisco:**
```cisco
interface GigabitEthernet0/1
  ip ospf cost 10

interface GigabitEthernet0/2
  ip ospf cost 20
```

**MikroTik (RouterOS v7):**
```bash
/routing ospf interface-template
add cost=10 interfaces=ether1
add cost=20 interfaces=ether2
```

### Настройка Passive Interface

**Cisco (блокировка всего, открытие нужного):**
```cisco
router ospf 1
  passive-interface default
  no passive-interface GigabitEthernet0/0
```

**MikroTik (RouterOS v7):**
```bash
/routing ospf interface-template
add interfaces=ether1 passive
```

### Базовая настройка OSPF (Single Area 0) на MikroTik

Объединение нескольких подсетей в Backbone Area 0.

```bash
# 1. Создание инстанса и установка Router ID
/routing ospf instance
add name=default-ospf router-id=1.1.1.1

# 2. Создание Area 0
/routing ospf area
add instance=default-ospf name=backbone area-id=0.0.0.0

# 3. Добавление сетей в процесс OSPF
/routing ospf interface-template
add area=backbone interfaces=ether1 networks=192.168.10.0/24
add area=backbone interfaces=ether2 networks=192.168.20.0/24
```

### Базовая настройка OSPF на Cisco

```cisco
router ospf 1
  router-id 1.1.1.1
  network 192.168.10.0 0.0.0.255 area 0
  network 192.168.20.0 0.0.0.255 area 0
```

### Диагностика OSPF

**Cisco:**
*   `show ip ospf neighbor` — статус соседств (Full, 2-Way, ExStart).
*   `show ip ospf database` — просмотр LSDB.
*   `show ip route ospf` — таблица маршрутизации (маршруты O).

**MikroTik:**
*   `/routing ospf neighbor print` — список соседей.
*   `/routing ospf lsa print` — содержимое базы LSA.
*   `/ip route print where ospf` — маршруты, полученные по OSPF.

## Дополнительная информация

- [BGP](./bgp.md) — протокол внешней маршрутизации
- [Сетевой уровень](../OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md) — основы маршрутизации
- [Протоколы и оборудование](../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md) — обзор протоколов маршрутизации
