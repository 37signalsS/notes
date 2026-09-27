# VRF (Virtual Routing and Forwarding) в Linux

## Определения

* **VRF (Virtual Routing and Forwarding)** — технология сетевой изоляции на уровне L3 (сетевой уровень OSI), позволяющая создавать несколько независимых таблиц маршрутизации (Routing Tables) внутри одного экземпляра операционной системы.
* **VRF-интерфейс (L3 Master Device)** — виртуальный сетевой интерфейс, выступающий в роли «контейнера» для других устройств. Он ассоциирует привязанные к нему интерфейсы с конкретной таблицей маршрутизации.
* **Slave-интерфейс** — физический или виртуальный сетевой интерфейс (например, `eth0`, `vlan10`), привязанный к VRF-мастеру. Трафик этого интерфейса обрабатывается исключительно в рамках FIB (Forwarding Information Base) данного VRF.

## Предусловия

Для использования VRF в Linux необходимо выполнение следующих требований:

### Версия ядра и системные требования

*   **Ядро Linux:** Минимальная версия **4.3** (базовая поддержка), рекомендуется **4.15+** (полная функциональность, включая VRF-aware conntrack).
*   **Утилиты:** Пакет `iproute2` (команда `ip`) версии 4.2+ для управления VRF через `ip link`.
*   **Архитектура:** Поддерживается на всех основных архитектурах (x86_64, ARM64, и др.).

### Проверка поддержки VRF

```bash
# Проверка версии ядра
uname -r
# → 5.15.0-76-generic

# Проверка наличия модуля ядра (обычно встроен)
modinfo vrf | grep filename
# → filename: /lib/modules/$(uname -r)/kernel/drivers/net/vrf.ko

# Проверка поддержки через ip link
ip link help vrf
# → Usage: ip link { add | set | ... } type vrf [TABLE <table>]
```

### Необходимые пакеты

*   **Debian/Ubuntu:** `iproute2` (устанавливается по умолчанию).
*   **RHEL/CentOS/Fedora:** `iproute` (устанавливается по умолчанию).
*   **Дополнительно:** `iptables`/`nftables` для настройки правил файрвола в контексте VRF.

## Основные концепции

### Механизм работы

В Linux VRF реализован через инфраструктуру **L3 Master Device**. Когда пакет поступает на slave-интерфейс или генерируется локально процессом, привязанным к VRF, ядро выполняет поиск в таблице маршрутизации (FIB lookup), связанной с этим VRF, игнорируя таблицу `main`.

1.  **Ingress:** Пакет помечается идентификатором VRF при поступлении на интерфейс.
2.  **Routing:** Ядро использует таблицу маршрутизации, указанную в параметрах VRF-интерфейса.
3.  **Egress:** Пакет покидает систему через slave-интерфейс, принадлежащий тому же VRF.

### Сравнение VRF и Network Namespaces (NetNS)

| Характеристика | VRF | Network Namespaces (NetNS) |
| :--- | :--- | :--- |
| **Уровень изоляции** | Только L3 (маршрутизация). | Полный стек (L2-L7, порты, Netfilter). |
| **Управление** | Единое пространство имен, все интерфейсы видны в `ip link`. | Раздельные пространства имен, полная изоляция видимости. |
| **Производительность** | Высокая (минимальные накладные расходы). | Чуть ниже из-за переключения контекста и veth-пар. |
| **Общие ресурсы** | Общие сокеты, память, файловая система. | Изолированные ресурсы. |
| **Основной кейс** | Мультитенантность маршрутизации, Management VRF. | Контейнеризация, полная изоляция сервисов. |

### Взаимодействие с Loopback

В контексте VRF интерфейс `lo` продолжает работать глобально, однако каждый VRF может иметь свои локальные маршруты. Для корректной работы локальных соединений внутри VRF (например, `ping` на локальный адрес интерфейса в VRF) ядро автоматически создает правила маршрутизации.

### Netfilter и Conntrack

