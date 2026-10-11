# Сеть: продвинутые сценарии Unikernel

**Актуально для:** Unikraft v0.21.0, KraftKit v0.12.15, Nanos (актуальная ветка), MirageOS v4.11.x, OSv v0.57.0; примеры для on-premise развёртываний

## Определения

**Продвинутые сетевые сценарии для юникернелов** — это конфигурации, выходящие за рамки базового TAP/bridge/NAT, необходимые для production-сред: сегментация трафика (VLAN), отказоустойчивость канала (bonding/LACP), современный firewall (nftables), автоматическая адресация (DHCP) и синхронизация времени (NTP).

Базовая информация — в [Обзоре Unikernel](./unikernel_overview.md).

## Предварительные требования

### Аппаратные требования (хост)

- **NIC:** Минимум 2 NIC для production (bonding). Поддержка VLAN (802.1Q) и LACP в BIOS/UEFI.
- **CPU:** Intel VT-x или AMD-V для KVM.
- **RAM:** 4 ГБ для хоста + 64–256 МБ на каждый юникернел.

### Программные требования (on-premise, Linux хост)

| Компонент | Требование | Проверка |
| :--- | :--- | :--- |
| **Ядро Linux** | 5.10+ (для VLAN-aware bridge, eBPF) | `uname -r` |
| **iproute2** | v5.10+ | `ip -V` |
| **bridge-utils** | Установлен | `bridge -V` |
| **nftables** | v1.0+ | `nft --version` |
| **dnsmasq** | v2.80+ | `dnsmasq --version` |
| **chrony** | v4.0+ | `chronyd -v` |
| **KVM/QEMU** | Установлен | `kvm-ok` / `lsmod \| grep kvm` |
| **Модули ядра** | ` bonding`, `8021q`, `nf_tables`, `virtio_net` | `lsmod \| grep -E 'bonding\|8021q\|nf_tables'` |

### Инициализация хоста

```bash
# Загрузка модулей
sudo modprobe bonding
sudo modprobe 8021q
sudo modprobe nf_tables

# Включение IP forwarding
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.d/99-ipforward.conf
```

## Основные концепции

### Топологии сети

```
┌──────────────────────────────────────────────────────┐
│  Хост (Linux)                                        │
│                                                      │
│  ┌─────────────┐     ┌──────────────┐               │
│  │   bond0     │─────│    br0       │─── eth0 ──→    │
│  │  (LACP)     │     │ (VLAN-aware) │    (Интернет)  │
│  └──────┬──────┘     └──────────────┘               │
│         │                                            │
│  ┌──────┴──────────────────────────────────────┐    │
│  │  TAP-интерфейсы юникернелов                │    │
│  │  tap0 → VLAN 10 (DNS)                      │    │
│  │  tap1 → VLAN 20 (Proxy)                    │    │
│  │  tap2 → VLAN 30 (Firewall)                  │    │
│  └─────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### Слои сети

| Слой | Технология | Назначение |
| :--- | :--- | :--- |
| **Физический** | bonding, LACP | Агрегация каналов, отказоустойчивость |
| **Канальный** | VLAN (802.1Q) | Сегментация трафика |
| **Сетевой** | маршрутизация, NAT | Маршрутизация между подсетями |
| **Транспортный** | TCP/UDP | Порты, соединения |
| **Прикладной** | DHCP, NTP, DNS | Автоматическая конфигурация |

## Практические сценарии

### 1. VLAN (IEEE 802.1Q)

#### VLAN-aware мост

```bash
# Создание VLAN-aware моста
sudo ip link add name br0 type bridge
sudo ip link set br0 type bridge vlan_filtering 1

# Назначение PVID порту
sudo bridge vlan add dev eno1 pvid untagged 10
sudo bridge vlan add dev eno1 vid 10

# Создание TAP-интерфейса для юникернела
sudo ip tuntap add tap0 mode tap
sudo ip link set tap0 master br0
sudo ip link set tap0 type bridge_slave vlan_id 10
sudo ip link set tap0 up

