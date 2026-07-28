# Open vSwitch (OVS) — программный коммутатор

## Определения

**Open vSwitch (OVS)** — это высокопроизводительный многоуровневый программный коммутатор с открытым исходным кодом, оптимизированный для работы в виртуализированных и динамических средах. В отличие от стандартного Linux Bridge, OVS спроектирован для поддержки программно-определяемых сетей (SDN) и расширенных протоколов управления.

**OVN (Open Virtual Network)** — это надстройка над OVS, обеспечивающая сетевую абстракцию более высокого уровня (L2/L3, логические мосты, маршрутизаторы, ACL, балансировщики). Является современным стандартом управления OVS в OpenStack и Kubernetes (через OVN-Kubernetes).

## Основные концепции

### Архитектура OVS

Система разделена на три функциональных блока:

1.  **ovs-vswitchd**: Демон пространства пользователя (userspace). Реализует «интеллект» коммутатора: обработку логики OpenFlow, управление таблицами потоков и взаимодействие с SDN-контроллерами.
2.  **ovsdb-server**: Легковесная база данных (JSON-RPC), хранящая конфигурацию (мосты, порты, параметры QoS, туннели). Конфигурация сохраняется после перезагрузки.
3.  **Datapath (Kernel Module / DPDK)**: Компонент плоскости данных (forwarding plane).
    *   **openvswitch.ko**: Модуль ядра Linux для быстрой пересылки. Использует кеширование потоков (fast path).
    *   **Userspace Datapath (DPDK)**: Позволяет обрабатывать пакеты полностью вне ядра для достижения максимальной производительности.

### Ключевые сущности

*   **Bridge (Мост)**: Виртуальный коммутатор. Один экземпляр OVS может поддерживать множество независимых мостов.
*   **Port (Порт)**: Точка входа/выхода трафика. Типы:
    *   `Physical`: Привязка к физическому NIC.
    *   `Internal`: Виртуальный интерфейс для связи с хостом (например, для назначения IP мосту).
    *   `Tunnel`: Инкапсуляция (VXLAN, GRE, Geneve).
    *   `Patch`: Соединение двух мостов внутри одного экземпляра OVS.
*   **Flow (Поток)**: Набор правил в таблице OpenFlow. Состоит из условий сопоставления (L2-L4 заголовки) и действий (отправить в порт, изменить заголовок, отбросить).

### Механизмы мониторинга и телеметрии

OVS поддерживает современные стандарты сбора статистики:
*   **NetFlow/IPFIX**: Сбор данных об IP-потоках.
*   **sFlow**: Статистическое сэмплирование пакетов.
*   **Port Mirroring (SPAN/RSPAN)**: Копирование трафика порта для анализа.

## Практические сценарии

### Управление конфигурацией (ovs-vsctl)

Основная утилита для настройки структуры коммутатора.

```bash
# Просмотр всей иерархии (мосты, порты, интерфейсы)
ovs-vsctl show

# Создание моста и добавление интерфейсов
ovs-vsctl add-br br-int
ovs-vsctl add-port br-int eth0

# Настройка внутреннего интерфейса для управления
ovs-vsctl add-port br-int mgmt0 -- set Interface mgmt0 type=internal
ip addr add 192.168.1.10/24 dev mgmt0
ip link set mgmt0 up
```

### Настройка VLAN (802.1Q)

```bash
# Порт в режиме Access (VLAN 10)
ovs-vsctl add-port br-int vnet0 tag=10

# Порт в режиме Trunk (разрешить VLAN 10, 20, 30)
ovs-vsctl set port eth0 trunks=10,20,30

# Динамическое изменение тега
ovs-vsctl set port vnet0 tag=20
```

### Настройка туннелей (VXLAN)

OVS часто используется как VTEP (VXLAN Tunnel End Point).

```bash
# Создание туннеля к удаленному хосту
ovs-vsctl add-port br-int vxlan0 -- set interface vxlan0 type=vxlan options:remote_ip=172.16.1.5
```

### Управление потоками (ovs-ofctl)

Низкоуровневая работа с OpenFlow.

```bash
# Просмотр установленных правил
ovs-ofctl dump-flows br-int

# Добавление правила: переслать пакеты с порта 1 на порт 2 (приоритет 100)
ovs-ofctl add-flow br-int "priority=100, in_port=1, actions=output:2"

# Глобальное правило "отбросить всё остальное" (Drop)
ovs-ofctl add-flow br-int "priority=0, actions=drop"
```

### Отладка и диагностика (ovs-appctl)

Утилита для взаимодействия с запущенными демонами.

```bash
# Проверка состояния таблицы MAC-адресов
ovs-appctl fdb/show br-int

# Трассировка обработки пакета логикой OpenFlow (эмуляция)
ovs-appctl ofproto/trace br-int in_port=1,dl_src=52:54:00:11:22:33,dl_dst=52:54:00:44:55:66
```

### Интеграция с DPDK

Для сценариев NFV (Network Function Virtualization) и высоконагруженных облаков.

```bash
# Инициализация DPDK (требует настройки HugePages в ОС)
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true

# Создание моста с datapath в userspace
ovs-vsctl add-br br-dpdk -- set bridge br-dpdk datapath_type=netdev

# Добавление порта DPDK
ovs-vsctl add-port br-dpdk dpdk0 -- set Interface dpdk0 type=dpdk options:dpdk-devargs=0000:04:00.0
```
Подробности см. в **[Практические сценарии DPDK и SR-IOV](../Concepts/dpdk/scenarios.md)**.

## Дополнительная информация

### Сравнение с Linux Bridge

| Характеристика | Linux Bridge | Open vSwitch |
| :--- | :--- | :--- |
| **Реализация** | Целиком в ядре Linux | Гибридная (Kernel + Userspace) |
| **Управление** | `ip link`, `bridge` | `ovs-vsctl`, `ovs-ofctl`, `ovsdb` |
| **Поддержка SDN** | Нет | Полная (OpenFlow, OVN) |
| **Туннелирование** | Требует создания устройств в ОС | Интегрировано в коммутатор |
| **Производительность** | Высокая (низкие накладные расходы) | Экстремальная (с DPDK) |
| **Сложность** | Низкая | Высокая |

### Связанные темы

- **[SDN (Software-Defined Networking) Обзор](../Concepts/sdn/sdn_overview.md)**
- **[OpenFlow Протокол](../Concepts/sdn/openflow.md)**
- **[L2 Switching и VLAN: Практические сценарии](../Concepts/vlan_l2_switching/practical_scenarios.md)**
- **[Обзор DPDK](../Concepts/dpdk/dpdk_overview.md)**