По умолчанию `conntrack` в Linux не разделяет соединения по VRF. Если в разных VRF используются одинаковые IP-адреса (IP overlap), это может привести к коллизиям в таблице состояний.
*   Для решения этой проблемы используется **VRF-aware conntrack** (доступно в новых ядрах).
*   В `nftables` можно использовать селекторы `iifname` или `meta l3mdev` для разграничения правил фильтрации между доменами маршрутизации.

### Параметры ядра (sysctl)

Для корректной работы мульти-VRF среды необходимо настроить следующие параметры:

*   **`net.ipv4.tcp_l3mdev_accept = 1`** — позволяет TCP-сервисам (например, SSH) принимать входящие соединения из любого VRF, даже если они слушают на `0.0.0.0`.
*   **`net.ipv4.udp_l3mdev_accept = 1`** — аналогично для UDP-сервисов (DNS, SNMP).
*   **`net.ipv4.raw_l3mdev_accept = 1`** — разрешает работу ICMP (ping) и других raw-сокетов в контексте VRF.
*   **`net.ipv6.conf.all.keep_addr_on_down = 1`** — предотвращает удаление IPv6-адресов при кратковременном переходе slave-интерфейса в состояние DOWN во время привязки к VRF.

## Практические сценарии

### Создание и базовая настройка

```bash
# 1. Создать VRF-интерфейс, привязанный к таблице маршрутизации 100
sudo ip link add vrf-blue type vrf table 100

# 2. Активировать интерфейс
sudo ip link set vrf-blue up

# 3. Привязать физический интерфейс к VRF
# ВАЖНО: Привязка сбрасывает текущее состояние интерфейса и может удалить IP-адреса
sudo ip link set eth1 master vrf-blue
sudo ip link set eth1 up

# 4. Проверить конфигурацию
ip vrf show
# → Name              Table
# → -----------------------
# → vrf-blue            100
```

### Управление маршрутизацией

При использовании VRF таблицы маршрутизации полностью разделены.

```bash
# Добавить маршрут по умолчанию в таблицу VRF
sudo ip route add default via 192.168.1.1 dev eth1 vrf vrf-blue

# Просмотр таблицы маршрутизации конкретного VRF
ip route show vrf vrf-blue
# → default via 192.168.1.1 dev eth1

# Предотвращение утечки трафика (Leakage) в таблицу main
# Добавление unreachable маршрута с метрикой выше основной
sudo ip route add unreachable default table 100 metric 8192
```

### Настройка VRF с VLAN

Распространенный сценарий — изоляция трафика разных VLAN в разных VRF.

```bash
# Создание VLAN интерфейса
sudo ip link add link eth1 name eth1.10 type vlan id 10

# Привязка VLAN к VRF
sudo ip link set eth1.10 master vrf-blue
sudo ip link set eth1.10 up

# Назначение IP-адреса
sudo ip addr add 10.0.0.1/24 dev eth1.10
```

### Запуск приложений в VRF

1.  **Неадаптированные приложения:** Используйте `ip vrf exec`. Это помещает процесс в `cgroup`, ассоциированную с VRF.
    ```bash
    # Запуск curl через конкретный VRF
    ip vrf exec vrf-blue curl icanhazip.com
    ```
2.  **VRF-aware приложения:** Современное ПО (FRRouting, Bird, Strongswan, sshd) может самостоятельно привязываться к VRF через опции конфигурации или `setsockopt(SO_BINDTODEVICE)`.

### Постоянная конфигурация

Методы сохранения настроек после перезагрузки:

#### Netplan (Ubuntu 18.04+)

```yaml
# /etc/netplan/01-vrf.yaml
network:
  version: 2
  renderer: networkd
  vrfs:
    vrf-blue:
      table: 100
      interfaces:
        - eth1
      routes:
        - to: default
          via: 192.168.1.1
      routing-policy:
        - from: 192.168.1.0/24
          table: 100
          priority: 100
```

Применение: `sudo netplan apply`

#### NetworkManager (RHEL/CentOS/Fedora)

```bash
# Создание VRF
sudo nmcli connection add type vrf ifname vrf-blue con-name vrf-blue table 100

# Привязка интерфейса к VRF
sudo nmcli connection modify 'eth1' connection.slave-type vrf connection.master vrf-blue

# Добавление маршрута
sudo nmcli connection modify vrf-blue +ipv4.routes "0.0.0.0/0 192.168.1.1"

# Активация
sudo nmcli connection up vrf-blue
```

