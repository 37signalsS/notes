# VLAN в Linux: механизмы, настройка и диагностика

## Определения

**VLAN (Virtual LAN)** в Linux — программная реализация стандарта **IEEE 802.1Q** на уровне ядра. Позволяет разделять трафик на логические сегменты (L2) в рамках одного физического интерфейса или агрегата (Bonding).

**802.1Q sub-interface** — традиционный метод (legacy), при котором для каждого VLAN ID создается отдельный виртуальный сетевой интерфейс (например, `eth0.100`), имеющий собственный MAC-адрес (обычно наследуемый) и стек протоколов.

**VLAN-aware Bridge** — современный механизм (начиная с ядра 3.8), превращающий обычный Linux Bridge в полноценный L2-коммутатор с поддержкой тегирования. Позволяет управлять VLAN-тегами непосредственно на портах моста (Trunk/Access), избавляя от необходимости создавать сотни сабинтерфейсов.

**FDB (Forwarding Database)** — внутренняя таблица моста, сопоставляющая MAC-адреса устройств с портами моста. Управляется утилитой `bridge fdb`.

**PVID (Port VLAN ID)** — идентификатор VLAN по умолчанию для нетегированных кадров, поступающих на порт моста. Управляется флагом `pvid` в `bridge vlan add`.

**Egress Untagged** — флаг, указывающий, что при выходе с порта тег данного VLAN должен быть удалён (аналог Native VLAN в Trunk или Access-порта).

## Основные механизмы VLAN в Linux

### 1. Традиционные сабинтерфейсы (802.1Q)
Создаются с помощью утилиты `ip link` (пакет `iproute2`).
- **Флаги ядра (VLAN Flags):**
    - **REORDER_HDR:** Удаляет VLAN-заголовок из пакета перед его передачей выше по стеку. Это стандартное поведение, необходимое для корректной работы большинства приложений.
    - **LOOSE_BINDING:** Состояние VLAN-интерфейса не привязывается жестко к состоянию физического интерфейса (интерфейс может оставаться UP, даже если кабель вынут).
    - **GVRP / MVRP:** Поддержка протоколов динамической регистрации VLAN.
- **Ограничения:** для каждого VLAN требуется отдельный интерфейс. При большом количестве VLAN (100+) возникает накладная overhead на ядро и увеличивается потребление памяти.

### 2. VLAN-aware Bridge
Активируется флагом `vlan_filtering 1`. Мост начинает анализировать теги входящих кадров и сопоставлять их с таблицей фильтрации (`VLAN Filter Table`).
- **PVID (Port VLAN ID):** Определяет VLAN для нетегированных входящих кадров (аналог Access-порта).
- **Egress Untagged:** Указывает, что при выходе с этого порта тег данного VLAN должен быть удален (аналог Native VLAN в Trunk или просто Access-порта).
- **Self VLAN:** Параметр, применяемый к самому мосту (не порту). Определяет VLAN-тег для трафика, генерируемого самим хостом (например, ARP-запросы от IP-адреса моста).

### 3. VLAN поверх агрегации (Bonding/Teaming)
Для обеспечения отказоустойчивости VLAN-интерфейсы создаются не на физических картах (`eth0`), а на логическом агрегате (`bond0`).
- **SSoT:** Подробнее см. **[Агрегация каналов (Bonding)](../../Concepts/link_aggregation.md)**.

### 4. VLAN в macvlan/ipvlan
Позволяет создавать виртуальные интерфейсы с собственным MAC-адресом (macvlan) или разделяющим MAC-адрес (ipvlan) поверх физического интерфейса. Используется в контейнерных средах для полной изоляции.
- **SSoT:** Подробнее см. **[macvlan](../../../Docker/Docker_network/drivers/macvlan.md)** и **[ipvlan](../../../Docker/Docker_network/drivers/ipvlan.md)**.

## Инструменты диагностики

### 1. Утилита `ip` (iproute2)

Основной инструмент для управления и диагностики VLAN-интерфейсов.

