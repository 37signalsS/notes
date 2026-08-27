# TUN vs TAP — виртуальные сетевые интерфейсы

## Определения

**TUN (Network TUNnel)** — виртуальный сетевой интерфейс третьего уровня (L3 — сетевой уровень), эмулирующий устройство точка-точка (Point-to-Point). Он работает непосредственно с IP-пакетами и не содержит заголовков канального уровня (Ethernet).

**TAP (Network TAP)** — виртуальный сетевой интерфейс второго уровня (L2 — канальный уровень), эмулирующий программный сетевой адаптер (NIC). Он работает с полноценными Ethernet-кадрами, включая MAC-адреса и поддержку широковещательного трафика (Broadcast).

**Общие характеристики:**

- **Реализация:** Реализованы как модули ядра Linux (`tun.ko`, `tap.ko`).
- **Интерфейс драйвера:** Доступны из пользовательского пространства через символьное устройство `/dev/net/tun`.
- **Механизм:** Связь между user-space и ядром осуществляется через системные вызовы `ioctl()` и файловые операции read/write.
- **Применение:** Используются VPN-решениями (OpenVPN, WireGuard), системами виртуализации (QEMU/KVM) и контейнеризацией.

> **См. также:** [Обзор сетевых туннелей](./tunneling_overview.md), [Сетевые интерфейсы Linux](../../Linux/Networking/Concepts/linux_network_interfaces.md)

---

## Предварительные требования

### Версии ядра и пакетов

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **Ядро Linux** | 2.4 (базовая поддержка TUN/TAP) | 5.10+ (multi-queue, BIG TCP, XDP) |
| **iproute2** | 3.12 (ip link add type tun/tap) | 5.15+ |
| **QEMU** (для TAP) | 1.0 | 8.0+ (virtio-net multi-queue) |
| **OpenVPN** (для TUN) | 2.0 | 2.6+ |

### Проверка наличия модулей ядра

```bash
# Проверка модуля TUN
modinfo tun | head -3
# → filename:       /lib/modules/$(uname -r)/kernel/drivers/net/tun.ko
# → license:        GPL

# Проверка модуля TAP
modinfo tap | head -3
# → filename:       /lib/modules/$(uname -r)/kernel/drivers/net/tap.ko

# Проверка загруженных модулей
lsmod | grep -E "^(tun|tap)"
# → tun     49152  3
# → tap     32768  0

# Проверка символьного устройства
ls -la /dev/net/tun
# → crw-rw---- 1 root root 10, 200 ... /dev/net/tun
```

### Включение IP-форвардинга (для маршрутизации через TUN)

```bash
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/91-tun-tap.conf
sudo sysctl -p /etc/sysctl.d/91-tun-tap.conf
```

### Установка зависимостей

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install iproute2 bridge-utils ethtool tcpdump

