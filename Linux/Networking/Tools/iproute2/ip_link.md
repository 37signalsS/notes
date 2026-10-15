# ip link: Управление сетевыми интерфейсами

## Определения

* **`ip link`** — специализированная утилита из набора `iproute2`, предназначенная для управления объектами канального уровня (**L2 — Data Link Layer**) сетевого стека Linux.
* Работает напрямую с драйверами сетевых устройств, позволяя изменять состояние линка, параметры MTU, MAC-адреса, создавать виртуальные устройства и настраивать аппаратные функции (SR-IOV, XDP).

> **Важно:** Утилита оперирует исключительно на уровнях L1-L2. Для настройки сетевых адресов (L3) используется инструмент [`ip address`](./ip_address.md).

### Предварительные требования

* **Пакет `iproute2`** — должен быть установлен в системе.

| Дистрибутив | Команда установки |
| :--- | :--- |
| **Debian / Ubuntu** | `sudo apt install iproute2` |
| **RHEL / Fedora / CentOS** | `sudo dnf install iproute` |
| **Arch Linux** | `sudo pacman -S iproute2` |
| **Alpine** | `apk add iproute2` |
| **openSUSE** | `sudo zypper install iproute2` |

* **Права root** — большинство операций изменений требуют `sudo` или выполнения от пользователя `root`.
* **Ядро Linux** — версия ядра 3.0+ для базовых функций; 4.0+ для XDP; 5.0+ для расширенных возможностей SR-IOV.

## Основные концепции

### Классификация типов интерфейсов

| Тип | Назначение | Технические особенности |
| :--- | :--- | :--- |
| **lo** | Loopback | Виртуальный интерфейс для локальных соединений (127.0.0.1). |
| **ether** | Ethernet | Физические адаптеры и их виртуальные аналоги (veth). |
| **veth** | Virtual Ethernet | Работает парами. Фундамент для связи контейнеров и `netns`. |
| **bridge** | Сетевой мост | Программный L2-коммутатор (см. [Linux Bridge](../../Concepts/linux_bridge.md)). |
| **bond / team** | Агрегация каналов | Объединение интерфейсов для отказоустойчивости или скорости. |
| **vlan** | 802.1Q | Виртуальные сети с тегированием трафика. |
| **vxlan** | Overlay-сети | Инкапсуляция L2 в L3 (UDP), стандарт для виртуализации сетей. |
| **dummy** | Фиктивный | Приемник трафика, всегда UP (для Anycast IP). |
| **vrf** | Маршрутизация | Изоляция таблиц маршрутизации (см. [VRF](../../vrf.md)). |
| **wireguard** | VPN | Криптографический интерфейс для защищенных туннелей. |
| **tun / tap** | Туннели | TUN (L3, IP-пакеты) / TAP (L2, Ethernet-кадры). Используются в VPN и виртуализации. |
| **macvlan** | MACVLAN | Множество виртуальных интерфейсов с уникальными MAC поверх одного физического. |
| **ipvlan** | IPVLAN | Аналог MACVLAN, но все интерфейсы делят MAC-адрес родителя. |

### Состояния интерфейса (Operstate)

* **UP**: Программно включен и имеет физический сигнал (LOWER_UP).
* **DOWN**: Выключен административно.
* **LOWERLAYERDOWN**: Программно включен, но физический линк отсутствует (нет кабеля).
* **DORMANT**: Ожидание внешнего события (например, завершения аутентификации 802.1X).
* **UNKNOWN**: Стандартное состояние для большинства виртуальных устройств без привязки к железу.
* **NOTPRESENT**: Интерфейс физически отсутствует (извлечен SFP, отключено устройство).

### Флаги интерфейсов

| Флаг | Описание |
| :--- | :--- |
| **BROADCAST** | Поддержка широковещательных пакетов. |
| **MULTICAST** | Поддержка multicast-пакетов. |
| **POINTOPOINT** | Точечное соединение (туннели, PPP). |
| **PROMISC** | Promiscuous mode — прием всех пакетов в сегменте. |
| **ALLMULTI** | Прием всех multicast-пакетов. |
| **NOARP** | Отсутствие необходимости в ARP (loopback, tunnel). |
| **MASTER** | Интерфейс является master-устройством (bridge, bond). |
| **SLAVE** | Интерфейс привязан к master-устройству. |
| **LOWER_UP** | Физический линк активен (L1). |

