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

### Безопасность и аутентификация OSPF

OSPF vulnerable к нескольким типам атак, связанных с подменой или перехватом LSA-пакетов. Аутентификация является основным механизмом защиты.

#### Типы атак на OSPF

| Атака | Описание | Последствия |
| :--- | :--- | :--- |
| **LSA Spoofing** | Злоумышленник отправляет поддельные LSA-пакеты (Type 1-5) | Изменение SPF-дерева, перенаправление трафика |
| **OSPF Neighbor Spoofing** | Подмена Router ID существующего соседа | Разрыв соседства, потеря маршрутов |
| **LSA Flooding Attack** | Массовая рассылка LSA с коротким MaxAge | Перегрузка CPU (пересчёт SPF), исчерпание LSDB |
| **Hello Spoofing** | Поддельные Hello-пакеты с неправильными параметрами | DR/BDR selection hijacking, разделение домена |

#### Механизмы защиты

**1. OSPF Аутентификация (RFC 2328, Section D.3):**

| Тип | Описание | Уровень безопасности |
| :--- | :--- | :--- |
| **Null (Type 0)** | Аутентификация отключена (по умолчанию) | Нет |
| **Simple Password (Type 1)** | Пароль передаётся открытым текстом | Низкий (перехват) |
| **Cryptographic/MD5 (Type 2)** | HMAC-MD5 подпись пакета | Высокий |
| **SHA-256 (RFC 5709)** | HMAC-SHA-256 (поддерживается modern equipment) | Очень высокий |

**2. Area Containment:**
- Использование Stub/NSSA-зон для ограничения распространения внешних LSA.
- Виртуальные ссылки (Virtual Links) только при необходимости.

**3. Passive Interface:**
- Отключение OSPF на интерфейсах, где нет соседей (уже рассмотрено).

**4. LSDB Overload Protection:**
- Ограничение максимального количества LSA в LSDB.
- Мониторинг размера LSDB и частоты пересчёта SPF.

### OSPF Таймеры

OSPF использует несколько таймеров для управлениясоседством и распространением LSA:

| Таймер | Интервал (Broadcast/P2P) | Интервал (NBMA) | Описание |
| :--- | :--- | :--- | :--- |
| **Hello Interval** | 10 сек | 30 сек | Интервал отправки Hello-пакетов (обнаружение соседей) |
| **Dead Interval** | 40 сек (4 × Hello) | 120 сек (4 × Hello) | Время ожидания Hello قبل объявления соседа «мёртвым» |
| **Wait Interval** | 40 сек (= Dead) | 120 сек (= Dead) | Ожидание перед началом выборов DR/BDR |
| **Retransmit Interval** | 5 сек | 5 сек | Повторная отправка LSA при отсутствии ACK |
| **Max Age** | 3600 сек (1 час) | 3600 сек | Максимальный возраст LSA перед удалением из LSDB |
| **Min LS Interval** | 5 сек | 5 сек | Минимальный интервал между обновлениями одного LSA |
| **Min LS Arrival** | 1 сек | 1 сек | Минимальный интервал между приёмом двух копий одного LSA |

> **Важно:** Таймеры должны быть **одинаковыми** на обоих концах линка. Несовпадение Hello/Dead Interval — частая причина отказа соседства.

#### Настройка таймеров

**Cisco:**
```cisco
interface GigabitEthernet0/1
  ip ospf hello-interval 5
  ip ospf dead-interval 20
```

**FRRouting:**
```bash
interface eth0
  ip ospf hello-interval 5
  ip ospf dead-interval 20
```

**MikroTik:**
```bash
/routing ospf interface-template
add interfaces=ether1 hello-interval=5s dead-interval=20s
```

### Типы сетей OSPF

OSPF поддерживает несколько типов сетей, которые определяют поведениесоседства и выбор DR/BDR:

