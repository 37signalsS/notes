# Протокол GRE (Generic Routing Encapsulation)

## Определения и назначение

**GRE (Generic Routing Encapsulation)** — универсальный протокол туннелирования, разработанный Cisco, предназначенный для инкапсуляции широкого спектра протоколов сетевого уровня (L3) и канального уровня (L2) внутри IP-пакетов.

Протокол обеспечивает создание виртуальных каналов «точка-точка» (Point-to-Point) или «точка-многоточка» (Multipoint) поверх существующей IP-инфраструктуры. Определяется стандартами [RFC 2784](https://datatracker.ietf.org/doc/html/rfc2784) и [RFC 2890](https://datatracker.ietf.org/doc/html/rfc2890).

**Ключевые характеристики:**

| Параметр | Значение |
|----------|----------|
| **Протокол в IP-заголовке** | IP 47 |
| **Уровень OSI** | L3 (базовый), L2 (в режиме GRETAP) |
| **Шифрование** | Отсутствует (трафик передаётся в открытом виде) |
| **Аутентификация** | Опционально через поле Key (слабая защита) |
| **Топология** | Point-to-Point, Multipoint (mGRE) |
| **Overhead** | 24–28 байт (L3), ~42 байта (GRETAP) |

---

## Архитектура и основные концепции

### Формат заголовка GRE

Заголовок GRE добавляется между внешним IP-заголовком и полезной нагрузкой. Минимальный размер составляет 4 байта.

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|C|R|K|S|s|Recur|  Flags  | Ver |         Protocol Type         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|      Checksum (optional)      |       Reserved1 (optional)    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Key (optional)                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                 Sequence Number (optional)                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

**Флаги и ключевые поля:**

| Поле | Описание |
|------|----------|
| **C (Checksum)** | Бит 0. Указывает на наличие поля контрольной суммы (Checksum). |
| **R (Routing)** | Бит 1. Зарезервирован. Должен быть 0. |
| **K (Key)** | Бит 2. Указывает на наличие поля Key (32-битный идентификатор туннеля). |
| **S (Sequence Number)** | Бит 3. Указывает на наличие порядкового номера для контроля последовательности. |
| **s (Strict Source Route)** | Бит 4. Строгая маршрутизация по источнику. |
| **Recur** | 3 бита. Количество рекурсивных инкапсуляций (обычно 0). |
| **Flags** | 5 бит. Зарезервированы, должны быть 0. |
| **Ver** | Версия протокола. `0` — стандартный GRE, `1` — используется в PPTP. |
| **Protocol Type** | Тип инкапсулированного протокола (EtherType). Основные значения: `0x0800` — IPv4, `0x86DD` — IPv6, `0x6558` — Ethernet (GRETAP), `0x88BE` — ERSPAN. |
| **Key** | 32-битный идентификатор. Используется для мультиплексирования туннелей или простой аутентификации. Не является криптографическим ключом. |
| **Sequence Number** | Порядковый номер пакета. Используется для обнаружения потерь и порядка доставки (опционально). |

### Режимы работы и модификации

1.  **Point-to-Point GRE:** Классический туннель между двумя фиксированными IP-адресами. Простейшая конфигурация, не требует дополнительных протоколов разрешения адресов.
2.  **Multipoint GRE (mGRE):** Позволяет одному интерфейсу терминировать множество туннелей. Адреса удаленных точек определяются динамически через протокол **NHRP (Next Hop Resolution Protocol)**. Является основой технологии **DMVPN (Dynamic Multipoint VPN)**.
3.  **GRETAP (L2 GRE):** Режим инкапсуляции Ethernet-кадров. В заголовке GRE используется Protocol Type `0x6558` (Transparent Ethernet Bridging). Позволяет объединять удаленные сегменты L2 в один мост (bridge). Оверхед увеличивается до ~42 байт (20 IP + 4-12 GRE + 14 Ethernet).
4.  **ERSPAN (Encapsulated Remote SPAN):** Расширение GRE (Protocol Type `0x88BE`) для зеркалирования трафика L2 через маршрутизируемые IP-сети. Используется для централизованного мониторинга и анализа трафика. Поддерживает две версии: v1 (Cisco) и v2 (современная, стандарт Linux).

### Принцип инкапсуляции

1.  **Поступление пакета:** Пакет (IPv4, IPv6, Ethernet) поступает на туннельный интерфейс.
2.  **Инкапсуляция GRE:** Добавляется заголовок GRE (4–12 байт) в зависимости от используемых опций (Key, Checksum, Sequence).
3.  **Внешний заголовок:** Добавляется внешний IP-заголовок (обычно IPv4, 20 байт) с адресами конечных точек туннеля (`source` и `destination`).
4.  **Маршрутизация:** Пакет маршрутизируется через транзитную сеть как обычный IP-трафик (протокол 47). Промежуточные маршрутизаторы не видят инкапсулированный трафик — для них это обычные IP-пакеты.
5.  **Декапсуляция:** На удалённой стороне outer IP и GRE заголовки снимаются, внутренний пакет передаётся во внутреннюю сеть или обрабатывается локально.

---

## Практическая реализация

### Предварительные требования

- Два Linux-хоста с маршрутизируемыми (публичными или внутренними) IP-адресами
- Загруженный модуль ядра: `modprobe ip_gre` (проверка: `lsmod | grep ip_gre`)
- Утилита `ip` из пакета `iproute2` (установлена во всех современных дистрибутивах)
- Root-доступ или права `sudo`
- Разрешён протокол IP 47 (GRE) в файрволе между эндпоинтами

### Базовая настройка Point-to-Point GRE в Linux

```bash
# === Хост A (198.51.100.1) ===

# Создание GRE-туннеля
sudo ip link add dev gre0 type gre \
    local 198.51.100.1 \
    remote 203.0.113.2 \
    ttl inherit \
    key 100

# Установка MTU (рекомендуется 1400 для запаса под IPsec при необходимости)
sudo ip link set gre0 mtu 1400

# Назначение IP-адреса внутри туннеля
sudo ip address add 10.0.0.1/30 dev gre0

# Активация интерфейса
sudo ip link set gre0 up

# Добавление маршрута до удалённой подсети через туннель
sudo ip route add 172.16.0.0/24 via 10.0.0.2 dev gre0

# === Хост B (203.0.113.2) ===
sudo ip link add dev gre0 type gre \
    local 203.0.113.2 \
    remote 198.51.100.1 \
    ttl inherit \
    key 100
sudo ip link set gre0 mtu 1400
sudo ip address add 10.0.0.2/30 dev gre0
sudo ip link set gre0 up
sudo ip route add 192.168.0.0/24 via 10.0.0.1 dev gre0
```

**Параметры:**

| Параметр | Описание |
|----------|----------|
| `local` / `remote` | Внешние IP-адреса эндпоинтов туннеля |
| `key` | 32-битный идентификатор туннеля (должен совпадать на обоих концах) |
| `ttl inherit` | Наследование TTL от внутреннего пакета (рекомендуется для корректного `traceroute`) |
| `mtu` | Установка MTU для предотвращения фрагментации |

### Настройка GRETAP (L2-туннель)

Используется для объединения двух удаленных сегментов в один программный мост (bridge):

```bash
# Создание GRETAP-туннеля
sudo ip link add dev tap0 type gretap \
    local 198.51.100.1 \
    remote 203.0.113.2

# Добавление в мост (предполагается, что br0 уже создан)
sudo ip link set tap0 master br0
sudo ip link set tap0 mtu 1450
sudo ip link set tap0 up
```

### Настройка ERSPAN (зеркалирование трафика)

```bash
# erspan_ver 1 (совместимость с Cisco) или 2 (современный Linux)
# erspan <ID> — идентификатор сессии зеркалирования
sudo ip link add dev erspan0 type erspan \
    local 198.51.100.1 \
    remote 203.0.113.2 \
    erspan_ver 2 erspan 10
sudo ip link set erspan0 up
```

### Настройка файрвола

GRE использует IP-протокол 47 (не TCP/UDP), поэтому классические правила портов не работают.

**nftables (рекомендуется):**
```bash
# Разрешение входящего GRE-трафика
nft add rule inet filter input ip protocol gre accept

# РазрешениеGRE только от конкретного эндпоинта (безопаснее)
nft add rule inet filter input ip saddr 203.0.113.2 ip protocol gre accept
```

**iptables (legacy):**
```bash
sudo iptables -A INPUT -p 47 -s 203.0.113.2 -j ACCEPT
sudo iptables -A INPUT -p 47 -j DROP
```

**Для FOU (GRE-over-UDP):**
```bash
# Разрешение UDP-порта для FOU
nft add rule inet filter input udp dport 6666 accept
```

### Настройка Keepalive

GRE — **stateless-протокол**. Интерфейс остаётся в состоянии `UP`, даже если удалённая точка недоступна. Это приводит к «чёрной дыре» маршрутизации.

**Важно:** Ядро Linux (`ip_gre`) **не поддерживает** нативные Cisco-style keepalives в большинстве версий. Команда `ip tunnel change gre1 keepalive 10 3` доступна начиная с ядер 5.10+, но поведение может отличаться от Cisco IOS. При межplatformном взаимодействии (Linux-Cisco) рекомендуется отключать keepalive на стороне Cisco и использовать альтернативные механизмы.

**Альтернативные механизмы обнаружения недоступности удалённой точки:**

1.  **Рouting protocol dead-timers (рекомендуется):** Запуск OSPF/BGP через туннель. Протокол маршрутизации обнаруживает отказ через hello/dead таймеры и автоматически выводит маршрут из таблицы.
    ```bash
    # FRRouting: OSPF на GRE-интерфейсе
    vtysh << 'EOF'
    conf t
    interface gre0
      ip ospf area 0
      ip ospf hello-interval 5
      ip ospf dead-interval 20
    EOF
    ```

2.  **BFD (Bidirectional Forwarding Detection):** Обнаружение отказов за <1 секунду. Работает через FRRouting.
    ```bash
    vtysh << 'EOF'
    conf t
    interface gre0
      bfd profile fast
    EOF
    ```

3.  **Пользовательский скрипт (ping-based):** Простой мониторинг через cron.
    ```bash
    # /usr/local/bin/gre-check.sh
    #!/bin/bash
    REMOTE Tunnel_IP="203.0.113.2"
    FAILURES=0
    for i in {1..3}; do
        ping -c 1 -W 2 $REMOTE_IP > /dev/null 2>&1 || ((FAILURES++))
    done
    if [ "$FAILURES" -ge 3 ]; then
        logger "GRE tunnel to $REMOTE_IP is DOWN"
        # Здесь: алерт, переключение на резервный канал и т.д.
    fi
    ```

4.  **eBPF/XDP-решение:** Проект [linux-gre-keepalive](https://github.com/jamesits/linux-gre-keepalive) добавляет поддержку reply-only keepalive через XDP. Требует загрузки eBPF-программы:
    ```bash
    ip link set dev gre0 xdp object build/keepalive_gre.o
    # Отключение: ip link set dev gre0 xdp off
    ```

**На Cisco IOS (для Cisco-to-Cisco туннелей):**
```
interface Tunnel0
 keepalive 10 3
```

### Решение проблем MTU и MSS

Инкапсуляция увеличивает размер пакета, что может привести к превышению MTU физического канала и фрагментации.

**Расчёт эффективного MTU (при физическом MTU 1500):**

| Конфигурация | Оверхед (байт) | Итоговый MTU |
|--------------|----------------|--------------|
| **GRE (базовый)** | 24 (20 IP + 4 GRE) | **1476** |
| **GRE + Key** | 28 (20 IP + 8 GRE) | **1472** |
| **GRE + Checksum + Key** | 32 (20 IP + 12 GRE) | **1468** |
| **GRETAP (L2)** | 42 (20 IP + 8 GRE + 14 Ethernet) | **1458** |
| **GRE over UDP (FOU)** | 32 (20 IP + 8 UDP + 4 GRE) | **1468** |
| **GRE + IPsec (Transport)** | 56–96 | **1404–1444** |

**MSS Clamping:** Для предотвращения «зависания» TCP-сессий из-за блокировки ICMP (PMTUD Black Hole) необходимо принудительно ограничивать MSS.

```bash
# iptables: автоматическая подстройка под PMTU
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre0 -j TCPMSS --clamp-mss-to-pmtu

# iptables: жёсткая установка MSS (для MTU 1400 → MSS = 1400 - 40 = 1360)
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre0 -j TCPMSS --set-mss 1360

# nftables
nft add rule inet filter forward oifname "gre0" tcp flags syn \
    tcp option maxseg size set rt mtu
```

**Проверка MTU через туннель:**
```bash
# -M do — запрет фрагментации (DF=1)
# -s <размер> = MTU - 28 (20 IP + 8 ICMP)
ping -M do -s 1372 10.0.0.2    # Проверка MTU 1400
ping -M do -s 1452 10.0.0.2    # Проверка MTU 1480
```

### Прохождение через NAT (NAT Traversal)

Стандартный GRE (IP 47) не имеет портов, поэтому классический PAT (Port Address Translation) может обслуживать только один GRE-туннель за одним публичным IP.

**Решение — FOU (Foo Over UDP):** Инкапсуляция GRE внутри UDP-пакета. Это позволяет использовать порты для NAT и задействовать аппаратное ускорение RSS/ECMP на промежуточных узлах.

```bash
# 1. Создание UDP-слушателя для GRE (порт 6666)
sudo ip fou add port 6666 ipproto 47

# 2. Создание туннеля, упакованного в UDP
sudo ip link add name gre_fou type gre \
    remote 203.0.113.2 local 198.51.100.1 \
    encap fou encap-sport auto encap-dport 6666

sudo ip link set gre_fou up
sudo ip address add 10.0.10.1/30 dev gre_fou
```

**Другие методы:**
*   **PPTP ALG:** Использование помощников (Application Layer Gateway) на домашних роутерах.
*   **DDNS + policy-based routing:** Динамическое обновление DNS-записи с последующей маршрутизацией по имени.

### Постоянная конфигурация (Persistence)

Команды `ip link add`/`ip tunnel add` действуют до перезагрузки. Для сохранения настроек:

**Netplan (Ubuntu/Debian):**
Файл `/etc/netplan/60-gre-tunnel.yaml`:
```yaml
network:
  version: 2
  tunnels:
    gre0:
      mode: gre
      local: 198.51.100.1
      remote: 203.0.113.2
      addresses:
        - 10.0.0.1/30
      keys:
        input: 100
        output: 100
      routes:
        - to: 172.16.0.0/24
          via: 10.0.0.2
```

**systemd-networkd:**
Файл `/etc/systemd/network/25-gre.netdev`:
```ini
[NetDev]
Name=gre0
Kind=gre

[Tunnel]
Local=198.51.100.1
Remote=203.0.113.2
Key=100
```

Файл `/etc/systemd/network/25-gre.network`:
```ini
[Match]
Name=gre0

[Network]
Address=10.0.0.1/30

[Route]
Destination=172.16.0.0/24
Gateway=10.0.0.2
```

**NetworkManager (nmcli):**
```bash
sudo nmcli connection add type ip-tunnel ifname gre0 con-name gre0-tunnel \
    mode gre remote 203.0.113.2 local 198.51.100.1 \
    ip-tunnel.input-key 100 ip-tunnel.output-key 100

sudo nmcli connection modify gre0-tunnel ipv4.addresses 10.0.0.1/30 ipv4.method manual
sudo nmcli connection modify gre0-tunnel +ipv4.routes "172.16.0.0/24 10.0.0.2"
sudo nmcli connection up gre0-tunnel
```

### Аппаратное ускорение и производительность

Современные сетевые карты (NIC) поддерживают функции разгрузки для GRE:
*   **TSO/GSO (Segmentation Offload):** Позволяет ОС передавать большие блоки данных карте, которая сама разбивает их на пакеты с правильными GRE/IP заголовками.
*   **GRO (Receive Offload):** Агрегация входящих GRE-пакетов в один большой буфер перед передачей в стек протоколов ОС.
*   **RSS (Receive Side Scaling):** Балансировка входящего инкапсулированного трафика по ядрам CPU (особенно эффективно при использовании FOU/UDP).

**Проверка состояния offload:**
```bash
ethtool -k eth0 | grep -E "tcp-segmentation|generic-receive"
# → tcp-segmentation-offload: on
# → generic-receive-offload: on
```

### Интеграция с облачными провайдерами

| Провайдер | Поддержка GRE | Ограничения |
|-----------|---------------|-------------|
| **AWS** | Transit Gateway (Connect attachments) | MTU обычно 1500, требует учёта оверхеда внутри VPC;.overlay-сети используют VXLAN |
| **GCP** | Cloud Router + VPN | Ограничения на фрагментацию; стандартный MTU 1460 |
| **Azure** | Ограниченная поддержка чистого GRE | Чаще используется NVGRE (Network Virtualization using GRE) |
| **Yandex Cloud** | VPC Peering, Static Routes | Стандартный MTU 1500 |

---

## Безопасность

### Векторы атак на GRE

| Атака | Описание | Риск | Защита |
|-------|----------|------|--------|
| **Spoofing** | Подмена внешнего IP в GRE-пакете | Высокий | Anti-spoofing ACL, rp_filter |
| **Key brute-force** | Перебор 32-битного Key | Средний | ACL, monitoring, rate limiting |
| **GRE injection** | Вставка GRE-пакетов в сеть | Высокий | Firewall (IP 47), rate limiting |
| **Amplification** | GRE как транспорт для DDoS | Высокий | Фильтрация на edge |
| **Tunnel hijack** | Перехват туннеля через spoofing | Средний | IPsec, ACL |

### Anti-spoofing ACL

```bash
# nftables: разрешение GRE только от известного peer
nft add rule inet filter input ip saddr 203.0.113.2 ip protocol 47 accept
nft add rule inet filter input ip protocol 47 drop

# iptables: аналогичное правило
sudo iptables -A INPUT -s 203.0.113.2 -p 47 -j ACCEPT
sudo iptables -A INPUT -p 47 -j DROP
```

**На Cisco IOS:**
```cisco
! Anti-spoofing ACL для GRE
access-list 101 permit gre host 203.0.113.2 host 198.51.100.1
access-list 101 deny gre any any log
interface Tunnel0
 tunnel protection ipsec profile anti-spoofing
```

### Rate limiting GRE-трафика

```bash
# Ограничение GRE: не более 1000 пакетов/сек от одного IP
nft add rule inet filter input ip protocol 47 meter gre_rate \
    { ip saddr limit rate 1000/second burst 50 packets } accept
nft add rule inet filter input ip protocol 47 drop

# iptables
sudo iptables -A INPUT -p 47 -m hashlimit \
    --hashlimit-above 1000/sec --hashlimit-burst 50 \
    --hashlimit-mode srcip --hashlimit-name gre_rate \
    -j DROP
```

### Network namespaces для изоляции GRE

```bash
# Создание namespace для GRE-туннеля
sudo ip netns add gre_isolated

# Перемещение GRE-интерфейса в namespace
sudo ip link set gre0 netns gre_isolated

# Настройка внутри namespace
sudo ip netns exec gre_isolated ip addr add 10.0.0.1/30 dev gre0
sudo ip netns exec gre_isolated ip link set gre0 up
sudo ip netns exec gre_isolated ip link set lo up

# Маршрутизация из namespace на основной хост
sudo ip netns exec gre_isolated ip route add default via 10.0.0.2
sudo ip link add veth-gre0 type veth peer name veth-gre0-br
sudo ip link set veth-gre0 netns gre_isolated
sudo ip link set veth-gre0-br master br0
sudo ip netns exec gre_isolated ip addr add 192.168.100.1/24 dev veth-gre0
sudo ip netns exec gre_isolated ip link set veth-gre0 up
sudo ip link set veth-gre0-br up
```

### Включение rp_filter

```bash
# Защита от spoofing-атак
sudo sysctl -w net.ipv4.conf.all.rp_filter=1
sudo sysctl -w net.ipv4.conf.gre0.rp_filter=1

# При использовании keepalive-скриптов
sudo sysctl -w net.ipv4.conf.all.accept_local=1
```

### Сравнение безопасных альтернатив

| Решение | Шифрование | Сложность | Мультикаст | Производительность |
|---------|------------|-----------|------------|-------------------|
| **GRE** | Нет | Низкая | Да | Высокая |
| **GRE + IPsec** | Да (AES-GCM) | Средняя | Да | Средняя |
| **WireGuard** | Да (ChaCha20) | Низкая | Нет | Высокая |
| **OpenVPN** | Да (TLS) | Средняя | Нет | Низкая |

Подробнее: [GRE vs WireGuard](./gre_vs_wireguard.md), [GRE с IPsec](./gre_ipsec_integration.md)

---

## Диагностика и устранение неисправностей

### Инструментарий

| Задача | Команда |
|--------|---------|
| Просмотр параметров туннеля (Key, TTL, эндпоинты) | `ip -d link show gre0` |
| Статистика ошибок и дропов | `ip -s link show gre0` |
| Просмотр всех GRE-туннелей | `ip -d link show type gre` |
| Анализ GRE-трафика на физическом интерфейсе | `tcpdump -i any proto 47 -nn` |
| Проверка маршрута к эндпоинту | `ip route get 203.0.113.2` |
| Проверка MTU через туннель | `ping -M do -s <size> <tunnel_ip>` |
| Просмотр таблицы маршрутизации | `ip route show dev gre0` |

### Чек-лист при неисправности

1.  **Связность Underlay:** Пингуется ли `remote` IP с хоста? Если нет — проблема в маршрутизации Underlay.
2.  **Firewall:** Разрешён ли протокол **IP 47 (GRE)** в правилах `INPUT` на обоих концах?
3.  **Key mismatch:** Совпадают ли `key` (идентификаторы туннеля) на обоих концах?
4.  **MTU/MSS:** Проходит ли `ping -M do -s 1372 <remote_tunnel_ip>`? Если нет — настройте MSS Clamping.
5.  **Маршрутизация:** Добавлены ли маршруты до удалённых подсетей через туннельный интерфейс?

### Таблица устранения неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Интерфейс UP, пинга нет** | Firewall блокирует GRE (IP 47) или ICMP внутри туннеля | Проверить правила `nftables`/`iptables` на обоих концах |
| **Мелкие пакеты проходят, крупные — нет** | Проблема MTU/MSS (PMTUD Black Hole) | Настроить MSS Clamping до 1360–1400 байт |
| **Трафик идёт только в одну сторону** | NAT/PAT без поддержки GRE | Использовать FOU (GRE-over-UDP) |
| **Keepalive не работает (Linux)** | Ядро Linux не поддерживает Cisco-style keepalive | Использовать OSPF/BGP или BFD через FRRouting |
| **Дропы на интерфейсе** | Файрвол блокирует протокол | `nft add rule inet filter input ip protocol gre accept` |
| **Ошибки key mismatch** | Разные ключи на концах туннеля | Проверить `ip -d link show gre0` на обоих хостах |
| **TCP-соединения зависают** | MSS превышает MTU туннеля | Применить MSS Clamping: `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -o gre0 -j TCPMSS --clamp-mss-to-pmtu` |

### Тюнинг sysctl для GRE

```bash
# Включение PMTUD (по умолчанию включена)
sudo sysctl -w net.ipv4.ip_no_pmtu_disc=0

# Включение reverse path filtering на интерфейсе туннеля
sudo sysctl -w net.ipv4.conf.gre0.rp_filter=1

# При использовании keepalive-скриптов (приём пакетов от "lokal'ных" адресов)
sudo sysctl -w net.ipv4.conf.all.accept_local=1
```

### Packet analysis: tcpdump deep-dive

**Здоровый GRE-трафик:**
```bash
# Просмотр всех GRE-пакетов на физическом интерфейсе
sudo tcpdump -i eth0 proto 47 -nn -vv

# Пример вывода (здоровый туннель):
# 12:00:01 IP 198.51.100.1 > 203.0.113.2: GRE length=116:
#   (gre encap:EtherType=IPv4 (0x0800), length=92)
#   10.0.0.1 > 10.0.0.2: ICMP echo request, ...
```

**Фильтрация по ключу (key):**
```bash
# Только пакеты с определённым ключом (ключ 100 = 0x64)
sudo tcpdump -i eth0 proto 47 -nn "gre[0:1] & 0x20 != 0 and gre[8:4] = 0x00000064"

# Ключ в десятичном формате (grep)
sudo tcpdump -i eth0 proto 47 -nn -vv | grep "key"
```

**Обнаружение MTU black hole:**
```bash
# При MTU black hole видны.fragmented GRE-пакеты и ICMP need-fragment
sudo tcpdump -i eth0 proto 47 or icmp -nn "icmp[0] == 3 and icmp[1] == 4"

# Пример вывода (frag needed):
# 12:00:05 IP 203.0.113.2 > 198.51.100.1: ICMP 203.0.113.2 unreachable need fragmentation,
#   mtu 1472, length 556
```

**Обнаружение key mismatch:**
```bash
# GRE-пакеты с другими ключами (potential attack)
sudo tcpdump -i eth0 proto 47 -nn "gre[8:4] != 0x00000064"

# Или все GRE с расшифровкой полей
sudo tcpdump -i eth0 proto 47 -nn -e -vv
```

**Wireshark-фильтры:**
```
# Все GRE-пакеты
gre

# GRE с определённым ключом
gre.key == 100

# GRE + внутренний ICMP
gre && icmp

# GRE + внутренний TCP на порту 80
gre && tcp.port == 80

# GRE-ошибки (frag needed)
icmp.type == 3 && icmp.code == 4

# GRE с определёнными source/destination
ip.src == 198.51.100.1 && ip.dst == 203.0.113.2 && ip.proto == 47
```

**tracepath для PMTU discovery:**
```bash
# Определение MTU пути
tracepath 10.0.0.2

# tracepath покажет:
# 1: [LOCALHOST] pmtu 1500
# 2: [gateway]   pmtu 1500
# 3: 10.0.0.2    reached, path mtu 1400  ← MTU туннеля
```

---

## Производительность и sizing

### Ограничения ядра Linux

| Параметр | Значение | Описание |
|----------|----------|----------|
| **Максимум GRE-интерфейсов** | ~1000 | Ограничение `max_user_ns` |
| **Максимум ключей на интерфейс** | 1 (Point-to-Point) | Для mGRE — один интерфейс, несколько ключей |
| **PMTU кеш** | 5 минут (default) | `net.ipv4.route.min_advmss` |
| **GRE reassembly** | Отключён по умолчанию | Нет Sequence Number |

### Hardware offloading

```bash
# Проверка поддержки offloading
ethtool -k eth0 | grep -E "tcp-segmentation|generic-receive|tx-checksum"

# Включение TSO (TCP Segmentation Offload) для GRE
sudo ethtool -K eth0 tso on

# Включение GRO (Generic Receive Offload)
sudo ethtool -K eth0 gro on

# Включение TX checksum offload
sudo ethtool -K eth0 tx-checksum-ipv4 on
```

### Throughput benchmarks (типовое)

| Сценарий | CPU cores | Throughput | MTU |
|----------|-----------|------------|-----|
| GRE (no encryption) | 1 | ~9.5 Gbps | 1500 |
| GRE + IPsec AES-GCM-256 | 2 | ~5.2 Gbps | 1400 |
| GRE + IPsec AES-CBC | 3 | ~3.8 Gbps | 1400 |
| WireGuard ChaCha20 | 1 | ~7.8 Gbps | 1420 |
| GRETAP (L2) | 2 | ~6.0 Gbps | 1450 |

**Влияние MTU на throughput:**

```
MTU 1500: maximum TCP payload = 1460 bytes
MTU 1400: maximum TCP payload = 1360 bytes (GRE overhead учтён)
MTU 1360: maximum TCP payload = 1320 bytes (GRE + IPsec overhead)

Throughput reduction: (1500 - MTU) / 1500 * 100%
MTU 1400: -6.7% throughput
MTU 1360: -9.3% throughput
```

### Мониторинг CPU

```bash
# Просмотр CPU load на интерфейсе
mpstat -P ALL 1 5

# Просмотр softirq (GRE-обработка)
cat /proc/softirqs | grep NET_RX

# Проверка статистики ядра
cat /proc/net/snmp | grep -E "Ip|Gre"
```

---

## Дополнительная информация

### Сравнение с альтернативами

| Критерий | GRE | IPIP/SIT | VXLAN | WireGuard |
|----------|-----|----------|-------|-----------|
| **Уровень** | L2/L3 | L3 | L2 | L3 |
| **Мультипротокольность** | Да (любой EtherType) | Нет (только IP) | Только Ethernet | Да |
| **Транспорт** | IP (47) | IP (4/41) | UDP (4789) | UDP |
| **NAT Traversal** | Плохо (требует FOU) | Плохо | Отлично | Отлично |
| **Шифрование** | Нет (требует IPsec) | Нет | Нет | Да (нативно, ChaCha20/Poly1305) |
| **Keepalive (Linux)** | Нативно не поддерживается | Нет | N/A | Да (нативно) |
| **Динамическая маршрутизация** | Да (mGRE + NHRP) | Нет | Multicast/BGP EVPN | Нет |

### Связанные документы

*   [GRE: практические сценарии](./gre_practical_scenarios.md) — настройка в Linux (iproute2, Netplan, systemd-networkd, nmcli) и Cisco.
*   [GRE с IPsec](./gre_ipsec_integration.md) — создание защищённых каналов (GRE over IPsec, VTI, XFRM).
*   [GRE vs WireGuard](./gre_vs_wireguard.md) — сравнение протоколов, критерии выбора, миграция.
*   [DMVPN](./dmvpn.md) — динамический multipoint VPN (mGRE + NHRP + IPsec).
*   [Мониторинг GRE](./gre_monitoring.md) — наблюдаемость, Prometheus, алертинг, NetFlow.
*   [Обзор туннелирования](../tunneling_overview.md) — концептуальное сравнение протоколов туннелирования.
*   [MTU и VPN](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) — подробный разбор проблем фрагментации, PMTUD Black Hole и MSS Clamping.
*   [ip tunnel vs ip link](../../../Linux/Networking/Tools/iproute2/ip_tunnel.md) — управление туннелями в Linux.
