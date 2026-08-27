# MTU, PMTUD и диагностика в VPN/облаках

## Определения

**MTU (Maximum Transmission Unit)** — максимальный размер полезной нагрузки кадра канального уровня (L2), который может быть передан через сетевой интерфейс без фрагментации. Стандарт для Ethernet — **1500 байт**. Для IPv6 — **минимум 1280 байт** (RFC 8200). Управление через `ip link set dev <iface> mtu <value>`. Авто-установка: ядро берёт min MTU среди активных портов (особенно актуально для Linux bridge).

**Jumbo Frames** — Ethernet-кадры, размер полезной нагрузки (MTU) которых превышает стандартные 1500 байт (чаще всего **9000 байт**). Используются в ЦОД и облаках для снижения нагрузки на CPU за счет уменьшения количества обрабатываемых пакетов. Требуют согласования MTU на обоих концах линка; если только одна сторона поддерживает jumbo — пакеты отбрасываются.

**MSS (Maximum Segment Size)** — максимальный размер полезной нагрузки **TCP-сегмента** (L4). Это объем данных, который TCP может поместить в один IP-пакет без учета заголовков. Устанавливается в TCP SYN/SYN-ACK через опцию `MSS` (16 бит).
- Формула: `MSS = MTU - (IP_Header) - (TCP_Header)`.
- Для стандартного Ethernet: `1500 - 20 - 20 = 1460 байт`.
- Для IPv6: `MTU - 40 - 20 = 1440` (фиксированный IPv6-заголовок 40 байт).

**Path MTU (PMTU)** — наименьшее значение MTU среди всех участков пути от отправителя до получателя. Именно оно определяет реальный лимит размера пакета для сквозной сессии. Кэшируется на отправителе (RFC 1191: 10 минут, RFC 8201: более длительный срок для IPv6).

**Оверхед (Overhead)** — разница между размером физического кадра и размером полезных данных из-за заголовков протоколов инкапсуляции (IPsec, GRE, VXLAN и др.). Пример: WireGuard добавляет 60–80 байт заголовков → при физическом MTU 1500 доступно только 1420 байт для полезных данных.

## Связь с соседними уровнями

```text
L4 (TCP/UDP) ← MSS согласуется через TCP Options в SYN/SYN-ACK
       ↕
L3 (IP)      ← MTU определяет max размер IP-пакета; DF=1 запрещает фрагментацию
       ↕
L2 (Ethernet)← Физический MTU = 1500 (или 9000 для Jumbo); инкапсуляция туннеля
       ↕               уменьшает доступный MTU
L1 (PHY)     ← Скорость линка определяет, какой MTU безопасен для производительности
```

| Уровень | Влияние на MTU |
| :--- | :--- |
| **L1 → MTU** | Скорость линка: на 10Gbps+ Jumbo Frames безопасны; на 100Mbps — Jumbo может увеличить latency из-за serialization delay |
| **L2 → MTU** | Ethernet: 1500; QinQ: 1508; 802.1Q + Jumbo: 9004; Linux bridge: min MTU среди всех портов |
| **L3 → MTU** | Заголовок IP: 20-60 байт (IPv4) / 40 байт (IPv6); DF=1 → PMTUD; DF=0 → фрагментация |
| **L4 → MTU** | TCP MSS = MTU - L3/L4 заголовков; UDP: данные идут как есть (нет MSS); QUIC: PLPMTUD (RFC 8899) |
| **Tunnel → MTU** | Каждый уровень инкапсуляции «съедает» MTU (GRE: -24, IPsec: -50..73, VXLAN: -50) |

## Базовые концепции

### Path MTU Discovery (PMTUD)

Механизм (RFC 1191 для IPv4, RFC 8201 для IPv6), позволяющий хостам автоматически определять минимальный MTU на пути следования.

