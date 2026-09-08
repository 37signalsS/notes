# VLAN — виртуальные локальные сети

## Определения

**VLAN (Virtual Local Area Network — виртуальная локальная сеть)** — технология канального уровня (L2), позволяющая логически разделить одну физическую сетевую инфраструктуру на несколько независимых широковещательных доменов.

**Широковещательный домен (Broadcast Domain)** — сегмент сети, в котором широковещательный кадр (с MAC-адресом назначения `FF:FF:FF:FF:FF:FF`) доставляется всем устройствам. VLAN ограничивает распространение таких кадров рамками одного идентификатора (VLAN ID).

**IEEE 802.1Q** — основной промышленный стандарт тегирования трафика, определяющий добавление 4-байтового тега в Ethernet-кадр для идентификации принадлежности к конкретной VLAN.

> **См. также:** **[Формат кадра 802.1Q](./VLAN/vlan_8021q_frame.md)**, **[Модель OSI](../OSI_TCP_IP_Model/osi_model.md)**

### Визуальный обзор VLAN в сетевой инфраструктуре

```
                        ┌─────────────────────────────────────────────┐
                        │              СЕТЬ БЕЗ VLAN                  │
                        │  Все устройства в одном broadcast-домене    │
                        │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │
                        │  │ PC1 │ │ PC2 │ │ PC3 │ │ PC4 │          │
                        │  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘          │
                        └─────┼───────┼───────┼───────┼──────────────┘
                              │       │       │       │
                         ┌────┴───────┴───────┴───────┴────┐
                         │      Коммутатор (L2)             │
                         └─────────────────────────────────┘
                                   │ Broadcast
                                   │ storms
                                   ▼

                        ┌─────────────────────────────────────────────┐
                        │              СЕТЬ С VLAN                    │
                        │  Логическое разделение                      │
                        │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │
                        │  │PC1  │ │PC2  │ │PC3  │ │PC4  │          │
                        │  │VLAN │ │VLAN │ │VLAN │ │VLAN │          │
                        │  │ 10  │ │ 10  │ │ 20  │ │ 20  │          │
                        │  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘          │
                        └─────┼───────┼───────┼───────┼──────────────┘
                              │       │       │       │
                         ┌────┴───────┴───────┴───────┴────┐
                         │      Коммутатор (L2)             │
                         │  ┌──────────┐  ┌──────────┐     │
                         │  │ VLAN 10  │  │ VLAN 20  │     │
                         │  │ Broadcast│  │ Broadcast│     │
                         │  │ Domain   │  │ Domain   │     │
                         │  └──────────┘  └──────────┘     │
                         └─────────────────────────────────┘
                                    │
                          Трафик между VLAN
                          только через L3
                                    │
                         ┌──────────┴──────────┐
                         │  Маршрутизатор / L3   │
                         │  коммутатор (Inter-   │
                         │  VLAN routing)        │
                         └──────────────────────┘
```

## Основные концепции

### Назначение и преимущества

Использование VLAN позволяет группировать устройства по логическому признаку, независимо от их физического расположения.

| Преимущество | Описание |
| :--- | :--- |
| **Изоляция трафика** | Устройства в разных VLAN изолированы на L2. Это предотвращает утечку данных и широковещательные штормы. |
| **Повышение безопасности** | Критически важные сегменты (управление, БД) отделяются от общих сетей. |
| **Оптимизация** | Уменьшение размера широковещательного домена снижает нагрузку на CPU хостов. |
| **Гибкость** | Перемещение пользователя в другой отдел требует смены настроек порта, а не перекладки кабеля. |

### Типы портов коммутатора

1. **Access-порт (порт доступа):** принадлежит одной VLAN. Предназначен для подключения конечных устройств (ПК, серверы), не понимающих тегирование. Весь входящий нетегированный трафик помечается VLAN ID порта (PVID).
2. **Trunk-порт (магистральный порт):** передаёт трафик нескольких VLAN одновременно. Кадры тегируются согласно 802.1Q. Используется для связи коммутаторов или подключения к гипервизорам.
3. **Hybrid-порт:** специфичен для некоторых вендоров (Huawei, HP). Может передавать как тегированный, так и нетегированный трафик для разных VLAN на одном порту.
4. **Voice VLAN:** специальный режим access-порта (преимущественно Cisco), позволяющий передавать нетегированный трафик данных и тегированный трафик голоса одновременно.