#### systemd-networkd

```ini
# /etc/systemd/network/20-vrf-blue.netdev
[NetDev]
Name=vrf-blue
Kind=vrf

[VRF]
Table=100
```

```ini
# /etc/systemd/network/25-veth1.network
[Match]
Name=eth1

[Network]
VRF=vrf-blue
Address=192.168.1.10/24

[Route]
Gateway=192.168.1.1
Destination=0.0.0.0/0
```

Включение: `sudo systemctl restart systemd-networkd`

#### ifupdown2 (Debian/Ubuntu legacy)

```ini
# /etc/network/interfaces
auto vrf-blue
iface vrf-blue inet manual
    vrf-table 100

auto eth1
iface eth1 inet static
    address 192.168.1.10/24
    vrf vrf-blue
```

Применение: `sudo ifreload -a`

#### Bash-скрипт для автозагрузки

```bash
#!/bin/bash
# /usr/local/bin/setup-vrf.sh

set -e

# Создание VRF
ip link add vrf-blue type vrf table 100
ip link set vrf-blue up

# Привязка интерфейса
ip link set eth1 master vrf-blue
ip addr add 192.168.1.10/24 dev eth1

# Маршрутизация
ip route add default via 192.168.1.1 vrf vrf-blue
ip route add unreachable default table 100 metric 8192

# Sysctl
sysctl -w net.ipv4.tcp_l3mdev_accept=1
sysctl -w net.ipv4.udp_l3mdev_accept=1
```

Systemd-юнит для этого скрипта:
```ini
# /etc/systemd/system/vrf-setup.service
[Unit]
Description=VRF Setup
After=network-pre.target
Before=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/setup-vrf.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

## Диагностика

### Проверка конфигурации VRF

```bash
# Просмотр всех VRF и их таблиц маршрутизации
ip vrf show
# → Name              Table
# → -----------------------
# → vrf-blue            100
# → vrf-red             200

# Просмотр детальной информации о VRF
ip -d link show vrf-blue
# → vrf-blue: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 65536 qdisc noqueue state UP ...
# →     vrf table 100

# Просмотр всех интерфейсов, привязанных к VRF
ip link show master vrf-blue
# → 3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
```

### Проверка маршрутизации

```bash
# Просмотр таблицы маршрутизации конкретного VRF
ip route show vrf vrf-blue
# → default via 192.168.1.1 dev eth1

# Просмотр всех таблиц маршрутизации (включая VRF)
ip route show table all | grep -A 5 "vrf\|table 100"

# Проверка маршрута для конкретного IP внутри VRF
ip route get 8.8.8.8 vrf vrf-blue
# → 8.8.8.8 via 192.168.1.1 dev eth1 vrf vrf-blue table 100 src 10.0.0.1 uid 0

# Проверка правил маршрутизации для VRF
ip rule show vrf vrf-blue
# → 0:	from all l3mdev vrf-blue
```

### Проверка сетевых соединений

```bash
# Поиск активных сокетов в контексте VRF
ss -ntlp
# → Local Address:Port ... Device
# → 0.0.0.0:22            ... vrf-blue

# Просмотр соединений в конкретном VRF
ss -tnp vrf vrf-blue

# Проверка прослушивания портов в VRF
ss -tlnp | grep vrf-blue
```

### Анализ трафика

```bash
# Захват трафика на slave-интерфейсе (сырой трафик до маршрутизации)
sudo tcpdump -i eth1 -n -v

# Захват трафика на VRF-мастере (трафик после L3-обработки)
sudo tcpdump -i vrf-blue -n -v

# Захват трафика с фильтрацией по VRF (через interface)
sudo tcpdump -i eth1 -n "vrf vrf-blue"

# Анализ трафика с выводом имени VRF
sudo tcpdump -i any -n -v | grep -i vrf
```

### Мониторинг состояния VRF

```bash
# Просмотр статистики интерфейса в контексте VRF
ip -s link show dev eth1 master vrf-blue