#### Принцип работы (IPv4)
1. Отправитель шлет пакет с установленным флагом **DF (Don't Fragment)**.
2. Если пакет слишком велик для какого-то транзитного узла, маршрутизатор отбрасывает его и возвращает **ICMP Type 3 Code 4** (Fragmentation Needed), указывая в сообщении свой MTU.
3. Отправитель получает ICMP, кэширует значение (PMTU Cache) и снижает размер пакетов до указанного значения для этого получателя.

#### Принцип работы (IPv6)
Маршрутизаторы в IPv6 **никогда** не фрагментируют транзитные пакеты. Если пакет велик, узел шлет **ICMPv6 Type 2** (Packet Too Big). Обязательный минимальный MTU на любом звене IPv6 — **1280 байт**.

### Проблема «Черной дыры» (PMTUD Black Hole)
Если на пути следования криво настроенные файрволы блокируют ICMP-сообщения (Type 3/Code 4 для IPv4 или Type 2 для IPv6), отправитель никогда не узнает о необходимости снизить MTU и продолжит слать большие пакеты, которые будут молча отбрасываться.

**Симптомы (выборочная неработоспособность):**
- **Веб-серфинг:** Главная страница сайта открывается (она маленькая), но изображения или стили не загружаются, либо HTTPS-соединение зависает на этапе TLS-рукопожатия (обмен большими сертификатами).
- **Передача файлов:** SSH работает (короткие команды), но SCP или SFTP «зависают» сразу после начала передачи данных.
- **API и микросервисы:** Мелкие GET-запросы проходят успешно, но POST-запросы с большим JSON-телом уходят в таймаут.
- **Базы данных:** Простые SQL-запросы выполняются, но выборки с большим количеством данных обрывают соединение.

### PLPMTUD (Packetization Layer Path MTU Discovery)
Современный метод (RFC 4821, обновлён RFC 8899), решающий проблему Black Hole. Работает на уровне L4 (TCP/QUIC). Не полагается на ICMP, а использует пробные пакеты разного размера: если пакет подтвержден (ACK), значит MTU достаточен. Если ответа нет — MTU снижается.

**Принцип работы:**
```
1. Определить `base_size` = размер пакета, который гарантированно проходит (обычно 1024 байт)
2. Выбрать `probe_size` = target MTU (например, 1460)
3. Отправить probe-пакет (с TESTING bit) + regular пакет
4. Если ACK получен — probe_size безопасен → попробовать следующий (поиск методом бинарного поиска)
5. Если ACK не получен в timeout — снизить probe_size
6. Результат —_probebed MTU сохраняется для этого соединения
```

**PLPMTUD vs PMTUD:**

| Критерий | PMTUD (RFC 1191) | PLPMTUD (RFC 8899) |
| :--- | :--- | :--- |
| Зависимость от ICMP | Обязательна | Не нужна |
| Работа при Black Hole | ❌ Ломается | ✅ Работает |
| Поддержка UDP | Нет (UDP не имеет ACK) | Да (UDP Lite, QUIC) |
| Поддержка TCP | Да | Да (ядро Linux ≥ 5.18) |
| Overhead | Минимальный (1 probe) | Выше (много probe-пакетов) |
| Кэширование | Глобальная (PMTU cache) | Per-connection |

## Влияние туннелирования и облаков на MTU

Любая инкапсуляция добавляет свои заголовки к исходному пакету, «отъедая» место у полезных данных. Если физический MTU = 1500, то MTU виртуального интерфейса должен быть меньше.

### Таблица оверхеда туннелей

| Технология | Оверхед (байт) | MTU (при физическом 1500) | Примечание |
| :--- | :--- | :--- | :--- |
| **IPIP / SIT** | 20 | 1480 | Базовая инкапсуляция L3-in-L3 |
| **GRE (без ключа)** | 24 | 1476 | Универсальная инкапсуляция (IP Protocol 47) |
| **GRE (с ключом)** | 28 | 1472 | 32-битный ключ добавляет 4 байта |
| **GRE over UDP (FOU)** | 32 | 1468 | Обход «тупых» NAT, улучшение RSS/ECMP |
| **IPsec (ESP Transport)** | 50–53 | 1447–1450 | Без внешнего IP-заголовка |
| **IPsec (ESP Tunnel)** | 56–73 | ~1420–1444 | Зависит от алгоритма (AES-GCM минимален) |
| **L2TP/IPsec** | 57–73 | ~1420 | L2TP(6-8) + IPsec(50-73) — двойной оверхед |
| **WireGuard** | 60–80 | 1420 | Рекомендуемый современный стандарт |
| **VXLAN** | 50 | 1450 | Стандарт для Overlay-сетей (Docker/Kubernetes) |
| **GENEVE** | 50+ | 1450 | Используется в Cilium; поддерживает variable options |
| **QinQ (802.1ad)** | 8 | 1508 | 2×VLAN tag; требует увеличения физического MTU |
| **GRETAP** | 42 | 1458 | L2-over-GRE (для мостинга VLAN) |
| **NVGRE (RFC 7637)** | 28 | 1472 | Microsoft Hyper-V (устаревает) |
| **STT (RFC 7638)** | 52–58 | ~1442 | Неконвертируемые транспортные сегменты (устаревает) |

**Важно:** При использовании **каскадной инкапсуляции** (например, VXLAN внутри WireGuard внутри Ethernet) оверхед суммируется: `VXLAN(50) + WireGuard(60) = 110 байт → MTU = 1500 - 110 = 1390`.

### Особенности публичных облаков (2026)

| Облачный провайдер | Базовый MTU | MTU через VPN/Peering | MTU Overlay (Docker/K8s) | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **AWS VPC** | 9001 (Jumbo) | 1500 (IGW, VPN) | 1500 (bridge) или 1450 (VXLAN) | Peering между регионами: 1500 |
| **GCP VPC** | 1460 (по умолчанию) | 1460 | 1410 (1460-50 для VXLAN) | Настройка через `gcloud compute network update` |
| **Azure VNet** | 1500 | 1500 | 1450 (Azure CNI) | Jumbo Frames поддерживаются в Azure Ev2/SBv2 |
| **Yandex Cloud VPC** | 1500 | 1500 | 1450 | Стандартная конфигурация |
| **Oracle Cloud VCN** | 9000 (Jumbo) | 1500 (Dynamic Routing Gateway) | 1450 | Supports Jumbo Frames между VM в одном AD |

**Проблема Kubernetes в GCP:** Сеть по умолчанию 1460. Если CNI использует VXLAN (calico, flannel), MTU пода = `1460 - 50 = 1410`. При неправильной настройке `clusterCIDR` и `podCIDR` возникает PMTU Black Hole. Решение: `ip link set dev cni0 mtu 1410` или настройка в `kubeadm-config.yaml` → `networking.podSubnetCIDR` с правильным MTU.

### Docker и контейнеры

**Docker Bridge (docker0):** По умолчанию MTU = 1500. При использовании overlay-сети (Docker Swarm) добавляется VXLAN-инкапсуляция → MTU = 1450.

```bash
# Проверка MTU Docker bridge
ip link show docker0

# Настройка MTU для Docker daemon (все сети)
cat > /etc/docker/daemon.json << 'EOF'
{
  "mtu": 1450
}
EOF
systemctl restart docker

# Проверка MTU внутри контейнера
docker exec <container> ip link show eth0
```

**Docker Compose:**
```yaml
networks:
  app_net:
    driver: bridge
    driver_opts:
      com.docker.network.driver.mtu: 1450
```

**Podman:** Аналогично Docker, но через `containers.conf`:
```toml
[network]
default_mtu = 1450
```

## Практические сценарии диагностики

### Метод 1: Ручной поиск MTU через ping (DF-биты)
Позволяет инженеру вручную нащупать «потолок» MTU без фрагментации.

```bash
# -M do — запретить фрагментацию (установить DF-бит)
# -s <size> — размер полезной нагрузки (данных ICMP).
# Итоговый размер пакета = size + 28 (20 байт IPv4 + 8 байт ICMP)

# Проверка прохождения стандартного MTU 1500:
ping -s 1472 -M do 8.8.8.8

# Если пакет не проходит, постепенно уменьшайте размер (например, до 1420 или 1372), 
# пока не получите стабильный ответ. Это определит реальный Path MTU.

# Бинарный поиск (быстрее):
# Проверяем: 1472, 1200, 1350, 1420 — находим точное значение

# IPv6 (заголовок 40 байт, а не 20):
ping -6 -s 1432 -M do -c 3 2001:4860:4860::8888
# size + 40 (IPv6) + 8 (ICMPv6) = MTU → 1432 + 48 = 1480
```

### Метод 2: Использование tracepath
В отличие от обычного `traceroute`, `tracepath` умеет определять PMTU на каждом узле маршрута. Не требует root-прав.

```bash
tracepath -n google.com
# → 1:  [LOCALHOST]               pmtu 1500
# → 2:  10.0.0.1                  pmtu 1420  <-- Узкое место (VPN-шлюз)
# → Resume: pmtu 1420

# С фильтрацией по конкретному интерфейсу:
tracepath -n -m 15 8.8.8.8   # max 15 хопов
```

### Метод 3: Анализ MSS при установке TCP-соединения
С помощью `tcpdump` можно проверить, какой размер сегмента (MSS) согласовали стороны во время TCP Handshake (SYN-пакеты).

```bash
# Захват SYN-пакетов для анализа MSS
sudo tcpdump -i <interface> 'tcp[tcpflags] & tcp-syn != 0' -v

# В выводе ищем значение "mss 1460". Если оно не соответствует ожидаемому MTU 
# (например, MSS 1460 при MTU пути 1420), пакеты будут дропаться.

# Конкретный пример для WireGuard-интерфейса:
sudo tcpdump -i wg0 'tcp[tcpflags] & tcp-syn != 0' -vv 2>&1 | grep -E "mss|options"
```

### Метод 4: Диагностика через iperf3
Если ICMP заблокирован, можно проверить прохождение TCP-сегментов с конкретным MSS.

```bash
# Тест MSS 1380 (означает MTU 1420)
iperf3 -c 10.0.0.1 -M 1380

# Сравнение пропускной способности при разных MSS (поиск оптимального):
for mss in 1360 1380 1400 1420 1440 1460; do
  echo "=== MSS $mss ==="
  iperf3 -c 10.0.0.1 -M $mss -t 3 -P 1 2>&1 | grep -E "sender|receiver|Bitrate"
done
```

### Метод 5: Просмотр текущего MTU и статистики фрагментации

```bash
# Текущий MTU всех интерфейсов
ip -o link show | awk '{print $2, $14}'

# Детальная информация (включая offload):
ip -d link show eth0

# Проверка TSO/GRO/LRO (если включены — tcpdump показывает гигантские пакеты):
ethtool -k eth0 | grep -E "tcp-segmentation|generic-receive|large-receive"

# Счётчики фрагментации в ядре:
nstat -az | grep -E "IpFrag|IpReasm|IpOutFrag"

# Конкретный интерфейс:
cat /proc/net/snmp | grep -E "Ip:|Ip6:"
#  字段: InReceives, InHdrErrors, InAddrErrors, InUnknownProtos, InDiscards, 
#        InDelivers, OutRequests, RoutingDiscards, OutDiscards, OutNoRoutes,
#        FragmentationOKs, FragmentationFails, FragmentationCreates

# PMTU cache (Linux ≥ 4.14):
ip route get 8.8.8.8 | grep -o "mtu [0-9]*"
```

### Метод 6: Проверка PMTUD Black Hole

```bash
# Шаг 1: Определяем, есть ли проблема с ICMP
# Отправляем пакет с DF=1 и размером > 1472 (если MTU 1500):
ping -s 1500 -M do -c 3 8.8.8.8
# Если нет ответа → либо MTU < 1528, либо ICMP Type 3/4 заблокирован

# Шаг 2: Определяем, блокируется ли ICMP файрволом
# Проверка от другого хоста:
mtr --no-dns 8.8.8.8  # смотрим, отвечает ли промежуточный роутер

# Шаг 3: Проверяем TCP через iperf3 (если ping не работает, а TCP работает — PMTU Black Hole)
iperf3 -c 8.8.8.8 -M 1460 -t 5
# Если зависает → PMTU Black Hole (ICMP Type 3/4 заблокирован)
```

### Метод 7: Диагностика PMTUD через TCP Window Scaling

```bash
# Если MSS в SYN не совпадает с ожидаемым — проблема MTU
# Пример: при tunnels MTU 1420, MSS должен быть ≤ 1380

# Быстрая проверка MSS vs MTU:
ms=$(sudo tcpdump -i eth0 -r /dev/stdin 'tcp[tcpflags] & tcp-syn != 0' -c 100 2>/dev/null | \
  grep -o "mss [0-9]*" | head -1 | awk '{print $2}')
echo "Agreed MSS: $ms"
echo "Expected MTU: $((ms + 40))"

## Методы решения (Митигация)

### 1. TCP MSS Clamping
Самый эффективный и универсальный метод для TCP-трафика. Выполняется на маршрутизаторах или VPN-шлюзах. Маршрутизатор на лету перехватывает SYN-пакеты (устанавливающие соединение) и принудительно уменьшает в них значение MSS, заставляя обе стороны сразу слать пакеты нужного размера.

**В Linux (iptables):**
```bash
# Автоматическая подстройка под PMTU
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

# Или жесткая установка безопасного лимита (например, 1360 для MTU 1400)
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1360

# Для конкретного интерфейса (WireGuard):
iptables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1380

# Просмотр существующих правил:
iptables -t mangle -L FORWARD -v -n | grep MSS
```

**В Linux (nftables):**
```bash
# Через nft (современный синтаксис):
nft add rule inet filter forward oifname "wg0" tcp flags syn tcp option maxseg size set 1380

# Или в таблице:
table inet filter {
    chain forward {
        type filter hook forward priority 0;
        tcp flags syn tcp option maxseg size set 1380
    }
}

# Автоматический clamp (ядро само вычисляет MTU):
nft add rule inet filter forward oifname "wg0" tcp flags syn tcp option maxseg size set 1380
```

**На маршрутизаторах (Cisco IOS):**
```
interface Tunnel0
 ip mtu 1400
 ip tcp adjust-mss 1360
```

**На MikroTik RouterOS:**
```
/interface bridge settings set allow-fast-path=no
/ip firewall mangle add chain=forward protocol=tcp tcp-flags=syn \
  action=change-mss new-mss=1360
```

### 2. Принудительная настройка MTU на интерфейсе
Если устройства находятся под вашим контролем, просто установите правильный MTU на виртуальных интерфейсах.

```bash
# Для WireGuard
ip link set dev wg0 mtu 1420

# Для.vxlan
ip link set dev vxlan0 mtu 1450

# Для Docker bridge
ip link set dev docker0 mtu 1450

# Для Linux bridge (минимальный MTU среди всех портов)
ip link set dev br0 mtu 1450

# Временно (до перезагрузки):
ip link set dev wg0 mtu 1420

# Постоянно (systemd-networkd):
cat > /etc/systemd/network/20-wg0.network << 'EOF'
[Match]
Name=wg0

[Network]
MTUBytes=1420
EOF
systemctl restart systemd-networkd

# Постоянно (NetworkManager):
nmcli connection modify "wg0-conn" 802-3-ethernet.mtu 1420
nmcli connection up "wg0-conn"

# Постоянно (netplan, Ubuntu):
# /etc/netplan/01-wg.yaml:
network:
  version: 2
  ethernets:
    wg0:
      mtu: 1420
```

**Проверка после установки:**
```bash
ip link show wg0 | grep -o "mtu [0-9]*"
ip -d link show wg0   # детали + offload
```

### 3. Разрешение ICMP на Firewall
На всех межсетевых экранах (Security Groups, iptables) **обязательно** должны быть разрешены служебные сообщения:
- **IPv4:** ICMP Type 3, Code 4 (Fragmentation Needed) — для PMTUD.
- **IPv6:** ICMPv6 Type 2 (Packet Too Big) — для PMTUD в IPv6.

```bash
# Проверка текущих правил ICMP:
iptables -L INPUT -v -n | grep icmp
nft list ruleset | grep icmp

# Разрешение ICMP Type 3 Code 4 (если файрвол блокирует):
iptables -A INPUT -p icmp --icmp-type 3/4 -j ACCEPT
iptables -A FORWARD -p icmp --icmp-type 3/4 -j ACCEPT

# Для IPv6 (ICMPv6 Type 2):
ip6tables -A INPUT -p icmpv6 --icmpv6-type packet-too-big -j ACCEPT
ip6tables -A FORWARD -p icmpv6 --icmpv6-type packet-too-big -j ACCEPT
```

### 4. Настройка sysctl для управления фрагментацией и PMTUD

```bash
# Включение PMTUD (по умолчанию включена)
net.ipv4.ip_no_pmtu_disc=0

# Ограничение памяти на фрагменты (защита от атаки Teardrop/Fragmentation Flood)
net.ipv4.ipfrag_high_thresh=4194304    # 4 MB — начало очистки
net.ipv4.ipfrag_low_thresh=3145728     # 3 MB — конец очистки

# Время жизни фрагментов (секунды)
net.ipv4.ipfrag_time=15

# Логирование ошибок фрагментации (martian packets)
net.ipv4.conf.all.log_martians=1
net.ipv4.conf.default.log_martians=1

# IPv6 PMTU discovery (RFC 8201)
net.ipv6.conf.all.mtu_discover=1       # 0=disabled, 1=defaults
net.ipv6.conf.default.mtu_discover=1

# Кэширование PMTU (в секундах, Linux ≥ 4.14)
net.ipv4.route.mtu_expires=600         # 10 минут (RFC 1191 default)
```

### 5. Обход MSS Clamping — когда это необходимо

В некоторых случаях MSS Clamping может сломать сценарии:
- **HPC / RDMA:** если приложение само вычисляет optimal MSS
- **Базы данных:** PostgreSQL с做大 block size (>16KB) может требовать конкретный MSS
- **SMB/CIFS:** файловые протоколы с negotiating max payload

Решение — **отключение MSS Clamping** при условии корректного PMTUD:
```bash
# Удаление MSS Clamping правила:
iptables -t mangle -D FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
# Или замена наmanuel MSS для конкретного трафика:
iptables -t mangle -A FORWARD -s 10.0.1.0/24 -d 10.0.2.0/24 -p tcp \
  --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1460
```

## Безопасность и MTU

| Проблема | Описание | Решение |
| :--- | :--- | :--- |
| **Fragmentation Attack** | Zloumylennik отправляет много мелких фрагментов, перегружая CPU маршрутизатора | `sysctl net.ipv4.ipfrag_high_thresh=2097152` (2MB) |
| **Teardrop Attack** | Перекрывающиеся фрагменты с неверными offset вызывают crash устаревших ОС | Обновление ОС; фильтрация фрагментов на файрволе |
| **MTU-based fingerprinting** | Определение ОС/стека по размеру пакета (TCP MSS reveals kernel version) | Нет стандартного решения; релевантно для скрытности |
| **ICMP Redirect for MTU** | Фальшивое ICMP PTB с очень маленьким MTU → DoS (очень медленная передача) | `sysctl net.ipv4.conf.all.accept_redirects=0` |
| **Overlapping Fragments** | IDS/Firewall может пропустить атаку из-за перекрывающихся фрагментов (Talisker/Teardrop) | `net.nf_conntrack_frag_high_thresh` + modern firewall |

## Типичные проблемы и чеклист

| Симптом | Вероятная причина | Шаги диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **SSH «зависает» после-login** | MTU снижается на пути (VPN, tunnel) | `ping -M do -s 1472 <dst>`, `tracepath <dst>` | MSS Clamping или уменьшение MTU |
| **HTTPS handshake не проходит** | TLS certificate обмен превышает MTU | `tcpdump 'tcp[tcpflags] & tcp-syn != 0'` (проверить MSS) | MSS Clamping для HTTPS |
| ** SCP/rsync зависает** | Фрагментированные данные отбрасываются | `iperf3 -c <host> -M 1380` | MSS Clamping или PLPMTUD |
| **DNS timeout в Docker** | Large DNS-ответ > MTU overlay | `ping -M do -s 1200 <dns-server>` | MTU 1450 в Docker daemon.json |
| **Kubernetes pod network break** | CNI overlay MTU > физического MTU | `kubectl exec <pod> -- ip link show eth0` | Настройка MTU в CNI config |
| **OpenVPN slow** | OpenVPN added 57-73 bytes overhead | `ip link show tun0` → mtu 1390 | MSS Clamping на tun0 |

## Сводная таблица

| Параметр | Значение |
| :--- | :--- |
| **Ethernet MTU** | 1500 байт (IEEE 802.3) |
| **Jumbo Frame MTU** | 9000 байт (до 9016 с headers) |
| **IPv6 Minimum MTU** | 1280 байт (RFC 8200) |
| **MSS (standard Ethernet)** | 1460 байт (1500-20-20) |
| **MSS (IPv6)** | 1440 байт (1500-40-20) |
| **PMTU Cache (IPv4)** | 10 минут (RFC 1191) |
| **PMTU Cache (IPv6)** | Длительное (RFC 8201) |
| **Типичный MTU VPN** | 1420 (WireGuard), 1420 (IPsec), 1476 (GRE) |
| **Типичный MTU Overlay** | 1450 (VXLAN, GENEVE), 1410 (GCP VXLAN) |
| **Формула MSS** | `MTU - IP_Header - TCP_Header` |
| **Формула ping test** | `Size = MTU - 28` (IPv4), `Size = MTU - 48` (IPv6) |

## Дополнительная информация

### См. также
- **[Фрагментация IP-пакетов](./Protocols/ip_fragmentation.md)** — механизмы разделения пакетов, PLPMTUD и уязвимости.
- **[Структура IP-пакета (IPv4)](./Protocols/ip_packet_structure.md)** — детали заголовка и DF-бита.
- **[Протокол ICMP](../../Protocols/ICMP/icmp_overview.md)** — типы сообщений.
- **[VPN и туннелирование](../../Tunnels/tunneling_overview.md)** — инкапсуляция и накладные расходы.
- **[Сетевой уровень (L3)](./Concepts/network_layer_overview.md)** — обзор L3, PDU, маршрутизация, QoS, IPsec.
- **[Сравнение Proxy и VPN](../../Concepts/proxy-vs-vpn.md)** — overhead VPN vs Proxy.
- **[GRE](../../Tunnels/ipip_and_sit.md)** — инкапсуляция и MTU (24 байта overhead).
- **[IPsec](../../Tunnels/ipsec/ipsec.md)** — ESP и IKEv2, MTU-ознаменности.
- **[IP-адресация](../../Protocols/IP_addressing/ip_overview.md)** — структура адресов и масок.
- **[Практические сценарии](./Concepts/routing_scenarios.md)** — MTU Black Hole, PMTUD.
- **[Dual Stack IPv4/IPv6](./Concepts/ipv4_ipv6_dual_stack.md)** — MTU-различия между IPv4 и IPv6.