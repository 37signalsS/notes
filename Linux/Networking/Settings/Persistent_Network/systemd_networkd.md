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

### 6.1. Туннели GRE и IPIP (Persistent)

**GRE (Generic Routing Encapsulation)** и **IPIP (IP-in-IP)** — протоколы туннелирования L3-в-L3. Используются для соединения удалённых сетей, обхода ограничений провайдера и построения VPN. В systemd-networkd настраиваются через `.netdev` и `.network` файлы.

**/etc/systemd/network/36-gre-tunnel.netdev (GRE-туннель):**
```ini
[NetDev]
Name=gre-tunnel0
Kind=gre

[Tunnel]
Local=198.51.100.1
Remote=203.0.113.5
TTL=64
```

**/etc/systemd/network/36-gre-tunnel.network:**
```ini
[Match]
Name=gre-tunnel0

[Network]
Address=10.100.0.1/30

[Route]
Gateway=10.100.0.2
```

**/etc/systemd/network/37-ipip-tunnel.netdev (IPIP-туннель):**
```ini
[NetDev]
Name=ipip-tunnel0
Kind=ipip

[Tunnel]
Local=198.51.100.1
Remote=203.0.113.5
```

**/etc/systemd/network/37-ipip-tunnel.network:**
```ini
[Match]
Name=ipip-tunnel0

[Network]
Address=10.200.0.1/30
```

**Обязательные sysctl-параметры для туннелей:**

```bash
# /etc/sysctl.d/99-tunnel.conf
net.ipv4.ip_forward = 1
net.ipv4.conf.default.rp_filter = 0
net.ipv4.conf.all.rp_filter = 0
```

**Проверка:**
```bash
networkctl status gre-tunnel0
ip tunnel show
ip route show | grep gre
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

### 10. Агрегация каналов (Bonding) с LACP

```ini
# /etc/systemd/network/10-bond0.netdev
[NetDev]
Name=bond0
Kind=bond

[Bond]
Mode=802.3ad
LACPTransmitRate=fast
TransmitHashPolicy=layer3+4

# /etc/systemd/network/20-bond0-slave.network
[Match]
Name=enp1s0 enp2s0

[Network]
Bond=bond0

# /etc/systemd/network/30-bond0.network
[Match]
Name=bond0

[Network]
Address=192.168.1.10/24
Gateway=192.168.1.1
```

**Проверка:**
```bash
networkctl status bond0
# → State: routable (configured)
# → Link File: /usr/lib/systemd/network/99-default.link
# → Network File: /etc/systemd/network/30-bond0.network
```

### 11. WireGuard

```ini
# /etc/systemd/network/20-wg0.netdev
[NetDev]
Name=wg0
Kind=wireguard

[WireGuard]
PrivateKey=<private_key>
ListenPort=51820

[WireGuardPeer]
PublicKey=<peer_public_key>
AllowedIPs=10.0.0.0/24
Endpoint=203.0.113.5:51820
PersistentKeepalive=25

# /etc/systemd/network/20-wg0.network
[Match]
Name=wg0

[Network]
Address=10.0.0.1/24
```

### 12. VRF (Virtual Routing and Forwarding)

```ini
# /etc/systemd/network/10-vrf10.netdev
[NetDev]
Name=vrf10
Kind=vrf

[VRF]
Table=10

# /etc/systemd/network/20-eth1.network
[Match]
Name=eth1

[Network]
VRF=vrf10
Address=192.168.10.10/24
```

### 13. MACVLAN и MACVTAP

```ini
# /etc/systemd/network/30-macvlan.netdev
[NetDev]
Name=macvlan0
Kind=macvlan

[MACVLAN]
Mode=vepa
Parent=eth0

# /etc/systemd/network/30-macvlan.network
[Match]
Name=macvlan0

[Network]
Address=192.168.50.10/24
```

### 14. Статический ARP и NDP

```ini
# /etc/systemd/network/40-static-neigh.network
[Match]
Name=enp1s0

[Network]
Address=10.10.10.10/24

[Neighbor]
Address=10.10.10.1
LLAddress=aa:bb:cc:dd:ee:ff