### Принцип работы коммутации с VLAN

1. **Ingress (Приём):** коммутатор сопоставляет входящий кадр с VLAN ID (по тегу или по настройке порта).
2. **Коммутация:** решение о пересылке принимается только в пределах портов, принадлежащих этой же VLAN.
3. **Trunking:** если получатель на другом коммутаторе, в кадр вставляется тег 802.1Q.
4. **Egress (Выдача):** перед передачей в access-порт тег удаляется (untagging).

### Диапазоны VLAN ID

Согласно стандарту 802.1Q, поле VID имеет длину 12 бит, что дает 4096 значений (0–4095).

| Диапазон | ID | Описание |
| :--- | :--- | :--- |
| **Reserved** | 0, 4095 | Зарезервированы для системных целей (например, приоритезация трафика без ID). |
| **Normal** | 1–1005 | Стандартный диапазон. ID 1 — Default VLAN. 1002–1005 зарезервированы для Token Ring/FDDI. |
| **Extended** | 1006–4094 | Расширенный диапазон. Требует поддержки VTP Transparent mode или VTPv3. Используется в крупных сетях и ЦОД. |

### Управление и расширения VLAN

#### VTP (VLAN Trunking Protocol)
Проприетарный протокол Cisco для синхронизации базы VLAN между коммутаторами.
- **VTPv1/v2:** поддерживает только Normal Range. Риск "затирания" базы при подключении нового коммутатора с более высоким Revision Number.
- **VTPv3:** поддерживает Extended Range, парольную защиту и режим Primary Server для предотвращения случайных изменений.

#### GVRP / MVRP
Стандартные протоколы (IEEE 802.1ak) для динамической регистрации VLAN. В отличие от VTP, они не создают VLAN глобально, а лишь динамически разрешают прохождение трафика существующих VLAN через Trunk-порты (Pruning).

#### IVL (Independent VLAN Learning)
Механизм независимого обучения MAC-адресов в современных коммутаторах. В отличие от устаревших устройств с общей CAM-таблицей для всех VLAN, IVL обеспечивает отдельную таблицу MAC-адресов для каждого VLAN. Это позволяет использовать один и тот же MAC-адрес в разных VLAN на разных портах без конфликтов. Все современные коммутаторы поддерживают IVL по умолчанию.

#### QinQ (VLAN Stacking / IEEE 802.1ad)
Технология вложенных тегов, где во внешний Ethernet-кадр добавляется два тега: **S-tag** (провайдерский) и **C-tag** (клиентский). Позволяет пробрасывать клиентские VLAN через магистраль провайдера. **MTU:** Требует увеличения MTU на магистральных линках до 1508+ байт.

#### Private VLAN (PVLAN)
Позволяет изолировать хосты внутри одного VLAN.
- **Promiscuous:** общается со всеми (обычно uplink к маршрутизатору).
- **Isolated:** общается только с promiscuous (хосты не видят друг друга).
- **Community:** общается с promiscuous и внутри своей группы.

#### Динамическое назначение (802.1X)
Механизм, при котором VLAN назначается порту динамически после аутентификации пользователя на сервере RADIUS/TACACS+.

## VLAN в современных инфраструктурах

### Сравнение VLAN и VXLAN
В крупных ЦОД ограничения VLAN (максимум 4094 ID) стали критичными, что привело к появлению VXLAN.

| Характеристика | VLAN (802.1Q) | VXLAN (RFC 7348) |
| :--- | :--- | :--- |
| **Уровень** | L2 (Канальный) | L2-over-L3 (Туннелирование) |
| **Лимит ID** | 4094 | ~16 миллионов (VNI) |
| **Транспорт** | Ethernet | UDP/IP |
| **Масштаб** | Локальная сеть | Глобальная сеть / Облака |

Подробнее: **[Обзор VXLAN](../Tunnels/vxlan.md)**.

### Настройка в Linux

В современных системах существует два подхода:

1. **Традиционные сабинтерфейсы:**
```bash
# Создание eth0.10
sudo ip link add link eth0 name eth0.10 type vlan id 10
```