# RHEL/CentOS/Rocky
sudo dnf install iproute bridge-utils ethtool tcpdump
```

---

## Основные концепции

### Сравнительная таблица характеристик

| Характеристика | TUN (L3) | TAP (L2) |
| :--- | :--- | :--- |
| **Уровень OSI** | Layer 3 (Сетевой) | Layer 2 (Канальный) |
| **Единица данных** | IP-пакет (IPv4/IPv6) | Ethernet-кадр |
| **Тип интерфейса** | Point-to-Point | Виртуальный Ethernet (NIC) |
| **Заголовки** | Только IP | Ethernet + MAC-адреса |
| **Broadcast / Multicast** | Не передаёт (L2) | Полная поддержка (как физический NIC) |
| **ARP / DHCP** | Не поддерживает (не требуются) | Поддерживает нативно |
| **Накладные расходы** | Минимальные (~20-40 байт IP) | +14–18 байт Ethernet |
| **Маршрутизация** | Нативная IP-маршрутизация | Через Bridge (мост) или коммутацию |
| **Не-IP трафик** | Не поддерживает | Поддерживает (IPX, NetBIOS, AppleTalk) |

### Принцип работы и путь пакета

**Интерфейс TUN (L3):**
Приложение читает/пишет IP-пакеты напрямую. Ядро маршрутизирует трафик через `tun0` как обычный сетевой интерфейс.
```text
[Приложение (VPN)] <-> [IP-пакет] <-> [/dev/net/tun] <-> [tun0] <-> [Стек IP ядра] <-> [Физическая сеть]
```

**Интерфейс TAP (L2):**
Приложение работает с полноценными Ethernet-кадрами. Для интеграции с физической сетью обычно требуется bridge (мост), объединяющий `tap0` и физический интерфейс.
```text
[Приложение (VM)] <-> [Ethernet-кадр] <-> [/dev/net/tap] <-> [tap0] <-> [Bridge] <-> [eth0] <-> [Физическая сеть]
```

### Формат данных и служебные заголовки

Помимо полезной нагрузки, интерфейсы могут использовать дополнительные метаданные:

1.  **Packet Information (PI):**
    - Добавляет 4 байта перед каждым пакетом (2 байта флаги, 2 байта протокол).
    - Позволяет приложению знать, какой протокол инкапсулирован (важно для multi-protocol TUN).
    - В выводе `ip -d link` отображается как `pi on/off`.

2.  **Virtual Network Header (vnet_hdr):**
    - Используется в виртуализации (virtio-net).
    - Позволяет передавать информацию о GSO (Generic Segmentation Offload) и контрольных суммах между гостем и хостом.

3.  **Накладные расходы (Overhead) и MTU:**
    - **TUN:** ~20 байт (IPv4) или ~40 байт (IPv6).
    - **TAP:** Дополнительные 14–18 байт Ethernet-заголовка.
    - **Важно:** При использовании поверх физических интерфейсов с MTU 1500, MTU виртуального интерфейса должен быть уменьшен (например, до 1450), чтобы избежать фрагментации инкапсулированных пакетов.

### Производительность и Multi-queue (MQ)

- **CPU usage:** У TUN ниже, так как ядру не нужно обрабатывать стек L2 и ARP.
- **Пропускная способность:** TUN обычно на 5–10% быстрее TAP при прочих равных.
- **Multi-queue (MQ):** Позволяет создавать несколько дескрипторов (очередей) для одного интерфейса.
    - **Рекомендация:** Количество очередей должно соответствовать числу vCPU (до 16). Это устраняет блокировки (lock contention) и позволяет масштабировать трафик выше 10 Gbps.
    - **BIG TCP (Linux 6.3+):** TUN/TAP поддерживают BIG TCP, что позволяет передавать пакеты до 512 КБ в стеке, снижая нагрузку на CPU при высоких скоростях.

### MACVTAP — альтернатива TAP

**MACVTAP** — это комбинация драйвера `macvlan` и `tap`. 
- **Преимущество:** Прямая связь с физическим интерфейсом, минуя программный Bridge. Это снижает задержки и нагрузку на CPU на 10–20%.
- **Ограничение:** Хост не может общаться с гостем через тот же физический интерфейс без дополнительных настроек (требуется отдельный мост или veth для управления).

---

## Практические сценарии

### Управление интерфейсами (iproute2)

**Создание TUN/TAP:**
```bash
# Современный способ (Linux 3.18+)
sudo ip link add name tun1 type tun
sudo ip link add name tap1 type tap multi_queue on
```

**Проверка параметров:**
```bash
# Детальный просмотр параметров
ip -d link show tun1
# → tun1: <NOARP,UP,LOWER_UP> mtu 1500 ... state UNKNOWN ...
# →     tun type tun pi off vnet_hdr on multi_queue on ...

# Проверка статистики
ip -s link show tun1
# → RX:  bytes=0 packets=0 errors=0 dropped=0
# → TX:  bytes=0 packets=0 errors=0 dropped=0

# Удаление интерфейса
sudo ip link delete tun1
```

**Удаление TUN/TAP через `ip tuntap` (legacy-способ):**
```bash
# Создание TUN с привязкой к пользователю
sudo ip tuntap add mode tun dev tun0 user vpnuser group vpnuser

# Создание TAP
sudo ip tuntap add mode tap dev tap0 user kvmuser

# Удаление
sudo ip tuntap del mode tun dev tun0
```

### Лаборатория: TUN-туннель между Network Namespaces

Полный пример настройки L3-туннеля между двумя изолированными пространствами имён:

```bash
# Создание двух пространств имён
ip netns add ns1
ip netns add ns2

# Создание TUN-интерфейсов
ip link add tun1 type tun
ip link add tun2 type tun

# Перемещение интерфейсов в пространства имён
ip link set tun1 netns ns1
ip link set tun2 netns ns2

# Настройка адресов и поднятие интерфейсов
ip netns exec ns1 ip addr add 10.0.0.1/24 dev tun1
ip netns exec ns1 ip link set tun1 up
ip netns exec ns1 ip link set lo up

ip netns exec ns2 ip addr add 10.0.0.2/24 dev tun2
ip netns exec ns2 ip link set tun2 up
ip netns exec ns2 ip link set lo up