# Просмотр счётчиков пакетов для VRF
cat /proc/net/vrf_stats
# → Name              RxBytes  RxPackets  TxBytes  TxPackets
# → vrf-blue          1234567  12345      7654321  76543

# Мониторинг в реальном времени
watch -n 1 'ip -s link show dev eth1 master vrf-blue'
```

## Устранение неполадок (Troubleshooting)

### Типичные ошибки и их решения

#### 1. Интерфейс не привязывается к VRF

**Симптом:** Команда `ip link set eth1 master vrf-blue` завершается ошибкой.

**Причины и решения:**
```bash
# Проверка существования VRF
ip link show type vrf
# → vrf-blue: <BROADCAST,MULTICAST,UP,LOWER_UP> ...

# Проверка, не привязан ли интерфейс к другому VRF или bridge
ip link show eth1 | grep master
# → master vrf-blue  (или master bridge0)

# Если интерфейс привязан к другому мастеру, сначала отвяжите
sudo ip link set eth1 nomaster
sudo ip link set eth1 master vrf-blue
```

#### 2. Трафик не маршрутизируется внутри VRF

**Симптом:** `ping` из VRF не работает, хотя интерфейс активен.

**Диагностика:**
```bash
# Проверка наличия маршрута по умолчанию в VRF
ip route show vrf vrf-blue | grep default
# → default via 192.168.1.1 dev eth1

# Если маршрута нет, добавьте
sudo ip route add default via 192.168.1.1 vrf vrf-blue

# Проверка правил маршрутизации
ip rule show | grep vrf-blue
# → 0:	from all l3mdev vrf-blue

# Если правило отсутствует, проверьте настройки sysctl
sysctl net.ipv4.tcp_l3mdev_accept
```

#### 3. Утечка трафика между VRF

**Симптом:** Трафик из одного VRF попадает в другой.

**Решение:**
```bash
# Добавление unreachable маршрута для предотвращения утечки
sudo ip route add unreachable default table 100 metric 8192
sudo ip route add unreachable default table 200 metric 8192

# Проверка таблицы маршрутизации
ip route show table 100
# → unreachable default metric 8192
```

#### 4. Приложение не видит VRF

**Симптом:** Приложение не использует таблицу маршрутизации VRF.

**Решения:**
```bash
# Вариант 1: Запуск через ip vrf exec
ip vrf exec vrf-blue /path/to/application

# Вариант 2: Для VRF-aware приложений - настройка в конфигурации
# Например, для FRRouting:
# router bgp 65000 vrf vrf-blue
#   bgp router-id 10.0.0.1

# Вариант 3: Использование cgroup v2
sudo mkdir -p /sys/fs/cgroup/vrf-blue
echo "VRF=vrf-blue" | sudo tee /sys/fs/cgroup/vrf-blue/cgroup.procs
```

#### 5. Conntrack не различает соединения из разных VRF

**Симптом:** При пересекающихся IP-адресах в разных VRF возникают коллизии в таблице состояний.

**Решение:**
```bash
# Включение VRF-aware conntrack (требуется ядро 4.15+)
sudo sysctl -w net.netfilter.nf_conntrack_vrf=1

# Использование conntrack zones в nftables
sudo nft add rule ip nat prerouting iifname "eth*" meta nftrace set 1
```

#### 6. IPv6-адреса удаляются при привязке к VRF

**Симптом:** При привязке интерфейса к VRF IPv6-адреса исчезают.

**Решение:**
```bash
# Включение сохранения IPv6-адресов
sudo sysctl -w net.ipv6.conf.all.keep_addr_on_down=1
sudo sysctl -w net.ipv6.conf.default.keep_addr_on_down=1
```

### Логирование и аудит

```bash
# Включение логирования изменений в VRF
sudo sysctl -w net.core.message_cost=5

# Просмотр логов ядра, связанных с VRF
dmesg | grep -i vrf
journalctl -k | grep -i vrf