2. **VLAN-aware Bridge (рекомендуется для виртуализации):**
Позволяет использовать один bridge как полноценный коммутатор с фильтрацией VLAN на портах.
```bash
# Включение фильтрации на мосту
sudo ip link set br0 type bridge vlan_filtering 1
# Назначение VLAN 10 на порт как Untagged (PVID)
sudo bridge vlan add dev eth0 vid 10 pvid untagged
```
Подробнее: **[VLAN в Linux: настройка и диагностика](./VLAN/vlan_linux_diagnostics.md)**.

### Диагностика и проверка

| Команда | Вендор / Платформа | Описание |
| :--- | :--- | :--- |
| `show vlan brief` | Cisco IOS | Список всех активных VLAN и привязанных к ним портов. |
| `show interfaces trunk` | Cisco IOS | Проверка активных транков и разрешенных VLAN. |
| `show vlans` | Juniper Junos | Общий список VLAN и их статусы. |
| `bridge vlan show` | Linux (iproute2) | Просмотр таблицы VLAN на мостах. |
| `tcpdump -i eth0 -e vlan` | Linux (tcpdump) | Захват трафика с отображением 802.1Q тегов. |

Подробнее о production-мониторинге: **[Наблюдаемость VLAN](./VLAN/vlan_monitoring.md)** — SNMP, NetFlow, Prometheus.

## Безопасность VLAN

### VLAN Hopping
Тип атаки, позволяющий перепрыгнуть из одного сегмента в другой в обход маршрутизатора.
1. **Switch Spoofing:** использование протокола DTP для перевода порта в режим Trunk.
   - **Защита:** `switchport nonegotiate`.
2. **Double Tagging:** эксплуатация Native VLAN для проброса кадра со вторым тегом.
   - **Защита:** изменение Native VLAN с ID 1 на неиспользуемый и `vlan dot1q tag native`.

Подробнее: **[Безопасность портов и VLAN Hopping](./VLAN/vlan_dtp_security.md)** и **[Жёсткая защита L2: DHCP Snooping, DAI, IPSG, BPDU Guard, Storm Control](./VLAN/vlan_security_hardening.md)**.

## Рекомендации по проектированию (Best Practices)

1. **Принцип «Один VLAN = Одна подсеть»:** упрощает маршрутизацию, настройку фаерволов и диагностику (трафик всегда идет через шлюз).
2. **VLAN Pruning:** разрешайте на транках только необходимые VLAN (`switchport trunk allowed vlan`), чтобы ограничить распространение broadcast-трафика.
3. **Management VLAN:** выделяйте отдельную изолированную VLAN для интерфейсов управления оборудованием.
4. **Native VLAN:** всегда меняйте Native VLAN (по умолчанию 1) на произвольный номер, не используемый для данных.
5. **Port Security:** на access-портах отключайте DTP (`nonegotiate`) и ограничивайте количество MAC-адресов.
6. **Black Hole VLAN:** неиспользуемые порты переводите в состояние `shutdown` и назначайте в немаршрутизируемую «чёрную» VLAN (например, ID 999).

### Конфигурация VLAN на коммутаторах

#### Cisco IOS (IOS-XE/IOS-XR)

**Базовая настройка VLAN:**
```bash
# Создание VLAN
Switch(config)# vlan 10
Switch(config-vlan)# name Management
Switch(config-vlan)# exit
Switch(config)# vlan 20
Switch(config-vlan)# name Users
Switch(config-vlan)# exit

# Назначение порта в VLAN (access)
Switch(config)# interface GigabitEthernet0/1
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 10
Switch(config-if)# description PC-MANAGEMENT
Switch(config-if)# exit

# Настройка trunk-порта
Switch(config)# interface GigabitEthernet0/24
Switch(config-if)# switchport mode trunk
Switch(config-if)# switchport trunk allowed vlan 10,20,30
Switch(config-if)# switchport trunk native vlan 999
Switch(config-if)# exit
```

**Voice VLAN:**
```bash
# Cisco IP-телефон + ПК на одном порту
Switch(config)# interface GigabitEthernet0/3
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 10
Switch(config-if)# switchport voice vlan 20
Switch(config-if)# spanning-tree portfast
```

