# Linux Bridge: программный коммутатор в ядре

## Определения

**Linux Bridge (Мост)** — программный коммутатор канального уровня (**L2 — Data Link Layer**), реализованный непосредственно в ядре Linux. Он позволяет объединять несколько сетевых интерфейсов (физических, виртуальных или VLAN) в единый логический сегмент (broadcast-домен).

**Порты моста (Bridge Ports)** — интерфейсы, подключенные к мосту. При включении в мост интерфейс переходит в режим работы «slave» и перестает использовать собственные настройки сетевого уровня (**L3 — IP**), делегируя обработку входящих кадров мосту.

**FDB (Forwarding Database — база пересылки)** — внутренняя таблица моста, сопоставляющая MAC-адреса устройств с портами моста, через которые они доступны.

**VLAN Filtering** — механизм, позволяющий одному мосту обрабатывать несколько VLAN-тегов (**IEEE 802.1Q**) на портах, выполняя роль VLAN-aware коммутатора без создания множества отдельных виртуальных интерфейсов.

**PVID (Port VLAN ID)** — идентификатор VLAN по умолчанию для нетегированных кадров, поступающих на порт. Управляется флагом `pvid` в `bridge vlan add`.

**Egress Untagged** — флаг, указывающий, что при выходе с порта тег данного VLAN должен быть удалён (аналог Native VLAN в Trunk или Access-порта).

**Edge Port (аналог PortFast)** — порт моста, который сразу переходит в состояние `forwarding` без прохождения стадий `listening` и `learning`. Используется для подключения конечных устройств (серверы, ВМ), чтобы ускорить поднятие соединения и избежать задержек STP.

**MAC Flapping** — состояние, при котором один и тот же MAC-адрес появляется на разных портах моста. Причины: петля в топологии, миграция ВМ, дублирование MAC. Мост начинает flood-ить трафик для этого MAC на все порты.

**Ageing Time** — время (в секундах), в течение которого запись в FDB считается актуальной. Если устройство не отправляет кадры дольше ageing time, запись удаляется. По умолчанию 300 секунд.

**Storm Control** — механизм ограничения скорости broadcast, multicast и unknown-unicast трафика на порту. В Linux реализуется через `tc` (traffic control), так как аппаратный storm control отсутствует.

**Q-in-Q (VLAN Stacking, IEEE 802.1ad)** — метод двойного тегирования, при котором внутри одного сервисного VLAN (S-VLAN) пробрасываются клиентские VLAN (C-VLAN). Требует увеличения MTU на 4 байта за каждый тег.

## Основные концепции

### Принцип работы

Linux Bridge имитирует поведение стандартного управляемого коммутатора:
1.  **Обучение (Learning):** Мост анализирует поле Source MAC во входящих кадрах и обновляет таблицу FDB.
2.  **Пересылка (Forwarding):** Если Destination MAC есть в FDB, кадр отправляется в соответствующий порт.
3.  **Лавинная рассылка (Flooding):** Если адрес неизвестен или является широковещательным, кадр рассылается во все порты, кроме порта-источника.

### STP (Spanning Tree Protocol)

Linux Bridge поддерживает STP (802.1D) и RSTP (802.1w) для предотвращения петель в топологии. В современных высоконагруженных средах (ЦОД) STP на мостах часто отключают в favour более сложных механизмов на уровне физической сети, чтобы избежать задержек при перестроении топологии.

**Ключевые параметры STP:**
- **Priority** — приоритет моста для выбора Root Bridge. Кратен 4096. Значение по умолчанию: 32768.
- **Forward Delay** — время перехода порта из состояния `listening` в `learning` и далее в `forwarding`. По умолчанию 15 сек (802.1D) или 4 сек (RSTP).
- **Max Age** — максимальное время жизни BPDU. По умолчанию 20 сек.
- **Edge Port** — порт, подключенный к конечному устройству, которое не может создавать петли. Порт сразу переходит в `forwarding`, минуя стадии обучения. Аналог PortFast на Cisco.
- **BPDU Guard** — при получении BPDU на edge-порту порт блокируется. В Linux настраивается через `nftables` или `bridge link set dev <iface> bpduguard on` (если supported).

**Настройка STP:**
```bash
# Включение STP
sudo ip link set br0 type bridge stp_state 1

# Установка приоритета
sudo ip link set br0 type bridge priority 4096

# Установка forward delay (секунды)
sudo ip link set br0 type bridge forward_delay 4

# Установка max age (секунды)
sudo ip link set br0 type bridge max_age 600

# Включение edge port (PortFast)
sudo bridge link set dev eth0 edgeport on

# Просмотр состояния
bridge link show
# → 2: eth0 state forwarding priority 32 cost 100
```