# Настройка IP на мосте
sudo ip addr add 10.0.10.1/24 dev br0
sudo ip link set br0 up
```

#### VLAN-под-интерфейсы

```bash
# Традиционный способ: VLAN на интерфейсе
sudo ip link add link eno1 name eno1.10 type vlan id 10
sudo ip addr add 10.0.10.1/24 dev eno1.10
sudo ip link set eno1.10 up

# Мост поверх VLAN
sudo ip link add name br10 type bridge
sudo ip link set br10 up
sudo ip link add link eno1.10 master br10 type bridge_slave
```

#### QinQ (802.1ad) для сервис-провайдеров

```bash
# Внешний тег (S-VLAN) + внутренний (C-VLAN)
sudo ip link add link eno1 name eno1.100 type vlan proto 802.1ad id 100
sudo ip link add link eno1.100 name eno1.100.200 type vlan id 200
sudo ip addr add 10.0.20.1/24 dev eno1.100.200
sudo ip link set eno1.100.200 up
```

**Примечание:** QinQ добавляет 8 байт overhead (4 байта S-VLAN + 4 байта C-VLAN). Убедитесь что MTU на всех интерфейсах позволяет передавать увеличенные кадры (стандартный Ethernet MTU 1500 может быть недостаточным при использовании туннелей).

### 2. Bonding (LACP)

```bash
# Создание LACP-бонда
sudo ip link add bond0 type bond mode 802.3ad miimon 100

# Добавление интерфейсов
sudo ip link set eno1 master bond0
sudo ip link set eno2 master bond0
sudo ip link set eno1 up
sudo ip link set eno2 up

# Настройка bonding
sudo ip link set bond0 type bond lacp_rate 1
sudo ip link set bond0 up

# Проверка
cat /proc/net/bonding/bond0
# → Bonding Mode: IEEE 802.3ad Dynamic link aggregation
```

#### Bonding для VM с юникернелами

```bash
# Мост поверх бонда
sudo ip link add name br0 type bridge
sudo ip link set br0 up
sudo ip link set bond0 master br0

# Создание TAP-интерфейсов
sudo ip tuntap add tap0 mode tap
sudo ip tuntap add tap1 mode tap
sudo ip link set tap0 master br0
sudo ip link set tap1 master br0
sudo ip link set tap0 up
sudo ip link set tap1 up
```

**Варианты балансировки:**
- `balance-rr` (mode 0) — round-robin, не требует поддержки LACP на коммутаторе, но может привести к out-of-order доставке.
- `active-backup` (mode 1) — один активный, один резервный. Просто, но не агрегирует bandwidth.
- `802.3ad` (mode 4) — требует LACP на коммутаторе, агрегирует bandwidth, поддерживает балансировку по MAC/IP.

#### Bonding + xmit_hash_policy

```bash
# Хэширование по L3+L4 для лучшей балансировки
sudo ip link set bond0 type bond xmit_hash_policy layer3+4
```

### 3. MTU и MSS для юникернелов

Virtio-net добавляет overhead: заголовок virtio (12 байт) + возможный tso/gso offload. При стандартном MTU=1500 на TAP-интерфейсе реальный полезный payload может быть меньше, что приводит к фрагментации.

```bash
# Рекомендуемый MTU для TAP-интерфейса с учетом overhead
sudo ip link set tap0 mtu 1450

# Или MSS clamping на bridge (если MTU host-side = 1500)
sudo iptables -t mangle -A FORWARD -o tap0 -p tcp --tcp-flags SYN,RST SYN \
  -j TCPMSS --clamp-mss-to-pmtu
```

**Проверка:**
```bash
# PMTUD diagnostic
ping -M do -s 1472 10.0.10.2
# → 1472 + 28 (IP+ICMP header) = 1500, должно проходить

# Текущий MSS в соединениях
ss -ti | grep mss
```

### 4. nftables

#### Базовый firewall

```bash
# Создание таблицы
sudo nft add table inet unikernel

# Создание цепочки
sudo nft add chain inet unikernel forward { type filter hook forward priority 0; policy drop; }

