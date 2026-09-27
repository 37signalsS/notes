# Сетевые интерфейсы в Linux: типы и применение

## Определения

**Сетевой интерфейс** — программная абстракция в ядре Linux, представляющая собой точку входа и вывода для сетевого трафика. Каждый интерфейс имеет уникальное имя, состояние, MAC-адрес, MTU и привязан к драйверу сетевого адаптера или виртуальному устройству. Интерфейс может быть привязан к физическому устройству (**NIC — Network Interface Card**) или быть полностью виртуальным.

**NIC (Network Interface Card)** — аппаратный сетевой адаптер (Ethernet, Wi-Fi, Fiber Channel). В Linux каждый NIC представляется как один или несколько сетевых интерфейсов, привязанных к драйверу через sysfs (`/sys/class/net/<iface>/device/driver`).

**Netlink / Rtnetlink** — механизм межпроцессного взаимодействия между userspace и ядром Linux для управления сетевым стеком. Утилиты `ip`, `ss`, `nft` используют netlink сокеты для настройки интерфейсов, адресов, маршрутов и правил.

**Sysfs (`/sys/class/net`)** — виртуальная файловая система, отражающая состояние всех сетевых интерфейсов. Содержит симлинки на устройство, драйвер, статистику, MTU, MAC-адрес и атрибуты.

**Udev / Systemd-udevd** — демон управления устройствами в userspace. Читает правила из `/etc/udev/rules.d/` и `/lib/udev/rules.d/` для назначения имен интерфейсам, создания симлинков и применения статических атрибутов.

**ethtool** — утилита для диагностики и настройки параметров NIC на уровне драйвера: скорость, дуплекс, коалесценция, аппаратные offload, кольцевые буферы, статистика.

**MAC-адрес (Media Access Control)** — уникальный идентификатор интерфейса на L2. Может быть статическим (записан в EEPROM NIC) или динамическим (спойфен/changed через `ip link set dev <iface> address <mac>`).

**MTU (Maximum Transmission Unit)** — максимальный размер полезной нагрузки кадра, передаваемого через интерфейс без фрагментации. Стандарт Ethernet — 1500 байт. Для IPv6 минимальный MTU — 1280 байт (RFC 8200).

**Promiscuous mode (PROMISC)** — режим интерфейса, при котором NIC принимает все кадры из сегмента, а не только адресованные его MAC-адресу. Используется для сниффинга, мониторинга и работы bridge.

## Основные концепции

### 1. Физические интерфейсы

Напрямую привязаны к аппаратному обеспечению. В современных дистрибутивах используются **предсказуемые имена** (Predictable Network Interface Names), отражающие физическое расположение устройства на шине.

*   **Имена:** `enp3s0` (Ethernet на шине PCI 3, слот 0), `wlp2s0` (Wi-Fi на шине PCI 2), `ens1f0` (onboard, slot 1, function 0). Старые имена `ethX` сохраняются при отключении этой функции через параметры ядра (`net.ifnames=0`) или в облачных средах.
*   **Стратегии именования:**
    *   **biosdevname:** использует ACPI и данные BIOS (`/sys/class/net/` → `biosdevname`). Требует установки пакета `biosdevname`.
    *   **systemd predictable:** на основе ID шины PCI, slot, function. По умолчанию в systemd-based системах.
    *   **ifrename / udev:** кастомные правила в `/etc/udev/rules.d/70-persistent-net.rules` для переименования по MAC, slot или driver.
*   **Альтернативные имена (altnames):** Современные ядра позволяют назначать интерфейсу несколько имен. Это удобно для миграции или именования по ролям (например, `uplink0`).
    ```bash
    # Добавление альтернативного имени
    sudo ip link property add dev enp3s0 altname uplink0

    # Просмотр всех имен интерфейса
    ip -details link show enp3s0
    # → altname uplink0
    ```
*   **Связь с драйвером:**
    ```bash
    # Узнать драйвер интерфейса
    readlink /sys/class/net/enp3s0/device/driver
    # → ../../../../bus/pci/drivers/ice

    # Версия драйвера
    ethtool -i enp3s0
    # → driver: ice
    # → version: 4.10.0
    # → firmware-version: 3.00 0x800129cd
    ```

### 2. Состояния интерфейсов

При просмотре через `ip link` интерфейс имеет несколько флагов состояния. Понимание флагов критично для диагностики.

| Флаг | Значение | Диагностическое значение |
|------|----------|--------------------------|
| **UP** | Интерфейс программно активирован | Отсутствие = интерфейс выключен административно |
| **LOWER_UP** | Физический уровень (L1) активен | Отсутствие = нет линка, кабель не подключен, порт коммутатора выключен |
| **NO-CARRIER** | Физический линк отсутствует | Нужно проверить кабель, порт коммутатора, autonegotiation |
| **PROMISC** | Смешанный режим | Присутствует при работе bridge, tcpdump, containers |
| **LOOPBACK** | Интерфейс обратной петли | Только для `lo` |
| **BROADCAST** | Интерфейс поддерживает broadcast | Типично для Ethernet |
| **MULTICAST** | Интерфейс поддерживает multicast | Типично для Ethernet |
| **DYNAMIC** | Адрес получен динамически | RARP, BOOTP, DHCP |
| **NOARP** | ARP отключен | Для point-to-point интерфейсов (например, `tun`), loopback |
| **DEBUG** | Режим отладки драйвера | Обычно отсутствует |