**PVLAN (Private VLAN):**
```bash
# Создание Secondary VLAN
Switch(config)# vlan 100
Switch(config-vlan)# private-vlan primary
Switch(config-vlan)# private-vlan association 101,102
Switch(config-vlan)# exit

# Isolated VLAN
Switch(config)# vlan 101
Switch(config-vlan)# private-vlan isolated
Switch(config-vlan)# exit

# Community VLAN
Switch(config)# vlan 102
Switch(config-vlan)# private-vlan community
Switch(config-vlan)# exit

# Настройка порта (host mode)
Switch(config)# interface GigabitEthernet0/5
Switch(config-if)# switchport mode private-vlan host
Switch(config-if)# switchport private-vlan host-association 100 101
Switch(config-if)# exit

# Promiscuous порт (uplink к маршрутизатору)
Switch(config)# interface GigabitEthernet0/24
Switch(config-if)# switchport mode private-vlan promiscuous
Switch(config-if)# switchport private-vlan mapping 100 101,102
Switch(config-if)# exit
```

**VLAN Mapping / Translation:**
```bash
# Внешняя VLAN → Внутренняя VLAN (для межсетевого взаимодействия)
Switch(config)# vlan dot1q tag native
Switch(config)# interface GigabitEthernet0/1
Switch(config-if)# switchport vlan mapping 100 200
```

**Extended VLAN (1006–4094):**
```bash
# Включение расширенного диапазона (требуется VTP Transparent или VTPv3)
Switch(config)# vtp transparent
Switch(config)# vlan 2000
Switch(config-vlan)# name DATA-CENTER
```

#### Juniper Junos (EX Series)

**Базовая настройка VLAN:**
```bash
# Создание VLAN
set vlans Management vlan-id 10
set vlans Users vlan-id 20

# Назначение порта в VLAN
set interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members Management

# Настройка trunk-порта
set interfaces ge-0/0/23 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/23 unit 0 family ethernet-switching vlan members [ Management Users ]

# Native VLAN на trunk
set vlans DEFAULT vlan-id 999
set interfaces ge-0/0/23 unit 0 family ethernet-switching native-vlan-id 999
```

**Просмотр и проверка:**
```bash
# Список VLAN
show vlans

# Порты в VLAN
show ethernet-switching table

# Trunk-порты
show interfaces ge-0/0/23 switchport
```

#### Huawei (VRP)

**Базовая настройка VLAN:**
```bash
# Создание VLAN
[Switch] vlan batch 10 20 30

# Назначение порта в VLAN
[Switch] interface GigabitEthernet 0/0/1
[Switch-GigabitEthernet0/0/1] port link-type access
[Switch-GigabitEthernet0/0/1] port default vlan 10
[Switch-GigabitEthernet0/0/1] quit

# Настройка trunk-порта
[Switch] interface GigabitEthernet 0/0/24
[Switch-GigabitEthernet0/0/24] port link-type trunk
[Switch-GigabitEthernet0/0/24] port trunk allow-pass vlan 10 20 30
[Switch-GigabitEthernet0/0/24] port trunk pvid vlan 999
[Switch-GigabitEthernet0/0/24] quit

# Hybrid-порт (только Huawei)
[Switch] interface GigabitEthernet 0/0/5
[Switch-GigabitEthernet0/0/5] port link-type hybrid
[Switch-GigabitEthernet0/0/5] port hybrid untagged vlan 10 20
[Switch-GigabitEthernet0/0/5] port hybrid tagged vlan 30
[Switch-GigabitEthernet0/0/5] quit
```

**Просмотр:**
```bash
[Switch] display vlan brief
[Switch] display port vlan
[Switch] display vlan 10
```

#### Linux (iproute2 — VLAN-aware Bridge)