# Простая маршрутизация (без IP-форвардинга, напрямую через P2P)
ip netns exec ns1 ip route add 10.0.0.2/32 dev tun1
ip netns exec ns2 ip route add 10.0.0.1/32 dev tun2

# Тест
ip netns exec ns1 ping -c 2 10.0.0.2
# → PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.
# → 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.089 ms

# Очистка
ip netns exec ns1 ip link delete tun1
ip netns exec ns2 ip link delete tun2
ip netns del ns1
ip netns del ns2
```

### Лаборатория: TAP-мост с Bridge

Создание L2-сегмента через TAP и Bridge:

```bash
# Создание Bridge
ip link add br0 type bridge
ip addr add 192.168.100.1/24 dev br0
ip link set br0 up

# Создание TAP-интерфейса
ip link add tap0 type tap
ip link set tap0 master br0
ip link set tap0 up

# Включение forward для bridge
sysctl -w net.bridge.bridge-nf-call-iptables=0

# Проверка
bridge link show
# → tap0: <BROADCAST,MULTICAST,UP> master br0 state forwarding ...

bridge fdb show dev tap0
# → (пока пусто — FDB заполняется при появлении MAC)

# Просмотр MAC-таблицы bridge
bridge fdb show br br0
```

### Сценарий 1: VPN для маршрутизации (TUN)

- **WireGuard:** Использует исключительно TUN. Не поддерживает L2-бриджинг по дизайну. См. [WireGuard — подробное руководство](../../Vpn/wireguard.md).
- **OpenVPN:** Режим `dev tun`. Самый распространенный вариант для удаленного доступа.

**Пример: OpenVPN в режиме TUN (упрощённый):**

```bash
# Серверная конфигурация (server.conf)
# dev tun
# port 1194
# proto udp
# ca ca.crt
# cert server.crt
# key server.key
# dh dh2048.pem
# server 10.8.0.0 255.255.255.0

# Запуск сервера
sudo openvpn --config server.conf --daemon

# Проверка интерфейса
ip addr show tun0
# → tun0: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1500 ...
# →     inet 10.8.0.1 peer 10.8.0.2/32 scope global tun0
```

**Валидация TUN-туннеля:**
```bash
# Проверка, что интерфейс поднят и имеет адрес
ip -br addr show tun0
# → tun0      UP             10.8.0.1/24

# Проверка маршрута
ip route show dev tun0
# → 10.8.0.0/24 proto kernel scope link src 10.8.0.1

# ПроверкаMTU
ip link show tun0 | grep mtu
# → mtu 1500

# Прослушивание трафика
sudo tcpdump -ni tun0 icmp -c 5
```

### Сценарий 2: Мост для L2-доступа (TAP)

Используется, когда клиенту нужен «эффект присутствия» в локальной сети (доступ к DHCP, сетевым играм, не-IP протоколам).

```bash
# Создание Bridge
sudo ip link add br0 type bridge
sudo ip addr add 192.168.1.1/24 dev br0
sudo ip link set br0 up

# Создание TAP-интерфейса и привязка к Bridge
sudo ip link add tap0 type tap
sudo ip link set tap0 master br0
sudo ip link set tap0 up

# Включение STP (защита от петель)
sudo ip link set br0 type bridge stp_state 1

# Настройка NAT для доступа в интернет (опционально)
sudo iptables -t nat -A POSTROUTING -s 192.168.1.0/24 -o eth0 -j MASQUERADE
```

**Валидация TAP + Bridge:**
```bash
# Проверка привязки TAP к Bridge
bridge link show dev tap0
# → tap0: <BROADCAST,MULTICAST,UP> master br0 state forwarding ...

# Проверка STP
bridge link show dev br0 | grep -o "stp_state [0-9]"
# → stp_state 1

# Проверка MAC-таблицы bridge
bridge fdb show br br0 | head -5

# Проверка IP-адреса bridge
ip addr show br0
# → br0: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
# →     inet 192.168.1.1/24 scope global br0
```

### Сценарий 3: Виртуализация (QEMU/KVM)

Подключение VM к сети хоста. В современных системах предпочтительно использовать `virtio-net` с поддержкой очередей.

**Запуск QEMU с использованием Multi-queue:**
```bash
qemu-system-x86_64 \
  -netdev tap,id=net0,ifname=tap0,queues=4,vhost=on \
  -device virtio-net-pci,netdev=net0,mq=on,vectors=10 \
  ...
```

**Валидация Multi-queue:**
```bash
# Проверка числа очередей TAP
ethtool -l tap0
# → Pre-set settings:
# →     Combined:   4 queues
# → Current hardware settings:
# →     Combined:   4 queues

