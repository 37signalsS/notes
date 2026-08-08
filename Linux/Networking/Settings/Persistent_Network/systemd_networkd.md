# systemd-networkd

**systemd-networkd** — системная служба, входящая в состав системного менеджера systemd, предназначенная для управления сетевыми интерфейсами. Она предоставляет декларативный способ настройки сети через конфигурационные файлы и идеально подходит для серверов, контейнеров и минималистичных систем благодаря отсутствию внешних зависимостей и высокой производительности.

## Определения

- **systemd-networkd** — легковесный менеджер сети, работающий в пространстве пользователя и взаимодействующий с ядром через Netlink.
- **Декларативная конфигурация** — подход, при котором описывается конечное желаемое состояние системы, а не последовательность команд для его достижения.
- **Drop-in директории** — каталоги вида `*.d/`, позволяющие переопределять или дополнять настройки без изменения основных файлов.
- **RequiredForOnline** — параметр, определяющий, должен ли интерфейс быть успешно настроен для того, чтобы состояние сети считалось «online» (используется `systemd-networkd-wait-online`).
- **LLDP (Link Layer Discovery Protocol)** — протокол канального уровня, позволяющий сетевым устройствам анонсировать свою идентичность и характеристики в локальной сети. `systemd-networkd` поддерживает как получение, так и отправку LLDP-сообщений.
- **CDP (Cisco Discovery Protocol)** — проприетарный протокол Cisco, поддержку которого `systemd-networkd` обеспечивает в режиме приема для обнаружения соседнего оборудования.
- **DHCP Relay (DHCP-ретранслятор)** — служба, пересылающая DHCP-запросы между клиентами и серверами, находящимися в разных подсетях.

## Базовые концепции

Конфигурация `systemd-networkd` хранится в трех основных директориях (в порядке возрастания приоритета):
1. `/usr/lib/systemd/network/` — настройки от поставщика ОС (не изменять).
2. `/run/systemd/network/` — временные настройки (генерируемые на лету, например, через `cloud-init`).
3. `/etc/systemd/network/` — настройки администратора (основное место работы).

Файлы обрабатываются в лексикографическом порядке по имени файла, независимо от того, в какой из директорий они находятся.

### Типы конфигурационных файлов

| Расширение | Назначение | Ключевые секции |
| :--- | :--- | :--- |
| **`*.link`** | Настройка физических параметров. Применяется `udev` при обнаружении устройства. | `[Match]`, `[Link]` |
| **`*.netdev`** | Создание виртуальных устройств (VLAN, Bridge, Bond, Tunnel, VRF, VXLAN). | `[Match]`, `[NetDev]`, `[Tunnel]` |
| **`*.network`** | Сетевая настройка интерфейсов (IP, маршруты, DNS, DHCP, PBR). | `[Match]`, `[Network]`, `[Address]`, `[Route]` |

### Приоритеты и Drop-ins

Для изменения существующей конфигурации рекомендуется использовать drop-in файлы. Например, для дополнения файла `20-wired.network` создайте директорию `20-wired.network.d/` и поместите туда файл `extra.conf`. Это позволяет сохранять чистоту основной конфигурации.

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
```

### 2. Секция [Match]: Критерии сопоставления

Секция `[Match]` определяет, к каким интерфейсам будет применена конфигурация. Если указано несколько условий, они должны выполняться одновременно (логическое И).

```ini
[Match]
# Сопоставление по имени (поддерживает маски *, ?, [])
Name=enp*
# Сопоставление по MAC-адресу
MACAddress=52:54:00:12:34:56
# Сопоставление по драйверу устройства
Driver=virtio_net
# Сопоставление по архитектуре системы
Architecture=x86-64
# Сопоставление по параметру командной строки ядра
KernelCommandLine=net.ifnames=1
```

### 3. Статическая настройка и управление состоянием Online

Для критических серверов важно явно указывать критерии готовности сети.

```ini
# /etc/systemd/network/20-wired.network
[Match]
Name=enp1s0

[Network]
Address=10.10.10.10/24
Gateway=10.10.10.1
DNS=8.8.8.8
# Включение LLDP для обнаружения оборудования
LLDP=yes
EmitLLDP=customer-bridge

# Управление состоянием online (v256+)
RequiredForOnline=routable
RequiredFamilyForOnline=ipv4

[Address]
Address=10.10.10.20/24
Label=VIP1
```

### 4. Настройка IPv6 (SLAAC, DHCPv6 и Privacy Extensions)

```ini
# /etc/systemd/network/25-ipv6.network
[Match]
Name=enp2s0

[Network]
IPv6AcceptRA=yes
DHCP=ipv6

[IPv6AcceptRA]
UsePrivacyExtensions=yes
Token=::1

[DHCPv6]
WithoutRA=no
```

### 5. Создание моста и VLAN-транкинга

**/etc/systemd/network/30-br0.netdev:**
```ini
[NetDev]
Name=br0
Kind=bridge

[Bridge]
VLANFiltering=yes
STP=yes
```

**/etc/systemd/network/30-br0.network:**
```ini
[Match]
Name=br0

[Network]
Address=192.168.100.1/24

[VLAN]
StaticVLAN=10
StaticVLAN=20
```

### 6. Виртуализация: VXLAN и MACVLAN

**/etc/systemd/network/35-vxlan.netdev:**
```ini
[NetDev]
Name=vx10
Kind=vxlan

[VXLAN]
VNI=10
Remote=203.0.113.5
Local=198.51.100.2
DestinationPort=4789
```

### 7. Маршрутизация на основе политик (PBR)

```ini
# /etc/systemd/network/45-pbr.network
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

### 8. DHCP Relay (v255+)

```ini
# /etc/systemd/network/50-relay.network
[Match]
Name=eth2

[Network]
DHCPRelay=yes

[DHCPRelay]
ServerAddress=10.50.0.1
GatewayAddress=192.168.1.1
```

### 9. Интеграция с DNS-over-TLS и безопасный DNS

Настройка безопасного DNS на уровне конкретного интерфейса (требует `systemd-resolved`).

```ini
# /etc/systemd/network/55-secure.network
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