| Тип сети | Описание | DR/BDR | Соседство | Примеры |
| :--- | :--- | :--- | :--- | :--- |
| **Broadcast** | Мультикаст, все видят друг друга | Да | Multi-access | Ethernet, Wi-Fi |
| **Point-to-Point (P2P)** | Два маршрутизатора на линке | Нет | Полное mesh | PPP, HDLC, GRE |
| **Point-to-Multipoint (P2MP)** | Один маршрутизатор — несколько удалённых | Нет ( Noon-Broadcast) | Full mesh между всеми | Frame Relay (инвертированный) |
| **Non-Broadcast Multi-Access (NBMA)** | Мультикаст, но не все видят друг друга | Да | Ручная настройка neighbor | Frame Relay, ATM |
| **Point-to-Multipoint Non-Broadcast** | P2MP без автоматического обнаружения | Нет | Ручная настройка neighbor | Frame Relay (partial mesh) |

#### Определение типа сети

| Способ | Описание |
| :--- | :--- |
| **ip ospf network <type>** | Ручная установка типа сети на интерфейсе |
| **Автоматическое** | OSPF определяет тип по типу интерфейса (broadcast для Ethernet, P2P дляпоследовательных) |
| **Bandwidth** | Некоторые реализации используют bandwidth для определения типа |

#### Настройка типа сети

**Cisco:**
```cisco
! Broadcast (по умолчанию для Ethernet)
interface GigabitEthernet0/1
  ip ospf network broadcast

! Point-to-Point (по умолчанию дляпоследовательных)
interface Serial0/0
  ip ospf network point-to-point

! Point-to-Multipoint (для Frame Relay)
interface Serial0/0
  ip ospf network point-to-multipoint

! NBMA (для Frame Relay с ручным neighbor)
interface Serial0/0
  ip ospf network non-broadcast
  neighbor 10.0.0.2 priority 1
```

**FRRouting:**
```bash
interface eth0
  ip ospf network point-to-point
```

**MikroTik:**
```bash
/routing ospf interface-template
add interfaces=ether1 network=point-to-point
```

### Состояния соседства OSPF (Adjacency States)

OSPF проходит через несколько стадий при установкесоседства. Полная таблица состояний:

| Состояние | Описание | Когда возникает |
| :--- | :--- | :--- |
| **Down** | Сосед не обнаружен | Начальное состояние |
| **Attempt** | Hello отправлен, но ответ не получен (NBMA) | Ручная настройка neighbor на NBMA |
| **Init** | Получен Hello от соседа, но наш Router ID не в его списке | Первый Hello получен |
| **2-Way** | Двустороннее обнаружение; DR/BDR выбраны (Broadcast) | Конецсоседского обнаружения; **/convergenceзавершения** (на.broadcast) |
| **ExStart** | Определение роли (Master/Slave) для обмена DBD | Начало обмена базой данных |
| **Exchange** | Обмен DBD (Database Description) — описаниями LSA | Сравнение LSDB |
| **Loading** | Запрос и получение отсутствующих LSA (LSR → LSU → LSAck) | Загрузка недостающих LSA |
| **Full** | Полная синхронизация LSDB; соседство установлено | **Нормальное рабочее состояние** |

#### Визуализация стадий

```
Down → Init → 2-Way → ExStart → Exchange → Loading → Full
         ↓
       ( NBMA: ручная настройка neighbor → Attempt → Init )
```

> **Важно:**
> - Состояние **2-Way** является нормальным для DR/BDR и DROther в Broadcast-сети (DROther не устанавливает Full с другими DROther).
> - Состояние **Full** означает полную синхронизацию LSDB. **Это целевое состояние длясоседства.**
> - Состояние **ExStart/Exchange/Loading** является временным. Если застряло — проблема с MTU или аутентификацией.

#### Диагностика состояний соседства

**Cisco:**
```bash
show ip ospf neighbor
# Пример вывода:
#   Neighbor ID  Pri  State       Dead Time  Address      Interface
#   10.0.0.2     1    FULL/DR     00:00:38   10.0.0.2     Gi0/0
#   10.0.0.3     1    2WAY/DROTHER 00:00:37  10.0.0.3     Gi0/0
```

