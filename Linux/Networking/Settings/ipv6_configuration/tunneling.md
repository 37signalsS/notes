# Туннелирование IPv6 в Linux

## Определения

**Туннелирование IPv6** — технология передачи IPv6-пакетов через сетевую инфраструктуру, поддерживающую другие протоколы (обычно IPv4), путем их инкапсуляции в «несущие» пакеты. В контексте IPv6 туннелирование используется для:
- Подключения к брокерам IPv6 через IPv4-интернет (например, Tunnelbroker).
- Организации Site-to-Site связности между IPv6-сетями через промежуточные IPv4-сегменты.
- Интеграции IPv6-only сегментов с legacy IPv4-инфраструктурой.

**Основные протоколы и технологии:**

- **WireGuard**: современный высокопроизводительный VPN-протокол с нативной поддержкой IPv6. Рекомендуемый стандарт безопасности и производительности.
- **SIT (Simple Internet Transition, 6in4)**: инкапсуляция IPv6 в IPv4 (протокол IP 41). Широко используется для подключения к брокерам IPv6 (например, Tunnelbroker).
- **GRE (Generic Routing Encapsulation)**: универсальный протокол (IP 47). Поддерживает L3 (GRE) и L2 (GRETAP) туннелирование.
- **6rd (IPv6 Rapid Deployment)**: механизм быстрого развертывания IPv6 через IPv4-сети провайдеров ([RFC 5969](https://datatracker.ietf.org/doc/html/rfc5969)).
- **MAP-E / MAP-T**: современные методы трансляции и инкапсуляции для обеспечения связи IPv6-only клиентов с IPv4-интернетом.
- **FOU / GUE (Foo Over UDP / Generic UDP Encapsulation)**: инкапсуляция SIT/GRE в UDP-пакеты для обхода NAT и улучшения балансировки (RSS/ECMP).
- **6to4 / Teredo**: автоматические механизмы, считающиеся **устаревшими** ([RFC 7526](https://datatracker.ietf.org/doc/html/rfc7526)). Не рекомендуются для промышленного использования.

## Основные концепции

### Реализация в современном Linux

В современных дистрибутивах (ядро 6.x+) управление туннелями выполняется через универсальные интерфейсы:

1.  **ip link (iproute2)**: основной инструмент. Позволяет создавать туннели как виртуальные сетевые устройства.
2.  **NetworkManager (nmcli)**: стандарт для персистентных настроек на серверах.
3.  **systemd-networkd**: предпочтительный метод для облачных сред и инфраструктуры как код (IaC).

### Принцип инкапсуляции и обработка заголовков

При инкапсуляции IPv6 в IPv4 (SIT) или IPv4 в IPv4 (IPIP) ядро Linux выполняет следующие действия:
1. Внутренний IPv6/IPv4 пакет помещается в поле полезной нагрузки внешнего IPv4-пакета.
2. Внешний заголовок получает адреса конечных точек туннеля (`local` и `remote`).
3. Поле **Next Header** во внешнем заголовке указывает протокол инкапсуляции (41 для SIT, 4 для IPIP, 47 для GRE).
4. При декапсуляции на удаленной стороне внешние заголовки удаляются, внутренний пакет передается на обработку стеку IPv6 или IPv4.

**Особенности TTL/Hop Limit:**
- В IPv4 используется поле **TTL** (Time To Live). При инкапсуляции значение TTL внутреннего пакета уменьшается на 1.
- В IPv6 используется поле **Hop Limit**. Для туннелей IPv6-over-IPv4 аналогичная логика применяется к внешнему IPv4-заголовку, а внутренний IPv6-заголовок сохраняет собственный Hop Limit.
- Рекомендуется использовать `ttl inherit` при создании туннеля, чтобы traceroute корректно отображал путь через туннель.

### Специфика IPv6-туннелей

В отличие от IPv4, где NAT является обычным явлением, «чистый» IPv6 не предполагает NAT. Это влияет на туннелирование следующим образом:
- **Отсутствие портов**: протоколы SIT (IP 41) и GRE (IP 47) не имеют L4-портов. Классический PAT не может сопоставить их с сессиями, что делает такие туннели несовместимыми с большинством SOHO-роутеров и NAT.
- **PMTUD критичнее**: в IPv6 маршрутизаторы **не фрагментируют** пакеты. Если инкапсулированный пакет превышает MTU пути, он отбрасывается, и отправляется **ICMPv6 Type 2 (Packet Too Big)**. Блокировка этого типа на файрволе создает «черную дыру» MTU (PMTUD Black Hole).
- **ICMPv6 обязателен**: в отличие от IPv4, где можно ограничивать ICMP, для работы IPv6 требуется разрешать определенные типы ICMPv6 (NDP, MLD, Packet Too Big).

### 6rd и MAP-E / MAP-T

**6rd (IPv6 Rapid Deployment)** — механизм, при котором провайдер инкапсулирует IPv6-трафик в IPv4, используя заранее выделенные IPv4-адреса. Отличается от обычного SIT тем, что использует только часть IPv6-префикса для маршрутизации, что снижает накладные расходы на таблицы маршрутизации.

**MAP-E (Mapping of Address and Port using Encapsulation)** и **MAP-T (Mapping of Address and Port using Translation)** — современные методы (RFC 7597, RFC 7599), обеспечивающие связь IPv6-only клиентов с IPv4-интернетом через туннелирование или трансляцию. MAP-E использует инкапсуляцию (GRE), MAP-T — stateless трансляцию.

### Технические нюансы и ограничения

- **MTU (Maximum Transmission Unit)**: Инкапсуляция добавляет дополнительные заголовки, уменьшая полезный объем данных (Payload).
    - **SIT/IPIP**: 20 байт (IPv4-header) → MTU 1480.
    - **WireGuard**: ~60-80 байт → MTU 1420.
    - **GRE**: 24-28 байт → MTU 1476.
    - **FOU/GUE**: ~32 байт (UDP + encapsulation) → MTU 1468.
- **PMTUD (Path MTU Discovery)**: Для корректной работы туннелей необходимо разрешать **ICMPv6 Type 2 (Packet Too Big)**. Блокировка этого типа сообщений приводит к «зависанию» TCP-сессий при передаче крупных пакетов.
- **MSS Clamping**: Механизм принудительного уменьшения значения MSS (Maximum Segment Size) в TCP SYN пакетах. Это гарантирует, что хосты не будут отправлять пакеты больше, чем может пропустить туннель.
- **Безопасность**: туннели SIT, GRE, IPIP передают трафик без шифрования. Для защиты используйте IPsec (VTI) или WireGuard.

## Практические сценарии

### 1. WireGuard (IPv6 через UDP)

Обеспечивает нативную поддержку IPv6 и высокую скорость.

```bash
# Создание интерфейса
sudo ip link add dev wg0 type wireguard

# Настройка (подробности в Vpn/wireguard.md)
sudo wg set wg0 private-key ./private.key peer <PublicKey> endpoint <IPv4>:51820 allowed-ips 2001:db8:1::/64

# Активация
sudo ip addr add 2001:db8:1::1/64 dev wg0
sudo ip link set wg0 up
```

### 2. SIT-туннель (6in4) через ip link

Классический метод инкапсуляции (протокол 41).

```bash
# Создание устройства SIT
sudo ip link add name sit1 type sit remote <remote_ipv4> local <local_ipv4> ttl 64

# Поднятие интерфейса и назначение адреса
sudo ip link set sit1 up
sudo ip addr add 2001:db8:abc::2/64 dev sit1

# Установка маршрута по умолчанию через туннель
sudo ip -6 route add default dev sit1
```

### 3. GRE-туннель через ip link

Универсальный L3-туннель (протокол 47). Поддерживает инкапсуляцию любых протоколов, включая IPv6.

```bash
# Создание GRE-туннеля
sudo ip link add name gre1 type gre remote <remote_ipv4> local <local_ipv4> ttl 64

# Поднятие и настройка IPv6
sudo ip link set gre1 up
sudo ip addr add 2001:db8:gre::1/64 dev gre1

# Маршрут через туннель
sudo ip -6 route add 2001:db8:gre::2 dev gre1
```

Для GRETAP (L2-туннель):
```bash
sudo ip link add name gretap1 type gretap remote <remote_ipv4> local <local_ipv4>
sudo ip link set gretap1 up
```

### 4. Настройка MSS Clamping (nftables / ip6tables)

Рекомендуемый способ решения проблем с MTU в туннелях. Значения MSS зависят от типа туннеля:

| Туннель | Overhead | Рекомендуемый MSS (при MTU 1500) |
| :--- | :--- | :--- |
| **SIT / IPIP** | 20 B | 1460 |
| **GRE (без ключа)** | 24 B | 1456 |
| **GRE (с ключом)** | 28 B | 1452 |
| **WireGuard** | ~60 B | 1420 |
| **FOU / GUE** | ~32 B | 1448 |
| **VXLAN over IPv4** | ~50 B | 1440 |
| **VXLAN over IPv6** | ~70 B | 1410 |

**nftables:**
```bash
# /etc/nftables.conf
table inet filter {
    chain forward {
        type filter hook forward priority 0;
        # MSS Clamping для трафика через SIT (MTU 1480 → MSS 1460)
        oifname "sit1" tcp flags syn tcp option maxseg size set 1460

        # MSS Clamping для трафика через GRE (MTU 1476 → MSS 1456)
        oifname "gre1" tcp flags syn tcp option maxseg size set 1456

        # MSS Clamping для трафика через WireGuard (MTU ~1420 → MSS 1420)
        oifname "wg0" tcp flags syn tcp option maxseg size set 1420
    }
}
```

**ip6tables (legacy):**
```bash
sudo ip6tables -t mangle -A FORWARD -o sit1 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1460
sudo ip6tables -t mangle -A FORWARD -o gre1 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1456
sudo ip6tables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1420
```

### 5. Настройка 6rd через ip link

6rd использует аналогичный с SIT синтаксис, но с дополнительными параметрами для указания префикса.

```bash
# Создание 6rd-туннеля
sudo ip link add name 6rd1 type sit remote <remote_ipv4> local <local_ipv4> ttl 64
sudo ip link set 6rd1 up

# Настройка 6rd-параметров
sudo ip tunnel change 6rd1 mode any ttl 64

# Назначение IPv6-адреса (префикс от провайдера)
sudo ip addr add 2001:db8:6rd::1/64 dev 6rd1

# Маршрут по умолчанию
sudo ip -6 route add default dev 6rd1
```

### 6. FOU / GUE (инкапсуляция в UDP)

Позволяет передавать GRE/SIT через NAT и балансировщики.

```bash
# Загрузка модуля FOU
sudo modprobe fou

# Создание FOU-порта (UDP 6666)
sudo ip fou add port 6666 ipproto 47

# Создание GRE поверх FOU
sudo ip link add name gre-fou1 type gre remote <remote_ipv4> local <local_ipv4> encap fou encap-sport auto encap-dport 6666
sudo ip link set gre-fou1 up
sudo ip addr add 2001:db8:fou::1/64 dev gre-fou1
```

### 7. Netplan (Ubuntu 18.04+ / Debian)

Персистентная настройка через YAML.

```yaml
# /etc/netplan/10-sit.yaml
network:
  version: 2
  tunnels:
    sit1:
      mode: sit
      local: <local_ipv4>
      remote: <remote_ipv4>
      mtu: 1480
      addresses:
        - 2001:db8:beef::1/64
      routes:
        - to: default
          via: ::1
          on-link: true
```

Применение:
```bash
sudo netplan apply
```

### 8. NetworkManager / nmcli

Персистентная настройка на рабочих станциях и серверах.

```bash
# Создание SIT-туннеля
sudo nmcli connection add type ip-tunnel ifname sit1 mode sit remote <remote_ipv4> local <local_ipv4>
sudo nmcli connection modify sit1 ipv4.method disabled ipv6.method manual ipv6.addresses 2001:db8:beef::1/64
sudo nmcli connection up sit1

# Создание GRE-туннеля
sudo nmcli connection add type ip-tunnel ifname gre1 mode gre remote <remote_ipv4> local <local_ipv4>
sudo nmcli connection modify gre1 ipv4.method disabled ipv6.method manual ipv6.addresses 2001:db8:gre::1/64
sudo nmcli connection up gre1
```

### 9. systemd-networkd (Персистентная настройка)

Идеально для серверов.

```ini
# /etc/systemd/network/10-sit.netdev
[NetDev]
Name=sit1
Kind=sit

[Tunnel]
Local=<local_ipv4>
Remote=<remote_ipv4>

# /etc/systemd/network/10-sit.network
[Match]
Name=sit1

[Network]
Address=2001:db8:beef::1/64
```

```ini
# /etc/systemd/network/10-gre.netdev
[NetDev]
Name=gre1
Kind=gre

[Tunnel]
Local=<local_ipv4>
Remote=<remote_ipv4>

# /etc/systemd/network/10-gre.network
[Match]
Name=gre1

[Network]
Address=2001:db8:gre::1/64
```

Применение:
```bash
sudo systemctl restart systemd-networkd
```

## Диагностика и проверка

### Анализ состояния туннеля

```bash
# Просмотр параметров и оверхеда
ip -d link show sit1

# Просмотр статистики ошибок (дропы из-за MTU)
ip -s link show sit1

# Список всех активных туннелей IPv6
ip -6 tunnel show
```

### Проверка MTU

```bash
# Трассировка с определением MTU на пути
tracepath6 -n 2001:db8:beef::2

# Проверка прохождения пакетов заданного размера без фрагментации
# Для SIT (MTU 1480): payload 1452 + 28 (IPv6+ICMPv6) = 1480
ping6 -M do -s 1452 2001:db8:beef::2

# Для WireGuard (MTU ~1420): payload 1392 + 28 = 1420
ping6 -M do -s 1392 2001:db8:1::2
```

### Проверка связности через туннель

```bash
# Ping через туннельный интерфейс
ping6 -I sit1 2001:db8:beef::2

# Traceroute через туннель (проверка пути)
traceroute6 -i sit1 2001:db8:beef::2

# Проверка маршрута до удаленного адреса
ip -6 route get 2001:db8:beef::2
```

### Перехват и анализ трафика

```bash
# Просмотр инкапсулированного трафика на физическом интерфейсе
sudo tcpdump -i eth0 proto 41 -c 10

# Просмотр расшифрованного IPv6-трафика на туннельном интерфейсе
sudo tcpdump -i sit1 -n ip6 -c 10

# Перехват ICMPv6 Packet Too Big (диагностика PMTUD)
sudo tcpdump -i eth0 'icmp6 and icmp6[0] == 2' -nn
```

## Типичные ошибки и устранение

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Tunnel is down / NOARP** | Интерфейс не поднят | `ip link show <tunnel>` | `ip link set <tunnel> up` |
| **Нет connectivity через туннель** | IP-форвардинг отключен | `sysctl net.ipv6.conf.all.forwarding` | `sysctl -w net.ipv6.conf.all.forwarding=1` |
| **TCP зависает, ping проходит** | PMTUD Black Hole | `tcpdump -i eth0 icmp6[0] == 2` | Настроить MSS Clamping, разрешить ICMPv6 Type 2 |
| **Фрагментация пакетов** | MTU туннеля не уменьшен | `ping6 -M do -s <size> <peer>` | Уменьшить MTU / настроить MSS Clamping |
| **FOU не работает** | Модуль fou не загружен | `lsmod | grep fou` | `sudo modprobe fou` |
| **Пакеты отбрасываются firewall** | nftables блокирует протокол | `nft list ruleset | grep <proto>` | Добавить правила разрешения |
| **GRE с ключом не работает** | Ключ не совпадает | `ip -d link show <gre_if>` | Проверить ключи на обоих узлах |
| **Адрес в `tentative`** | DAD не завершен или петля L2 | `ip -6 addr show` | Проверить DAD, исключить петли |

## Дополнительная информация

### Настройка файрвола

Для работы туннелей необходимо разрешить транспортные протоколы.

| Технология | Протокол/Порт | Правило nftables |
| :--- | :--- | :--- |
| **SIT** | IP 41 | `ip protocol 41 accept` |
| **GRE** | IP 47 | `ip protocol 47 accept` |
| **WireGuard** | UDP 51820 | `udp dport 51820 accept` |
| **FOU/GUE** | UDP (custom) | `udp dport 6666 accept` |

### Лучшие практики

1. **Всегда настраивайте MSS Clamping** для туннелей, особенно если трафик включает крупные файлы или BLOB-передачи.
2. **Используйте `ttl inherit`** при создании туннеля для корректной работы traceroute.
3. **Привязывайте туннель к интерфейсу** (`dev` параметр) на multi-homed серверах, чтобы избежать утечки трафика.
4. **Разрешайте ICMPv6 Type 2** на файрволе для поддержки PMTUD.
5. **Для production используйте WireGuard** вместо SIT/GRE, если не требуется поддержка multicast или L2-туннелирование.

### См. также

- **[Firewall для IPv6](./firewall.md)** — критические правила ICMPv6 и фильтрация.
- **[Диагностика IPv6](./diagnostics.md)** — методы отладки NDP и PMTUD.
- **[Туннели IPIP и SIT](../../../../Networking/Tunnels/ipip_and_sit.md)** — глубокая теория инкапсуляции.
- **[Мониторинг IPv6](./monitoring.md)** — Prometheus, Blackbox Exporter, alerting для IPv6.