### VLAN-aware мост

VLAN-aware мост позволяет обрабатывать несколько VLAN на одном физическом интерфейсе без создания сабинтерфейсов (`eth0.10`, `eth0.20`).

**Ключевые концепции:**
- **VLAN Pruning:** удаление неиспользуемых VLAN с порта. Например, если trunk-порт должен передавать только VLAN 10 и 20, удаляем VLAN 1 (по умолчанию) и все остальные.
- **VLAN 1 (Default/Black Hole):** на VLAN-aware мостах VLAN 1 присутствует по умолчанию на всех портах. В production рекомендуется удалять его (`bridge vlan del dev eth0 vid 1 self`), чтобы предотвратить неконтролируемый broadcast.
- **PVID и Egress Untagged:** на Access-порту нетегированные кадры помечаются PVID при входе, а тег удаляется при выходе.
- **Bridge VLAN Filtering:** включается при создании моста (`vlan_filtering 1`) или через `bridge vlan` команды.

**Настройка VLAN-aware моста:**
```bash
# Создание моста с VLAN filtering
sudo ip link add name br0 type bridge vlan_filtering 1

# Trunk порт: только VLAN 10 и 20 (VLAN pruning)
sudo bridge vlan add dev eth0 vid 10
sudo bridge vlan add dev eth0 vid 20
sudo bridge vlan del dev eth0 vid 1 self

# Access порт: VLAN 10, PVID, Untagged
sudo bridge vlan add dev vnet0 vid 10 pvid untagged

# Просмотр конфигурации
bridge vlan show
# → port    vlan ids
# → eth0    10 20
# → vnet0   10 PVID Egress Untagged
```

### FDB (Forwarding Database)

FDB хранит пары `<MAC, VLAN, порт>`. Записи имеют время ageing (по умолчанию 300 секунд). Если устройство не отправляет кадры в течение ageing time, запись удаляется.

**Ограничения FDB:**
- `fdb_max_global` — максимальное количество записей в FDB всего моста.
- `fdb_max_per_port` — максимальное количество записей на один порт.
При достижении лимита новые MAC-адреса не добавляются в таблицу, и трафик flood-ится.

**MAC Flapping:** возникает при перемещении одного MAC-адреса между портами (например, при миграции ВМ или наличии петли). Мост генерирует логи ядра (`kernel: br0: detected MAC flapping on ...`).

**Управление FDB:**
```bash
# Просмотр таблицы
bridge fdb show dev br0

# Просмотр с привязкой к VLAN
bridge fdb show dev br0 | grep vlan 10

# Добавление статической записи (Port Security аналог)
sudo bridge fdb add dev br0 52:54:00:12:34:56 master br0 vlan 10 self

# Удаление записи
sudo bridge fdb del dev br0 52:54:00:12:34:56 dev br0 vlan 10

# Очистка всей FDB
sudo bridge fdb flush dev br0

# Установка лимитов
sudo ip link set br0 type bridge fdb_max_global 10000
sudo ip link set br0 type bridge fdb_max_per_port 50
```

### IGMP Snooping

Механизм оптимизации многоадресного (Multicast) трафика. Мост «прослушивает» IGMP-сообщения и пересылает Multicast-кадры только в те порты, где есть активные подписчики группы. Это предотвращает засорение сети ненужным трафиком. По умолчанию включено в современных ядрах.

**Управление:**
```bash
# Включение/отключение
sudo ip link set br0 type bridge multicast_snooping 1

# Просмотр
cat /sys/class/net/br0/bridge/multicast_snooping
```

### Hairpin (Reflective Relay)

По умолчанию мост не отправляет кадр обратно в тот же порт, из которого он пришел. Режим **Hairpin** отменяет это ограничение. Это необходимо, например, когда несколько виртуальных машин или контейнеров общаются через один и тот же порт (например, при использовании VEPA — Virtual Ethernet Port Aggregator).

```bash
# Включение hairpin на порту
sudo bridge link set dev veth0 hairpin on

# Просмотр
bridge link show
# → 5: veth0 state forwarding hairpin on ...
```

### Фильтрация и безопасность