```bash
# Просмотр всех интерфейсов с VLAN-меткой
ip -d link show type vlan

# Детальный вывод для конкретного интерфейса (флаги, MTU, VLAN ID)
ip -d link show eth0.100
# → vlan protocol 802.1Q id 100 <REORDER_HDR> ...
# → mtu 1500 qdisc noqueue state UP ...
# → link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff

# Просмотр IP-адресов на VLAN-интерфейсе
ip addr show eth0.100

# Просмотр статистики (ошибки, dropped, overruns)
ip -s link show eth0.100
```

**Ключевые поля в выводе `ip -d`:**
- `vlan protocol 802.1Q id 100`: подтверждение протокола и ID.
- `<REORDER_HDR>`: флаг удаления заголовка (обычно активен).
- `<LOOSE_BINDING>`: если присутствует, интерфейс не падает при потере линка.
- `master br0`: указывает, что интерфейс является портом моста.

### 2. Утилита `bridge`

Управление VLAN-aware мостами и их портами.

```bash
# Просмотр VLAN-таблицы на всех портах моста
bridge vlan show
# → port    vlan ids
# → eth0    1 PVID Egress Untagged    <-- Access-порт в VLAN 1
# → eth1    10                        <-- Trunk-порт (разрешен VLAN 10)
# →         20                        <-- Trunk-порт (разрешен VLAN 20)
# →         999 PVID Egress Untagged  <-- Trunk с Native VLAN 999

# Просмотр VLAN на конкретном порту
bridge vlan show dev eth0

# Просмотр VLAN на мосте (self)
bridge vlan show dev br0

# Добавление VLAN на порт
sudo bridge vlan add dev eth0 vid 10

# Настройка Access-порта (PVID + нетегированный выход)
sudo bridge vlan add dev eth0 vid 10 pvid untagged

# Настройка Native VLAN для Trunk-порта
sudo bridge vlan add dev eth0 vid 999 pvid untagged

# Удаление VLAN с порта
sudo bridge vlan del dev eth0 vid 10

# Удаление VLAN 1 по умолчанию (рекомендуется)
sudo bridge vlan del dev eth0 vid 1
sudo bridge vlan del dev eth0 vid 1 self
```

### 3. Файловая система `/proc`

Ядро экспортирует информацию о VLAN в текстовом виде.

```bash
# Список всех VLAN и их физических устройств
cat /proc/net/vlan/config
# → VLAN Dev name    VID   Plugins  BRIDGE
# → eth0.100         100   8021q
# → bond0.200        200   8021q

# Статистика и флаги для конкретного интерфейса
cat /proc/net/vlan/eth0.100
# → eth0.100  VID: 100  REORDER_HDR: 1  MVRP: 0  GVRP: 0
# → Device: eth0  VLAN_INGRESS: BRIDGE_INGRESS
# → total frames received        12345
# → total bytes received          1234567
# → total frames transmitted      12340
# → total bytes transmitted       1234000
```

### 4. Файловая система `/sys` (sysfs)

Параметры моста доступны через sysfs для мониторинга и тонкой настройки.

```bash
# Проверка VLAN-фильтрации
cat /sys/class/net/br0/bridge/vlan_filtering
# → 1

# Просмотр всех VLAN на порту моста
ls /sys/class/net/br0/bridge/vlan/
# → default  10  20  999

# Просмотр PVID порта
cat /sys/class/net/eth0/bridge/vlan_pvid
# → 999

# Просмотр STP состояния
cat /sys/class/net/br0/bridge/stp_state
# → 1 (включен) / 0 (выключен)

# Просмотр FDB limit
cat /sys/class/net/br0/bridge/fdb_max
# → 10000 (значение по умолчанию)

# Просмотр MTU моста
cat /sys/class/net/br0/mtu
# → 1500
```

### 5. `ethtool` (Hardware Offloading)

Проверка аппаратной поддержки VLAN-тегирования.

```bash
# Проверка hardware offloading для VLAN
ethtool -k eth0 | grep vlan
# → rx-vlan-offload: on
# → tx-vlan-offload: on

# Проверка поддержки protocols
ethtool -k eth0 | grep -i "vlan\|802.1"
# → vlan-challenged: off
```