```bash
# Диагностика состояния
ip -details link show enp3s0
# → 2: enp3s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000
# → link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff

# Проверка только флагов
ip link show enp3s0 | grep -o '<[^>]*>' | tr ',' '\n'
# → BROADCAST
# → MULTICAST
# → UP
# → LOWER_UP
```

### 3. Виртуальные интерфейсы общего назначения

#### Интерфейс обратной петли (Loopback)

Интерфейс `lo` указывает на локальный хост (`127.0.0.1` / `::1`). Критически важен для работы внутренних сервисов и IPC (Inter-Process Communication). Всегда должен иметь состояние UP и адрес 127.0.0.1/8.

```bash
# Проверка loopback
ip -4 addr show lo
# → inet 127.0.0.1/8 scope host lo
# → inet6 ::1/128 scope host

# Пинг loopback (базовая проверка TCP/IP стека)
ping -c 3 127.0.0.1
# → 3 packets transmitted, 3 received, 0% packet loss
```

#### Виртуальный Ethernet (veth)

Создается парой (`veth pair`). Работает как виртуальный патч-корд: пакет, входящий в один интерфейс, выходит из другого. Является фундаментом для контейнеризации.

*   **Применение:** Соединение сетевых пространств имен (**Network Namespaces**) контейнеров (Docker, Podman) с мостами хоста.
*   **Параметры:** `peer name` (имя второго интерфейса), `queue` (количество очередей для multi-queue), `mode` (режим работы).
*   **Особенности:** При удалении одного интерфейса пара автоматически удаляется.

```bash
# Создать пару
sudo ip link add veth0 type veth peer name veth1

# Проверка
ip link show type veth
# → 5: veth1@veth0: <BROADCAST,MULTICAST,M-DOWN> mtu 1500 qdisc noop state DOWN mode DEFAULT group default qlen 1000
# → 6: veth0@veth1: <BROADCAST,MULTICAST,M-DOWN> mtu 1500 qdisc noop state DOWN mode DEFAULT group default qlen 1000

# Переместить veth1 в другое сетевое пространство имен
sudo ip netns add my-ns
sudo ip link set veth1 netns my-ns

# Активировать интерфейсы
sudo ip link set veth0 up
sudo ip netns exec my-ns ip link set veth1 up

# Назначить адреса
sudo ip addr add 10.0.0.1/24 dev veth0
sudo ip netns exec my-ns ip addr add 10.0.0.2/24 dev veth1

# Проверка связности
ping -c 3 10.0.0.2
# → 3 packets transmitted, 3 received, 0% packet loss

# Удаление
sudo ip link del veth0
```

#### Фиктивный интерфейс (Dummy)

Аналог Loopback, но с произвольным именем. Пакеты, отправленные в него, отбрасываются.

*   **Применение:** Удержание Anycast IP-адресов для протоколов маршрутизации (BGP/OSPF). Это позволяет адресу оставаться доступным в системе, даже если все физические интерфейсы упали.
*   **SSoT для Anycast:** См. раздел **[Маршрутизация в Linux](../../SystemAdministration/routing.md)**.

```bash
# Создание dummy-интерфейса
sudo ip link add dummy0 type dummy

# Назначение Anycast-адреса
sudo ip addr add 192.0.2.1/32 dev dummy0
sudo ip link set dummy0 up

# Проверка
ip -brief addr show dummy0
# → dummy0               UNKNOWN        192.0.2.1/32

# Удаление
sudo ip link del dummy0
```

### 4. Интерфейсы виртуализации и изоляции

#### Сетевой мост (Bridge)

Программный L2-коммутатор в ядре Linux. Позволяет объединять физические и виртуальные интерфейсы в один сегмент сети с независимой forwarding database (FDB).

*   **SSoT:** Подробности в **[Linux Bridge](./linux_bridge.md)**.
*   **Управление:** `ip link add name br0 type bridge`, `bridge link show`, `bridge fdb show`.

```bash
# Создание моста
sudo ip link add name br0 type bridge
sudo ip link set br0 up

# Добавление портов
sudo ip link set enp3s0 master br0
sudo ip link set veth0 master br0

# Проверка портов моста
bridge link show
# → 2: enp3s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master br0 state forwarding priority 32 cost 4
# → 6: veth0: <BROADCAST,MULTICAST> mtu 1500 master br0 state disabled priority 32 cost 70

# Просмотр MAC-таблицы (FDB)
bridge fdb show dev br0
# → aa:bb:cc:dd:ee:ff vlan 1 master br0 permanent
# → 00:16:3e:a1:b2:c3 vlan 1 master br0 temporary

# VLAN-aware мост (современный подход)
sudo ip link add name br0 type bridge vlan_filtering 1
bridge vlan show dev br0
# → port              vlan-id
# → enp3s0             1 PVID Egress Untagged
# → veth0              10 PVID Egress Untagged
```

#### MACVLAN и IPVLAN

Механизмы создания множества виртуальных интерфейсов поверх одного физического (родительского). Позволяют контейнерам/ВМ иметь прямую связь с физической сетью без моста.