**FRRouting:**
```bash
show ip ospf neighbor
# Пример вывода:
#   Neighbor ID     Pri  State       Dead Time  Address         Interface
#   10.0.0.2         1   Full/DR     37.155s    10.0.0.2        eth0
```

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

### Базовая настройка OSPF на FRRouting (Linux)

FRRouting — современный демон маршрутизации для Linux, поддерживающий OSPF, BGP, IS-IS.

**Установка FRRouting:**
```bash
# Debian/Ubuntu
sudo apt install frr

# Fedora/RHEL
sudo dnf install frr

# Arch
sudo pacman -S frr
```

**Включение OSPF в FRR:**
```bash
# Включить OSPF-демон
sudo sed -i 's/bgpd=yes/ospfd=yes/' /etc/frr/daemons
sudo systemctl restart frr
```

**Конфигурация OSPF:**
```bash
sudo vtysh

# Переход в OSPF-режим
conf t

# Установка Router ID
router ospf
  ospf router-id 1.1.1.1

  # Добавление сетей в OSPF
  network 192.168.10.0/24 area 0
  network 192.168.20.0/24 area 0

  # Аутентификация (MD5)
  area 0 authentication message-digest

  # Passive Interface
  passive-interface eth1

  # Redistribution статики
  redistribute static

  # Redistribuition connected
  redistribute connected

exit

# Настройка аутентификации на интерфейсе
interface eth0
  ip ospf message-digest-key 1 md5 MySecretKey

exit
write
```

**Просмотрсоседства в FRR:**
```bash
sudo vtysh -c "show ip ospf neighbor"
sudo vtysh -c "show ip ospf database"
sudo vtysh -c "show ip ospf interface"
sudo vtysh -c "show ip ospf"
```

**Просмотр таблицы маршрутизации:**
```bash
sudo vtysh -c "show ip route ospf"
# Или черезip route:
ip route show proto ospf
```

### Базовая настройка OSPF на Juniper Junos

```bash
# Переход в конфигурационный режим
configure

# Настройка OSPF
set protocols ospf area 0 interface ge-0/0/0
set protocols ospf area 0 interface ge-0/0/1

# Установка Router ID
set routing-options router-id 1.1.1.1

# Настройка интерфейсов с параметрами
set protocols ospf area 0 interface ge-0/0/0 metric 10
set protocols ospf area 0 interface ge-0/0/0 hello-interval 5
set protocols ospf area 0 interface ge-0/0/0 dead-interval 20

# Аутентификация (MD5)
set protocols ospf area 0 interface ge-0/0/0 authentication md5 1 secret MySecretKey

# Passive Interface
set protocols ospf area 0 interface ge-0/0/2 passive

# Multi-area
set protocols ospf area 1 interface ge-0/0/2
set protocols ospf area 1 interface ge-0/0/3

# Redistribution connected
set protocols ospf export CONNECTED-TO-OSPF
set policy-options policy-statement CONNECTED-TO-OSPF term 1 from protocol direct
set policy-options policy-statement CONNECTED-TO-OSPF term 1 then accept

commit
exit
```

**Просмотрсоседства:**
```bash
show ospf neighbor
show ospf database
show ospf interface
show route protocol ospf
```

### Базовая настройка OSPF на Huawei

```bash
# Переход в system view
system-view

# Установка Router ID
router id 1.1.1.1

# Включение OSPF
ospf 1 router-id 1.1.1.1

# Добавление.area
area 0.0.0.0

# Добавление сетей
network 192.168.10.0 0.0.0.255
network 192.168.20.0 0.0.0.255

quit

# Настройка интерфейсов
interface GigabitEthernet0/0/1
 ospf cost 10
 ospf hello-interval 5
 ospf dead-interval 20

# Аутентификация (MD5)
interface GigabitEthernet0/0/1
 ospf authentication-mode md5 1 MySecretKey

# Passive Interface
interface GigabitEthernet0/0/2
 ospf silent-interface

quit
return
```

**Просмотрсоседства:**
```bash
display ospf peer
display ospf lsdb
display ospf interface
display ip routing-table protocol ospf
```