**Важно:** При включённом `rx-vlan-offload` ядро удаляет тег до передачи в пользовательское пространство. Это значит, что `tcpdump -i eth0 -e` может не отображать тег. Для диагностики тегов временно отключите offloading:
```bash
sudo ethtool -K eth0 rx-vlan-offload off tx-vlan-offload off
# ... диагностика ...
sudo ethtool -K eth0 rx-vlan-offload on tx-vlan-offload on
```

### 6. `tcpdump` (Захват трафика)

Критически важный инструмент для проверки тегирования на физическом линке.

```bash
# Захват всех VLAN-тегированных кадров на физическом интерфейсе
sudo tcpdump -i eth0 -e -nn vlan

# Фильтрация по конкретному VLAN ID
sudo tcpdump -i eth0 -e -nn vlan 10

# Захват только 802.1Q кадров с отображением PCP (приоритет)
sudo tcpdump -i eth0 -e -nn 'vlan and (vlan & 0xe0 != 0)'

# Захват кадров с двойным тегом (QinQ / VLAN Hopping detection)
sudo tcpdump -i eth0 -e -nn 'vlan and vlan'

# Захват на VLAN-интерфейсе (трафик уже без тега)
sudo tcpdump -i eth0.100 -e -nn

# Захват с ограничением по количеству пакетов
sudo tcpdump -i eth0 -e -nn vlan 10 -c 10
```

**Различия захвата:**
| Интерфейс | Что видно | Типичное применение |
| :--- | :--- | :--- |
| `eth0` (физический) | Все кадры с тегами 802.1Q | Проверка Trunk, поиск атак |
| `eth0.100` (сабинтерфейс) | Только кадры VLAN 100, без тегов | Диагностика приложения |
| `br0` (мост) | Кадры после обработки мостом | Проверка фильтрации |
| `vnet0` (VM interface) | Кадры от/к конкретной VM | Диагностика виртуализации |

### 7. `tc` (Traffic Control)

Управление очередями и фильтрация на уровне VLAN.

```bash
# Просмотр текущих qdisc на интерфейсе
tc qdisc show dev eth0

# Добавление фильтра для приоритезации по VLAN PCP
# ( requires kernel 4.4+ and flower classifier)
sudo tc qdisc add dev eth0 ingress
sudo tc filter add dev eth0 parent fff: protocol 802.1q \
  flower vlan_id 10 vlan_pcp 5 \
  action mirred egress redirect dev eth0.10

# Просмотр активных фильтров
tc filter show dev eth0 ingress
```

## Валидация конфигурации

### Валидация сабинтерфейсов

```bash
# 1. Интерфейс существует и UP
ip link show eth0.100
# → state UP

# 2. VLAN ID корректен
ip -d link show eth0.100 | grep "vlan id"
# → vlan protocol 802.1Q id 100

# 3. IP-адрес назначен
ip addr show eth0.100
# → inet 192.168.10.100/24

# 4. Теги присутствуют на физическом линке
sudo tcpdump -i eth0 -e -nn vlan 100 -c 5

# 5. Пинг шлюза
ping -c 3 192.168.10.1

# 6. Статистика (ошибок быть не должно)
ip -s link show eth0.100
# → RX: 0 errors, 0 dropped
# → TX: 0 errors, 0 dropped
```

### Валидация VLAN-aware Bridge

```bash
# 1. Мост существует и включена фильтрация
ip link show br0
# → vlan_filtering 1

# 2. VLAN-таблица корректна
bridge vlan show
# → port    vlan ids
# → eth0    10 20 999 PVID Egress Untagged
# → vnet0   10 PVID Egress Untagged

# 3. FDB содержит записи для нужных VLAN
bridge fdb show dev br0 | grep "vlan 10"
# → aa:bb:cc:dd:ee:ff dev vnet0 master br0 self

# 4. Порты моста в нужном состоянии
ip link show master br0
# → eth0: state UP
# → vnet0: state UP

# 5. Проверка VLAN 1 удалена (рекомендуется)
bridge vlan show | grep "1 PVID"
# → (не должно быть строк除了 self на br0)

# 6. Проверка self VLAN на мосте
bridge vlan show dev br0 self
# → 999 PVID Egress Untagged
```

### Валидация QinQ (802.1ad)

