# ip link: Управление сетевыми интерфейсами

## Определения

**`ip link`** — команда `iproute2` для управления сетевыми интерфейсами (устройствами L1/L2). Работает с параметрами: состояние, MTU, MAC-адрес, promiscuous mode.

> **Важно:** `ip link` не управляет IP-адресами — для этого используется [`ip address`](./ip_address.md).

## Базовые концепции

### Типы интерфейсов

| Тип | Пример | Описание |
|-----|--------|----------|
| **lo** | `lo` | Loopback (127.0.0.1), для локальной связи |
| **Ethernet** | `enpXsY`, `eth0` | Физические адаптеры (предсказуемые имена) |
| **Wireless** | `wlan0`, `wlpXsY` | Беспроводные адаптеры |
| **Virtual** | `vethX`, `docker0` | Виртуальные пары, мосты |
| **Tunnel** | `gre1`, `ipip1`, `vxlan0` | Туннельные интерфейсы |
| **VLAN** | `eth0.100` | VLAN-интерфейсы (802.1Q) |
| **Bond** | `bond0` | Агрегация каналов (LACP) |

### Состояния интерфейса

| Состояние | Описание |
|-----------|----------|
| **UP** | Интерфейс активен |
| **DOWN** | Интерфейс отключён |
| **UNKNOWN** | Состояние неизвестно (часто для veth) |
| **NO-CARRIER** | Нет физического соединения (кабель) |

### MTU (Maximum Transmission Unit)

Максимальный размер кадра за одну передачу.

| Тип | MTU по умолчанию |
|-----|------------------|
| Ethernet | 1500 байт |
| Loopback | 65536 байт |
| VLAN | 1500 (меньше на 4 байта) |
| GRE-туннель | 1476 (1500 - 24) |
| VXLAN | 1450 (1500 - 50) |

> **Jumbo frames:** 9000 байт (требует поддержки оборудования)

## Практические сценарии

### Просмотр интерфейсов

```bash
# Все интерфейсы
ip link show

# Краткий вывод (одна строка на интерфейс)
ip -br link show

# Только активные
ip link show up

# Конкретный интерфейс
ip link show eth0

# Со статистикой (ошибки, дропы)
ip -s link show eth0

# Детальная информация
ip -d link show eth0
```

**Интерпретация статистики:**

* Рост `errors` — проблемы с оборудованием/драйвером
* Рост `dropped` — переполнение буферов, нет ресурсов
* `collisions` — коллизии (редко для full-duplex)

### Управление состоянием

```bash
# Включить интерфейс
sudo ip link set eth0 up

# Выключить интерфейс
sudo ip link set eth0 down

# Перезагрузить (down + up)
sudo ip link set eth0 down && sudo ip link set eth0 up
```

> **Важно:** Виртуальные интерфейсы (туннели, veth) создаются в состоянии `DOWN` и требуют явного включения.

### Изменение MTU

```bash
# Установить MTU
sudo ip link set eth0 mtu 1400

# Для jumbo frames
sudo ip link set eth0 mtu 9000

# Для туннелей (учитывать overhead)
sudo ip link set gre1 mtu 1476
```

### Изменение MAC-адреса

```bash
# Отключить интерфейс (обязательно)
sudo ip link set eth0 down

# Изменить MAC
sudo ip link set eth0 address 00:11:22:33:44:55

# Сгенерировать случайный MAC
sudo ip link set eth0 address random

# Включить обратно
sudo ip link set eth0 up

# Проверить
ip link show eth0 | grep link/ether
```

### Promiscuous mode

Режим для сниффинга трафика (tcpdump, Wireshark, виртуализация).

```bash
# Включить
sudo ip link set eth0 promisc on

# Выключить
sudo ip link set eth0 promisc off

# Проверить (искать PROMISC в выводе)
ip link show eth0
```

### Создание виртуальных интерфейсов

```bash
# VETH-пара (для namespace/контейнеров)
sudo ip link add veth-host type veth peer name veth-guest

# VLAN (802.1Q)
sudo ip link add link eth0 name eth0.100 type vlan id 100

# Bridge (мост)
sudo ip link add name br0 type bridge

# Bond (агрегация)
sudo ip link add name bond0 type bond mode 802.3ad
```

### Определение драйвера

```bash
# Через ethtool
ethtool -i eth0 | grep driver

# Через sysfs
cat /sys/class/net/eth0/device/driver/module

# Для virtio (виртуальные машины)
ethtool -i eth0 | grep virtio
```

> **virtio-net:** Паравиртуальный драйвер для KVM/QEMU. Производительнее эмулируемых (e1000).

## Дополнительная информация

### Связанные темы

* **[Сетевые интерфейсы](../../Concepts/linux_network_interfaces.md)** — типы, мосты, вeth-пары
* **[ip address](./ip_address.md)** — управление IP-адресами
* **[ethtool](../ethtool.md)** — диагностика адаптеров
* **[Оптимизация TCP](../../Concepts/tcp_tuning/tcp_tuning_overview.md)** — MTU, fragmentation

### Типичные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| `NO-CARRIER` | Нет кабеля, порт выключен | Проверить кабель, switch |
| `errors` растут | Проблема с драйвером/кабелем | `ethtool -S`, замена кабеля |
| `dropped` растут | Переполнение буферов | Увеличить `netdev_max_backlog` |
| MTU проблемы | Фрагментация | Проверить PMTUD, уменьшить MSS |