### Virtual Links (Виртуальные ссылки)

**Назначение:** Логическое соединение между ABR и Area 0 через непрерывную область (Transit Area). Используется, когдафизически невозможно подключить ABR напрямую к Area 0.

```
[Area 1] --- [Transit Area 2] --- [Area 0]
   ABR1           ABR2              Backbone
         ←—— Virtual Link ——→
```

**Когда использовать:**
- Два ABR в разных зонах, разделённых третьей зоной.
- Повреждение физического линка к Area 0 (временное решение).
- Исторические топологии, которые сложно перестроить.

**Когда НЕ использовать (рекомендации):**
- Если можно перестроить топологию — лучше физическое подключение.
- Virtual Link добавляет задержку и сложность диагностики.
- Должен быть **стабильный** Transit Area — любой flapping в Transit Area повлияет на Virtual Link.

#### Настройка Virtual Links

**Cisco:**
```cisco
# На ABR1 (в Area 1, не имеет физического подключения к Area 0)
router ospf 1
  area 1 virtual-link 2.2.2.2    # Router ID ABR2

# На ABR2 (в Area 0 и Area 2, Transit Area = Area 2)
router ospf 1
  area 2 virtual-link 1.1.1.1    # Router ID ABR1
```

**FRRouting:**
```bash
sudo vtysh
conf t

# На ABR1
router ospf
  area 1 virtual-link 2.2.2.2

# На ABR2
router ospf
  area 2 virtual-link 1.1.1.1

exit
write
```

**MikroTik:**
```bash
# На ABR1
/routing ospf area
add instance=default-ospf name=transit area-id=0.0.0.2

/routing ospf interface-template
add area=backbone interfaces=virtual-link1

# На ABR2
/routing ospf area
add instance=default-ospf name=transit area-id=0.0.0.2

/routing ospf interface-template
add area=backbone interfaces=virtual-link2
```

**Диагностика Virtual Links:**
```bash
# Cisco
show ip ospf virtual-links
show ip ospf neighbor detail

# FRRouting
sudo vtysh -c "show ip ospf virtual-link"
sudo vtysh -c "show ip ospf neighbor"
```

### Диагностика OSPF

#### Команды по вендорам

**Cisco IOS/IOS-XE:**
```bash
# Соседства
show ip ospf neighbor
show ip ospf neighbor detail
show ip ospf neighbor <router-id>

# База данных LSA
show ip ospf database
show ip ospf database router
show ip ospf database network
show ip ospf database summary
show ip ospf database asbr-summary
show ip ospf database external

# Интерфейсы
show ip ospf interface
show ip ospf interface brief
show ip ospf interface GigabitEthernet0/0

# Процесс OSPF
show ip ospf
show ip ospf | include Router ID|Area|SPF

# Таблица маршрутизации
show ip route ospf

# Статистика
show ip ospf statistics
show ip ospf statistics spf

# Debug
debug ip ospf events
debug ip ospf adj
debug ip ospf lsa
```

**FRRouting (Linux):**
```bash
# Соседства
sudo vtysh -c "show ip ospf neighbor"
sudo vtysh -c "show ip ospf neighbor detail"

# База данных LSA
sudo vtysh -c "show ip ospf database"
sudo vtysh -c "show ip ospf database router"
sudo vtysh -c "show ip ospf database network"
sudo vtysh -c "show ip ospf database summary"
sudo vtysh -c "show ip ospf database asbr-summary"
sudo vtysh -c "show ip ospf database external"

# Интерфейсы
sudo vtysh -c "show ip ospf interface"
sudo vtysh -c "show ip ospf interface eth0"

# Процесс OSPF
sudo vtysh -c "show ip ospf"

# Таблица маршрутизации
sudo vtysh -c "show ip route ospf"
ip route show proto ospf

# Статистика
sudo vtysh -c "show ip ospf statistics"
sudo vtysh -c "show ip ospf statistics spf"

# Routing table OSPF
sudo vtysh -c "show ip ospf rib"
```