# Аудит правил iptables/nftables для VRF
sudo iptables -L -v -n | grep -i vrf
sudo nft list ruleset | grep -i vrf
```

## Лучшие практики (Best Practices)

### Проектирование VRF-инфраструктуры

1.  **Именование VRF:** Используйте осмысленные, консистентные имена (например, `vrf-mgmt`, `vrf-prod`, `vrf-dev`). ИзJKLMNOPSlug hạn chế кириллицу и специальные символы.
2.  **Таблицы маршрутизации:** Выделяйте уникальные ID таблиц для каждого VRF. Рекомендуется использовать диапазоны (100-199 для production, 200-299 для development).
3.  **Документация:** Ведите реестр VRF с указанием назначения, таблицы маршрутизации, привязанных интерфейсов и ответственных.

### Безопасность

1.  **Изоляция Management VRF:** Всегда выделяйте отдельный VRF для управления сетевыми устройствами (`vrf-mgmt`).
2.  **Защита от утечки:** Всегда добавляйте `unreachable` маршруты для предотвращения непреднамеренной маршрутизации между VRF.
3.  **Файрвол:** Настройте правила `iptables`/`nftables` с привязкой к VRF для контроля меж-VRF трафика.

### Производительность

1.  **Минимизация переключений:** Старайтесь не создавать избыточные VRF для каждого сервиса. Оптимально 2-5 VRF на хост.
2.  **Мониторинг:** Регулярно отслеживайте статистику VRF через `/proc/net/vrf_stats`.
3.  **Conntrack:** При большом количестве соединений в VRF настройте `nf_conntrack_max` и `nf_conntrack_buckets`.

### Совместимость

1.  **Ядро:** Используйте LTS-версии ядра (5.10, 5.15, 6.1) для стабильности.
2.  **Docker/Kubernetes:** VRF совместим с контейнерными средами, но требует дополнительной настройки сети.
3.  **Сетевые протоколы:** Убедитесь, что BGP/OSPF daemon поддерживают VRF-aware режим.

## Очистка и удаление (Cleanup)

### Безопасное удаление VRF

```bash
# 1. Отключение всех интерфейсов от VRF
sudo ip link set eth1 nomaster
sudo ip link set eth2 nomaster

# 2. Удаление VRF
sudo ip link del vrf-blue

# 3. Проверка удаления
ip link show type vrf
# → (пустой вывод)

# 4. Очистка таблицы маршрутизации (опционально)
sudo ip route flush table 100
```

### Полная очистка конфигурации

```bash
# Удаление всех VRF и связанной конфигурации
for vrf in $(ip -o link show type vrf | awk -F': ' '{print $2}'); do
    sudo ip link set nomaster $(ip link show master $vrf | awk -F': ' '{print $2}' | head -1) 2>/dev/null
    sudo ip link del $vrf
done

# Очистка sysctl параметров (если необходимо)
sudo sysctl -w net.ipv4.tcp_l3mdev_accept=0
sudo sysctl -w net.ipv4.udp_l3mdev_accept=0
sudo sysctl -w net.ipv4.raw_l3mdev_accept=0
```

### Восстановление после ошибок

```bash
# Если интерфейс "завис" в VRF
sudo ip link set eth1 nomaster
sudo ip link set eth1 down
sudo ip link set eth1 up

# Сброс всех правил маршрутизации (ОСТОРОЖНО!)
sudo ip rule flush
sudo ip route flush table main
sudo ip route flush table local
```

## Ограничения и особые случаи (Edge Cases)

### Технические ограничения

1.  **Количество VRF:** Теоретически не ограничено, но на практике рекомендуется не более 10-15 VRF на хост из-за накладных расходов на переключение контекстов.
2.  **Производительность:** Каждый VRF добавляет небольшие накладные расходы (дополнительные lookup в FIB). Влияние минимально для 2-5 VRF, но может быть значительным при большом количестве.
3.  **Совместимость с Netfilter:** VRF-aware conntrack доступен только в ядрах 4.15+. В старых версиях ядра conntrack не различает соединения из разных VRF.

### Проблемные сценарии

#### 1. Пересекающиеся IP-адреса

**Проблема:** Если в разных VRF используются одинаковые IP-адреса, возникают конфликты в таблице состояний.

**Решение:**
```bash
# Включение VRF-aware conntrack
sudo sysctl -w net.netfilter.nf_conntrack_vrf=1