[IPv6Address]
Address=fd00::1/64
```

### 15. Управление MAC-адресом

```ini
# /etc/systemd/network/10-mac.link
[Match]
Name=enp1s0

[Link]
Name=lan0
MACAddress=00:11:22:33:44:55
MTUBytes=9000
```

### 16. MTU и offloading

```ini
# /etc/systemd/network/10-mtu.link
[Match]
Name=enp1s0

[Link]
MTUBytes=9000
```

Для управления offloading (TSO, GSO, GRO) используйте `ethtool` в диспетчерском скрипте или oneshot-юните:

```bash
# /etc/networkd-dispatcher/routable.d/50-ethtool
#!/bin/bash
IFACE=$1
ACTION=$2
ethtool -K $IFACE tso on gso on gro on
```

### 17. Продвинутый DHCP

```ini
# /etc/systemd/network/25-dhcp.network
[Match]
Name=enp1s0

[Network]
DHCP=yes

[DHCP]
ClientIdentifier=mac
VendorClassIdentifier=my-server
UseMTU=yes
RouteMetric=100
```

### 18. Опциональные интерфейсы

Интерфейсы, отсутствие которых не должно блокировать загрузку:

```ini
# /etc/systemd/network/20-optional.network
[Match]
Name=usb0

[Network]
DHCP=yes

[Link]
RequiredForOnline=no
```

## Валидация и откат изменений

### Обязательный бэкап

Перед любым изменением создайте резервную копию:

```bash
sudo cp -r /etc/systemd/network /root/networkd.bak.$(date +%F)
```

### Верификация конфигурации

`systemd-networkd` не имеет отдельной команды `generate`/`dry-run` как Netplan, но проверку можно выполнить через:

```bash
# Проверка статуса конкретного интерфейса
networkctl status enp1s0

# Проверка применённых файлов конфигурации
networkctl status enp1s0 | grep -E "Network File|Link File"

# Проверка синтаксиса INI-файлов
python3 -c "import configparser; c=configparser.ConfigParser(); c.read('/etc/systemd/network/20-wired.network')"

# Dry-run journalctl (просмотр логов без перезапуска)
journalctl -u systemd-networkd --since "5 minutes ago"
```

### Безопасное применение

```bash
# Перезагрузка конфигурации без перезапуска всей службы
networkctl reload

# Немедленное применение к конкретному интерфейсу
networkctl reconfigure enp1s0

# Полный перезапуск (при добавлении .netdev)
systemctl restart systemd-networkd
```

### Откат

При потере доступа к узлу после изменения конфигурации используйте:

- **Console/vKVM** для ручного восстановления конфигурации из бэкапа.
- **Аварийный shell** через systemd: `systemctl edit --full getty@tty1.service` и добавление `ExecStart=-/bin/bash`.
- **systemd-networkd-wait-online** с увеличенным тайм-аутом для доступа к удалённому узлу через резервный интерфейс.

## Жизненный цикл конфигурации и systemd-интеграция

### Порядок загрузки

1. Ядро определяет устройства → `systemd-udevd` применяет `.link`-файлы.
2. `systemd-networkd` загружает `.netdev`-файлы (виртуальные устройства).
3. Применяются `.network`-файлы к соответствующим интерфейсам.
4. `systemd-networkd-wait-online` ожидает готовности интерфейсов с `RequiredForOnline=yes`.

### network-online.target

Для критичных сервисов указывайте зависимости:

```ini
# /etc/systemd/system/myservice.service.d/override.conf
[Unit]
After=network-online.target
Wants=network-online.target
```

Тайм-аут ожидания по умолчанию — 2 минуты. Для изменения:

```ini
# /etc/systemd/system/systemd-networkd-wait-online.service.d/override.conf
[Service]
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --timeout=30
```

### RequiredForOnline

| Значение | Поведдение |
| :--- | :--- |
| `yes` | Интерфейс блокирует `network-online.target` до перехода в `routable` |
| `no` | Интерфейс игнорируется при ожидании сети |
| `ipv4` | Достаточно наличия IPv4-адреса |
| `ipv6` | Достаточно наличия IPv6-адреса |
| `routable` | Требуется шлюз по умолчанию (значение по умолчанию) |

## Автоматизация и IaC

### Соглашения по именованию файлов

Файлы обрабатываются в лексикографическом порядке. Рекомендуемая схема:

```
00-<layer>.link      # физические параметры
10-<name>.netdev     # виртуальные устройства
20-<name>.network    # сетевая конфигурация
30-<extra>.d/        # drop-in директории
```

### Ansible

```yaml
- name: Развёртывание systemd-networkd конфигурации
  copy:
    src: "{{ item }}"
    dest: "/etc/systemd/network/{{ item | basename }}"
    owner: root
    group: systemd-network
    mode: '0644'
  loop:
    - 10-wan.link
    - 20-bridge.netdev
    - 30-bridge.network
  notify: restart systemd-networkd