Для фильтрации трафика на уровне моста используются следующие механизмы:
*   **ebtables / nftables (family `bridge`):** Позволяют фильтровать кадры на основе Ethernet-заголовков (MAC-адреса, типы протоколов L2). В современных ядрах (5.x+) рекомендуется использовать `nftables` с семейством `bridge`, так как оно поддерживает stateful-фильтрацию через `conntrack` на уровне L2 без модуля `br_netfilter`.
*   **br_netfilter:** ИсторическиRequired модуль для передачи трафика моста в цепочки `iptables`/`nftables` уровня L3. В 2026 году при использовании нативного семейства `bridge` в `nftables` этот модуль **не рекомендуется** использовать без необходимости, так как он вызывает побочные эффекты в маршрутизации и двойную обработку пакетов.
*   **tc (traffic control):** Используется для storm control (ограничение broadcast/multicast) и rate-limiting на портах моста.
*   **nftables L2-фильтрация:** позволяет применять правила `arp operation`, `ether type`, `icmpv6 type` на bridge-интерфейсах.

### MTU и производительность

*   **MTU:** Размер MTU моста автоматически устанавливается равным минимальному MTU среди всех его активных портов. Если к мосту с MTU 9000 подключить интерфейс с MTU 1500, MTU всего моста упадет до 1500.
*   **Hardware Offloading:** некоторые NIC поддерживают offload для bridge (встроенный switch). Проверяется через `ethtool -k <iface> | grep -i bridge`.
*   **Оверхед:** Использование `br_netfilter` вносит дополнительную задержку. В высоконагруженных системах (DPDK, XDP) мосты часто заменяются на более быстрые механизмы.
*   **CPU overhead:** при极高ом PPS Software Bridge создаёт значительную нагрузку на CPU из-за обработки SoftIRQ. Для критичных нагрузок рассмотрите SR-IOV, macvlan mode bridge или Open vSwitch.

### Взаимодействие с другими технологиями

*   **Bonding + Bridge:** LACP-агрегат (`bond0`) можно подключить к мосту как единый порт. VLAN-интерфейсы создаются поверх `bond0`, а не физических интерфейсов.
*   **macvlan mode bridge:** создаёт виртуальные интерфейсы с собственными MAC-адресами, которые общаются через мост без промискуозного режима. Подходит для контейнеров с прямой L2-связностью.
*   **veth + Bridge:** стандартная схема для контейнеров (Docker, LXC). Один конец veth остаётся в мосту, второй перемещается в netns.
*   **VXLAN:** мост можно подключить к VXLAN-туннелю для создания overlay-сети поверх L3.

## Практические сценарии

### Сценарий 0: Проверка аппаратной поддержки и драйвера

Перед созданием моста убедитесь, что сетевой драйвер поддерживает необходимые функции.

```bash
# Проверка драйвера и доступных функций
ethtool -k eth0 | grep -iE 'vlan|tx-hw|rx-hw|seg|hw'

# Проверка поддержки bridge offload
ethtool -k eth0 | grep -i bridge

# Проверка текущего режима link
ip -d link show eth0
# → eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP mode DEFAULT
# →    link/ether 52:54:00:12:34:56 brd ff:ff:ff:ff:ff:ff
```

**Требования (Prerequisites):**

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (kernel 3.8+ для `vlan_filtering`, 5.x+ для нативных nftables bridge) |
| **Утилиты** | iproute2 (`ip`, `bridge`), ethtool |
| **Права** | root (sudo) |
| **Драйвер** | должен поддерживать VLAN offload (`tx-vlan-offload`, `rx-vlan-offload`) |

### Сценарий 1: Управление через iproute2

Современный стандарт управления сетевым стеком.

```bash
# Создание моста с VLAN filtering и STP
sudo ip link add name br0 type bridge vlan_filtering 1 stp_state 1

# Настройка STP параметров
sudo ip link set br0 type bridge priority 4096
sudo ip link set br0 type bridge forward_delay 4
sudo ip link set br0 type bridge max_age 600

# Активация моста
sudo ip link set br0 up

# Добавление физического интерфейса в мост
sudo ip link set eth0 master br0

# Включение edge port (аналог PortFast)
sudo bridge link set dev eth0 edgeport on

# Просмотр портов моста
ip link show master br0

# Просмотр таблицы MAC-адресов (FDB)
bridge fdb show dev br0

# Установка лимитов FDB
sudo ip link set br0 type bridge fdb_max_global 10000
sudo ip link set br0 type bridge fdb_max_per_port 50
```

