# systemd-networkd

**Reliability Score: 10 (SSoT + Web)**

**systemd-networkd** — системная служба, входящая в состав системного менеджера systemd, предназначенная для управления сетевыми интерфейсами. Она предоставляет декларативный способ настройки сети через конфигурационные файлы и идеально подходит для серверов, контейнеров и минималистичных систем благодаря отсутствию внешних зависимостей и высокой производительности.

## Определения

- **systemd-networkd** — легковесный менеджер сети, работающий в пространстве пользователя и взаимодействующий с ядром через Netlink.
- **Декларативная конфигурация** — подход, при котором описывается конечное желаемое состояние системы, а не последовательность команд для его достижения.
- **Drop-in директории** — каталоги вида `*.d/`, позволяющие переопределять или дополнять настройки без изменения основных файлов.
- **RequiredForOnline** — параметр, определяющий, должен ли интерфейс быть успешно настроен для того, чтобы состояние сети считалось «online» (используется `systemd-networkd-wait-online`).
- **DHCP Relay (DHCP-ретранслятор)** — служба, пересылающая DHCP-запросы между клиентами и серверами, находящимися в разных подсетях.

## Базовые концепции

Конфигурация `systemd-networkd` хранится в трех основных директориях (в порядке возрастания приоритета):
1. `/usr/lib/systemd/network/` — настройки от поставщика ОС (не изменять).
2. `/run/systemd/network/` — временные настройки (генерируемые на лету).
3. `/etc/systemd/network/` — настройки администратора (основное место работы).

Файлы обрабатываются в лексикографическом порядке (по имени файла).

### Типы конфигурационных файлов

| Расширение | Назначение |
| :--- | :--- |
| **`*.link`** | Настройка физических параметров (имена, MAC-адреса, MTU, SR-IOV). Применяется `udev`. |
| **`*.netdev`** | Создание виртуальных устройств (VLAN, Bridge, Bond, Tunnel, VRF). |
| **`*.network`** | Сетевая настройка интерфейсов (IP, маршруты, DNS, DHCP, PBR). |

### Приоритеты и Drop-ins

Для изменения существующей конфигурации рекомендуется использовать drop-in файлы. Например, для дополнения файла `20-wired.network` создайте директорию `20-wired.network.d/` и поместите туда файл `extra.conf`.

## Практические сценарии

### 1. Фиксация имени и параметры физического уровня

Файлы `.link` позволяют задать предсказуемые имена интерфейсам на основе их характеристик.

```ini
# /etc/systemd/network/10-wan.link
[Match]
MACAddress=00:a1:b2:c3:d4:e5

[Link]
Name=wan0
MTUBytes=1500
# v255+: Автоматическая настройка Link-Local только для прямых соединений
# ID_NET_AUTO_LINK_LOCAL_ONLY=1 (через udev)
```

### 2. Статическая настройка и управление состоянием Online

Для критических серверов важно явно указывать, что считается «рабочей сетью».

```ini
# /etc/systemd/network/20-wired.network
[Match]
Name=enp1s0

[Network]
Address=10.10.10.10/24
Gateway=10.10.10.1
DNS=8.8.8.8

# Управление состоянием online (v256+)
# routable — интерфейс считается online, когда есть маршрут
RequiredForOnline=routable
# IPv4 обязателен для статуса 'online'
RequiredFamilyForOnline=ipv4

[Address]
Address=10.10.10.20/24
Label=VIP1
```

### 3. Настройка моста и VLAN-транкинга

Создание моста с поддержкой VLAN (VLAN-aware bridge).

**/etc/systemd/network/25-br0.netdev:**
```ini
[NetDev]
Name=br0
Kind=bridge

[Bridge]
VLANFiltering=yes
STP=yes
```

**/etc/systemd/network/25-br0.network:**
```ini
[Match]
Name=br0

[Network]
Address=192.168.100.1/24

[VLAN]
StaticVLAN=10
StaticVLAN=20
```

### 4. Маршрутизация на основе политик (PBR) {#pbr}

Используется для управления трафиком через несколько каналов или таблиц маршрутизации.

```ini
# /etc/systemd/network/30-pbr.network
[Match]
Name=eth1

[Network]
Address=192.168.110.100/24

[Route]
Gateway=192.168.110.1
Table=101

[RoutingPolicyRule]
From=192.168.110.100
Table=101
Priority=1000
```

### 5. DHCP Relay (v255+)

Современный способ настройки ретранслятора DHCP.

```ini
# /etc/systemd/network/35-relay.network
[Match]
Name=eth2

[Network]
DHCPRelay=yes

[DHCPRelay]
ServerAddress=10.50.0.1
GatewayAddress=192.168.1.1
```

### 6. Интеграция с DNS-over-TLS

Настройка безопасного DNS на уровне конкретного интерфейса (требует `systemd-resolved`).

```ini
# /etc/systemd/network/20-secure.network
[Match]
Name=wan0

[Network]
DHCP=ipv4
DNS=1.1.1.1#cloudflare-dns.com
DNS=8.8.8.8#dns.google
DNSOverTLS=yes
DNSSEC=allow-downgrade
```

## Дополнительная информация

### Управление и диагностика через networkctl

Утилита `networkctl` — основной инструмент для работы с `systemd-networkd`.

| Команда | Описание |
| :--- | :--- |
| `networkctl list` | Общий список интерфейсов и их операционный статус. |
| `networkctl status [IFACE]` | Детальная информация о настройках, IP, DNS и файлах конфигурации. |
| `networkctl edit [IFACE]` | (v255+) Быстрое создание drop-in файла для интерфейса. |
| `networkctl reload` | Перезагрузка конфигурации без перезапуска всей службы. |
| `networkctl reconfigure [IFACE]` | Применение изменений к конкретному интерфейсу немедленно. |

### Отладка и логирование

Если интерфейс не получает настройки, проверьте логи:

```bash
# Просмотр логов в реальном времени
journalctl -u systemd-networkd -f

# Проверка того, какой файл применился к интерфейсу
networkctl status enp1s0 | grep "Network File"
# → Network File: /etc/systemd/network/20-wired.network
```

### См. также

- **[systemd-resolved: настройка DNS](../../Concepts/dns_client.md)** — глубокая интеграция резолвинга.
- **[Linux Bridge: концепции](../../Concepts/linux_bridge.md)** — подробнее о работе мостов в ядре.
- **[Policy-Based Routing (PBR)](../../Policy_Based_Routing/administration.md#systemd-networkd)** — настройка таблиц маршрутизации.
- **[Netplan](./ubuntu_netplan.md)** — высокоуровневая абстракция для Ubuntu, использующая networkd как бэкенд.