### Рекомендации по MTU (Maximum Transmission Unit)

| Значение | Назначение | Примечания |
| :--- | :--- | :--- |
| **1500** | Стандартный Ethernet | Значение по умолчанию. |
| **9000** | Jumbo Frames | Снижение нагрузки на CPU в локальных сетях. Требует поддержки всеми устройствами в сегменте. |
| **1450** | VXLAN | Запас под заголовок 50 байт. |
| **1420** | WireGuard | Запас под инкапсуляцию 80 байт. |
| **1400** | OpenVPN (TUN) | Запас под заголовки VPN 100 байт. |
| **1350** | IPSec (ESP) | Запас под ESP + ESP trailer. |
| **1508** | Q-in-Q (802.1ad) | Двойное VLAN-тегирование. |

> **Важно:** MTU должно быть одинаковым на всех участниках сегмента. Несоответствие MTU приводит к Black Hole — пакеты молча отбрасываются без уведомления отправителя.

## Практические сценарии

### Просмотр и диагностика

```bash
# Краткий список интерфейсов и их статусов
ip -br link show
# → lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP>
# → eth0             UP             52:54:00:12:34:56 <BROADCAST,MULTICAST,UP,LOWER_UP>

# Детальная статистика по конкретному типу
ip -d link show type bridge

# Вывод в формате JSON для автоматизации (скрипты, мониторинг)
ip -j -p link show eth0

# Просмотр статистики (ошибки, дропы)
ip -s link show eth0
# → RX: bytes=12345678 packets=98765 errors=0 dropped=0 overrun=0 frame=0
# → TX: bytes=87654321 packets=54321 errors=0 dropped=0 overrun=0 carrier=0

# Двойная статистика (максимальная детализация)
ip -s -s link show eth0

# Просмотр только интерфейсов в состоянии UP
ip link show | grep -B1 "state UP"

# Мониторинг изменений состояния интерфейсов в реальном времени
ip monitor link
```

### Управление именами и состоянием

```bash
# Включить интерфейс
sudo ip link set eth0 up
# → (нет вывода при успехе)

# Выключить интерфейс
sudo ip link set eth0 down

# Добавить альтернативное имя (alias), сохраняющееся в выводе
sudo ip link property add dev eth0 altname public-nic

# Переименование (интерфейс должен быть в состоянии DOWN)
sudo ip link set eth0 name lan0

# Добавить описание (alias) для интерфейса
sudo ip link set dev eth0 alias "Primary uplink to core switch"
```

### Настройка параметров L2

```bash
# Изменение MAC-адреса (требуется DOWN)
sudo ip link set eth0 address 00:11:22:33:44:55

# Установка MTU и поднятие линка
sudo ip link set dev eth0 mtu 9000 && ip link set dev eth0 up
# → MTU должен совпадать на всём пути сегмента

# Включение Promiscuous mode (прослушивание всего трафика в сегменте)
sudo ip link set eth0 promisc on

# Отключение ARP на интерфейсе (для не-IP протоколов)
sudo ip link set eth0 arp off

# Включение multicast
sudo ip link set eth0 multicast on
```

### Создание виртуальных устройств

```bash
# Создание veth-пары для связи пространств имен
sudo ip link add veth-host type veth peer name veth-container
# → ( интерфейсы veth-host и veth-container созданы)

# Создание тегированного VLAN (ID 10)
sudo ip link add link eth0 name eth0.10 type vlan id 10

# Создание VRF для изоляции трафика
sudo ip link add vrf-mgmt type vrf table 100
sudo ip link set vrf-mgmt up

# Создание dummy-интерфейса для Anycast
sudo ip link add dummy0 type dummy

# Создание bond-интерфейса (LACP, mode 802.3ad)
sudo ip link add bond0 type bond mode 802.3ad

# Создание MACVLAN-интерфейса
sudo ip link add macvlan0 link eth0 type macvlan mode bridge

# Создание TUN-интерфейса
sudo ip link add tun0 type tun

# Удаление виртуального интерфейса
sudo ip link delete veth-host
```

### Управление Master-устройствами (Enslaving)

Привязка интерфейсов к мостам, бондам или VRF.