**Базовая настройка:**
```bash
# Создание VLAN-подинтерфейса
sudo ip link add link eth0 name eth0.10 type vlan id 10
sudo ip addr add 192.168.10.1/24 dev eth0.10
sudo ip link set eth0.10 up

# VLAN-aware bridge (рекомендуется для виртуализации)
sudo ip link add br0 type bridge vlan_filtering 1
sudo ip link set eth0 master br0
sudo ip link set eth1 master br0

# Назначение VLAN 10 на порт eth0 как Untagged (PVID)
sudo bridge vlan add dev eth0 vid 10 pvid untagged

# Назначение VLAN 20 на порт eth1 как Tagged (trunk)
sudo bridge vlan add dev eth1 vid 20

# Назначение VLAN 10 и 20 на порт eth2 (trunk)
sudo bridge vlan add dev eth2 vid 10
sudo bridge vlan add dev eth2 vid 20

# Просмотр таблицы VLAN
bridge vlan show

# Настройка Native VLAN (PVID) для bridge
sudo bridge vlan add dev br0 vid 999 pvid untagged self
```

**Настройка через netplan (Ubuntu):**
```yaml
# /etc/netplan/01-vlan.yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
  vlans:
    eth0.10:
      id: 10
      link: eth0
      addresses: [192.168.10.1/24]
    eth0.20:
      id: 20
      link: eth0
      addresses: [192.168.20.1/24]
```

**Настройка через systemd-networkd:**
```ini
# /etc/systemd/network/10-vlan10.netdev
[NetDev]
Name=eth0.10
Kind=vlan

[VLAN]
Id=10

# /etc/systemd/network/10-vlan10.network
[Match]
Name=eth0.10

[Network]
Address=192.168.10.1/24
```

### Меж-VLAN маршрутизация (Inter-VLAN Routing)

Трафик между VLAN не проходит напрямую на L2 — маршрутизация обязательна.

#### Router-on-a-Stick (ROAS)

Маршрутизатор подключается к коммутатору по одному физическому линку, разделяя трафик по подинтерфейсам:

```
[Коммутатор] ──── trunk (802.1Q) ──── [Маршрутизатор]
                                       ├── subif.10 (192.168.10.1)
                                       ├── subif.20 (192.168.20.1)
                                       └── subif.30 (192.168.30.1)
```

**Настройка Cisco Router (ROAS):**
```bash
# Физический интерфейс — без IP
Router(config)# interface GigabitEthernet0/0
Router(config-if)# no shutdown
Router(config-if)# exit

# Подинтерфейс VLAN 10
Router(config)# interface GigabitEthernet0/0.10
Router(config-subif)# encapsulation dot1Q 10
Router(config-subif)# ip address 192.168.10.1 255.255.255.0
Router(config-subif)# exit

# Подинтерфейс VLAN 20
Router(config)# interface GigabitEthernet0/0.20
Router(config-subif)# encapsulation dot1Q 20
Router(config-subif)# ip address 192.168.20.1 255.255.255.0
Router(config-subif)# exit

# Native VLAN на подинтерфейсе
Router(config)# interface GigabitEthernet0/0.999
Router(config-subif)# encapsulation dot1Q 999 native
Router(config-subif)# ip address 192.168.99.1 255.255.255.0
```

**Преимущества/недостатки ROAS:**
| Параметр | ROAS | L3 Switch |
| :--- | :--- | :--- |
| **Скорость** | Ограничена пропускной способностью физического линка (1-10 Гбит/с) | Wire-speed маршрутизация (100+ Гбит/с) |
| **Задержка** | Выше (двойная инкапсуляция) | Минимальная (hardware-based) |
| **Стоимость** | Низкая ( маршрутизатор) | Высокая (L3 коммутатор) |
| **Применение** | Малые сети, лабораторные среды | Enterprise, ЦОД |

#### SVI (Switch Virtual Interface) — L3 Switch

L3-коммутатор маршрутизирует между VLAN на аппаратном уровне:

```
[Коммутатор L3]
├── VLAN 10 → SVI 10 (192.168.10.1/24)
├── VLAN 20 → SVI 20 (192.168.20.1/24)
└── VLAN 30 → SVI 30 (192.168.30.1/24)
```