```bash
# 1. Внешний (service) интерфейс существует
ip -d link show eth0.1000
# → vlan protocol 802.1ad id 1000

# 2. Внутренний (customer) интерфейс существует
ip -d link show eth0.1000.10
# → vlan protocol 802.1Q id 10

# 3. Оба тега видны на физическом линке
sudo tcpdump -i eth0 -e -nn 'vlan 1000 and vlan 10' -c 3

# 4. MTU физического интерфейса увеличен
ip link show eth0 | grep mtu
# → mtu 1508
```

## Типичные проблемы и их решения (Troubleshooting)

| Проблема | Симптомы | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Нет пинга, настройки верны** | `ping` не проходит, ARP не резолвится | Порт коммутатора в режиме Access, а не Trunk | `tcpdump -i eth0 -e vlan` — если входящих тегов нет, проблема на коммутаторе. Переведите порт в trunk |
| **VLAN-интерфейс DOWN** | `ip link show eth0.100` — state DOWN | Физический интерфейс `eth0` выключен или нет link | `ip link show eth0` — проверьте UP/DOWN. Если DOWN: `sudo ip link set eth0 up` |
| **Ошибки MTU (Packet drops)** | Пакеты >1500 байт отбрасываются; SSH работает, SCP зависает | MTU физического интерфейса = 1500, а кадр с тегом = 1504. Если QinQ — 1508 | `sudo ip link set dev eth0 mtu 1508` (или 9000 для jumbo). Проверка: `ping -M do -s 1472 <dest>` |
| **Hardware offload скрывает теги** | `tcpdump -i eth0 -e` не показывает теги | `rx-vlan-offload` включён — ядро снимает тег до tcpdump | `sudo ethtool -K eth0 rx-vlan-offload off tx-vlan-offload off` (временно). После диагностики включить обратно |
| **Дублирование MAC-адресов** | Кадры приходят не в тот VLAN | Конфликт MAC в VLAN-aware Bridge | `bridge fdb show` — проверьте MAC-таблицу. Удалите дублирующие записи |
| **VLAN 1 traffic leak** | Широковещательный трафик из VLAN 1 появляется в пользовательских VLAN | VLAN 1 не удалена с портов моста | `bridge vlan del dev eth0 vid 1` и `bridge vlan del dev eth0 vid 1 self` |
| **FDB满了 (fdb_max overflow)** | Новые MAC-адреса не обучаются, трафик floodится | Достигнут лимит `fdb_max` | Увеличьте: `sudo ip link set br0 type bridge fdb_max 20000` или найдите rogue-устройство |
| **Native VLAN mismatch** | Широковещательный трафик попадает в неправильный VLAN | Разные PVID на двух концах Trunk | На обоих концах установите одинаковый PVID: `bridge vlan add dev eth0 vid 999 pvid untagged` |
| **tc filter не работает** | Приоритезация по PCP не влияет на обработку | `flower` classifier не поддерживается в ядре | Проверьте `tc filter show`. Используйте `u32` classifier как альтернативу |

### Пошаговая процедура диагностики

```
1. ФИЗИЧЕСКИЙ УРОВЕНЬ
   └─ ip link show <iface>          → state UP? speed/duplex?
   └─ ethtool <iface>              → link detected: yes?
   └─ ip -s link show <iface>      → errors, dropped?

2. VLAN-КОНФИГУРАЦИЯ
   └─ ip -d link show <iface>      → vlan id, flags?
   └─ cat /proc/net/vlan/config    → список всех VLAN
   └─ bridge vlan show             → таблица фильтрации (для bridge)

3. ТЕГИРОВАНИЕ
   └─ tcpdump -i <phys_iface> -e vlan <ID>
   └─ tcpdump -i <phys_iface> -e 'vlan and vlan'  → QinQ / double-tag?

4. FDB И MAC-ТАБЛИЦА
   └─ bridge fdb show | grep <MAC> → есть ли запись?
   └─ bridge fdb show dev <iface>  → какие MAC на порту?

5. IP-УРОВЕНЬ
   └─ ip addr show <vlan_iface>    → IP назначен?
   └─ ip route show                → маршрут есть?
   └─ ping -c 3 <gateway>          → связность

6. MTU
   └─ ping -M do -s 1472 <dest>    → Path MTU проверка
   └─ ip link show <iface> | grep mtu

7. STP
   └─ bridge link show             → Forwarding/Blocking?
   └─ cat /sys/class/net/br0/bridge/stp_state
```