*   **Режимы MACVLAN:**
    *   **vepa (Virtual Ethernet Port Aggregator):** внешний коммутатор должен поддерживать VEPA. MACVLAN не пересылает трафик между своими интерфейсами на хосте.
    *   **bridge:** стандартный режим. Интерфейсы общаются между собой и с внешней сетью. Самый частый для контейнеров.
    *   **private:** запрещает общение между MACVLAN-интерфейсами на одном хосте. Внешний коммутатор видит разные MAC.
    *   **passthru:** один MACVLAN на интерфейс, передает все кадры напрямую.
    *   **source:** фильтрация по MAC-адресу отправителя. Для мониторинга.
*   **Режимы IPVLAN:**
    *   **L2:** работает как мост на уровне L2, все интерфейсы делят MAC родителя.
    *   **L3:** работает как роутер на уровне L3, каждый интерфейс имеет свой IP, но делит MAC родителя. Полезно в сетях с ограничением на количество MAC (Wi-Fi, облака, некоторые коммутаторы).
*   **Детали:** См. **[VLAN — обзор](../../../Networking/Protocols/vlan.md)** и **[MACVLAN в Docker](../../../Docker/Docker_network/drivers/macvlan.md)**.

```bash
# MACVLAN bridge mode
sudo ip link add link enp3s0 name macveth0 type macvlan mode bridge
sudo ip link set macveth0 up
sudo ip addr add 192.168.1.10/24 dev macveth0

# IPVLAN L3 mode (общий MAC)
sudo ip link add link enp3s0 name ipvl0 type ipvlan mode l3
sudo ip link set ipvl0 up
sudo ip addr add 192.168.1.20/24 dev ipvl0

# Проверка
ip -brief link show type macvlan
ip -brief link show type ipvlan

# Удаление
sudo ip link del macveth0
sudo ip link del ipvl0
```

#### VLAN (802.1Q)

Создание логических интерфейсов для тегированного трафика. Ядро поддерживает 802.1Q (802.1Q-in-Q для Q-in-Q).

*   **Подходы:**
    *   **Традиционные сабинтерфейсы:** `eth0.10` для VLAN 10. Просто, но много интерфейсов при большом количестве VLAN.
    *   **VLAN-aware Bridge:** один мост обрабатывает все VLAN. Рекомендуется для виртуализации. Порт моста имеет PVID (Port VLAN ID) и разрешенные VLAN.
*   **SSoT:** См. **[VLAN в Linux](../../../Networking/Protocols/VLAN/vlan_linux_diagnostics.md)**.

```bash
# Создание VLAN-интерфейса
sudo ip link add link enp3s0 name enp3s0.10 type vlan id 10
sudo ip link set enp3s0.10 up
sudo ip addr add 192.168.10.2/24 dev enp3s0.10

# Проверка
cat /sys/class/net/enp3s0.10/vlan/ingress
# → untagged: 10

# VLAN-aware bridge
sudo ip link add name br0 type bridge vlan_filtering 1
sudo ip link set enp3s0 master br0
sudo bridge vlan add dev enp3s0 vid 10 pvid untagged
sudo bridge vlan add dev br0 vid 10 self

# Просмотр VLAN-таблицы
bridge vlan show dev br0
```

### 5. Туннельные и защищенные интерфейсы

#### TUN/TAP

Интерфейсы, позволяющие программам из Userspace читать и писать пакеты напрямую в стек ядра.

*   **TUN (L3):** Работает с IP-пакетами (VPN: OpenVPN, WireGuard).
*   **TAP (L2):** Работает с Ethernet-кадрами (Виртуализация: QEMU/KVM).
*   **Создание:** `ip tuntap add dev tun0 mode tun`, `ip tuntap add dev tap0 mode tap`.
*   **SSoT:** См. **[TUN/TAP интерфейсы](../../../Networking/Tunnels/tun_vs_tap.md)**.

```bash
# Создание TUN-интерфейса
sudo ip tuntap add dev tun0 mode tun
sudo ip link set tun0 up
sudo ip addr add 10.0.0.1/24 dev tun0

# Создание TAP-интерфейса
sudo ip tuntap add dev tap0 mode tap
sudo ip link set tap0 up
sudo ip addr add 192.168.100.1/24 dev tap0

# Проверка
ip -brief link show type tun
ip -brief link show type tap

# Удаление
sudo ip link del tun0
sudo ip link del tap0
```

#### Современные инкапсуляции

*   **VXLAN / GENEVE:** L2 поверх L3. Используются в Overlay-сетях (Kubernetes, OpenStack).
    ```bash
    # Создание VXLAN
    sudo ip link add vxlan100 type vxlan id 100 local 10.0.0.1 remote 10.0.0.2 dstport 4789
    sudo ip link set vxlan100 up
    sudo ip addr add 192.168.100.1/24 dev vxlan100

    # GENEVE (более гибкий, поддерживает options)
    sudo ip link add geneve0 type geneve vni 100 remote 10.0.0.2 dstport 6081
    ```