### Сценарий 2: Настройка VLAN-aware моста

Позволяет использовать один мост для множества VLAN без создания интерфейсов типа `br0.10`.

```bash
# Создание моста с поддержкой VLAN filtering
sudo ip link add name br0 type bridge vlan_filtering 1

# Настройка порта как Access (PVID 10, нетегированный)
sudo bridge vlan add dev eth0 vid 10 pvid untagged

# Настройка порта как Trunk (тегированные VLAN 10 и 20)
sudo bridge vlan add dev eth1 vid 10
sudo bridge vlan add dev eth1 vid 20

# Удаление VLAN 1 по умолчанию (Black Hole)
sudo bridge vlan del dev eth1 vid 1 self

# Просмотр конфигурации VLAN
bridge vlan show
```

**Персистентная конфигурация (systemd-networkd):**

```ini
# /etc/systemd/network/30-br0.netdev
[NetDev]
Name=br0
Kind=bridge

[Bridge]
STP=yes
VLANFiltering=yes
FDBMaxGlobal=10000
FDBMaxPerPort=50
```

```ini
# /etc/systemd/network/31-br0-eth1.network
[Match]
Name=eth1

[Network]
Bridge=br0

[BridgeVLAN]
VLAN=10
[BridgeVLAN]
VLAN=20
```

Применение: `sudo networkctl reload && sudo networkctl reconfigure br0`

### Сценарий 3: Настройка через systemd-networkd

Рекомендуемый способ для серверов с системным менеджером systemd.

**/etc/systemd/network/25-br0.netdev:**
```ini
[NetDev]
Name=br0
Kind=bridge

[Bridge]
STP=yes
VLANFiltering=yes
```

**/etc/systemd/network/25-br0-bind.network:**
```ini
[Match]
Name=eth0

[Network]
Bridge=br0
```

### Сценарий 4: Bond + Bridge (LACP + VLAN-aware)

**Задача:** Создать отказоустойчивый LACP-агрегат и подключить его к VLAN-aware мосту.

```bash
# 1. Создание bonding (mode 802.3ad)
sudo modprobe bonding
sudo ip link add name bond0 type bond mode 802.3ad
sudo ip link set eth1 down
sudo ip link set eth2 down
sudo ip link set eth1 master bond0
sudo ip link set eth2 master bond0
sudo ip link set bond0 up

# 2. Создание моста с VLAN filtering
sudo ip link add name br0 type bridge vlan_filtering 1
sudo ip link set bond0 master br0
sudo ip link set br0 up

# 3. Настройка trunk на bond0 (VLAN 10, 20)
sudo bridge vlan add dev bond0 vid 10
sudo bridge vlan add dev bond0 vid 20
sudo bridge vlan del dev bond0 vid 1 self

# 4. Access порт для VM (vnet0 → VLAN 10)
sudo bridge vlan add dev vnet0 vid 10 pvid untagged
```

**Требования (Prerequisites):**

| Требование | Значение |
| :--- | :--- |
| **ОС** | Linux (kernel 3.10+ для bonding) |
| **Утилиты** | iproute2, ethtool |
| **Аппарат** | 2+ NIC, коммутатор с поддержкой LACP |
| **VLAN IDs** | 10, 20 |

**Ожидаемый результат (Validation):**
```bash
# Проверка bonding
cat /sys/class/net/bond0/bonding/ad_actor_oper_port_state
# → 1 (актор LACP активен)

# Проверка моста
bridge vlan show
# → port    vlan ids
# → bond0   10 20
# → vnet0   10 PVID Egress Untagged

# Проверка FDB
bridge fdb show dev br0
```

### Сценарий 5: Production hardening (FDB limit, Storm Control, VLAN Pruning)

Для production-сред рекомендуется применять hardening, аналогичный управляемым коммутаторам.

```bash
# 1. VLAN pruning: удаляем VLAN 1, оставляем только нужные
sudo bridge vlan del dev eth0 vid 1 self

# 2. FDB limit: защита от MAC Flooding
sudo ip link set br0 type bridge fdb_max_global 10000
sudo ip link set br0 type bridge fdb_max_per_port 50

# 3. Storm Control: ограничение broadcast/multicast через tc
sudo tc qdisc replace dev br0 clsact
sudo tc filter add dev br0 ingress protocol all flower \
  dst_mac ff:ff:ff:ff:ff:ff police rate 50mbit burst 100k drop

# 4. Edge Port: ускоряем поднятие link для серверов
sudo bridge link set dev eth0 edgeport on
sudo bridge link set dev eth0 bpduguard on
```