**Настройка Cisco L3 Switch:**
```bash
# Включение IP routing
Switch(config)# ip routing

# Создание SVI для VLAN 10
Switch(config)# interface Vlan10
Switch(config-if)# ip address 192.168.10.1 255.255.255.0
Switch(config-if)# no shutdown
Switch(config-if)# exit

# Создание SVI для VLAN 20
Switch(config)# interface Vlan20
Switch(config-if)# ip address 192.168.20.1 255.255.255.0
Switch(config-if)# no shutdown
Switch(config-if)# exit

# SVI для управления (Management VLAN)
Switch(config)# interface Vlan999
Switch(config-if)# ip address 192.168.99.1 255.255.255.0
Switch(config-if)# no shutdown
Switch(config-if)# exit

# Маршрутизация по умолчанию (к fw/rtr)
Switch(config)# ip route 0.0.0.0 0.0.0.0 192.168.99.254

# DHCP Relay для VLAN 10
Switch(config)# interface Vlan10
Switch(config-if)# ip helper-address 192.168.99.10
```

**Настройка Juniper L3 Switch (EX Series):**
```bash
# Создание VLAN
set vlans Management vlan-id 10
set vlans Users vlan-id 20

# L3-интерфейс (irb)
set interfaces irb unit 10 family inet address 192.168.10.1/24
set interfaces irb unit 20 family inet address 192.168.20.1/24

# Привязка VLAN к irb
set vlans Management l3-interface irb.10
set vlans Users l3-interface irb.20

# Включение маршрутизации
set routing-options static route 0.0.0.0/0 next-hop 192.168.99.254
```

**Настройка Linux (L3-роутинг через iproute2):**
```bash
# Включение IP forwarding
sudo sysctl -w net.ipv4.ip_forward=1

# Включение VLAN-aware bridge с роутингом
sudo ip link add br0 type bridge vlan_filtering 1
sudo ip link set eth0 master br0

# Создание VLAN-интерфейсов
sudo ip link add link eth0 name eth0.10 type vlan id 10
sudo ip link add link eth0 name eth0.20 type vlan id 20
sudo ip addr add 192.168.10.1/24 dev eth0.10
sudo ip addr add 192.168.20.1/24 dev eth0.20
sudo ip link set eth0.10 up
sudo ip link set eth0.20 up

# Маршрутизация между VLAN автоматически через ядро
```

### Voice VLAN — настройка и приоритизация

Voice VLAN позволяет объединить данные и голос на одном порту для IP-телефонов:

```
[Коммутатор] ──── access VLAN 10 + voice VLAN 20 ──── [Cisco IP Phone] ──── [PC]
                                       │
                              Телефон: тег VLAN 20
                              PC: нетег VLAN 10
```

**Настройка Cisco:**
```bash
Switch(config)# interface GigabitEthernet0/3
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 10
Switch(config-if)# switchport voice vlan 20
Switch(config-if)# mls qos trust dscp
Switch(config-if)# spanning-tree portfast
Switch(config-if)# exit

# QoS для голоса (приоритизация DSCP EF)
Switch(config)# mls qos
Switch(config)# class-map match-any VOICE
Switch(config-cmap)# match dscp ef
Switch(config-cmap)# exit
Switch(config)# policy-map VOICE-POLICY
Switch(config-pmap)# class VOICE
Switch(config-pmap-c)# priority percent 30
Switch(config-pmap-c)# exit
Switch(config-pmap)# exit
Switch(config)# interface GigabitEthernet0/3
Switch(config-if)# service-policy output VOICE-POLICY
```

**Настройка Huawei:**
```bash
[Switch] interface GigabitEthernet 0/0/3
[Switch-GigabitEthernet0/0/3] port link-type hybrid
[Switch-GigabitEthernet0/0/3] port hybrid untagged vlan 10
[Switch-GigabitEthernet0/0/3] port hybrid tagged vlan 20
[Switch-GigabitEthernet0/0/3] voice-vlan 20 enable
[Switch-GigabitEthernet0/0/3] stp edged-port enable
```

### QinQ — практическое применение

**Сценарий:** Провайдер пробрасывает клиентские VLAN через свою магистраль:

```
[Клиент A] ── VLAN 10 ──┐
                         ├── [Первый коммутатор] ── VLAN 500 ── [Магистраль] ── VLAN 500 ── [Второй коммутатор] ──┐
[Клиент B] ── VLAN 20 ──┘                                                                              └── VLAN 10 ── [Клиент A]
                                                                                                    └── VLAN 20 ── [Клиент B]
```