*   **XFRM:** Интерфейс для IPsec трафика, позволяющий маршрутизировать защищенные пакеты как обычные.
*   **WireGuard:** Виртуальный интерфейс для одноименного протокола VPN.
*   **VRF (Virtual Routing and Forwarding):** Позволяет разделять таблицу маршрутизации на уровне L3. Интерфейс, назначенный в VRF, использует свою таблицу маршрутизации и правил.
    ```bash
    # Создание VRF
    sudo ip link add vrf-blue type vrf table 100
    sudo ip link set vrf-blue up

    # Привязка интерфейса к VRF
    sudo ip link set enp3s0 master vrf-blue

    # Маршрут в VRF
    sudo ip route add 192.168.1.0/24 dev enp3s0 table 100
    ```
    *   **SSoT:** См. раздел **[VRF в Linux](../vrf.md)**.

### 6. Агрегация и отказоустойчивость

Интерфейсы можно объединять (Slave) в логические группы (Master) для повышения пропускной способности и отказоустойчивости.

*   **Bonding:** Традиционный механизм ядра. Поддерживает режимы `balance-rr`, `active-backup`, `802.3ad` (LACP), `balance-xor`, `broadcast`, `balance-tlb`, `balance-alb`.
*   **Team:** Более современная и модульная реализация, часть логики которой вынесена в Userspace (teamd). Поддерживает более сложные алгоритмы балансировки (DDBus, LACP with selection).
*   **SSoT:** См. **[Агрегация каналов](../../../Networking/Concepts/link_aggregation.md)**.

```bash
# Bonding через iproute2
sudo ip link add name bond0 type bond mode 802.3ad
sudo ip link set enp3s0 master bond0
sudo ip link set enp4s0 master bond0
sudo ip link set bond0 up
sudo ip addr add 192.168.1.10/24 dev bond0

# Проверка статуса бонда
cat /sys/class/net/bond0/bonding/ad_num_peers
# → 1 (количество партнеров по LACP)

cat /sys/class/net/bond0/bonding/mode
# → 802.3ad 4

# Team через iproute2
sudo ip link add name team0 type team
sudo ip link set enp3s0 master team0
sudo ip link set enp4s0 master team0
sudo ip link set team0 up
```

### 7. Аппаратная разгрузка и eBPF

Современные интерфейсы поддерживают механизмы ускорения обработки пакетов.

*   **Offloading (TSO, GSO, GRO):** Перенос сборки/разборки пакетов на сетевую карту.
*   **SR-IOV:** виртуализация I/O с прямым доступом к PCI. Создает Virtual Functions (VF) на базе Physical Function (PF).
*   **XDP (eXpress Data Path):** Позволяет запускать eBPF программы на самом низком уровне интерфейса (драйвер или NIC), обеспечивая экстремально быструю фильтрацию трафика до попадания в стек ядра.
*   **AF_XDP:** сокетный адресный тип для zero-copy передачи пакетов между NIC и userspace через eBPF.

```bash
# Проверка offload
ethtool -k enp3s0 | grep -E "tcp-segmentation|generic-receive|large-receive"
# → tcp-segmentation-offload: on
# → generic-segmentation-offload: on
# → generic-receive-offload: on

# Проверка SR-IOV VF
ethtool -i enp3s0
# → driver: ice
lspci | grep Ethernet
# → 0000:3d:00.0 Ethernet controller: Intel Corporation Ethernet Controller E810

# Количество VF
cat /sys/class/net/enp3s0/device/sriov_totalvfs
# → 64

# Создание VF
echo 4 | sudo tee /sys/class/net/enp3s0/device/sriov_numvfs
# → 4

# Проверка VF
ip link show enp3s0
# → 3: enp3s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
# →   vf 0: 5e:33:cc:00:00:01, spoof-checking on, link-state auto, trust off
```

### 8. Специализированные интерфейсы

#### nlmon (Netlink Monitor)

Виртуальный интерфейс для мониторинга netlink-сообщений. Позволяет перехватывать и анализировать netlink-трафик между процессами и ядром.

```bash
sudo ip link add nlmon0 type nlmon
sudo ip link set nlmon0 up
tcpdump -i nlmon0
```

#### batadv (B.A.T.M.A.N. Advanced)

Интерфейс для mesh-сетей (Wireless Mesh). Используется в проектах like OpenWrt и community mesh networks.

```bash
sudo ip link add bat0 type batadv
sudo ip link set bat0 up
sudo batctl if add wlan0
```

#### macsec (MACsec — IEEE 802.1AE)

Аппаратное шифрование L2. Требует поддержки со стороны NIC и коммутатора.

```bash
# Создание MACsec-интерфейса
sudo ip link add link enp3s0 name macsec0 type macsec encrypt on
sudo ip link set macsec0 up

# Настройка ключей (требуется утилита `ip macsec`)
sudo ip macsec add macsec0 address aa:bb:cc:dd:ee:ff port 1
sudo ip macsec add macsec0 address aa:bb:cc:dd:ee:ff port 1 key 1 00112233445566778899aabbccddeeff
```

## Практические сценарии

### 1. Управление именами и состояниями