# Правила для юникернела 10.0.10.2
sudo nft add rule inet unikernel forward ip saddr 10.0.10.2 ip daddr 10.0.10.0/24 accept
sudo nft add rule inet unikernel forward ip saddr 10.0.10.2 tcp dport 53 accept
sudo nft add rule inet unikernel forward ip saddr 10.0.10.2 udp dport 53 accept
sudo nft add rule inet unikernel forward ip saddr 10.0.10.2 tcp dport 80 accept
sudo nft add rule inet unikernel forward ip saddr 10.0.10.2 tcp dport 443 accept

# Логирование отказов
sudo nft add rule inet unikernel forward ip saddr 10.0.10.2 log prefix "UNIKERNEL-DROP: "

# Сохранение
sudo nft list ruleset > /etc/nftables.conf
sudo systemctl enable --now nftables
```

#### Rate limiting

```bash
# Ограничение SYN-пакетов
sudo nft add rule inet unikernel forward tcp flags syn limit rate 10/second accept

# Ограничение соединений
sudo nft add rule inet unikernel forward ct state new limit rate 50/second accept
```

**Примечание:** В `forward` chain nftables работает после принятия решения о маршрутизации. Если юникернел и хост в одной подсети — пакеты проходят через `forward`. Для inbound-трафика на сам хост используйте `input` chain.

### 5. DHCP

#### dnsmasq для локальных юникернелов

```bash
# Установка
sudo apt install dnsmasq

# Конфигурация
cat <<EOF > /etc/dnsmasq.d/unikernels.conf
interface=tap0
dhcp-range=10.0.10.10,10.0.10.100,12h
dhcp-option=option:router,10.0.10.1
dhcp-option=option:dns-server,10.0.10.1
dhcp-host=00:11:22:33:44:55,unikernel-dns,10.0.10.2,infinite
EOF

# Запуск
sudo systemctl restart dnsmasq

# Проверка
sudo systemctl status dnsmasq
# → active (running)
```

**Статические резервации (DHCP reservations):** Привязывайте MAC-адрес к фиксированному IP. Это гарантирует что юникернел всегда получает один и тот же адрес, что упрощает firewall правила и мониторинг.

### 6. NTP

#### chrony на хосте

```bash
# Установка
sudo apt install chrony

# Конфигурация
cat <<EOF > /etc/chrony/chrony.conf
pool ntp.example.com iburst
driftfile /var/lib/chrony/drift
makestep 1.0 3
rtcsync
allow 10.0.10.0/24
EOF

# Запуск
sudo systemctl restart chronyd

# Проверка
chronyc tracking
# → Reference ID: ...
# → System time: ...
```

#### NTP внутри юникернела (через libc)

```c
// Пример: NTP-клиент в C
#include <time.h>
#include <stdio.h>

int main() {
  time_t now = time(NULL);
  printf("Current time: %s", ctime(&now));
  return 0;
}
```

**Важно для юникернелов:** В большинстве случаев NTP-синхронизация должна происходить на хосте, а не внутри юникернела. Юникернел не имеет постоянного состояния и не может хранить driftfile. Если приложение требует точное время — используйтe `chronyc` на хосте и передавайте время через RPC или читайте `/proc/driver/rtc` если гипервизор пробросил часы.

### 7. Маршрутизация

```bash
# Включение IP forwarding
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.d/99-ipforward.conf

# Маршрут по умолчанию
sudo ip route add default via 10.0.10.1 dev br0

# Статическая маршрут
sudo ip route add 10.0.20.0/24 via 10.0.10.254 dev br0
```

#### Policy-Based Routing для многопоточных юникернелов

```bash
# Таблица 100 для трафика через bond0
echo "100 unikernel-out" | sudo tee -a /etc/iproute2/rt_tables

# Маршрут по умолчанию в таблице 100
sudo ip route add default via 10.0.10.1 dev bond0 table unikernel-out

# Правило: трафик от 10.0.10.2 использует таблицу 100
sudo ip rule add from 10.0.10.2 table unikernel-out
```

### 8. QoS (Quality of Service)

```bash
# Marking трафика юникернелов
sudo iptables -t mangle -A FORWARD -s 10.0.10.2 -j MARK --set-mark 10