## Сохранение конфигурации (Persistence)

Временные настройки `ip link` теряются при перезагрузке. Для постоянной конфигурации используйте один из методов:

### 1. Netplan (Ubuntu/Debian)
Описывается в `/etc/netplan/*.yaml`. Поддерживает VLAN, bridges, bonds.

```yaml
# /etc/netplan/01-vlans.yaml
network:
  version: 2
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
Применение: `sudo netplan apply`

### 2. systemd-networkd (Debian, Arch, Fedora)
Два типа файлов в `/etc/systemd/network/`:

```ini
# /etc/systemd/network/10-vlan10.netdev (создание VLAN)
[NetDev]
Name=eth0.10
Kind=vlan

[VLAN]
Id=10

# /etc/systemd/network/20-eth0.network (привязка к физическому интерфейсу)
[Match]
Name=eth0

[Network]
VLAN=eth0.10
VLAN=eth0.20
```

Для VLAN-aware bridge:
```ini
# /etc/systemd/network/30-br0.netdev
[NetDev]
Name=br0
Kind=bridge

[Bridge]
STP=yes
VLANFiltering=yes

# /etc/systemd/network/30-br0-bind.network
[Match]
Name=eth0

[Network]
Bridge=br0

# /etc/systemd/network/30-br0.network
[Match]
Name=br0

[Network]
Address=192.168.100.1/24
```
Применение: `sudo networkctl reload && sudo networkctl reconfigure br0`

### 3. NetworkManager (RHEL, CentOS, Ubuntu Desktop)
Использует `nmcli`.

```bash
# Создание VLAN-интерфейса
sudo nmcli connection add type vlan con-name vlan10 \
  dev eth0 id 10 \
  ipv4.addresses 192.168.10.100/24 \
  ipv4.method manual

# Активация
sudo nmcli connection up vlan10

# Создание VLAN-aware bridge
sudo nmcli connection add type bridge con-name br0 \
  bridge.vlan-filtering yes \
  ipv4.addresses 192.168.100.1/24

# Привязка физического интерфейса к мосту
sudo nmcli connection add type ethernet con-name br0-slave \
  ifname eth0 master br0
```

### 4. ifupdown2 (Debian, older Ubuntu)
Через `/etc/network/interfaces`.

```
# /etc/network/interfaces
auto eth0
iface eth0 inet manual

auto eth0.10
iface eth0.10 inet static
    address 192.168.10.100/24
    vlan-raw-device eth0

auto br0
iface br0 inet static
    address 192.168.100.1/24
    bridge-ports eth0
    bridge-vlan-aware yes
    bridge-vids 10 20 999
    bridge-pvid 999
```
Применение: `sudo ifup -a && sudo ifdown <old_iface>`

## Edge Cases

### 1. LOOSE_BINDING и hot-plug
Если VLAN-интерфейс создан с флагом `LOOSE_BINDING` (или через NetworkManager), он может оставаться UP даже после отключения физического кабеля. Это полезно для миграции, но опасно для мониторинга — проверяйте `ip -d link show` для флагов.

### 2. VLAN 1 по умолчанию
При создании VLAN-aware bridge все порты по умолчанию получают VLAN 1. Если VLAN 1 не используется, она создаёт broadcast-домен, который может засорять сеть. **Удаляйте VLAN 1** с портов и моста.

### 3. Проблема при добавлении интерфейса в bridge
При добавлении интерфейса в bridge (`ip link set eth0 master br0`) его VLAN-конфигурация сбрасывается. Вся настройка VLAN должна выполняться **после** добавления в мост.

### 4. FDB + VLAN = isolation
Записи в FDB содержат VLAN ID. MAC-адрес `aa:bb:cc:dd:ee:ff` в VLAN 10 и тот же MAC в VLAN 20 — это **разные записи**. Если MAC-конфликт только в одном VLAN, проверяйте `bridge fdb show vlan <id>`.

### 5. Мультикаст и IGMP Snooping
По умолчанию включён. Если multicast-трафик не проходит через bridge:
```bash
# Проверка IGMP snooping
cat /sys/class/net/br0/bridge/multicast_router
# → 1 (auto) / 0 (disabled) / 2 (enabled)