```bash
# Просмотр всех интерфейсов (кратко)
ip -brief link show
# → lo               UNKNOWN        127.0.0.1/8 ::1/128
# → enp3s0           UP             aa:bb:cc:dd:ee:ff <BROADCAST,MULTICAST,UP,LOWER_UP>
# → docker0          DOWN           ee:ff:gg:hh:ii:jj <NO-CARRIER,BROADCAST,MULTICAST,UP>

# Детальный просмотр
ip -details link show enp3s0
# → 2: enp3s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000
# →    link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff promiscuity 0
# →    vlan protocol 802.1Q simple tx 0 rx 0
# →    vlan protocol 802.1AD simple tx 0 rx 0
# →    allmulti 0 promisc 1

# Активация интерфейса
sudo ip link set dev enp3s0 up
# → (без вывода)

# Деактивация интерфейса
sudo ip link set dev enp3s0 down

# Добавление описания (alias)
sudo ip link set dev enp3s0 alias "Uplink to Core Switch"

# Проверка
ip link show enp3s0 | grep alias
# → altname uplink0
```

### 2. Диагностика физического уровня

```bash
# Состояние линка (speed, duplex, autonegotiation)
sudo ethtool enp3s0
# → Speed: 10000Mb/s
# → Duplex: Full
# → Auto-negotiation: on

# Статистика ошибок
sudo ethtool -S enp3s0 | grep -E "rx_|tx_|error|drop|miss|crc|collision|overrun"
# →     rx_errors: 0
# →     tx_errors: 0
# →     rx_missed_errors: 0
# →     rx_crc_errors: 0
# →     rx_fifo_errors: 0
# →     rx_frame_errors: 0
# →     rx_over_errors: 0

# Проверка SFP/DOM (оптический трансивер)
sudo ethtool -m enp3s0
# →    Laser wavelength: 850nm
# →    Temperature: 38.5 C
# →    Voltage: 3.30 V
# →    Current: 12.3 mA
# →    TX power: 2.1 mW (-2.8 dBm)
# →    RX power: 1.5 mW (-2.2 dBm)

# Проверка поддерживаемых скоростей
sudo ethtool enp3s0 | grep -A 10 "Supported link modes"
# →     Supported link modes:   1000baseT/Full
# →                          10000baseT/Full
# →                          25000baseCR/Full

# Принудительная настройка скорости (если autonegotiation не работает)
sudo ethtool -s enp3s0 speed 1000 duplex full autoneg off

# Включение autonegotiation
sudo ethtool -s enp3s0 autoneg on
```

### 3. Работа с виртуальными парами veth

```bash
# Создать пару
sudo ip link add veth0 type veth peer name veth1

# Проверка
ip link show type veth
# → 5: veth1@veth0: <BROADCAST,MULTICAST,M-DOWN> mtu 1500 qdisc noop state DOWN mode DEFAULT group default qlen 1000
# → 6: veth0@veth1: <BROADCAST,MULTICAST,M-DOWN> mtu 1500 qdisc noop state DOWN mode DEFAULT group default qlen 1000

# Переместить veth1 в другое сетевое пространство имен
sudo ip netns add my-ns
sudo ip link set veth1 netns my-ns

# Активировать интерфейсы
sudo ip link set veth0 up
sudo ip netns exec my-ns ip link set veth1 up

# Назначить адреса
sudo ip addr add 10.0.0.1/24 dev veth0
sudo ip netns exec my-ns ip addr add 10.0.0.2/24 dev veth1

# Проверка связности
ping -c 3 10.0.0.2
# → 3 packets transmitted, 3 received, 0% packet loss

# Удаление
sudo ip link del veth0
```

### 4. Управление MAC-адресами

```bash
# Просмотр MAC
ip link show enp3s0 | grep link/ether
# → link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff

# Изменение MAC (spoofing)
sudo ip link set dev enp3s0 address 00:11:22:33:44:55

# Проверка
ip link show enp3s0 | grep link/ether
# → link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff

# Возврат к永久ному MAC (permaddr)
sudo ip link set dev enp3s0 address $(cat /sys/class/net/enp3s0/address)

# Включение promiscuous mode
sudo ip link set dev enp3s0 promisc on
ip link show enp3s0 | grep PROMISC
# → <BROADCAST,MULTICAST,PROMISC,UP,LOWER_UP>

# Отключение promiscuous mode
sudo ip link set dev enp3s0 promisc off
```

### 5. Настройка MTU

```bash
# Просмотр MTU
ip link show enp3s0 | grep mtu
# → mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000

# Изменение MTU (например, для Jumbo Frames)
sudo ip link set dev enp3s0 mtu 9000

# Проверка
ip link show enp3s0 | grep mtu
# → mtu 9000 qdisc mq state UP mode DEFAULT group default qlen 1000

# Проверка через sysfs
cat /sys/class/net/enp3s0/mtu
# → 9000

# Примечание: MTU должен быть одинаковым на всех участках пути (end-to-end)
# Проверка PMTU
tracepath -n 10.0.0.1

# Установка MTU для VLAN-интерфейса
sudo ip link add link enp3s0 name enp3s0.100 type vlan id 100
sudo ip link set enp3s0.100 mtu 1504  # 1500 + 4 байта тега
```

### 6. Создание и управление VLAN-интерфейсами