```bash
# Добавить интерфейс в Bridge
sudo ip link set eth1 master br0
# → (eth1 теперь slave br0)

# Удалить из всех Master-устройств
sudo ip link set eth1 nomaster

# Привязать интерфейс к конкретному VRF
sudo ip link set eth1 master vrf-mgmt

# Просмотр всех интерфейсов, привязанных к bridge br0
ip link show master br0

# Просмотр всех slave-интерфейсов bond0
ip link show master bond0
```

### Агрегация каналов (Bonding)

```bash
# Создание bond-интерфейса с балансировкой нагрузки (LACP)
sudo ip link add bond0 type bond mode 802.3ad

# Настройка параметров bond
sudo ip link set bond0 miimon 100      # Интервал проверки линка (мс)
sudo ip link set bond0 xmit_hash_policy layer3+4  # Хэш для балансировки

# Привязка slave-интерфейсов
sudo ip link set eth1 down
sudo ip link set eth2 down
sudo ip link set eth1 master bond0
sudo ip link set eth2 master bond0
sudo ip link set eth1 up
sudo ip link set eth2 up
sudo ip link set bond0 up

# Проверка состояния
ip -d link show bond0
# → bond mode 802.3ad  miimon 100  updelay 0  downdelay 0

# Отключение bond
sudo ip link set eth1 nomaster
sudo ip link set eth2 nomaster
sudo ip link set bond0 down
sudo ip link delete bond0
```

### Настройка Bridge (сетевого моста)

```bash
# Создание моста
sudo ip link add br0 type bridge

# Добавление интерфейсов в мост
sudo ip link set eth0 master br0
sudo ip link set eth1 master br0

# Включение STP (Spanning Tree Protocol)
sudo ip link set br0 type bridge stp_state 1

# Настройка приоритета STP
sudo ip link set br0 type bridge priority 4096

# Настройка Forward Delay (время перехода в состояние forwarding)
sudo ip link set br0 type bridge forward_delay 4

# Включение VLAN-фильтрации
sudo ip link add br0 type bridge vlan_filtering 1

# Просмотр информации о мосте
ip -d link show br0

# Просмотр VLAN, настроенных на мосте
bridge vlan show

# Просмотр L2-таблицы пересылки (MAC->порт) и состояний портов моста
bridge fdb show br br0
bridge link show

# Удаление моста
sudo ip link set eth0 nomaster
sudo ip link set eth1 nomaster
sudo ip link set br0 down
sudo ip link delete br0
```

### Аппаратная виртуализация SR-IOV

Настройка виртуальных функций (VF) напрямую из ОС.

```bash
# Назначить MAC-адрес и VLAN для конкретной виртуальной функции
sudo ip link set eth0 vf 0 mac 00:11:22:33:44:66 vlan 100

# Установка лимитов скорости для VF (в Мбит/с)
sudo ip link set eth0 vf 0 rate 1000

# Отключение spoof checking для VF
sudo ip link set eth0 vf 0 spoofchk off

# Просмотр информации о всех VF
ip -d link show eth0 | grep -A5 "vf 0"
```

### Интеграция с XDP (eXpress Data Path)

Запуск eBPF-программ до обработки пакета основным стеком ядра.

```bash
# Прикрепить программу в режиме Generic (универсальный, работает на любом NIC)
sudo ip link set dev eth0 xdpgeneric obj drop_icmp.o sec xdp

# Прикрепить программу в режиме Native (требует поддержки драйвером)
sudo ip link set dev eth0 xdp obj drop_icmp.o sec xdp

# Прикрепить программу в режиме Offloaded (на NIC с program-microcode)
sudo ip link set dev eth0 xdpoffload obj drop_icmp.o sec xdp

# Просмотр текущей XDP-программы
ip -d link show eth0 | grep xdp

# Отключить XDP
sudo ip link set dev eth0 xdpgeneric off
```

### Сетевые пространства имен (Network Namespaces)

```bash
# Создание пространства имен и veth-пары
sudo ip netns add container1
sudo ip link add veth-host type veth peer name veth-cont

# Перемещение одного конца в namespace
sudo ip link set veth-cont netns container1

# Активация интерфейсов
sudo ip link set veth-host up
sudo ip netns exec container1 ip link set veth-cont up

# Просмотр интерфейсов в namespace
sudo ip netns exec container1 ip link show
```

### Настройка VLAN