# Использование conntrack zones
sudo nft add chain ip nat prerouting { type nat hook prerouting priority -100 \; }
sudo nft add rule ip nat prerouting iifname "eth*" meta nftrace set 1
```

#### 2. Loopback интерфейс

**Проблема:** Интерфейс `lo` работает глобально и не привязывается к VRF.

**Решение:** Используйте отдельные loopback интерфейсы для каждого VRF:
```bash
# Создание loopback для VRF
sudo ip link add loopback-blue type dummy
sudo ip link set loopback-blue master vrf-blue
sudo ip addr add 10.255.0.1/32 dev loopback-blue
```

#### 3. Мультикаст и broadcast

**Проблема:** multicast/broadcast трафик не изолируется между VRF по умолчанию.

**Решение:** Используйте `ip link set dev eth1 multicast off` или настройте `nftables` для фильтрации.

#### 4. DNS-резолвинг

**Проблема:** Системный DNS-резолвер работает глобально и не учитывает VRF.

**Решение:** Запускайте отдельные экземпляры `dnsmasq` или `unbound` для каждого VRF:
```bash
# Запуск dnsmasq в VRF
ip vrf exec vrf-blue dnsmasq --interface=eth1 --except-interface=lo
```

#### 5. Сетевые службы

**Проблема:** Многие системные службы (sshd, chrony, systemd-resolved) не поддерживают VRF-aware режим.

**Решение:** Используйте `ip vrf exec` для запуска или настройте службы через `systemd` с привязкой к VRF:
```bash
# Пример systemd-юнита для VRF
[Unit]
Description=My Service in VRF
After=network-online.target

[Service]
ExecStart=/usr/bin/ip vrf exec vrf-blue /usr/bin/my-service
Restart=always

[Install]
WantedBy=multi-user.target
```

### Известные проблемы

1.  **Docker и VRF:** Стандартный Docker bridge не поддерживает VRF. Используйте `macvlan` или `ipvlan` драйверы.
2.  **Kubernetes:** Поддержка VRF в CNI-плагинах ограничена. Рассмотрите использование `Multus` для мульти-интерфейсов.
3.  **VMware/VirtualBox:** VRF не влияет на виртуальные машины, так как они работают на L2 уровне.

### Альтернативы VRF

1.  **Network Namespaces:** Полная изоляция стека (L2-L7), но с большими накладными расходами.
2.  **Policy-Based Routing (PBR):** Гибкая маршрутизация на основе правил, но менее изолированная.
3.  **MPLS L3VPN:** Для масштабируемых решений в运营商 средах.

## Взаимодействие с протоколами маршрутизации

### BGP в VRF

Современные BGP-демоны (FRRouting, Bird2, OpenBGPD) поддерживают VRF-aware режим.

#### FRRouting (FRR)

```bash
# Конфигурация BGP в VRF
vtysh

# Включение VRF в FRR
router bgp 65000 vrf vrf-blue
  bgp router-id 10.0.0.1
  neighbor 192.168.1.2 remote-as 65001
  address-family ipv4 unicast
    network 10.0.0.0/24
    neighbor 192.168.1.2 activate
  exit-address-family
```

#### Bird2

```bash
# /etc/bird/bird.conf

router id 10.0.0.1;

protocol kernel {
  scan time 60;
  ipv4 {
    import filter where net ~ 10.0.0.0/24;
    export all;
  };
}

protocol bgp vrf_blue {
  vrf "vrf-blue";
  local 192.168.1.1 as 65000;
  neighbor 192.168.1.2 as 65001;
  ipv4 {
    import all;
    export all;
  };
}
```

### OSPF в VRF

#### FRRouting

```bash
# Конфигурация OSPF в VRF
vtysh

router ospf vrf vrf-blue
  ospf router-id 10.0.0.1
  network 192.168.1.0/24 area 0
  network 10.0.0.0/24 area 1