```bash
# Создание VLAN 100
sudo ip link add link enp3s0 name enp3s0.100 type vlan id 100
sudo ip link set enp3s0.100 up
sudo ip addr add 192.168.100.2/24 dev enp3s0.100

# Проверка
ip -brief link show enp3s0.100
# → enp3s0.100        UP             192.168.100.2/24

# Верификация через ping
ping -c 3 192.168.100.1
# → 3 packets transmitted, 3 received, 0% packet loss

# VLAN-aware bridge (современный подход)
sudo ip link add name br-vlan type bridge vlan_filtering 1
sudo ip link set enp3s0 master br-vlan
sudo ip link set br-vlan up

# Настройка VLAN на портах моста
sudo bridge vlan add dev enp3s0 vid 10 pvid untagged
sudo bridge vlan add dev enp3s0 vid 20
sudo bridge vlan add dev br-vlan vid 10 self
sudo bridge vlan add dev br-vlan vid 20 self

# Просмотр
bridge vlan show dev br-vlan
# → port              vlan-id
# → enp3s0             10 PVID Egress Untagged
# → enp3s0             20

# Удаление
sudo ip link del enp3s0.100
```

### 7. Network Namespaces и изоляция

```bash
# Создание namespace
sudo ip netns add ns-web

# Создание veth-пары для связи namespace с хостом
sudo ip link add veth-host type veth peer name veth-ns
sudo ip link set veth-ns netns ns-web

# Активация интерфейсов
sudo ip link set veth-host up
sudo ip netns exec ns-web ip link set veth-ns up
sudo ip netns exec ns-web ip link set lo up

# Назначение адресов
sudo ip addr add 10.200.1.1/30 dev veth-host
sudo ip netns exec ns-web ip addr add 10.200.1.2/30 dev veth-ns

# Включение forwarding на хосте
sudo sysctl -w net.ipv4.ip_forward=1

# NAT (masquerade) для выхода в интернет
sudo iptables -t nat -A POSTROUTING -s 10.200.1.0/30 -o enp3s0 -j MASQUERADE

# Проверка из namespace
sudo ip netns exec ns-web ping -c 3 8.8.8.8
# → 3 packets transmitted, 3 received, 0% packet loss

# Удаление namespace (все интерфейсы внутри удаляются)
sudo ip netns del ns-web
sudo ip link del veth-host
```

### 8. VRF — изоляция таблиц маршрутизации

```bash
# Создание VRF с таблицей 100
sudo ip link add vrf-blue type vrf table 100
sudo ip link set vrf-blue up

# Привязка интерфейса к VRF
sudo ip link set enp3s0 master vrf-blue

# Настройка маршрутов
sudo ip route add 192.168.10.0/24 dev enp3s0 table 100
sudo ip route add default via 192.168.10.1 dev enp3s0 table 100

# Просмотр таблиц
ip route show table 100
# → default via 192.168.10.1 dev enp3s0
# → 192.168.10.0/24 dev enp3s0 proto kernel scope link src 192.168.10.2

# Проверка связности в VRF
sudo ip vrf exec vrf-blue ping -c 3 192.168.10.1
# → 3 packets transmitted, 3 received, 0% packet loss

# Удаление
sudo ip link set enp3s0 nomaster
sudo ip link del vrf-blue
```

### 9. MACVLAN — контейнеры с собственным MAC

```bash
# Создание macvlan в режиме bridge
sudo ip link add link enp3s0 name macveth0 type macvlan mode bridge
sudo ip link set macveth0 up
sudo ip addr add 192.168.1.10/24 dev macveth0
sudo ip route add default via 192.168.1.1 dev macveth0

# Проверка
ping -c 3 192.168.1.1
# → 3 packets transmitted, 3 received, 0% packet loss

# Проверка ARP
ip neigh show dev enp3s0
# → 192.168.1.1 lladdr 00:11:22:33:44:55 REACHABLE

# Режим private (изоляция между macvlan-интерфейсами на хосте)
sudo ip link add link enp3s0 name macveth1 type macvlan mode private
sudo ip link set macveth1 up
sudo ip addr add 192.168.1.11/24 dev macveth1

# Удаление
sudo ip link del macveth0
```

### 10. Systemd .link — переименование интерфейсов

```bash
# Создание правила для переименования по MAC
sudo tee /etc/systemd/network/10-rename-enp3s0.link <<EOF
[Match]
MACAddress=aa:bb:cc:dd:ee:ff

[Link]
Name=uplink0
EOF

# Перезагрузка udev
sudo udevadm control --reload
sudo udevadm trigger --type=devices --attr-match=subsystem=net

# Проверка
ip link show uplink0
# → 2: uplink0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...

# Удаление правила
sudo rm /etc/systemd/network/10-rename-enp3s0.link
sudo udevadm control --reload
```

### 11. Диагностика интерфейсов