**Настройка Cisco (QinQ):**
```bash
# На входном порту (от клиента)
Switch(config)# interface GigabitEthernet0/1
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 100
Switch(config-if)# service-provider vlan
Switch(config-if)# exit

# На магистральном порту (к провайдеру)
Switch(config)# interface GigabitEthernet0/24
Switch(config-if)# switchport mode trunk
Switch(config-if)# switchport trunk allowed vlan 100
Switch(config-if)# exit
```

**MTU considerations:**
```bash
# QinQ добавляет 4 байта к кадру (8 байт на 2 тега)
# Стандартный MTU = 1500, минимальный для QinQ = 1508

# На Linux:
sudo ip link set eth0 mtu 1508

# Проверка:
ip link show eth0 | grep mtu
```

### STP и VLAN — взаимодействие

STP-инстансы работают с VLAN. Типичные проблемы и решения:

| Режим STP | Поведение | Рекомендация |
| :--- | :--- | :--- |
| **CST (Common Spanning Tree)** | Одно дерево для всех VLAN | Не рекомендуется — нет балансировки |
| **PVST+ (Cisco)** | Отдельный инстанс на каждый VLAN | При <100 VLAN |
| **MSTP (802.1s)** | VLAN-группы → инстансы | При >100 VLAN |

**Настройка MSTP на Linux:**
```bash
# Включение MSTP через bridge
sudo ip link add br0 type bridge stp_state 1

# Настройка VLAN → Instance mapping
sudo bridge vlan add dev eth0 vid 10-50 self
sudo bridge vlan add dev eth1 vid 51-100 self

# Bridge settings
sudo ip link set br0 type bridge priority 32768
sudo ip link set eth0 type bridge_slave priority 128
```

**Типичные ошибки:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Нет связи между VLAN | Не настроена Inter-VLAN маршрутизация | Добавить SVI или ROAS |
| Broadcast storm | Петля между коммутаторами | Включить STP, проверить trunk-порты |
| Нет голоса на IP-телефоне | Voice VLAN не настроен | `switchport voice vlan 20` |
| ПК не получает IP | DHCP Snooping блокирует | Добавить trusted порт |

### Автоматизация VLAN (Ansible, NETCONF/YANG)

**Ansible — управление VLAN на Cisco IOS:**
```yaml
# playbooks/vlans.yml
---
- name: Configure VLANs on switches
  hosts: switches
  gather_facts: no
  tasks:
    - name: Create VLANs
      cisco.ios.ios_vlans:
        config:
          - vlan_id: 10
            name: Management
            state: active
          - vlan_id: 20
            name: Users
            state: active
        state: merged

    - name: Configure access port
      cisco.ios.ios_l2_interfaces:
        config:
          - name: GigabitEthernet0/1
            access:
              vlan: 10
        state: merged

    - name: Configure trunk port
      cisco.ios.ios_l2_interfaces:
        config:
          - name: GigabitEthernet0/24
            trunk:
              allowed_vlans: 10,20,30
              native_vlan: 999
        state: merged
```

**Ansible — управление VLAN на Juniper Junos:**
```yaml
---
- name: Configure VLANs on Juniper
  hosts: juniper_switches
  tasks:
    - name: Create VLANs
      junipernetworks.junos.junos_vlans:
        config:
          - name: Management
            vlan_id: 10
          - name: Users
            vlan_id: 20
        state: merged

    - name: Configure access port
      junipernetworks.junos.junos_l2_interfaces:
        config:
          - name: ge-0/0/0
            unit: 0
            family:
              ethernet-switching:
                interface_mode: access
                vlan:
                  members: Management
        state: merged
```

**NETCONF/YANG (пример):**
```xml
<!-- Создание VLAN через NETCONF -->
<config>
  <vlans xmlns="http://openconfig.net/yang/vlan">
    <vlan>
      <vlan-id>10</vlan-id>
      <config>
        <vlan-id>10</vlan-id>
        <name>Management</name>
      </config>
    </vlan>
  </vlans>
</config>
```

**YANG-модели для VLAN:**
| Модель | Описание | Пример vendor |
| :--- | :--- | :--- |
| **openconfig-vlans** | Стандартная OpenConfig модель | Все major vendors |
| **Cisco IOS YANG** | `cisco-ios-xe-vlans.yang` | Cisco IOS-XE |
| **Junos YANG** | `junos-vlans.yang` | Juniper |
| **Huawei YANG** | `huawei-vlan.yang` | Huawei VRP |