**MikroTik (RouterOS v7):**
```bash
# Соседства
/routing ospf neighbor print
/routing ospf neighbor print detail

# LSA
/routing ospf lsa print
/routing ospf lsa print where type=router

# Интерфейсы
/routing ospf interface print
/routing ospf interface print detail

# Таблица маршрутизации
/ip route print where ospf
/ip route print where ospf=1

# Статистика
/routing ospf statistics print
```

**Juniper Junos:**
```bash
# Соседства
show ospf neighbor
show ospf neighbor detail

# База данных LSA
show ospf database
show ospf database router
show ospf database network

# Интерфейсы
show ospf interface
show ospf interface detail

# Таблица маршрутизации
show route protocol ospf

# Статистика
show ospf statistics
show ospf statistics spf
```

**Huawei:**
```bash
# Соседства
display ospf peer
display ospf peer brief

# LSA
display ospf lsdb
display ospf lsdb router
display ospf lsdb network

# Интерфейсы
display ospf interface
display ospf interface brief

# Таблица маршрутизации
display ip routing-table protocol ospf

# Статистика
display ospf statistics
display ospf statistics spf
```

#### Типичные ошибки и решения

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Соседство не устанавливается (стuck в Init/2-Way)** | Несовпадение Hello/Dead Interval | `show ip ospf interface` — проверить timers | Убедиться, что таймеры одинаковы на обоих концах |
| **Соседство не устанавливается** | Nismatch Area ID | `show ip ospf` — проверить area | Исправить area на интерфейсе |
| **Соседство не устанавливается** | IP-подсеть не совпадает | `show ip ospf neighbor` — проверить IP | Исправить network statement или IP-адрес |
| **Соседство не устанавливается** | MTU mismatch (особенно при Exchange) | `ping -s 1472 -M do <neighbor>` | Увеличить MTU или `ip ospf mtu-ignore` (временно) |
| **Соседство не устанавливается** | Аутентификация не совпадает | `debug ip ospf adj` — проверить auth | Убедиться, что ключи и типы аутентификации совпадают |
| **Соседство не устанавливается** | Firewall блокирует OSPF (Proto 89) | `tcpdump -i eth0 proto ospf` | Разрешить протокол 89 в firewall |
| **Соседство не устанавливается** | Passive Interface на интерфейсе | `show ip ospf interface brief` — проверить P | Убрать passive-interface или добавить network в area |
| **Маршруты не появляются** | LSA не распространяются (area mismatch) | `show ip ospf database` — проверить LSA | Проверить связность зон и ABR |
| **Маршруты не появляются** | Filter на ABR/ASBR | `show ip ospf database summary` — проверить LSA | Проверить distribute-list, route-maps |
| **SPF пересчитывается часто (flapping)** | Нестабильный линк | `show ip ospf statistics spf` — частота | Проверить физический линк; увеличить SPF throttle |
| **LSDB переполняется** | Много LSA от нестабильных маршрутов | `show ip ospf database` — количество LSA | Ограничить max-lsa; проверить redistribution |
| **DR/BDR не выбирается** | Все интерфейсы с priority 0 | `show ip ospf interface` — priority | Увеличить priority на нужных интерфейсах |
| **Virtual Link не работает** | Transit Area нестабильна | `show ip ospf virtual-links` | Убедиться, что Transit Area стабильна и connectivity есть |

#### Автоматизация мониторинга OSPF

**Скрипт проверки соседства:**
```bash
#!/bin/bash
# OSPF Neighbor Check Script
ROUTER_IP="${1:-localhost}"
EXPECTED_NEIGHBORS=2

# FRRouting
NEIGHBORS=$(sudo vtysh -c "show ip ospf neighbor" | grep -c "Full")

if [ "$NEIGHBORS" -lt "$EXPECTED_NEIGHBORS" ]; then
    echo "WARNING: Only $NEIGHBORS full neighbors (expected $EXPECTED_NEIGHBORS)"
    sudo vtysh -c "show ip ospf neighbor"
    exit 1
else
    echo "OK: $NEIGHBORS full neighbors"
    exit 0
fi
```