# Проверка числа очередей virtio-net (внутри VM)
ethtool -l eth0
# → Combined:   4 queues
```

### Взаимодействие с XDP и eBPF

В современных сетевых стеках TUN/TAP могут работать с eBPF:
- **Generic XDP (xdpgeneric):** Поддерживается всеми TUN/TAP устройствами. Позволяет фильтровать трафик до того, как он попадет в основной стек ядра, но после аллокации `sk_buff`.
- **Native XDP:** Доступен только для `virtio-net` (виртуальные машины), обеспечивая максимальную производительность.

---

## Управление и безопасность

### Управление правами доступа (Capabilities)

Доступ к `/dev/net/tun` обычно требует прав root. Для запуска приложений от обычного пользователя используются Linux Capabilities:

```bash
# Разрешить приложению создавать туннели без прав root
sudo setcap cap_net_admin+ep /usr/sbin/openvpn
```

Также можно создать интерфейс заранее и передать права пользователю:
```bash
sudo ip tuntap add mode tun dev tun0 user vpnuser
```

### Обеспечение персистентности (Netplan и NetworkManager)

Для сохранения настроек после перезагрузки:

**Netplan (/etc/netplan/01-netcfg.yaml):**
```yaml
tunnels:
  tun0:
    mode: tun
    user: vpnuser
    addresses: [10.8.0.1/24]
```

**NetworkManager:**
```bash
nmcli connection add type tun mode tun ifname tun0 con-name vpn-tun
```

---

## Диагностика

### Просмотр всех TUN/TAP-интерфейсов

```bash
# Список всех виртуальных интерфейсов типа tun/tap
ip -d link show type tun
ip -d link show type tap

# Просмотр через /sys
ls /sys/class/net/ | while read iface; do
  type=$(cat /sys/class/net/$iface/type 2>/dev/null)
  if [ "$type" = "65534" ]; then  # ARPHRD_TUN
    echo "$iface: TUN/TAP"
  fi
done
```

### Просмотр `/dev/net/tun`

```bash
# Проверка доступности устройства
ls -la /dev/net/tun
# → crw-rw---- 1 root root 10, 200 ... /dev/net/tun

# Просмотр процессов, использующих TUN/TAP
sudo lsof /dev/net/tun
# → COMMAND   PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
# → openvpn 1234 root  7u CHR  10,200      0t0  /dev/net/tun
```

### Диагностика через sysctl

```bash
# Проверка IP-форвардинга
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1

# Проверка support для multi-queue
sysctl net.core.netdev_max_backlog
# → net.core.netdev_max_backlog = 1000
```

---

## Типичные ошибки и их устранение

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`ERROR: Can't open /dev/net/tun`** | Нет модуля ядра или нет прав доступа | `ls -la /dev/net/tun`; `modprobe tun` | Загрузить модуль `tun`; проверить права доступа |
| **TUN/TAP интерфейс не виден в `ip link`** | Интерфейс не создан или не привязан к namespace | `ip link show type tun`; `ip netns list` | Проверить, что интерфейс создан и находится в нужном namespace |
| **Нет connectivity через TUN** | Маршрутизация не настроена | `ip route show dev tun0`; `ping -I tun0` | Добавить маршрут: `ip route add <remote>/32 dev tun0` |
| **MTU mismatch, фрагментация** | MTU виртуального интерфейса не уменьшен | `ip link show tun0 \| grep mtu` | Уменьшить MTU: `ip link set tun0 mtu 1450` |
| **TAP не получает DHCP-ответ** | Bridge не поднят или STP блокирует порт | `bridge link show`; `bridge fdb show` | Проверить STP, добавить `bridge vlan` |
| **Ошибки权限 `EPERM` при создании TUN** | Нет `CAP_NET_ADMIN` | `cat /proc/self/status \| grep Cap` | `sudo setcap cap_net_admin+ep /path/to/app` |
| **Multi-queue не работает** | Ядро или NIC не поддерживают MQ | `ethtool -l tap0`; `dmesg \| grep tun` | Обновить ядро до 5.10+; проверить драйвер NIC |
| **TAP-интерфейс вestado DOWN** | Интерфейс не поднят после создания | `ip link show tap0` | `ip link set tap0 up` |

---

## Лучшие практики

### Безопасность

1. **Ограничение доступа к `/dev/net/tun`:**
   ```bash
   # Проверка прав
   ls -la /dev/net/tun
   # → crw-rw---- 1 root root 10, 200

   # Добавление пользователя в группу (если настроен udev-правило)
   sudo usermod -aG netdev vpnuser
   ```