### Наблюдаемость и мониторинг VLAN

**SNMP-мониторинг:**
```bash
# Просмотр VLAN через SNMP
snmpwalk -v2c -c public <switch-ip> 1.3.6.1.2.1.17.7.1.4.1

# OID для VLAN:
# .1.3.6.1.2.1.17.7.1.4.1.1  - dot1qVlanStaticName
# .1.3.6.1.2.1.17.7.1.4.1.2  - dot1qVlanStaticEgressPorts

# Мониторинг трафика по VLAN (SNMP IF-MIB)
snmpwalk -v2c -c public <switch-ip> IF-MIB::ifDescr
snmpwalk -v2c -c public <switch-ip> IF-MIB::ifHCInOctets
```

**NetFlow/sFlow для анализа VLAN:**
```bash
# На Cisco — включить NetFlow на SVI
Switch(config)# interface Vlan10
Switch(config-if)# ip flow monitor VLAN-MONITOR input
Switch(config-if)# ip flow monitor VLAN-MONITOR output

# На Linux — сбор данных через pmacct
sudo pmacct -i eth0 -P mysql -T vlan
```

**Prometheus + SNMP Exporter:**
```yaml
# snmp.yml (SNMP Exporter)
modules:
  vlan:
    walk:
      - 1.3.6.1.2.1.17.7  # dot1qVlan
    lookups:
      - labels: ["dot1qVlanStaticEgressPorts"]
        labelname: "vlan_name"
        oid: 1.3.6.1.2.1.17.7.1.4.1.1
```

**Zabbix мониторинг VLAN:**
```
# Ключи элементов для мониторинга:
- snmp.get["1.3.6.1.2.1.17.4.3.1.1.{VLAN_ID}"]  # Трафик VLAN
- snmp.walk["1.3.6.1.2.1.17.7.1.4.1"]            # Список VLAN
- net.if.in["{INTERFACE}.{VLAN_ID}"]              # Входящий трафик
```

### Типичные ошибки и решения

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Нет связи между устройствами** | Разные VLAN на портах | `show vlan brief`, `bridge vlan show` | Проверить привязку портов к VLAN |
| **Trunk не работает** | Native VLAN mismatch | `show interfaces trunk` | Синхронизировать Native VLAN |
| **DHCP не работает** | VLAN-подсеть не настроена | `show ip interface brief` | Добавить SVI/IP-адрес |
| **Широковещательные штормы** | Петля или отсутствие STP | `show spanning-tree` | Включить STP, проверить топологию |
| **VLAN Hopping атака** | DTP включен, Native VLAN = 1 | `show dtp interface` | `switchport nonegotiate`, сменить Native VLAN |
| **QinQ не работает** | MTU < 1508 | `ping -s 1500 -M do <addr>` | Увеличить MTU на магистралях до 1508+ |
| **MSTP не синхронизируется** | Разные имена региона | `show spanning-tree mst` | Одинаковые `name`, `revision` |
| **Voice VLAN не работает** | DSCP/802.1p не настроен | Проверить на телефоне | Настроить `mls qos trust dscp` |

### Связанные документы
- **[Формат кадра 802.1Q](./VLAN/vlan_8021q_frame.md)** — структура и поля тега.
- **[Trunk и Native VLAN](./VLAN/vlan_trunk_native.md)** — работа магистральных портов.
- **[Безопасность портов: DTP и Port Security](./VLAN/vlan_dtp_security.md)** — защита от VLAN Hopping.
- **[Меж-VLAN маршрутизация](./VLAN/vlan_inter_vlan_routing.md)** — связь между сегментами.
- **[L2 Switching](../../Concepts/vlan_l2_switching/definitions_and_concepts.md)** — принципы работы коммутаторов.
- **[Spanning Tree Protocol (STP)](../stp.md)** — предотвращение петель.
- **[Проектирование VLAN: production-ready топологии](../../Concepts/vlan_l2_switching/vlan_design_patterns.md)** — Enterprise Campus, PVLAN, Leaf-Spine, production checklist.
- **[Наблюдаемость VLAN](./VLAN/vlan_monitoring.md)** — SNMP, NetFlow, Prometheus для production.