# Включение если отключён
echo 2 | sudo tee /sys/class/net/br0/bridge/multicast_router
```

## Best Practices

1. **Удаляйте VLAN 1** со всех портов и моста, если она не используется.
2. **Используйте VLAN-aware bridge** вместо множества сабинтерфейсов при количестве VLAN > 5.
3. **Отключайте hardware offload** при диагностики через tcpdump.
4. **Документируйте VLAN-таблицу:** для каждого порта моста ведите список VID ↔ назначение.
5. **Настройте `fdb_max`** при работе с контейнерами ( сотни MAC-адресов).
6. **Используйте `bridge vlan`** вместо `brctl` (устарело) для управления VLAN.
7. **Проверяйте MTU** при работе с QinQ и туннелями (GRE, WireGuard).
8. **Используйте persistent-метод** (Netplan/systemd-networkd/NetworkManager) вместо ручных команд `ip link`.

## Дополнительная информация

### VLAN в контейнерах (Docker/Podman)

Контейнеры могут использовать VLAN через несколько механизмов:

**Docker macvlan:**
```bash
# Создание macvlan-сети с VLAN
docker network create -d macvlan \
  --subnet=192.168.10.0/24 \
  --gateway=192.168.10.1 \
  -o parent=eth0 \
  -o macvlan_mode=bridge \
  vlan10_net

# Запуск контейнера в VLAN
docker run --rm -it --network vlan10_net --name app1 alpine
```

**Podman macvlan:**
```bash
# rootless macvlan
podman network create \
  --driver macvlan \
  --subnet 192.168.20.0/24 \
  --gateway 192.168.20.1 \
  -o parent=eth0 \
  vlan20_net

podman run --rm -it --network vlan20_net alpine
```

**Bridge VLAN для контейнеров:**
```bash
# Если контейнеры в VLAN-aware bridge — отключите PVID для isolation
sudo bridge vlan add dev docker0 vid 10
sudo bridge vlan add dev docker0 vid 20
# Для изоляции контейнеров: разные VLAN на разных портах
```

### Open vSwitch (OVS) — VLAN

Для production-сред с виртуализацией (KVM, OpenStack) используйте OVS вместо kernel bridge:

```bash
# Создание OVS моста с VLAN trunk
sudo ovs-vsctl add-br br-int
sudo ovs-vsctl add-port br-int eth0
sudo ovs-vsctl set port eth0 trunk=10,20,30

# Access port для VM
sudo ovs-vsctl add-port br-int tap0
sudo ovs-vsctl set port tag=10 tag=10

# Проверка VLAN
sudo ovs-vsctl show
sudo ovs-vsctl list port
```

Детали см. в **[Open vSwitch (OVS) и OVN](../../../Networking/ServicesAndTools/open_vswitch.md)**.

### Смежные документы

- **[Формат кадра 802.1Q](./vlan_8021q_frame.md)** — структура и поля тега.
- **[Trunk и Native VLAN](./vlan_trunk_native.md)** — работа магистральных портов и Native VLAN.
- **[Linux Bridge](../../../Linux/Networking/Concepts/linux_bridge.md)** — архитектура и возможности мостов в Linux.
- **[L2 Switching и VLAN: Практические сценарии](../../Concepts/vlan_l2_switching/practical_scenarios.md)** — расширенные примеры (QinQ, ROAS, Bonding+VLAN).
- **[Безопасность L2: DHCP Snooping, DAI, IPSG](./vlan_security_hardening.md)** — жёсткая защита VLAN-aware bridge.
- **[Проектирование VLAN](../../Concepts/vlan_l2_switching/vlan_design_patterns.md)** — production-ready топологии.
- **[Наблюдаемость VLAN](./vlan_monitoring.md)** — SNMP, NetFlow, Prometheus для production-мониторинга.
- **[Docker macvlan](../../../Docker/Docker_network/drivers/macvlan.md)** — сетевой драйвер macvlan для контейнеров.
- **[Ansible — сетевая автоматизация](../../../Ansible/ansible_network_automation.md)** — управление VLAN через Ansible.