```bash
# Создание VLAN на физическом интерфейсе
sudo ip link add link eth0 name eth0.100 type vlan id 100
sudo ip link set eth0.100 up

# Создание Q-in-Q (двойного тегирования)
sudo ip link set dev eth0 mtu 1508
sudo ip link add link eth0 name eth0.1000 type vlan protocol 802.1ad id 1000
sudo ip link add link eth0.1000 name eth0.1000.10 type vlan protocol 802.1Q id 10
sudo ip link set eth0.1000 up
sudo ip link set eth0.1000.10 up

# Просмотр информации о VLAN
ip -d link show eth0.100

# Удаление VLAN
sudo ip link set eth0.100 down
sudo ip link delete eth0.100 type vlan id 100
```

## Дополнительная информация

### Сохранение настроек (Персистентность)

Параметры `ip link` применяются временно. Для сохранения используйте системные конфигураторы.

#### systemd-networkd (.link файлы)

Создайте файл `/etc/systemd/network/10-eth0.link`:

```ini
[Match]
MACAddress=52:54:00:12:34:56

[Link]
Name=lan0
MTUBytes=9000
MACAddress=00:11:22:33:44:55
```

#### systemd-networkd (.netdev файлы для виртуальных устройств)

Создайте файл `/etc/systemd/network/20-br0.netdev`:

```ini
[NetDev]
Name=br0
Kind=bridge

[Bridge]
STP=true
ForwardDelaySec=4
```

#### Netplan (Ubuntu)

```yaml
network:
  version: 2
  ethernets:
    eth0:
      match:
        macaddress: 52:54:00:12:34:56
      set-name: lan0
      mtu: 9000
```

#### /etc/network/interfaces (Debian, ifupdown2)

```bash
auto eth0
iface eth0 inet manual
    mtu 9000
    hwaddress 00:11:22:33:44:55
```

### Диагностика и отладка

#### Интерпретация статистики

```bash
ip -s link show eth0
```

| Поле | Описание | Типичные причины |
| :--- | :--- | :--- |
| **errors** | Ошибки на физике или дуплексе. | Поврежденный кабель, несовпадение скорости/дуплекса, проблема с SFP. |
| **dropped** | Пакеты отброшены ядром. | Переполнение `netdev_max_backlog`, нехватка CPU, oversize packets. |
| **overruns** | Ядро не успевает забирать пакеты из ring buffer NIC. | Низкая производительность CPU, неправильные настройки ring buffer. |
| **frame** | Ошибки фреймирования (CRC, alignment). | Аппаратные проблемы NIC или шины. |
| **carrier** | Ошибки несущей (loss of carrier). | Проблемы с физическим линком, отключение кабеля. |
| **fifo** | Ошибки FIFO-очереди. | Проблемы с драйвером NIC. |
| **compressed** | Сжатые пакеты (TCP/IP header compression). | Информационное поле. |
| **multicast** | Объем multicast-трафика. | Нормальное поведение для bridge/bond. |

#### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Device or resource busy` | Попытка изменить параметр (MAC, Name) на активном линке. | `ip link set ... down` перед изменением. |
| `NO-CARRIER` | Отсутствует физический линк. | Проверьте кабель, SFP или порт соседа. `ethtool eth0` для диагностики. |
| `Unknown device type` | Модуль ядра для типа (vxlan, bond) не загружен. | `sudo modprobe <тип_устройства>`. |
| `RTNETLINK answers: Operation not supported` | Параметр не поддерживается драйвером или ядром. | Проверьте версию ядра и возможности драйвера. |
| `RTNETLINK answers: Permission denied` | Недостаточно прав. | Используйте `sudo`. |
| `Error: argument "eth0" is wrong: dev is not a device name` | Интерфейс не существует или имя некорректно. | `ip link show` для проверки списка интерфейсов. |
| `RTNETLINK answers: File exists` | Интерфейс с таким именем уже существует. | Выберите другое имя или удалите существующий. |
| MTU не применяется | Значение MTU выходит за пределы, поддерживаемые драйвером. | Проверьте `ethtool eth0 | grep -i mtu` для диапазона. |
| Интерфейс периодически падает (flapping) | Нестабильный физический линк, проблема с кабелем/SFP. | Проверьте логи (`dmesg`), замените кабель/SFP. |

#### Диагностические команды

