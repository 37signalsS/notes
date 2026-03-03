# Tun vs Tap

## Определения

**`tun` (network tunnel)** — виртуальный сетевой интерфейс L3 (сетевой уровень), эмулирующий IP-интерфейс точка-точка.

**`tap` (network tap)** — виртуальный сетевой интерфейс L2 (канальный уровень), эмулирующий Ethernet-адаптер (NIC).

**Общее:**
- Реализованы как модули ядра Linux (`tun.ko`, `tap.ko`)
- Доступны из пользовательского пространства через `/dev/net/tun`
- Используются VPN, виртуализацией, контейнерами

## Базовые концепции

### Сравнительная таблица

| Характеристика | `tun` (L3) | `tap` (L2) |
|---------------|------------|------------|
| **Уровень OSI** | Layer 3 (Сетевой) | Layer 2 (Канальный) |
| **Единица данных** | IP-пакет | Ethernet-кадр |
| **Тип интерфейса** | Point-to-Point | Виртуальный Ethernet (NIC) |
| **Заголовки** | Только IP | Ethernet + MAC-адреса |
| **Broadcast** | Не передаёт | Передаёт (как физический NIC) |
| **ARP/DHCP** | Не поддерживает | Поддерживает |
| **Overhead** | Минимальный | +14 байт (Ethernet) |
| **Маршрутизация** | Нативная | Через bridge |

### Принцип работы

**`tun` (L3):**
```
[Приложение] → [IP-пакет] → [/dev/net/tun] → [tun0] → [IP-стек] → [Сеть]
```

**`tap` (L2):**
```
[Приложение] → [Ethernet-кадр] → [/dev/net/tap] → [tap0] → [bridge] → [eth0] → [Сеть]
```

### Заголовки данных

**tun:**
- Инкапсулирует только IP-пакеты
- Нет MAC-адресов
- Меньший overhead (~20-40 байт IP)

**tap:**
- Полноценный Ethernet-кадр
- MAC-адреса источника/назначения (12 байт)
- EtherType (2 байта)
- Больший overhead (~40-60 байт)

## Практические сценарии

### 1. tun: VPN для маршрутизации (L3)

**Сценарий:** Безопасное соединение сетей или клиента с сетью.

**Примеры:**
- **WireGuard:** Использует только `tun`
- **OpenVPN:** Режим `dev tun`
- **IPsec:** Транспортный режим

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
```

**Преимущества:**
- Клиенты получают IP от локального DHCP
- Видимость через ARP
- Поддержка не-IP протоколов (IPX, NetBIOS)

**Когда использовать:**
- Виртуальные машины в сети хоста
- Промышленные сети (PROFIBUS, Modbus TCP)
- Старые сетевые игры
- Требуется полный L2-доступ

### 3. tun: Контейнеры и namespace

**Сценарий:** Сетевая изоляция контейнеров.

```bash
# Создание tun в network namespace
ip netns add container1
ip netns exec container1 ip link add dev tun0 type tun
ip netns exec container1 ip link set tun0 up
ip netns exec container1 ip address add 10.0.0.2/24 dev tun0
```

**Применение:**
- Docker (через bridge + veth)
- Kubernetes CNI
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
ip -d link show tap0

# Тип интерфейса
ethtool -i tun0 | grep driver

# Мониторинг трафика
tcpdump -i tun0 -n      # Только IP
tcpdump -i tap0 -e      # Ethernet + MAC
```

## Дополнительная информация

### Производительность

| Параметр | tun | tap |
|----------|-----|-----|
| **Overhead** | ~20-40 байт | ~40-60 байт |
| **CPU** | Ниже | Выше (обработка Ethernet) |
| **Пропускная способность** | Выше | Ниже (~5-10%) |

### Ограничения

**tun:**
- Только IP-трафик (IPv4/IPv6)
- Нет broadcast/multicast
- Не работает с DHCP (нужна статическая адресация)

**tap:**
- Больший overhead
- Требует bridge для интеграции
- Может вызывать broadcast-штормы при неправильной настройке

### Выбор между tun и tap

```
Требуется передача не-IP трафика?
├─ Да → tap
└─ Нет → Требуется DHCP/broadcast?
         ├─ Да → tap
         └─ Нет → tun (эффективнее)
```

### Ссылки

- [Linux Tun/Tap Documentation](https://www.kernel.org/doc/Documentation/networking/tuntap.txt)
- [OpenVPN Tun/Tap Guide](https://openvpn.net/community-resources/how-to/#tun-vs-tap)
- [QEMU Networking](https://wiki.qemu.org/Documentation/Networking)