**Prometheus-экспорт OSPF метрик:**
```bash
# Использование birdwatcher или frr-k8s для Prometheus
# frrk8s (для Kubernetes) экспортирует OSPF neighbor state

# Пример метрик:
# frr_ospf_neighbors_total{state="full"} 2
# frr_ospf_interfaces_up{interface="eth0"} 1
# frr_ospf_lsa_count{type="router"} 5
```

## Дополнительная информация

### Сравнение OSPFv2 и OSPFv3

| Характеристика | OSPFv2 (IPv4) | OSPFv3 (IPv6) |
| :--- | :--- | :--- |
| **RFC** | RFC 2328 | RFC 5340 |
| **Адресная база** | IPv4 (32-bit) | IPv6 (128-bit) |
| **IP Protocol** | 89 (unicast) | 89 (unicast), но срасширенных headers |
| **Аутентификация** | В пакете OSPF (Type 2) или IPsec | Обязательная IPsec AH; опционально Crypo-Auth |
| **Link-Local Address** | Не используется | Используется link-local (FE80::) длясоседства |
| **LSA Types** | 1-5, 7 | 1-5, 8 (Link-LSA), 9 (Intra-Area Prefix LSA) |
| **Router ID** | 32-bit (обычно IPv4-адрес) | 32-bit (аналогично OSPFv2) |
| **Поддержка** | Все вендоры | Все современные вендоры |
| **Применение** | Традиционные сети IPv4 | Dual-stack, чистые IPv6-сети |

#### OSPFv3 для IPv6 (конфигурация)

**Cisco:**
```cisco
ipv6 router ospf 1
  router-id 1.1.1.1

interface GigabitEthernet0/0
  ipv6 ospf 1 area 0
```

**FRRouting:**
```bash
sudo vtysh
conf t

router ospf6
  ospf6 router-id 1.1.1.1

interface eth0
  ipv6 ospf6 area 0.0.0.0

exit
write
```

### RFC и стандарты

- **RFC 2328** — OSPF Version 2 (основной стандарт для IPv4).
- **RFC 5340** — OSPF for IPv6 (OSPFv3).
- **RFC 5709** — OSPFv2 HMAC-SHA Cryptographic Authentication.
- **RFC 3623** — Graceful OSPF Restart (непрерывная маршрутизация при перезагрузке).
- **RFC 3101** — OSPF Not-So-Stubby Area (NSSA) Option.
- **RFC 1583** —устаревшая OSPFv2 ( replaced by RFC 2328).
- **IEEE 802.1D** — Spanning Tree Protocol (взаимодействие с OSPF в L2/L3 средах).

### Связанные протоколы и стандарты

| Протокол | Тип | Стандарт | Применение |
| :--- | :--- | :--- | :--- |
| **IS-IS** | IGP (Link-State) | ISO 10589 | Крупные операторские сети |
| **EIGRP** | IGP (Advanced Distance Vector) | Cisco Proprietary | Cisco-среды |
| **RIP/RIPng** | IGP (Distance Vector) | RFC 1058 / RFC 2080 | Малые сети, legacy |
| **BGP** | EGP (Path Vector) | RFC 4271 | Междоменная маршрутизация |
| **VRRP** | redundancy | RFC 5798 | Шлюз по умолчанию |
| **BFD** | detection | RFC 5880 | Быстрое обнаружение отказов линков |

### См. также

- [BGP](./bgp.md) — протокол внешней маршрутизации
- [Сетевой уровень](../OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md) — основы маршрутизации
- [Протоколы и оборудование](../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md) — обзор протоколов маршрутизации, безопасность OSPF, FRRouting
- [Меж-VLAN маршрутизация](./VLAN/vlan_inter_vlan_routing.md) — OSPF на SVI (Cisco/Juniper/Huawei)
- [Маршрутизация в Linux](../../Linux/SystemAdministration/routing.md) — FRRouting, ip route, diagnostics