```

### Статическая маршрутизация в VRF

```bash
# Добавление статического маршрута в VRF
sudo ip route add 172.16.0.0/12 via 192.168.1.254 vrf vrf-blue

# Добавление маршрута с метрикой
sudo ip route add 10.10.0.0/16 via 192.168.1.253 vrf vrf-blue metric 100

# Просмотр маршрутов VRF
ip route show vrf vrf-blue
```

### MPLS и VRF

VRF широко используется в MPLS-сетях для реализации L3VPN сервисов.

```bash
# Включение MPLS на интерфейсе
sudo sysctl -w net.mpls.conf.eth0.input=1
sudo sysctl -w net.mpls.platform_labels=1048576

# Создание VRF для MPLS клиента
sudo ip link add vrf-customer1 type vrf table 1000
sudo ip link set vrf-customer1 up

# Привязка MPLS-интерфейса к VRF
sudo ip link set mpls0 master vrf-customer1
```

## Маршрутизация между VRF (Route Leaking)

**Route Leaking** — механизм обмена маршрутами между VRF, позволяющий обеспечить контролируемую связность между изолированными доменами маршрутизации.

### Сценарии использования

1.  **Shared Services VRF:** Общие сервисы (DNS, NTP, syslog) доступны из всех VRF.
2.  **Transit VRF:** Магистральный VRF для связи между production и development средами.
3.  **Management VRF:** Доступ к устройствам управления из рабочих VRF.

### Методы реализации

#### 1. Статический route leaking

```bash
# Из vrf-blue в vrf-red
sudo ip route add 192.168.2.0/24 via 192.168.1.2 vrf vrf-blue
sudo ip route add 192.168.1.0/24 via 192.168.2.1 vrf vrf-red
```

#### 2. Route leaking через промежуточный VRF (Transit)

```bash
# Создание transit VRF
sudo ip link add vrf-transit type vrf table 300
sudo ip link set vrf-transit up

# Привязка интерфейсов
sudo ip link set eth2 master vrf-transit
sudo ip addr add 10.255.0.1/30 dev eth2

# Маршруты в transit VRF
sudo ip route add 192.168.1.0/24 via 10.255.0.2 vrf vrf-transit
sudo ip route add 192.168.2.0/24 via 10.255.0.2 vrf vrf-transit

# Маршруты из production в transit
sudo ip route add 192.168.2.0/24 via 10.255.0.1 vrf vrf-blue

# Маршруты из development в transit
sudo ip route add 192.168.1.0/24 via 10.255.0.1 vrf vrf-red
```

#### 3. Route leaking через BGP

```bash
# FRRouting: объявление маршрутов из VRF через BGP
vtysh

router bgp 65000
  address-family ipv4 unicast
    # Экспорт маршрутов из vrf-blue в default VRF
    network 192.168.1.0/24
  exit-address-family

router bgp 65000 vrf vrf-blue
  address-family ipv4 unicast
    # Импорт маршрутов из default VRF в vrf-blue
    neighbor 192.168.1.254 remote-as 65000
  exit-address-family
```

#### 4. Route leaking через static routes с policy routing

```bash
# Создание policy для leaking
sudo ip rule add from 192.168.1.0/24 to 192.168.2.0/24 table 300
sudo ip rule add from 192.168.2.0/24 to 192.168.1.0/24 table 300

# Маршруты в transit таблицу
sudo ip route add 192.168.1.0/24 via 192.168.1.1 table 300
sudo ip route add 192.168.2.0/24 via 192.168.2.1 table 300
```

### Безопасность при route leaking

```bash
# Ограничение leaking только определенных подсетей
sudo ip route add 192.168.2.0/24 via 192.168.1.2 vrf vrf-blue
# Вместо 전체 таблицы - только конкретный префикс

# Фильтрация через nftables
sudo nft add rule ip filter forward iifname "vrf-blue" oifname "vrf-red" ip daddr 192.168.2.0/24 accept
sudo nft add rule ip filter forward iifname "vrf-blue" oifname "vrf-red" drop
```

### Диагностика route leaking

```bash
# Проверка маршрутов в transit VRF
ip route show vrf vrf-transit