```bash
# Просмотр статистики интерфейса
cat /sys/class/net/enp3s0/statistics/rx_packets
# → 12345678
cat /sys/class/net/enp3s0/statistics/tx_packets
# → 12345679
cat /sys/class/net/enp3s0/statistics/rx_errors
# → 0
cat /sys/class/net/enp3s0/statistics/tx_dropped
# → 0

# Сводка через ip
ip -s link show enp3s0
# → RX: bytes  packets  errors  dropped overrun mcast
# →    1.2G      1234567  0       0       0       0
# → TX: bytes  packets  errors  dropped carrier collsns
# →    1.1G      1234566  0       0       0       0

# Мониторинг в реальном времени
watch -n1 'cat /sys/class/net/enp3s0/statistics/rx_packets'
# → 12345678
# → 12345690  (+12 за секунду)

# Проверка очередей (ring buffer)
sudo ethtool -g enp3s0
# → Ring parameters for enp3s0:
# → Pre-set maximums:
# → RX:        4096
# → RX Mini:   0
# → RX Jumbo:  0
# → TX:        4096
# → Current hardware settings:
# → RX:        1024
# → RX Mini:   0
# → RX Jumbo:  0
# → TX:        1024

# Настройка ring buffer
sudo ethtool -G enp3s0 rx 4096 tx 4096

# Проверка offload
sudo ethtool -k enp3s0
# → Features for enp3s0:
# → rx-checksumming: on
# → tx-checksum-ipv4: on
# → tx-checksum-ipv6: off
# → scatter-gather: on
# → tcp-segmentation-offload: on
# → udp-segmentation-offload: off
# → generic-segmentation-offload: on
# → generic-receive-offload: on
# → large-receive-offload: off
# → rx-vlan-offload: on
# → tx-vlan-offload: on
# → ntuple-filters: on
# → rx-hashing: on

# Проверка коалесценции (interrupt mitigation)
sudo ethtool -c enp3s0
# → Coalesce settings for enp3s0:
# → Adaptive RX: on  TX: on
# → stats-block-usecs: 0
# → sample-interval: 0
# → pkt-rate-low: 0
# → pkt-rate-high: 10

# Настройка коалесценции (пример для 10G)
sudo ethtool -C enp3s0 rx-usecs 50 rx-frames 16 tx-usecs 50 tx-frames 16

# Проверка количества очередей
sudo ethtool -l enp3s0
# → Channel parameters for enp3s0:
# → Pre-set maximums:
# → RX:     4
# → TX:     4
# → Other:  1
# → Combined: 4
# → Current hardware settings:
# → RX:     2
# → TX:     2
# → Other:  1
# → Combined: 2

# Настройка количества очередей (multi-queue)
sudo ethtool -L enp3s0 combined 4
```

## Диагностика и устранение неисправностей

### Типичные проблемы и решения

| Проблема | Симптом | Диагностика | Решение |
|----------|---------|-------------|---------|
| **Нет линка** | `NO-CARRIER` в `ip link` | `ethtool enp3s0`, проверка кабеля и порта коммутатора | Проверьте кабель, порт коммутатора, `ethtool -s enp3s0 autoneg on` |
| **Низкая скорость** | Ожидалась 10G, показывает 1G | `ethtool enp3s0 \| grep Speed` | Проверьте кабель (требуется Cat6a+ для 10G), порт коммутатора, настройки autonegotiation |
| **CRC ошибки** | Рост `rx_crc_errors` | `ethtool -S enp3s0 \| grep crc` | Замена кабеля/SFP, проверка совместимости трансивера |
| **Ошибки фреймов** | `rx_frame_errors > 0` | `ethtool -S enp3s0 \| grep frame` | Проверка duplex mismatch (`ethtool enp3s0 \| grep Duplex`), принудительная настройка `full duplex` |
| **RX dropped** | `rx_dropped` растет | `ip -s link show`, `ethtool -S` | Увеличьте ring buffer (`ethtool -G`), проверьте NAPI budget (`netdev_budget`) |
| **TX dropped** | `tx_dropped` растет | `ip -s link show`, `ethtool -S` | Увеличьте TX очередь, проверьте `tx-udp_tnl-segmentation` offload |
| **Drops в softnet_stat** | `dropped` или `squeezed` растет | `cat /proc/net/softnet_stat` | Увеличьте `net.core.netdev_max_backlog`, настройте NAPI budget |
| **VLAN-интерфейс в DOWN** | `ip link show eth0.10` — DOWN | `ip link show eth0` — физический DOWN | Поднять физический интерфейс: `sudo ip link set eth0 up` |
| **Теги не видны в tcpdump** | `tcpdump -i eth0 -e` не показывает 802.1Q | `ethtool -k eth0 \| grep vlan` — offload on | Отключить: `sudo ethtool -K eth0 rx-vlan-offload off tx-vlan-offload off` |
| **MACVLAN: нет связности** | ping не проходит | `ip link show`, `bridge link show` | Проверьте режим (`bridge` vs `private`), убедитесь что интерфейс UP, проверьте маршрут |

### Чек-лист диагностики

1.  **Состояние:** `ip -details link show <iface>` — проверьте флаги (UP, LOWER_UP, NO-CARRIER).
2.  **Линк:** `ethtool <iface>` — скорость, дуплекс, autonegotiation.
3.  **Ошибки L1:** `ethtool -S <iface> \| grep -E "crc\|frame\|miss\|drop"` — ошибки физического уровня.
4.  **Статистика ядра:** `ip -s link show <iface>` — пакеты, ошибки, dropped.
5.  **Счетчики sysfs:** `cat /sys/class/net/<iface>/statistics/*` — детальная статистика.
6.  **Ring buffer:** `ethtool -g <iface>` — текущий и максимальный размер очередей.
7.  **Offload:** `ethtool -k <iface>` — состояние аппаратных разгрузок.
8.  **Коалесценция:** `ethtool -c <iface>` — параметры прерываний.
9.  **Очереди:** `ethtool -l <iface>` — количество RX/TX очередей.
10. **Маршрут:** `ip route show dev <iface>` — таблица маршрутизации для интерфейса.