```bash
# Проверка физического состояния через ethtool
ethtool eth0 | grep -E "Speed|Duplex|Link detected"

# Просмотр драйвера и версии
ethtool -i eth0

# Проверка ring buffer
ethtool -g eth0

# Просмотр логов ядра для NIC
dmesg | grep -i eth0

# Мониторинг изменений состояния
ip monitor link
```

### Best Practices

1. **Перед изменением параметров** — всегда проверяйте текущее состояние: `ip -br link show`.
2. **MTU** — устанавливайте одинаковое значение на всех участниках сегмента. Проверяйте: `ping -M do -s <size> <gateway>`.
3. **Bonding** — используйте `802.3ad` (LACP) для максимальной производительности; `active-backup` для отказоустойчивости.
4. **Bridge** — включайте STP в масштабных средах для предотвращения петель. В замкнутых топологиях — отключайте.
5. **VRF** — используйте для изоляции трафика management/production без физического разделения.
6. **XDP** — начинайте с режима `xdpgeneric` для тестирования; переходите на `xdp` (native) для production.
7. **SR-IOV** — проверяйте поддержку IOMMU в BIOS перед настройкой VF.
8. **VLAN** — всегда изменяйте MTU физического интерфейса при использовании Q-in-Q.

### Edge Cases и ограничения

* **Одновременное использование master-устройств** — интерфейс не может быть slave в нескольких master-устройствах одновременно (кроме VLAN на bridge).
* **Rename активного интерфейса** — невозможен без предварительного `down`. При rename интерфейса, управляемого NetworkManager, возможны конфликты.
* **MTU и фрагментация** — если реальный MTU меньше заявленного, пакеты будут фрагментироваться или отбрасываться без уведомления (Black Hole).
* **Дублирование MAC** — два интерфейса с одинаковым MAC в одном broadcast-домене приводят к нестабильности ARP-таблицы.
* **Bonding и VLAN** — VLAN-интерфейсы создаются поверх bond, а не поверх slave-интерфейсов.
* **Bridge и STP** — включение STP добавляет задержку 30–50 сек (802.1D) или 1–10 сек (RSTP) при перестроении.
* **XDP и bridge** — XDP-программы не работают на интерфейсах, являющихся slave в bridge (используйте `tc` + eBPF).
* **Максимальное количество VFs** — зависит от NIC и может быть ограничено в BIOS/UEFI (типично 32–256).

### Версионная информация

| Возможность | Минимальная версия ядра | Примечания |
| :--- | :--- | :--- |
| Базовый `ip link` | 2.6.x | Стандартная функциональность. |
| XDP (generic) | 4.8 | Универсальный режим, работает на любом NIC. |
| XDP (native) | 4.18 | Требует поддержки драйвером NIC. |
| XDP (offload) | 5.3 | Выполнение на NIC с program-microcode. |
| SR-IOV VF настройка через `ip` | 3.x | Зависит от драйвера NIC. |
| `ip link ... altname` | 4.17 | Альтернативные имена интерфейсов. |
| MACVLAN в режиме `source` | 3.x | Фильтрация по MAC-источнику. |
| `ip -j` (JSON вывод) | 5.1 | Форматирование вывода в JSON. |

### Связанные темы

*   **[`ip address`](./ip_address.md)** — управление IP-адресами (L3).
*   **[`ip route`](./ip_route.md)** — управление таблицами маршрутизации.
*   **[`ip netns`](./ip_netns.md)** — управление сетевыми пространствами имен.
*   **[Сетевые интерфейсы Linux](../../Concepts/linux_network_interfaces.md)** — глубокий разбор типов (Bridge, Bond, VLAN, TUN/TAP).
*   **[Агрегация каналов (Link Aggregation)](../../../../Networking/Concepts/link_aggregation.md)** — режимы bonding (LACP, active-backup), teamd, xmit_hash_policy.
*   **[Linux Bridge](../../Concepts/linux_bridge.md)** — архитектура программного коммутатора, STP, VLAN filtering.
*   **[ethtool](../ethtool.md)** — низкоуровневая диагностика железа.
*   **[Обзор и настройка SR-IOV](../../../../Networking/Concepts/dpdk/sriov.md)** — глубокий разбор технологии и управление виртуальными функциями.
*   **[VRF](../../vrf.md)** — использование виртуальной маршрутизации.
*   **[systemd-networkd](../../Settings/Persistent_Network/systemd_networkd.md)** — персистентная настройка через .link/.netdev файлы.