Для комплексной защиты L2 (ARP guard, MAC guard, RA Guard) см. **[Жёсткая защита L2](../../../Networking/Protocols/VLAN/vlan_security_hardening.md)**.

### Сценарий 6: Диагностика и мониторинг

- **Статистика трафика на портах:**
  ```bash
  ip -s link show master br0
  ```

- **Просмотр состояния STP:**
  ```bash
  bridge link show
  # → 2: eth0 state forwarding priority 32 cost 100

  # Через sysfs
  cat /sys/class/net/br0/bridge/stp_state
  # → 1
  ```

- **Отладка FDB:**
  ```bash
  # Найти конкретный MAC
  bridge fdb show | grep 52:54:00:12:34:56

  # Просмотр с VLAN
  bridge fdb show dev br0 | grep vlan 10

  # Проверка MAC flapping в логах
  dmesg | grep "MAC flapping"
  # → kernel: br0: detected MAC flapping on eth0 (52:54:00:12:34:56)
  ```

- **Захват трафика на мосту (L2):**
  ```bash
  # Захват с выводом Ethernet-заголовков
  sudo tcpdump -i br0 -e -n

  # Фильтр по VLAN
  sudo tcpdump -i br0 -e -n vlan 10

  # Поиск broadcast storm
  sudo tcpdump -i eth0 -n broadcast -c 100
  ```

- **Проверка storm control (tc):**
  ```bash
  tc filter show dev br0 ingress
  # → filter ingress 8000: flower police rate 50Mbit burst 100Kb
  ```

- **Проверка hardware offload:**
  ```bash
  ethtool -k eth0 | grep -iE 'vlan|bridge'
  # → tx-vlan-offload: on
  # → rx-vlan-offload: on
  ```

- **Проверка nftables bridge правил:**
  ```bash
  sudo nft list ruleset | grep -A10 bridge
  ```

- **Проверка через sysfs:**
  ```bash
  # Все параметры моста
  ls /sys/class/net/br0/bridge/

  # Multicast snooping
  cat /sys/class/net/br0/bridge/multicast_snooping

  # Ageing time
  cat /sys/class/net/br0/bridge/ageing_time
  ```

### Сценарий 7: Типичные ошибки и устранение неполадок

| Проблема | Признак | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Нет связи между портами моста** | `ping` таймаутит | `ip link show br0` — состояние UP? | Поднять интерфейсы: `sudo ip link set eth0 up` |
| **MAC не появляется в FDB** | `bridge fdb show` пуст | `tcpdump -i eth0 -e` — кадры доходят? | Проверить режим promiscuous, MTU, VLAN tag mismatch |
| **MAC Flapping** | `dmesg` показывает flapping | `bridge fdb show` — MAC на разных портах | Исключить петлю; включить STP `stp_state 1` |
| **Broadcast Storm** | Высокая нагрузка на CPU/сеть | `tcpdump -i eth0 -n broadcast -c 100` | Включить storm control через `tc`; проверить петли |
| **VLAN 1 broadcast-шторм** | Неожиданный трафик в VLAN 1 | `bridge vlan show` — vid 1 на портах? | Удалить VLAN 1: `bridge vlan del dev eth0 vid 1 self` |
| **Traffic не виден в tcpdump** | Нет тегов VLAN | `ethtool -k eth0 | grep vlan` — offload on | Отключить offload для диагностики: `sudo ethtool -K eth0 rx-vlan-offload off` |
| **STP долго поднимает порты** | Задержка 30-50 сек | `bridge link show` — состояние `listening` | Использовать RSTP (`forward_delay 4`) или edgeport |
| **FDB переполнена** | Трафик flood-ится | `bridge fdb show | wc -l` — лимит достигнут | Увеличить `fdb_max_global` или устранить MAC Flooding |
| **Контейнеры не видят друг друга** | Ping между контейнерами не работает | `bridge link show` — порты в мосту? | Проверить netns, firewall (nftables), VLAN tagging |

### Сценарий 8: Очистка окружения (Cleanup)