```

### Верификация в CI/CD

```bash
#!/bin/bash
set -euo pipefail
find /etc/systemd/network -type f \( -name '*.link' -o -name '*.netdev' -o -name '*.network' \) -print0 | \
  xargs -0 -I{} python3 -c "import configparser, sys; c=configparser.ConfigParser(strict=False); c.read('{}'); print('OK: {}')"
```

## Типичные ошибки и решения

### Drop-in не применяется

**Причина:** Неправильное имя директории или расположение.
**Решение:** Директория должна называться точно как основной файл с добавлением `.d/`. Например, для `20-wired.network` создайте `20-wired.network.d/`.

### Интерфейс не получает конфигурацию

**Причина:** Секция `[Match]` не соответствует интерфейсу.
**Диагностика:**
```bash
networkctl status enp1s0 | grep "Network File"
# → Network File: /usr/lib/systemd/network/99-default.link
# Если файл отсутствует, [Match] не сработал
```

### Конфликт менеджеров

**Причина:** Два менеджера управляют одним интерфейсом.
**Решение:** Отключите ненужный менеджер:
```bash
sudo systemctl disable --now NetworkManager
sudo systemctl enable --now systemd-networkd
```

### DNS не разрешает имена

**Причина:** `systemd-resolved` не настроен или `/etc/resolv.conf` указывает неверно.
**Диагностика:**
```bash
resolvectl status
ls -la /etc/resolv.conf
```
**Решение:** Убедитесь, что `systemd-networkd` передаёт DNS в `resolved` или настройте `DNS=systemd-resolved`.

## Углублённое устранение неполадок

### "Interface not found" в networkctl

**Диагностика:**
```bash
# Поиск устройства в sysfs
ls /sys/class/net/

# События udev
udevadm monitor --kernel --property --subsystem-match=net

# Проверка .link файлов
networkctl status enp1s0 | grep "Link File"
```

### "No carrier"

**Причина:** Кабель не подключен, порт отключен на коммутаторе или неверный duplex.
**Диагностика:**
```bash
ethtool enp1s0 | grep -E "Link detected|Speed|Duplex"
networkctl status enp1s0 | grep "Carrier"
```

### "Configured" но не "routable"

**Причина:** Нет шлюза по умолчанию или маршрут недоступен.
**Диагностика:**
```bash
ip route show default
networkctl status enp1s0 | grep "Gateway"
```

### DHCP не получен

**Диагностика:**
```bash
journalctl -u systemd-networkd | grep -i dhcp
networkctl status enp1s0 | grep "DHCP"
```

### netplan try freeze

Если `netplan try` зависает, проверьте:
```bash
# Отмена через Ctrl+C или ожидание тайм-аута (120s по умолчанию)
journalctl -u systemd-networkd -b
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
- **[Агрегация каналов (Bonding)](../../../../Networking/Concepts/link_aggregation.md)** — теория LACP и балансировки.
- **[Netplan](./ubuntu_netplan.md)** — высокоуровневая абстракция для Ubuntu, использующая networkd как бэкенд.
- **[Туннели IPIP и SIT](../../../../Networking/Tunnels/ipip_and_sit.md)** — теория IPIP-туннелей и инкапсуляции.
- **[GRE-туннели](../../../../Networking/Tunnels/gre/gre.md)** — GRE: архитектура и настройка.
- **[sysctl: сетевые параметры ядра](../sysctl_network.md)** — параметры ядра, критичные для туннелей и маршрутизации.