# Проверка правил маршрутизации
ip rule show | grep -E "192.168.1|192.168.2"

# Трассировка маршрута
ip route get 192.168.2.100 vrf vrf-blue
ip route get 192.168.1.100 vrf vrf-red
```

## Мониторинг и логирование

### Сбор метрик VRF

#### Статистика ядра

```bash
# Просмотр статистики VRF
cat /proc/net/vrf_stats
# → Name              RxBytes  RxPackets  TxBytes  TxPackets
# → vrf-blue          1234567  12345      7654321  76543
# → vrf-red           9876543  98765      5432109  54321

# Детальная статистика по интерфейсу в VRF
ip -s -d link show dev eth1 master vrf-blue
```

#### Prometheus экспортеры

```bash
# Установка node_exporter с поддержкой VRF
sudo apt install prometheus-node-exporter

# Конфигурация для сбора метрик VRF
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'vrf_metrics'
    static_configs:
      - targets: ['localhost:9100']
    metrics_path: '/proc/net/vrf_stats'
```

#### SNMP мониторинг

```bash
# Включение SNMP агента для VRF
sudo apt install snmpd

# Конфигурация /etc/snmp/snmpd.conf
# view systemonly included .1.3.6.1.2.1.1
# view systemonly included .1.3.6.1.2.1.4.20
```

### Логирование событий VRF

#### Syslog

```bash
# Настройка логирования изменений VRF
sudo vim /etc/rsyslog.d/vrf.conf
# :programname, isequal, "ip" /var/log/vrf-changes.log

# Перезапуск rsyslog
sudo systemctl restart rsyslog
```

#### Auditd

```bash
# Добавление правил аудита для VRF
sudo auditctl -a always,exit -F arch=b64 -S setlink -S setaddr -F dir=/sys/class/net -F key=vrf_changes

# Просмотр аудит-логов
sudo ausearch -k vrf_changes
```

### Мониторинг в реальном времени

```bash
# Скрипт мониторинга VRF
#!/bin/bash
# /usr/local/bin/monitor-vrf.sh

while true; do
    echo "=== VRF Status $(date) ==="
    ip vrf show
    echo ""
    echo "=== VRF Stats ==="
    cat /proc/net/vrf_stats
    echo ""
    echo "=== Active Connections per VRF ==="
    for vrf in $(ip -o link show type vrf | awk -F': ' '{print $2}'); do
        echo "VRF: $vrf"
        ss -tnp "vrf $vrf" | wc -l
    done
    sleep 60
done
```

### Интеграция с системами мониторинга

#### Zabbix

```bash
# UserParameter для Zabbix
# /etc/zabbix/zabbix_agentd.d/vrf.conf
UserParameter=vrf.stats[*],cat /proc/net/vrf_stats | grep "$1" | awk '{print $$2}'
UserParameter=vrf.count,ip -o link show type vrf | wc -l
```

#### Grafana дашборды

```json
{
  "panels": [
    {
      "title": "VRF Traffic",
      "targets": [
        {
          "expr": "node_network_receive_bytes_total{device=~\"vrf.*\"}"
        }
      ]
    }
  ]
}
```

## Дополнительная информация

### Связанные темы

*   **[`ip link`](./Tools/iproute2/ip_link.md)** — управление сетевыми интерфейсами.
*   **[`ip route`](./Tools/iproute2/ip_route.md)** — расширенная настройка маршрутизации.
*   **[Маршрутизация по политикам (PBR)](./Policy_Based_Routing/index.md)** — использование `ip rule` и отличия от VRF.
*   **[Таблицы маршрутизации в Linux](../SystemAdministration/routing.md)** — общие принципы работы FIB.

### Полезные ссылки

*   [Kernel Documentation: VRF](https://www.kernel.org/doc/Documentation/networking/vrf.txt)
*   [Virtual Routing and Forwarding (VRF) — Virtualization Wiki](https://en.wikipedia.org/wiki/Virtual_routing_and_forwarding)
*   [Linux VRF Tutorial (ozlabs.org)](https://www.kernel.org/doc/html/latest/networking/vrf.html)