```bash
# Удаление VLAN с портов
sudo bridge vlan del dev eth0 vid 10
sudo bridge vlan del dev eth0 vid 20
sudo bridge vlan del dev vnet0 vid 10 pvid untagged

# Отключение STP
sudo ip link set br0 type bridge stp_state 0

# Удаление портов из моста
sudo ip link set eth0 nomaster
sudo ip link set vnet0 nomaster

# Удаление моста
sudo ip link set br0 down
sudo ip link delete br0 type bridge

# Удаление tc фильтров
sudo tc qdisc del dev br0 clsact

# Удаление nftables правил (если добавлялись)
sudo nft delete table inet arp_guard
sudo nft delete table inet mac_guard
```

## Ограничения и особенности (Edge Cases)

- **Малые пакеты (< 64 байт):** при очень высоком PPS (packets per second) накладные расходы обработки Software Bridge доминируют над полезной работой. Рассмотрите XDP_DROP, AF_XDP или SR-IOV.
- **UDP и MAC-флапы:** UDP-трафик без обратной связи не поддерживает коннекционистские механизмы, поэтому при перемещении MAC-адреса UDP-потоки могут теряться до обновления FDB.
- **KVM / QEMU:** интерфейсы `vnet*` создаются динамически. При миграции ВМ мост обновляет FDB, но может генерировать MAC flapping.
- **Контейнеры (Docker/LXC):** по умолчанию Docker создаёт isolated bridge для каждого проекта. Для L2-связности контейнеров используйте один общий bridge или macvlan.
- **cgroups / systemd:** мост наследует ограничения cgroup CPU/Net_cls от процесса, создавшего его (обычно systemd-networkd). Убедитесь, что служба имеет достаточный приоритет.
- **CONFIG_BRIDGE_NETFILTER:** если модуль `br_netfilter` загружен, он «пробрасывает» весь трафик моста в цепочки `filter/FORWARD` и `nat/POSTROUTING`. Это может вызвать неожиданное поведение firewall. Отключите модуль, если он не требуется: `sudo rmmod br_netfilter`.
- **VLAN-aware и legacy мосты одновременно:** на одном хосте можно иметь и VLAN-aware мост (`vlan_filtering 1`), и legacy сабинтерфейсы (`eth0.10`), но они не должны пересекаться на одном физическом интерфейсе.

## Сравнение с Open vSwitch (OVS)

| Характеристика | Linux Bridge | Open vSwitch |
| :--- | :--- | :--- |
| **Реализация** | Ядро Linux | Ядро + Userspace демоны |
| **Сложность** | Низкая (часть ОС) | Высокая (требует настройки) |
| **SDN / OpenFlow** | Нет | Да (полная поддержка) |
| **Туннелирование** | Ограничено (VXLAN через ip link) | Глубокая интеграция (VXLAN, Geneve) |
| **Применение** | Docker, LXC, простые KVM | OpenStack, сложные SDN, DPDK |
| **Storm Control** | Через `tc` | Нативное (hardware/software) |
| **FDB Limits** | `fdb_max_global`, `fdb_max_per_port` | Flow-based, более гибкие |

## См. также

* **[Протокол STP](../../../Networking/Protocols/stp.md)** — алгоритмы исключения петель и выбор Root Bridge.
* **[nftables: сегментирование сети](../Settings/tools/nftables/network_segmentation.md)** — примеры L2-фильтрации.
* **[nftables: прозрачный мост (OneButtonFirewall)](../Settings/tools/nftables/one_button_firewall.md)** — паттерн L2-брандмауэра на nftables.
* **[VLAN-aware Bridge: production-ready сценарий](../../../Networking/Concepts/vlan_l2_switching/vlan_design_patterns.md)** — VLAN pruning, FDB limit, storm control.
* **[Жёсткая защита Linux Bridge](../../../Networking/Protocols/VLAN/vlan_security_hardening.md)** — ARP guard, MAC guard, RA Guard, FDB limit.
* **[Практические сценарии L2 Switching и VLAN](../../../Networking/Concepts/vlan_l2_switching/practical_scenarios.md)** — Bonding + VLAN, Q-in-Q, Router-on-a-Stick.
* **[VLAN в Linux: диагностика](../../../Networking/Protocols/VLAN/vlan_linux_diagnostics.md)** — подробнее о VLAN-aware мостах и сабинтерфейсах.
* **[Драйвер Bridge в Docker](../../../Docker/Docker_network/drivers/bridge.md)** — реализация сетевой изоляции контейнеров.
* **[Сетевые интерфейсы в Linux](./linux_network_interfaces.md)** — обзор типов устройств (TAP, VETH, Bridge).
* **[iproute2: управление ссылками и мостами](../Tools/iproute2/ip_link.md)** — справка по командам `ip link` для bridge.