## Edge cases и ограничения

### Малые пакеты и overhead
- При передаче большого количества малых пакетов (64 байта) возможна перегрузка CPU на software fallback. Используйте аппаратное offload (TSO/GSO/GRO) или tune ring buffer.
- VLAN добавляет 4 байта к каждому кадру. При использовании Q-in-Q (802.1ad) — 8 байт. Убедитесь что MTU соответствующего физического интерфейса увеличен (`ip link set dev eth0 mtu 1508` для Q-in-Q).

### Виртуализация
- В KVM/QEMU виртуальный NIC (virtio) отображается как `eth0` или `ensX` внутри гостевой ОС. На хосте это может быть `vnet0` (непрозрачный мост) или `veth` (macvlan).
- Для SR-IOV убедитесь что IOMMU включен (`intel_iommu=on` или `amd_iommu=on` в GRUB), и VF привязаны к vfio-pci.

### Контейнеры
- Docker по умолчанию создает `docker0` мост и `veth`-пары для контейнеров. MAC-адрес контейнера совпадает с MAC-адресом его `veth`-интерфейса.
- Для избежания MAC-флудов на физическом коммутаторе используйте `macvlan` вместо моста, или настройте port-security/static MAC на порту коммутатора.

### Смешанный трафик (mixed MTU)
- При использовании VXLAN/GRE инкапсуляции убедитесь что MTU туннеля соответствует физическому MTU минус overhead (VXLAN: -50 байт, GRE: -24 байта).
- Используйте `tracepath` или `ping -M do -s <size>` для диагностики PMTU.

### Избыточный budget и лимиты
- Увеличение `netdev_budget` без соответственного увеличения кольцевых буферов (`ethtool -G`) не даст эффекта — пакеты будут отброшены на уровне NIC.
- При включении Threaded NAPI убедитесь что кольцевой буфер достаточно велик для обработки burst без потерь.

### br_netfilter
- При включении `bridge-nf-call-iptables` мост передает трафик через netfilter, что может вызвать падение производительности и неожиданные drops. Отключайте если нет необходимости в L3/L4 фильтрации на мосте.

### cgroup CPU limits
- Контейнеры с ограниченным CPU (`cpu.cfs_quota_us`) могут испытывать недостаток процессорного времени для обработки прерываний. Убедитесь что `cpu.cfs_period_us` и `cpu.cfs_quota_us` позволяют достаточный burst.
```bash
# Проверка throttled time
cat /sys/fs/cgroup/cpu/cpu.stat
# → usage_usec 123456789
# → user_usec 98765432
# → system_usec 24691357
# → nr_periods 1000
# → nr_throttled 150 (высокое значение = проблема)
```

## Чек-лист оптимизации сетевого планирования

1.  **Мониторинг:** Проверьте `softnet_stat` на наличие `squeezed` и `dropped`.
2.  **Аппаратное:** Настройте очереди и буферы через `ethtool -G` и `ethtool -L`.
3.  **Коалесценция:** Настройте `ethtool -C` для баланса latency/throughput.
4.  **MTU:** Убедитесь что MTU соответствует топологии сети (Jumbo Frames где возможно).
5.  **Offload:** Проверьте GRO/GSO/TSO через `ethtool -k`, отключайте при проблемах.
6.  **Виртуализация:** Для контейнеров используйте macvlan при необходимости, для ВМ — SR-IOV или virtio с multi-queue.
7.  **Валидация:** После всех изменений проверьте `rx_missed_errors`, `softnet_stat`, `%si`.

---

## Связанные темы

*   [**Многопоточная обработка трафика (RSS, RPS, RFS)**](../Concepts/rss_rps_rfs.md) — распределение нагрузки по ядрам.
*   [**Сетевая разгрузка (Offloading)**](../Concepts/offloading.md) — GRO, LRO, TSO, GSO и их влияние на интерфейсы.
*   [**Диагностика потерь в сетевом стеке**](../network_stack_packet_loss.md) — поиск дропов на всех уровнях.
*   [**ethtool: диагностика железа**](../Tools/ethtool.md) — настройка очередей, коалесценции, offloading.
*   [**Прерывания в ядре Linux**](../../Core/kernel/interrupts.md) — архитектура MSI-X и SoftIRQ.
*   [**Linux Bridge**](./linux_bridge.md) — программный L2-коммутатор.
*   [**TUN/TAP интерфейсы**](../../../Networking/Tunnels/tun_vs_tap.md) — виртуальные интерфейсы для VPN и виртуализации.
*   [**VRF в Linux**](../vrf.md) — изоляция таблиц маршрутизации.
*   [**iproute2: ip link**](../Tools/iproute2/ip_link.md) — управление сетевыми интерфейсами.
*   [**VLAN в Linux**](../../../Networking/Protocols/VLAN/vlan_linux_diagnostics.md) — механизмы 802.1Q.