# Priority queuing
sudo tc qdisc add dev bond0 root handle 1: htb default 30
sudo tc class add dev bond0 parent 1: classid 1:10 htb rate 100mbit ceil 100mbit prio 0
sudo tc class add dev bond0 parent 1: classid 1:20 htb rate 50mbit ceil 100mbit prio 1
sudo tc class add dev bond0 parent 1: classid 1:30 htb rate 10mbit ceil 50mbit prio 2

# Фильтр по mark
sudo tc filter add dev bond0 protocol ip parent 1:0 prio 1 handle 10 fw flowid 1:10
```

#### fq_codel для снижения буферблотинга

```bash
# fq_codel на интерфейсе хоста (рекомендуется для production)
sudo tc qdisc replace dev bond0 root fq_codel limit 1000
```

**DSCP marking для юникернелов:** Если юникернел генерирует трафик с разными приоритетами (например, DNS — высокий приоритет, бэкап — низкий), используйте DSCP-маркировку на выходе TAP-интерфейса.

```bash
# Mark DNS traffic with DSCP 46 (EF)
sudo nft add rule inet unikernel forward ip saddr 10.0.10.2 udp dport 53 ip dscp set 46
```

## Валидация и проверка работоспособности

- **VLAN:** `bridge vlan show dev br0` — VLAN фильтрация активна.
- **Bonding:** `cat /proc/net/bonding/bond0` — LACP активен.
- **nftables:** `nft list ruleset` — правила применены.
- **DHCP:** `sudo systemctl status dnsmasq`, `dig @10.0.10.1 unikernel-dns.local`.
- **NTP:** `chronyc tracking`, `timedatectl show`.
- **Маршрутизация:** `ip route show`, `traceroute 10.0.20.1`.
- **Связность:** `ping`, `nmap`, `curl` с хоста.

### Проверка end-to-end

```bash
# 1. Проверить что TAP-интерфейс поднят
ip link show tap0
# → tap0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 qdisc noqueue master br0 state DOWN

# 2. Проверить VLAN tagging
bridge vlan show dev tap0
# → tap0  10   PVID Egress Untagged

# 3. Проверить bonding
cat /proc/net/bonding/bond0 | grep -E 'MII|LACP|Speed'
# → MII Status: up, LACP Aggregator: 1

# 4. Проверить nftables
nft list ruleset | grep UNIKERNEL
# → правила присутствуют

# 5. Проверить DHCP
dig @10.0.10.1 unikernel-dns.local +short
# → 10.0.10.2

# 6. Проверить NTP
chronyc tracking | grep System
# → System time     : 0.000000001 seconds fast of NTP time