2. **Использование Capabilities вместо root:**
   ```bash
   # Вместо запуска OpenVPN от root — дать только CAP_NET_ADMIN
   sudo setcap cap_net_admin+ep /usr/sbin/openvpn

   # Проверка
   getcap /usr/sbin/openvpn
   # → /usr/sbin/openvpn cap_net_admin=ep
   ```

3. **Firewall для TAP-интерфейсов:**
   ```bash
   # Ограничение трафика на TAP (для VM)
   sudo iptables -A FORWARD -i tap0 -o eth0 -s 192.168.100.0/24 -j ACCEPT
   sudo iptables -A FORWARD -i tap0 -o eth0 -j DROP
   ```

### MTU-тюнинг

| Сценарий | Рекомендуемый MTU | Пояснение |
| :--- | :--- | :--- |
| **TUN-туннель (IPv4)** | 1450 | Стандартный Ethernet (1500) - IP/UDP overhead (50) |
| **TUN-туннель (IPv6)** | 1430 | IPv6 overhead больше (70 байт) |
| **TAP + Bridge** | 1500 | Без additional overhead (L2 в L2) |
| **TAP + IPsec** | 1400 | Учет ESP-overhead (50-70 байт) |

```bash
# Установка MTU
sudo ip link set tun0 mtu 1450

# Проверка Path MTU
ping -M do -s 1422 -c 1 <remote-ip>
# → 1422 + 28 (IP+ICMP) = 1450 = MTU
```

### Персистентность и автозагрузка

**systemd-юнит для TUN-интерфейса:**
```ini
# /etc/systemd/system/tun0.service
[Unit]
Description=TUN interface for VPN
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/sbin/ip link add tun0 type tun
ExecStart=/sbin/ip addr add 10.8.0.1/24 dev tun0
ExecStart=/sbin/ip link set tun0 up
ExecStop=/sbin/ip link delete tun0
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tun0.service
sudo systemctl start tun0.service
```

---

## Граничные случаи и ограничения

1. **Одновременное использование TUN и TAP на одном хосте:** Допустимо, но необходимо следить за маршрутами — трафик может пойти не через тот интерфейс.

2. **Multi-queue и IRQ affinity:** Для оптимальной производительности Multi-queue необходимо настроить IRQ affinity, чтобы очереди TUN/TAP распределялись по разным ядрам CPU:
   ```bash
   # Просмотр IRQ для TAP
   grep tap0 /proc/interrupts

   # Настройка IRQ affinity (пример)
   echo 2 > /proc/irq/<irq_number>/smp_affinity  # Ядро 1
   ```

3. **Контейнеры и TUN/TAP:** В Docker/Kubernetes TUN/TAP-устройства требуют `--privileged` или `--cap-add=NET_ADMIN` + volume-mount `/dev/net/tun`.

4. **IPv6 и TUN:** При работе с IPv6 необходимо учитывать больший overhead (40 байт IPv6 + 8 байт UDP = 48 байт). Рекомендуемый MTU: 1430.

5. **Нестандартные MTU в облаках:** AWS, GCP, Azure имеют специфические ограничения MTU. При использовании TUN/TAP поверх облачных VPC необходимо учитывать их overhead:
   - AWS: MTU 9001 (jumbo frames), но при VPN - ограничение 1500
   - GCP: MTU 1460
   - Azure: MTU 1500

---

## Дополнительная информация

### Безопасность
- **TUN (L3):** Меньшая поверхность атаки. Невозможен ARP-spoofing внутри туннеля.
- **TAP (L2):** Позволяет выполнять перехват (sniffing) и инъекции трафика на уровне L2. Требуется настройка `stp` на мостах для защиты от петель.

### Алгоритм выбора интерфейса

```text
Требуется передача не-IP трафика (IPX, AppleTalk)?
|-- Да -> TAP
`-- Нет -> Требуется DHCP или Broadcast в туннеле?
         |-- Да -> TAP (или MACVTAP для производительности)
         `-- Нет -> TUN (максимальная эффективность и безопасность)
```

### См. также
- **[Технология VXLAN](./vxlan.md)** — инкапсуляция L2 в UDP, стандарт для облачных сетей.
- **[WireGuard — подробное руководство](../../Vpn/wireguard.md)** — современный VPN на базе TUN.
- **[Linux Bridge: программный коммутатор](../../Linux/Networking/Concepts/linux_bridge.md)** — технология объединения TAP-интерфейсов.
