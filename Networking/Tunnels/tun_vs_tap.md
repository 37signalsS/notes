# Tun vs Tap

## Определения

**`tun` (network tunnel)** — виртуальный сетевой интерфейс L3 (сетевой уровень), эмулирующий IP-интерфейс точка — точка. Работает с IP-пакетами, не передаёт Ethernet-кадры.

**`tap` (network tap)** — виртуальный сетевой интерфейс L2 (канальный уровень), эмулирующий Ethernet-адаптер (NIC). Работает с полноценными Ethernet-кадрами, включая MAC-адреса.

**Общее:**

- Реализованы как модули ядра Linux (`tun.ko`, `tap.ko`)
- Доступны из пользовательского пространства через `/dev/net/tun`
- Используются VPN (OpenVPN, WireGuard), виртуализацией (QEMU/KVM), контейнерами
- Связь с user-space через `ioctl()` и файловые операции read/write

**Связанные темы:** [Сетевые туннели — обзор](./tunneling_overview.md), [Сетевые интерфейсы Linux](../../Linux/Networking/Concepts/linux_network_interfaces.md)

## Основные концепции

### Сравнительная таблица

| Характеристика | `tun` (L3) | `tap` (L2) |
|---------------|------------|------------|
| **Уровень OSI** | Layer 3 (Сетевой) | Layer 2 (Канальный) |
| **Единица данных** | IP-пакет | Ethernet-кадр |
| **Тип интерфейса** | Point-to-Point | Виртуальный Ethernet (NIC) |
| **Заголовки** | Только IP | Ethernet + MAC-адреса |
| **Broadcast** | Не передаёт | Передаёт (как физический NIC) |
| **ARP/DHCP** | Не поддерживает | Поддерживает |
| **Overhead** | Минимальный (~20-40 байт IP) | +14 байт Ethernet |
| **Маршрутизация** | Нативная | Через bridge |
| **Не-IP трафик** | Не поддерживает | Поддерживает (IPX, NetBIOS) |

### Принцип работы

**Интерфейс `tun` (L3):**

```
[Приложение] → [IP-пакет] → [/dev/net/tun] → [tun0] → [IP-стек] → [Сеть]
```

Приложение читает/пишет IP-пакеты напрямую. Ядро маршрутизирует трафик через `tun0` как обычный сетевой интерфейс.

**Интерфейс `tap` (L2):**

```
[Приложение] → [Ethernet-кадр] → [/dev/net/tap] → [tap0] → [bridge] → [eth0] → [Сеть]
```

Приложение работает с Ethernet-кадрами. Для интеграции с физической сетью требуется bridge, объединяющий `tap0` и `eth0`.

### Формат данных и заголовки

**Для `tun`:**

- Инкапсулирует только IP-пакеты (IPv4/IPv6)
- Нет MAC-адресов
- Overhead: ~20 байт (IPv4) или ~40 байт (IPv6)

**Для `tap`:**

- Полноценный Ethernet-кадр
- MAC-адреса источника/назначения (12 байт)
- EtherType (2 байта)
- Overhead: ~40-60 байт (Ethernet + IP)

### Управление интерфейсами

```bash
# Создание tun-интерфейса
ip tuntap add mode tun dev tun0
ip link set tun0 up
ip addr add 10.0.0.1/24 dev tun0

# Создание tap-интерфейса
ip tuntap add mode tap dev tap0
ip link set tap0 up

# Удаление интерфейса
ip link delete tun0
ip link delete tap0

# Проверка типа интерфейса
ip -d link show tun0
# → tun: тип tun, tap: тип tap
```

## Практические сценарии

### 1. tun: VPN для маршрутизации (L3)

**Сценарий:** Безопасное соединение сетей или клиента с корпоративной сетью.

**Примеры:**

- **WireGuard:** Использует только `tun` ([подробнее](../../Vpn/wireguard.md))
- **OpenVPN:** Режим `dev tun`
- **IPsec:** Транспортный режим ([подробнее](./ipsec/ipsec.md))

**Конфигурация OpenVPN (tun):**

```conf
# server.conf
dev tun
ifconfig 10.8.0.1 10.8.0.2
route 192.168.1.0 255.255.255.0

# client.conf
dev tun
remote vpn.example.com 1194
```

**Преимущества:**

- Простота настройки
- Эффективность (меньший overhead)
- Подходит для 95% VPN-сценариев

**Когда использовать:**

- Удалённый доступ к корпоративной сети
- Site-to-site VPN
- Только IP-трафик

### 2. tap: Мост для L2-доступа