# 7. Проверить QoS
tc -s class show dev bond0 class 1:10
# → Sent 123456 bytes 1234 pkt
```

## Лучшие практики

### Проектирование сети

- **Один мост на зону:** Используйте отдельный мост для каждой VLAN/зоны (например, `br10` для VLAN 10, `br20` для VLAN 20). Это упрощает отладку и предотвращает утечки трафика между зонами.
- **VLAN-aware мост вместо множества сабинтерфейсов:** При >3 VLAN используйте VLAN-aware мост (`vlan_filtering 1`) вместо создания `eno1.10`, `eno1.20` и отдельных мостов. Это уменьшает количество устройств и упрощает управление.
- **Bonding для redundancy, не для скорости:** В большинстве production-сценариев с юникернелами важнее redundancy, чем агрегация bandwidth. Используйте `active-backup` если коммутатор не поддерживает LACP.
- **Изолируйте management-сеть:** Разместите управление хоста (SSH, IPMI, API) в отдельном VLAN, недоступном из сети юникернелов.

### Безопасность

- **Default-drop в nftables:** Цепочка `forward` должна иметь политику `drop` по умолчанию. Разрешайте только необходимые порты для каждого юникернела.
- **Контроль broadcast/multicast:** Юникернелы обычно не нуждаются в broadcast-трафике. Используйте `nft add rule inet unikernel forward ip daddr 255.255.255.255/32 drop` для блокировки широковещания.
- **DHCP Snooping:** Если используете ненадежный DHCP-сервер (например, dnsmasq в тестовой среде), включите DHCP Snooping на коммутаторе для предотвращения rogue-серверов.
- **NTP аутентификация:** В production-среде настройте NTS (Network Time Security) или ключи chrony для предотвращения NTP-spoofing.

### Производительность и стабильность

- **MTU на TAP-интерфейсах:** Устанавливайте MTU=1450 на TAP-интерфейсах, чтобы учесть overhead virtio-net (12 байт) и избежать фрагментации. Стандартный MTU=1500 может работать, но при включенном TSO/GSO на хосте полезный payload уменьшается.
- **Scrape interval для мониторинга сети:** 15–30 секунд для базового мониторинга, 5 секунд для критичных сервисов. Используйте `bpftrace` для детального анализа без остановки трафика.
- **Ротация логов DHCP/NTP:** Настройте logrotate для `/var/log/dnsmasq.log` и `/var/log/chrony/*.log`. Логи nftables хранятся в journald — настройте `SystemMaxUse=200M` в `/etc/systemd/journald.conf`.
- **Документирование конфигурации:** Храните все правила nftables, конфигурации dnsmasq и chrony в Git. Используйте `nft list ruleset > /etc/nftables.conf` и коммитьте файл.

### Отказоустойчивость

- **Graceful failover для DHCP:** Настройте secondary DHCP-сервер (secondary dnsmasq или Kea HA) с 80/20 разделением пула адресов.
- **NTP fallback:** Настройте минимум 3 NTP-сервера в chrony. Используйте `minsources 2` чтобы chrony не принимал решение на основе одного источника.
- **Мониторинг bonding:** Добавьте в Prometheus правила для отслеживания состояния LACP: `node_bonding_lacp_status` (1 = active, 0 = inactive).

## Граничные случаи

### MTU и фрагментация

- **Virtio-net overhead:** Стандартный MTU TAP-интерфейса = 1500, но virtio-net добавляет 12 байт заголовка. При включенном TSO/GSO на хосте полезный payload может быть меньше, что приводит к молчаливому отбрасыванию больших пакетов (PMTUD Black Hole). Решение: установить MTU=1450 на TAP или настроить MSS clamping.
- **QinQ overhead:** Двойное тегирование 802.1ad добавляет 8 байт. При MTU=1500 на хосте полезный payload = 1492 байта. Убедитесь что юникернел может принимать такие кадры.
- **Jumbo Frames:** Если хост и коммутатор поддерживают Jumbo Frames (MTU 9000), TAP-интерфейс должен быть настроен соответствующим образом. Но гостевой юникернел должен явно поддерживать большой MTU — многие минимальные стеки TCP/IP имеют hardcoded MTU=1500.

### Bonding

- **Смешанные скорости:** LACP-бонд с интерфейсами разной скорости (1G + 10G) хеширует трафик только по скоростям. Медленный линк может быть перегружен. Решение: используйте separate bonds или active-backup.
- **ARP-миграция:** В bonded интерфейсах ARP-записи мигрируют между slave-интерфейсами. Это может вызвать кратковременную потерю связности при failover. Увеличьте `arp_interval` и `arp_ip_target` для снижения времени обнаружения.
- **Bond + VLAN-aware bridge:** Некоторые старые ядра (до 5.10) имеют bugs в обработке VLAN tagging на bond-интерфейсах, подключенных к VLAN-aware мосту. Симптом: пакеты доходят до хоста, но не дальше. Решение: обновите ядро или используйте традиционные VLAN-под-интерфейсы.

### nftables

- **Conntrack exhaustion:** При большом количестве короткоживущих соединений (например, UDP-трафик) таблица conntrack может переполниться. Увеличьте `net.netfilter.nf_conntrack_max` или используйте `notrack` для не stateful-трафика.
- **NAT и hairpin/NAT loopback:** Юникернел в той же подсети, что и сервис, который он пытается достичь через NAT, может столкнуться с hairpin problem. Решение: включите hairpin NAT на мосту или используйте прямой L2-доступ без NAT.
- **Порядок правил:** nftables обрабатывает правила сверху вниз. Первое совпадение определяет действие. Убедитесь что allow-правила идут перед drop, а логирование — перед accept.

### DHCP

- **Rogue-сервер:** В тестовой среде без DHCP Snooping на коммутаторе возможен запуск rogue DHCP-сервера (например, dnsmasq с неверной конфигурацией). Он может выдать неверный gateway или DNS. Решение: используйте статические IP в тестах или включите DHCP Snooping.
- **Lease exhaustion:** При массовом запуске юникернелов (например, during deploy) пул DHCP может исчерпаться. Увеличьте диапазон `dhcp-range` или настройте shorter lease time с резервированием статических адресов для старых инстансов.
- **DHCP и VLAN:** Если VLAN-под-интерфейс не поднят или не добавлен в мост, DHCP-запросы не дойдут до сервера. Проверяйте `bridge vlan show` и `ip link show`.

### NTP

- **Рассинхронизация при старте:** Юникернел стартует за миллисекунды, но NTP-синхронизация может занимать секунды. Если приложение зависит от точного времени при старте — используйте хост-время через virtio RTC или подождите `chronyc waitsync` на хосте перед запуском.
- **Stratum-градиент:** Если хост синхронизируется с внешним NTP (stratum 2), а юникернел читает время хоста — его effective stratum = 3. Для большинства сценариев это приемлемо, но для compliance (PCI DSS, некоторые regulations) требуется stratum ≤ 2. Решение: настроить хост как stratum 1 через GPS-приемник или подключиться напрямую к pool.ntp.org.

### QoS

- **TC статс сбрасывается при перезагрузке:** Правила `tc` не сохраняются между перезагрузками. Используйте `systemd-networkd` или скрипт в `/etc/network/if-up.d/` для автоматического восстановления.
- **HTB vs fq_codel:** HTB provides hard guarantees but requires manual tuning. fq_codel provides low latency automatically but no hard bandwidth guarantees. Для mixed-трафика (юникернелы + обычные сервисы) используйте комбинацию: HTB на bond0 для гарантий, fq_codel на TAP-интерфейсах для fairness.

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **VLAN не работает** | Не включен vlan_filtering | `ip link set br0 type bridge vlan_filtering 1` |
| **Bonding не агрегируется** | LACP не настроен на коммутаторе | Переключиться на active-backup |
| **DHCP не выдает IP** | dnsmasq не запущен или firewall блокирует | `systemctl status dnsmasq`, `iptables -L` |
| **NTP рассинхронизация** | Нет доступа к серверу | Проверить `chronyc sources` |
| **Трафик не маршрутизируется** | IP forwarding выключен | `sysctl -w net.ipv4.ip_forward=1` |
| **MTU mismatch — пинги проходят, HTTP нет** | PMTUD заблокирован, TCP MSS слишком большой | Установить MTU=1450 на TAP, настроить MSS clamping |
| **Один из bond-интерфейсов не поднимается** | Разная скорость/duplex на портах коммутатора | Проверить `ethtool eno1`, `ethtool eno2`, настроить autoneg |
| **nftables: правило не применяется** | Неверный hook/priority или семейство | Проверить `nft list ruleset`, убедиться что используется `forward` hook для routed-трафика |
| **Юникернел не получает DNS-ответы** | UDP/53 заблокирован или DNS-forwarding не настроен | Проверить `dig @10.0.10.1 google.com`, добавить правило nftables для UDP/53 |
| **QoS не работает** | tc qdisc установлен на неверном интерфейсе | Проверить `tc qdisc show dev bond0`, убедиться что qdisc на outgoing-интерфейсе |

## Дополнительная информация

### См. также
- [Обзор Unikernel](./unikernel_overview.md)
- [Оркестрация и управление](./orchestration_and_management.md)
- [Хранилище и резервное копирование](./storage_and_backup.md)
- [Безопасность и hardening](./security_hardening.md)

### Ссылки
- [Linux Networking — VLAN](../../Networking/Protocols/VLAN/vlan_8021q_frame.md)
- [Linux Networking — Bonding](../../Proxmox/proxmox_networking.md)
- [nftables — архитектура](../../Linux/Networking/Settings/tools/nftables/architecture_and_concepts.md)
- [DHCP — мониторинг](../../Networking/Protocols/DHCP/dhcp_monitoring_observability.md)
- [Chrony — документация](https://chrony.tuxfamily.org/)
- [MTU и PMTUD](../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)
- [Policy-Based Routing](../../Linux/Networking/Policy_Based_Routing/index.md)
