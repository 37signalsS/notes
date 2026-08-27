# Туннели IPIP и SIT

## Определения

**IPIP (IP-in-IP)** — протокол туннелирования, инкапсулирующий пакеты IPv4 в другие пакеты IPv4 ([RFC 2003](https://datatracker.ietf.org/doc/html/rfc2003)). Это один из старейших и простейших методов создания виртуальных L3-сетей, отличающийся минимальными накладными расходами.

**SIT (Simple Internet Transition)** — также известный как **6in4**, протокол инкапсуляции пакетов IPv6 в пакеты IPv4 ([RFC 4213](https://datatracker.ietf.org/doc/html/rfc4213)). Основное назначение — обеспечение связности IPv6-сетей через существующую IPv4-инфраструктуру.

**Ключевые характеристики:**

| Параметр | IPIP | SIT (6in4) |
| :--- | :--- | :--- |
| **Протокол (ID в IP-заголовке)** | 4 (IPv4-in-IPv4) | 41 (IPv6-in-IPv4) |
| **Внутренний протокол** | IPv4 | IPv6 |
| **Внешний протокол** | IPv4 | IPv4 |
| **Накладные расходы (Overhead)** | 20 байт (IPv4 Header) | 20 байт (IPv4 Header) |
| **Шифрование / Аутентификация** | Нет | Нет |

> **См. также:** [Обзор туннелирования](./tunneling_overview.md), [Проблемы MTU и фрагментация](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md), [Туннели GRE](./gre/gre.md)

---

## Предварительные требования

### Версии ядра и пакетов

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **Ядро Linux** | 2.6 (базовая поддержка IPIP/SIT) | 5.10+ (FOU, offload) |
| **iproute2** | 3.12 (`ip link add type ipip/sit`) | 5.15+ |
| **FOU-модуль** | 3.18 (`fou.ko`) | 5.10+ |

### Проверка наличия модулей ядра

```bash
# Проверка модуля IPIP
modinfo ipip | head -3
# → filename:       /lib/modules/$(uname -r)/kernel/net/ipv4/ipip.ko
# → license:        GPL

# Проверка модуля SIT
modinfo sit | head -3
# → filename:       /lib/modules/$(uname -r)/kernel/net/ipv6/sit.ko
# → license:        GPL

# Проверка модуля FOU
modinfo fou | head -3
# → filename:       /lib/modules/$(uname -r)/kernel/net/ipv4/fou.ko
# → license:        GPL

# Проверка загруженных модулей
lsmod | grep -E "^(ipip|sit|fou)"
# → ipip    20480  0
# → sit     28672  0
# → fou     20480  0
```

### Включение IP-форвардинга

IPIP/SIT-туннели работают на уровне L3 — для маршрутизации трафика между туннельным и физическим интерфейсами необходим IP-форвардинг:

```bash
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/91-ipip-sit.conf
sudo sysctl -p /etc/sysctl.d/91-ipip-sit.conf
```

### Установка зависимостей

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install iproute2 nftables tcpdump

# RHEL/CentOS/Rocky
sudo dnf install iproute nftables tcpdump
```

---

## Основные концепции

### Принцип работы и инкапсуляция

Оба протокола работают по принципу «прямой» инкапсуляции: внутренний IP-пакет помещается сразу за внешним IP-заголовком без использования промежуточных уровней (таких как UDP или GRE).

```text
[Внешний IPv4 заголовок (20B)] [Внутренний IP пакет (IPv4 или IPv6)]
```

**Особенности механизмов:**
- **Отсутствие состояний (Stateless):** Туннели не требуют «рукопожатия» (handshake). Пакет инкапсулируется и отправляется на основе статических настроек.
- **Копирование флагов:** Linux по умолчанию копирует бит **DF (Don't Fragment)** из внутреннего пакета во внешний, что критично для работы механизмов Path MTU Discovery (PMTUD).
- **TTL (Time to Live):** При инкапсуляции значение TTL внутреннего пакета обычно уменьшается на 1, а внешний заголовок получает собственное значение TTL.

### Проблемы NAT и сетевых экранов (NAT Traversal)

Туннели IPIP и SIT **крайне плохо работают через NAT** по следующим причинам:
1.  **Отсутствие портов:** Поскольку протоколы не используют TCP/UDP, классический NAT (PAT) не может сопоставить входящий пакет с сессией во внутренней сети.
2.  **SOHO-роутеры:** Большинство бытовых маршрутизаторов блокируют протоколы 4 и 41 по умолчанию.
3.  **Решение:** Для работы через NAT рекомендуется использовать **FOU (Foo Over UDP)** — инкапсуляцию туннеля в UDP-пакеты.

### Безопасность и фильтрация

Поскольку протоколы не имеют встроенной аутентификации, они уязвимы для **IP Spoofing**.
- **Риск:** Злоумышленник может отправить инкапсулированный пакет на внешний IP-адрес шлюза, подделав внутренний IP-адрес.
- **Защита:** На туннельных интерфейсах необходимо настраивать строгую фильтрацию (например, через `rp_filter` в Linux или правила `nftables/iptables`), разрешая прием пакетов только из доверенных внешних источников.

---

## Практические сценарии в Linux

Для настройки используется пакет `iproute2`. Команда `ip link` является предпочтительной по сравнению с устаревшей `ip tunnel`.

### Управление интерфейсами (iproute2)

**Создание IPIP/SIT-интерфейсов:**
```bash
# IPIP-туннель (современный способ)
sudo ip link add name ipip0 type ipip local 1.1.1.1 remote 2.2.2.2

# SIT-туннель
sudo ip link add name sit0 type sit local 1.1.1.1 remote 2.2.2.2 ttl 64

# Просмотр детальных параметров
ip -d link show ipip0
# → ipip0: <NOARP,UP,LOWER_UP> mtu 1480 ... state UNKNOWN ...
# →     ipip ipip remote 2.2.2.2 local 1.1.1.1 ...

# Удаление интерфейса
sudo ip link delete ipip0
```

### 1. Настройка IPIP-туннеля (IPv4-в-IPv4)

**Задача:** Соединить две подсети через IPv4-интернет.

**Узел A (Внешний: 1.1.1.1, Внутренний: 10.0.0.1):**
```bash
sudo ip link add name ipip0 type ipip local 1.1.1.1 remote 2.2.2.2
sudo ip link set ipip0 up
sudo ip addr add 10.0.0.1/30 dev ipip0
sudo ip route add 10.0.0.0/30 dev ipip0
```

**Узел B (Внешний: 2.2.2.2, Внутренний: 10.0.0.2):**
```bash
sudo ip link add name ipip0 type ipip local 2.2.2.2 remote 1.1.1.1
sudo ip link set ipip0 up
sudo ip addr add 10.0.0.2/30 dev ipip0
sudo ip route add 10.0.0.0/30 dev ipip0
```

**Валидация:**
```bash
# Проверка состояния интерфейса
ip -br addr show ipip0
# → ipip0      UP             10.0.0.1/30

# Проверка MTU (ожидается 1480)
ip link show ipip0 | grep mtu
# → mtu 1480

# Проверка маршрута
ip route show dev ipip0
# → 10.0.0.0/30 proto kernel scope link src 10.0.0.1

# Ping через туннель
ping -c 2 10.0.0.2
# → PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.
# → 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=1.23 ms

# Проверка на удалённом узле (на B)
ping -c 2 10.0.0.1
# → 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.19 ms

# Прослушивание трафика
sudo tcpdump -ni any proto 4 -c 5
# → 1.1.1.1 > 2.2.2.2: IP (tos 0x0, ttl 64, id ..., offset 0, proto IPIP (4), length: 84)
```

### 2. Настройка SIT-туннеля (6in4)

**Задача:** Получить доступ к IPv6-интернету через IPv4-брокера.

```bash
# Локальный сервер
sudo ip link add name sit0 type sit local <Local_IPv4> remote <Broker_IPv4> ttl 64
sudo ip link set sit0 up
sudo ip -6 addr add 2001:db8:1234::2/64 dev sit0
sudo ip -6 route add default dev sit0
```

**Валидация:**
```bash
# Проверка состояния
ip -6 -br addr show sit0
# → sit0       UP             2001:db8:1234::2/64

# Проверка IPv6-маршрута
ip -6 route show dev sit0
# → default dev sit0 proto static metric 1024 ...

# Тест IPv6-связности
ping6 -c 2 2001:4860:4860::8888
# → 64 bytes from 2001:4860:4860::8888: icmp_seq=1 ttl=56 time=30.1 ms

# Проверка внешнего заголовка
sudo tcpdump -ni any proto 41 -c 3
```

### 3. Инкапсуляция FOU (Foo Over UDP)

Позволяет обернуть IPIP/SIT в UDP для прохода через NAT и улучшения балансировки (RSS/ECMP).

```bash
# 1. Загрузка модуля
sudo modprobe fou

# 2. Настройка приемника UDP (например, порт 5555)
sudo ip fou add port 5555 ipproto 4

# 3. Создание туннеля с инкапсуляцией
sudo ip link add name ipip-fou type ipip \
     local 1.1.1.1 remote 2.2.2.2 \
     encap fou encap-sport 5555 encap-dport 5555
```

**Валидация FOU:**
```bash
# Проверка FOU-监听а
ip fou show
# → port 5555 ipproto 4

# Проверка состояния интерфейса
ip -d link show ipip-fou
# → ipip ipip remote 2.2.2.2 local 1.1.1.1 encap fou encap-sport 5555 encap-dport 5555 ...

# Проверка UDP-трафика
sudo tcpdump -ni any udp port 5555 -c 3
# → 1.1.1.1.5555 > 2.2.2.2.5555: UDP, length 84
```

### Лаборатория: IPIP-туннель между Network Namespaces

Полный пример настройки IPIP-туннеля между двумя изолированными пространствами имён:

```bash
# Создание пространств имён
ip netns add ns1
ip netns add ns2

# Создание физических пар (veth) для «внешней» сети
ip link add veth1-outer type veth peer name veth2-outer

# Перемещение в пространства имён
ip link set veth1-outer netns ns1
ip link set veth2-outer netns ns2

# Настройка «внешних» адресов
ip netns exec ns1 ip addr add 192.168.100.1/24 dev veth1-outer
ip netns exec ns1 ip link set veth1-outer up
ip netns exec ns1 ip link set lo up

ip netns exec ns2 ip addr add 192.168.100.2/24 dev veth2-outer
ip netns exec ns2 ip link set veth2-outer up
ip netns exec ns2 ip link set lo up

# Проверка связности «внешней» сети
ip netns exec ns1 ping -c 1 192.168.100.2
# → 64 bytes from 192.168.100.2: icmp_seq=1 ttl=64 time=0.05 ms

# Создание IPIP-туннеля (внутренняя сеть 10.0.0.0/30)
ip netns exec ns1 ip link add ipip1 type ipip local 192.168.100.1 remote 192.168.100.2
ip netns exec ns1 ip link set ipip1 up
ip netns exec ns1 ip addr add 10.0.0.1/30 dev ipip1
ip netns exec ns1 ip route add 10.0.0.0/30 dev ipip1

ip netns exec ns2 ip link add ipip1 type ipip local 192.168.100.2 remote 192.168.100.1
ip netns exec ns2 ip link set ipip1 up
ip netns exec ns2 ip addr add 10.0.0.2/30 dev ipip1
ip netns exec ns2 ip route add 10.0.0.0/30 dev ipip1

# Тест IPIP-туннеля
ip netns exec ns1 ping -c 2 10.0.0.2
# → PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.
# → 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.12 ms

# Проверка заголовков
ip netns exec ns1 tcpdump -ni veth1-outer proto 4 -c 2
# → 192.168.100.1 > 192.168.100.2: IP (..., proto IPIP (4), length: 84)

# Очистка
ip netns exec ns1 ip link delete ipip1
ip netns exec ns2 ip link delete ipip1
ip netns exec ns1 ip link delete veth1-outer
ip netns del ns1
ip netns del ns2
```

### Взаимодействие с XDP и eBPF

В Linux 5.10+ IPIP/SIT-туннели могут использовать XDP для аппаратного ускорения:
- **Generic XDP:** Работает на всех IPIP/SIT-устройствах, снижает нагрузку на CPU.
- **Native XDP:** Требует поддержки NIC driver (virtio-net, mlx5).

```bash
# Проверка XDP-поддержки
ip -d link show ipip0 | grep xdp
# → xdp: ...

# Привязка XDP-программы (пример)
ip link set dev ipip0 xdp obj prog.o sec xdp
```

---

## Диагностика

### Просмотр всех IPIP/SIT-интерфейсов

```bash
# Список всех IPIP-интерфейсов
ip -d link show type ipip

# Список всех SIT-интерфейсов
ip -d link show type sit

# Просмотр FOU-портов
ip fou show
```

### Команды диагностики

```bash
# Просмотр детальных параметров (MTU, TTL, local/remote)
ip -d link show ipip0

# Просмотр статистики ошибок (дропы из-за MTU или Firewall)
ip -s link show ipip0
# → RX:  bytes=1234 packets=10 errors=0 dropped=0
# → TX:  bytes=5678 packets=8 errors=0 dropped=0

# Проверка маршрута через туннель
ip route get 10.0.0.2
# → 10.0.0.2 dev ipip0 src 10.0.0.1 uid 0

# Мониторинг прохождения трафика (анализ внешнего заголовка)
sudo tcpdump -ni any proto 4 -c 5    # IPIP
sudo tcpdump -ni any proto 41 -c 5   # SIT

# Проверка ARP для туннельных адресов (IPIP)
ip neigh show dev ipip0
```

### Проверка PMTUD

```bash
# Проверка Path MTU
ping -M do -s 1452 -c 1 <remote-tunnel-end>
# → 1452 + 28 (IP+ICMP) + 20 (IPIP) = 1500 = физический MTU

# Проверка с different DF bit
ping -M do -s 1452 -c 1 -M want <remote-ip>
```

---

## Типичные ошибки и их устранение

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Tunnel is down / NOARP** | Интерфейс не поднят | `ip link show ipip0` | `ip link set ipip0 up` |
| **Нет connectivity через туннель** | IP-форвардинг отключен | `sysctl net.ipv4.ip_forward` | `sysctl -w net.ipv4.ip_forward=1` |
| **Фрагментация пакетов** | MTU туннеля не уменьшен | `ping -M do -s 1452 -c 1 <remote>` | Уменьшить MTU: `ip link set ipip0 mtu 1480` |
| **Пакеты дропаются (rp_filter)** | Strict reverse path filtering | `sysctl net.ipv4.conf.all.rp_filter` | `sysctl -w net.ipv4.conf.all.rp_filter=0` |
| **FOU не работает** | Модуль fou не загружен | `lsmod \| grep fou` | `sudo modprobe fou` |
| **NAT-транзит не работает** | IPIP/SIT без FOU через NAT | `tcpdump -ni any proto 4` | Использовать FOU или GRE |
| **Пакеты отбрасываются firewall** | nftables/iptables блокируют proto 4/41 | `nft list ruleset \| grep ipip` | Добавить правило: `nft add rule ip filter input ip protocol ipip accept` |
| **SIT-туннель не поднимается** | Конфликт с auto tunnels | `ip tunnel show mode sit` | Удалить auto tunnels: `ip tunnel del sit0` |
| **TTL туннеля = 1** | По умолчанию TTL не задан | `ip -d link show ipip0 \| grep ttl` | Указать TTL: `ip link add name ipip0 type ipip ... ttl 64` |
| **Модуль ipip/sit не найден** | Ядро собрано без поддержки | `modprobe ipip` | Включить в config: `CONFIG_NET_IPPIP=m` |

---

## Лучшие практики

### Безопасность

1. **Фильтрация по внешнему IP:**
   ```bash
   # Разрешить IPIP только от доверенного peer
   sudo nft add rule ip filter input ip saddr 2.2.2.2 ip protocol ipip accept
   sudo nft add rule ip filter input ip protocol ipip drop
   ```

2. **Настройка rp_filter:**
   ```bash
   # Strict mode для туннельных интерфейсов
   sudo sysctl -w net.ipv4.conf.ipip0.rp_filter=1

   # Loose mode (если strict вызывает проблемы)
   sudo sysctl -w net.ipv4.conf.ipip0.rp_filter=2
   ```

3. **Ограничение TTL:**
   ```bash
   # Отбрасывать пакеты с TTL < 64 (защита от loopback)
   sudo nft add rule ip filter input ip ttl lt 64 drop
   ```

### MTU-тюнинг

| Сценарий | Рекомендуемый MTU | Пояснение |
| :--- | :--- | :--- |
| **IPIP (чистый)** | 1480 | 1500 - 20 (IPv4 header) |
| **IPIP + IPsec** | 1420 | 1500 - 20 (IPIP) - 60 (ESP) |
| **SIT (чистый)** | 1480 | 1500 - 20 (IPv4 header) |
| **SIT + IPsec** | 1420 | 1500 - 20 (SIT) - 60 (ESP) |

```bash
# Установка MTU
sudo ip link set ipip0 mtu 1480

# MSS Clamping через nftables
nft add rule inet filter forward oifname "ipip0" tcp flags syn tcp option maxseg size set 1440
```

### Персистентность

**systemd-юнит для IPIP-туннеля:**
```ini
# /etc/systemd/system/ipip0.service
[Unit]
Description=IPIP tunnel ipip0
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/sbin/ip link add name ipip0 type ipip local 1.1.1.1 remote 2.2.2.2
ExecStart=/sbin/ip link set ipip0 up
ExecStart=/sbin/ip addr add 10.0.0.1/30 dev ipip0
ExecStop=/sbin/ip link delete ipip0
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable ipip0.service
sudo systemctl start ipip0.service
```

**Netplan (/etc/netplan/01-tunnels.yaml):**
```yaml
network:
  tunnels:
    ipip0:
      mode: ipip
      local: 1.1.1.1
      remote: 2.2.2.2
      addresses:
        - 10.0.0.1/30
```

### Очистка

```bash
# Удаление IPIP-туннеля
sudo ip link delete ipip0

# Удаление FOU-порта
sudo ip fou del port 5555

# Проверка, что интерфейс удалён
ip link show ipip0
# → Device "ipip0" does not exist.

# Остановка systemd-юнита
sudo systemctl stop ipip0.service
sudo systemctl disable ipip0.service
sudo rm /etc/systemd/system/ipip0.service
sudo systemctl daemon-reload
```

---

## Граничные случаи и ограничения

1. **IPIP не поддерживает multicast:** В отличие от GRE, IPIP не может передавать multicast-трафик. Для multicast используйте GRE или VXLAN.

2. **Конфликт с auto tunnels:** В Linux по умолчанию создаётся `sit0` для автоматических 6to4-туннелей. При создании собственного SIT-туннеля убедитесь, что имя не конфликтует.

3. **Одновременные IPIP и IPsec:** При использовании IPIP поверх IPsec учитывайте累积ный overhead (20 + 60 = 80 байт). MTU должен быть уменьшен до 1420.

4. **FOU и RSS (Receive Side Scaling):** FOU-инкапсуляция позволяет использовать RSS для балансировки туннельного трафика по ядрам CPU. Убедитесь, что RSS включён на NIC:
   ```bash
   ethtool -l eth0
   ethtool -K eth0 rxhash on
   ```

5. **Без шифрования — без защиты:** IPIP и SIT не имеют встроенной аутентификации. Всегда используйте их в комбинации с IPsec или в доверенных сетях.

6. **MTU и PMTUD:** Если удалённый хост не поддерживает PMTUD (блокирует ICMP), пакеты будут фрагментироваться. Используйте MSS Clamping для предотвращения проблем.

7. **NAT и IPIP/SIT:** Без FOU туннели IPIP/SIT не работают через NAT. При необходимости транзита через NAT всегда используйте FOU или переходите на WireGuard/GRE.

---

## Дополнительная информация

### Сравнение с альтернативами

| Технология | Overhead | NAT-T | Протоколы | Особенности |
| :--- | :--- | :--- | :--- | :--- |
| **IPIP / SIT** | **20 B** | Нет | IPv4 / IPv6 | Самый эффективный, но «капризный». |
| **GRE** | 24–28 B | Нет | Любые | Поддержка мультикаста и L2 (GRETAP). |
| **WireGuard** | ~60 B | Да | Любые | Встроенное шифрование, работа через UDP. |
| **VXLAN** | 50 B | Да | Ethernet | Стандарт для дата-центров и Kubernetes. |

### Связанные документы

- **[Обзор туннелирования](./tunneling_overview.md)** — классификация и выбор технологии.
- **[Проблемы MTU и фрагментация](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — глубокий разбор PMTUD.
- **[Туннели GRE](./gre/gre.md)** — когда IPIP недостаточно.
- **[Туннелирование IPv6 в Linux](../../Linux/Networking/Settings/ipv6_configuration/tunneling.md)** — специфика работы с SIT и Tunnelbroker.
- **[Механизм IPsec](./ipsec/ipsec.md)** — добавление шифрования к туннелям.