**Сценарий:** Полноценная интеграция удалённых клиентов в локальную сеть.

**Примеры:**

- **OpenVPN:** Режим `dev tap`
- **QEMU/KVM:** Сетевые интерфейсы VM
- **Промышленные протоколы:** Не-IP трафик

**Конфигурация OpenVPN (tap):**

```conf
# server.conf
dev tap
server-bridge 192.168.1.1 255.255.255.0 192.168.1.100 192.168.1.200

# client.conf
dev tap
remote vpn.example.com 1194
```

**Настройка bridge в Linux:**

```bash
# Создание моста
ip link add name br0 type bridge
ip link set tap0 master br0
ip link set eth0 master br0
ip link set br0 up
ip addr add 192.168.1.10/24 dev br0
```

**Преимущества:**

- Клиенты получают IP от локального DHCP
- Видимость через ARP
- Поддержка не-IP протоколов (IPX, NetBIOS)

**Когда использовать:**

- Виртуальные машины в сети хоста
- Промышленные сети (PROFIBUS, Modbus TCP)
- Требуется полный L2-доступ

### 3. tun: Контейнеры и сетевые пространства имен (Namespace)

**Сценарий:** Сетевая изоляция контейнеров.

```bash
# Создание network namespace
ip netns add container1

# Создание tun в namespace
ip -n container1 link add dev tun0 type tun
ip -n container1 link set tun0 up
ip -n container1 addr add 10.0.0.2/24 dev tun0
```

**Применение:**

- Docker (через bridge + veth, [подробнее](../../Docker/Docker_network/drivers/bridge.md))
- Kubernetes CNI (Calico, Cilium)
- LXC/LXD

### 4. tap: Виртуализация (QEMU/KVM)

**Сценарий:** Подключение VM к сети хоста.

```bash
# Запуск VM с tap-интерфейсом
qemu-system-x86_64 \
  -netdev tap,id=net0,ifname=tap0,script=no \
  -device e1000,netdev=net0 \
  vm-image.qcow2
```

**Libvirt (XML):**

```xml
<interface type='bridge'>
  <source bridge='br0'/>
  <model type='virtio'/>
</interface>
```

### 5. Проверка и диагностика

```bash
# Статус интерфейса
ip -d link show tun0
# → tun0: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1500 ... tun

# Мониторинг трафика
tcpdump -i tun0 -n
# → 10.8.0.2 > 10.8.0.1: ICMP echo request, id 1, seq 1, length 64

tcpdump -i tap0 -e
# → 00:11:22:33:44:55 > 66:77:88:99:aa:bb, ethertype IPv4 (0x0800), length 98: ...

# Статистика по интерфейсу
ip -s link show tun0
# → RX: bytes  packets  errors  dropped overrun mcast
# → 1234       10       0       0       0       0

# Проверка драйвера
ethtool -i tun0 | grep driver
# → driver: tun
```

## Дополнительная информация

### Производительность

| Параметр | tun | tap |
|----------|-----|-----|
| **Overhead** | ~20-40 байт (IP) | ~40-60 байт (Ethernet + IP) |
| **CPU usage** | Ниже | Выше (обработка Ethernet) |
| **Пропускная способность** | Выше | Ниже (~5-10%) |
| **Latency** | Минимальная | Немного выше |

### Ограничения

**Для `tun`:**

- Только IP-трафик (IPv4/IPv6)
- Нет broadcast/multicast на уровне L2
- Не работает с DHCP (нужна статическая адресация или DHCP relay на L3)

**Для `tap`:**

- Больший overhead на каждый пакет
- Требует bridge для интеграции с физической сетью
- Может вызывать broadcast-штормы при неправильной настройке
- Неприменим для маршрутизации без bridge

### Алгоритм выбора

```
Требуется передача не-IP трафика?
├─ Да → tap
└─ Нет → Требуется DHCP/broadcast на L2?
         ├─ Да → tap
         └─ Нет → tun (эффективнее)
```

### Безопасность

- **tun:** Изоляция на L3, трафик не виден другим хостам в сегменте
- **tap:** Полный L2-доступ, возможен sniffing трафика (как на физическом NIC)
- Для VPN-сценариев предпочтителен `tun` (меньшая поверхность атаки)

### См. также

- [Обзор туннелирования](./tunneling_overview.md)
- [Сетевые интерфейсы Linux](../../Linux/Networking/Concepts/linux_network_interfaces.md)
- [WireGuard](../../Vpn/wireguard.md)
- [IPsec](./ipsec/ipsec.md)
- [Docker bridge](../../Docker/Docker_network/drivers/bridge.md)
