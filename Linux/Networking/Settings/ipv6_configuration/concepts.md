# IPv6 в Linux — Концепции

## Определения

**IPv6 (Internet Protocol version 6)** — основной протокол сетевого уровня в современных дистрибутивах Linux. Поддержка IPv6 встроена в ядро Linux и активирована по умолчанию.

**Основные типы адресов:**

- **Link-Local (`fe80::/10`)** — автоматически назначаются каждому интерфейсу для локальной связи (L2-сегмент). Обязательны для работы протоколов обнаружения соседей (NDP).
- **Unique Local Address (ULA, `fc00::/7`)** — аналог частных (серых) адресов IPv4.
- **Global Unicast (GUA, `2000::/3`)** — публичные маршрутизируемые адреса.
- **IPv4-mapped IPv6 (`::ffff:0:0/96`)** — механизм представления IPv4-адресов внутри IPv6-стека для совместимости приложений.
- **Multicast (`ff00::/8`)** — групповые адреса, заменяют broadcast в IPv6.

**Зональный идентификатор (Scope ID)** — обязательный суффикс для Link-Local адресов (например, `fe80::1%eth0`), указывающий ядру, через какой физический интерфейс следует отправлять пакет, так как один и тот же Link-Local префикс существует на всех интерфейсах.

Подробное описание протокола и типов адресов см. в **[Обзоре IPv6](../../../../Networking/Protocols/ipv6_overview.md)**.

## Основные концепции

### Особенности реализации в Linux

| Аспект | Описание |
| :--- | :--- |
| **Стек ядра** | Поддержка IPv6 встроена в ядро (`builtin`). Модульная загрузка практически не используется. Стек оптимизирован для высокопроизводительной маршрутизации. |
| **Управление** | Основной инструмент — **iproute2** (`ip -6`). Все современные сетевые менеджеры (NetworkManager, systemd-networkd) используют его API. |
| **Segment Routing (SRv6)** | Linux поддерживает архитектуру SRv6 (с ядра 4.10), позволяя кодировать путь пакета непосредственно в заголовке IPv6 через Routing Extension Headers. |
| **Dual Stack** | Linux поддерживает одновременную работу IPv4 и IPv6. Параметр `net.ipv6.bindv6only` определяет, будет ли IPv6-сокет принимать IPv4-трафик. |
| **Файрвол** | Рекомендуется использовать **nftables** (семейство `inet`). Важно помнить, что фильтрация ICMPv6 критична для работы NDP и SLAAC. |

### Механизмы автоконфигурации

Ядро Linux поддерживает три основных способа получения адреса:
1. **SLAAC (Stateless Address Autoconfiguration)** — хост генерирует адрес сам на основе префикса от маршрутизатора (параметр `autoconf`). Использует EUI-64 или случайные идентификаторы.
2. **DHCPv6** — получение адреса от сервера. Может быть **Stateful** (адрес выдает сервер) или **Stateless** (адрес через SLAAC, опции через DHCPv6).
3. **Статическая настройка** — ручное назначение через `ip address` или конфигурационные файлы.

**Флаги Router Advertisement (RA), управляющие поведением хостов:**
- **M (Managed Address Configuration)** — если установлен в 1, хост должен использовать Stateful DHCPv6 для получения адреса.
- **O (Other Configuration)** — если установлен в 1, хост должен получить доп. параметры (DNS, домен поиска) через DHCPv6, даже если адрес получен через SLAAC.
- **H (Home Agent)** — используется для мобильности IPv6 (Mobile IPv6).

### Расширения конфиденциальности (Privacy Extensions, RFC 4941)

Механизм защиты путем генерации временных случайных адресов для исходящего трафика. Это скрывает постоянный идентификатор интерфейса (EUI-64), который может использоваться для отслеживания устройства при перемещении между сетями.

**Параметр `use_tempaddr`:**
- `0`: отключено.
- `1`: включено, но предпочтение отдается постоянному адресу.
- `2`: включено, предпочтительны временные адреса (рекомендуется для конечных устройств).

### Stable Privacy (RFC 7217)

Современный стандарт генерации идентификатора интерфейса. В отличие от EUI-64, генерирует стабильный, но случайный адрес для каждого сети/интерфейса, предотвращая отслеживание устройства при перемещении между сетями. В большинстве дистрибутивов включен по умолчанию.

### Обнаружение дубликатов адресов (DAD)

Процесс проверки уникальности IPv6-адреса в сегменте сети перед его активацией. В Linux управляется параметром `accept_dad`.
- **Optimistic DAD (RFC 4429)** — позволяет использовать адрес до завершения проверки DAD (в "оптимистичном" состоянии), что ускоряет установку связи (параметр `optimistic_dad`).

### Multicast Listener Discovery (MLD, RFC 2710/4594)

Протокол, аналог IGMP для IPv6. Позволяет хосту сообщать маршрутизаторам о своем интересе к multicast-группам. Управляется параметром `force_mld_version`. MLD работает поверх ICMPv6 и использует multicast-адреса `ff02::/16`.

### Path MTU Discovery (PMTUD)

В IPv6 маршрутизаторы **никогда** не фрагментируют пакеты. Если пакет превышает MTU пути, маршрутизатор отбрасывает его и отправляет отправителю **ICMPv6 Type 2 (Packet Too Big)**. Минимальный обязательный MTU в IPv6 — **1280 байт**. Блокировка этого ICMP-сообщения создает "черную дыру" MTU (PMTUD Black Hole). Для TCP критично настроить MSS Clamping при использовании туннелей (например, VXLAN overhead ~70 байт для IPv6).

### Управление через sysctl

Параметры настраиваются в пространстве `net.ipv6.conf.*`. Приоритет: `<ifname>` > `default` > `all` (для некоторых параметров).

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **`disable_ipv6`** | `0` / `1` | Полное отключение стека IPv6 на интерфейсе. |
| **`autoconf`** | `0` / `1` | Разрешает/запрещает генерацию адресов через SLAAC. |
| **`accept_ra`** | `0` / `1` / `2` | Прием RA от маршрутизаторов. `0` — выкл, `1` — вкл, `2` — принудительно при forwarding=1. |
| **`forwarding`** | `0` / `1` | Включает пересылку IPv6-пакетов между интерфейсами (режим маршрутизатора). |
| **`optimistic_dad`** | `0` / `1` | Разрешает использование адреса до завершения DAD (ускоряет роуминг). |
| **`use_tempaddr`** | `0` / `1` / `2` | Включение Privacy Extensions. `2` — временные адреса предпочтительны. |
| **`temp_valid_lft`** | секунды | Время жизни временного адреса Privacy Extensions. |
| **`accept_redirects`** | `0` / `1` | Прием ICMPv6 Redirect. На серверах рекомендуется `0`. |
| **`accept_source_route`** | `0` / `1` | Прием Extension Header Routing. На серверах рекомендуется `0`. |
| **`bindv6only`** | `0` / `1` | Если `1`, IPv6-сокеты не принимают IPv4-трафик (v4-mapped). По умолчанию `0`. |

### Выбор исходного адреса (Source Address Selection, RFC 6724)

При наличии нескольких IPv6-адресов на интерфейсе (GUA, ULA, временный), ядро Linux выбирает источник согласно RFC 6724:
1. Предпочтение одинаковых областей видимости (Scope).
2. Предпочтение адресов в состоянии `preferred` над `deprecated`.
3. Предпочтение временных адресов (Privacy Extensions) для клиентского трафика.
4. Выбор адреса с наиболее длинным общим префиксом с адресом назначения.

Политика задается в `/etc/gai.conf` (опционально переопределяется). По умолчанию ULA имеет приоритет над GUA для локальных назначений.

## Практические сценарии

### 1. Управление расширениями конфиденциальности

**Проверка текущего статуса:**

```bash
ip -6 addr show eth0
# → ищи флаг 'temporary' у адресов

# Проверка параметра sysctl
sysctl net.ipv6.conf.all.use_tempaddr
sysctl net.ipv6.conf.eth0.use_tempaddr
```

**Включение через `sysctl`:**

```bash
# Временно (до перезагрузки)
sudo sysctl -w net.ipv6.conf.all.use_tempaddr=2
sudo sysctl -w net.ipv6.conf.default.use_tempaddr=2
sudo sysctl -w net.ipv6.conf.eth0.use_tempaddr=2

# Постоянно (/etc/sysctl.d/60-ipv6-privacy.conf)
net.ipv6.conf.all.use_tempaddr = 2
net.ipv6.conf.default.use_tempaddr = 2
```

**Валидация:**

```bash
# После применения должны появиться временные адреса
ip -6 addr show eth0 | grep temporary

# Проверка сроков жизни
ip -6 addr show dev eth0
```

### 2. Конфигурация DHCPv6-клиента

**dhclient (ISC DHCP Client):**

```bash
# Запрос адреса через DHCPv6 Stateful
sudo dhclient -6 -P -N eth0

# Stateless DHCPv6 (только опции, адрес через SLAAC)
sudo dhclient -6 -S -N eth0

# Освобождение адреса
sudo dhclient -6 -r eth0
```

**dhcpcd (lightweight, используется в Alpine, Raspberry Pi OS):**

```bash
# Включение DHCPv6 в /etc/dhcpcd.conf:
sudo nano /etc/dhcpcd.conf
# ...
# Стандартный конфиг (статика):
# interface eth0
#   ipv6_address=2001:db8::10/64
#   ipv6_router=2001:db8::1

# DHCPv6 Stateful:
#   ipv6_only
#   ipv6_ra=1

# SLAAC + Stateless DHCPv6:
#   ipv6_ra=2

# Применение
sudo systemctl restart dhcpcd
```

**systemd-networkd (DHCPv6):**

```ini
# /etc/systemd/network/25-ipv6.network
[Match]
Name=enp2s0

[Network]
IPv6AcceptRA=yes
DHCP=ipv6

[DHCPv6]
WithoutRA=no
UseDelegatedPrefix=yes
```

**NetworkManager (DHCPv6):**

```bash
# DHCPv6 Stateful
sudo nmcli connection modify "eth0" ipv6.method dhcp

# Stateless DHCPv6 (адрес через SLAAC, опции через DHCPv6)
sudo nmcli connection modify "eth0" ipv6.method auto ipv6.ignore-auto-dns no
```

### 3. Настройка маршрутизатора (Router)

**Требования:**
- `net.ipv6.conf.all.forwarding=1`
- Установлен пакет `radvd` (Router Advertisement Daemon)

**sysctl для маршрутизатора:**

```bash
# /etc/sysctl.d/99-ipv6-router.conf
net.ipv6.conf.all.forwarding = 1
net.ipv6.conf.all.accept_ra = 0
net.ipv6.conf.default.accept_ra = 0
net.ipv6.conf.all.accept_redirects = 0
```

**Пример `/etc/radvd.conf`:**

```conf
interface eth0 {
    AdvSendAdvert on;
    AdvManagedFlag on;    # M flag: Stateful DHCPv6
    AdvOtherConfigFlag on; # O flag: Stateless DHCPv6
    prefix 2001:db8:1::/64 {
        AdvOnLink on;
        AdvAutonomous on;  # SLAAC включен
    };
    RDNSS 2001:db8::1 {
        AdvRDNSSLifetime 1800;
    };
};
```

**Применение:**

```bash
sudo sysctl --system
sudo systemctl enable --now radvd

# Проверка работы
rdisc6 eth0
# Должен показать собственный RA
```

### 4. Усиление безопасности серверов (IPv6 Security Hardening)

**Рекомендуемые параметры для серверов (без роли маршрутизатора):**

```bash
# /etc/sysctl.d/99-ipv6-server.conf

# RA/SLAAC
net.ipv6.conf.all.accept_ra = 0
net.ipv6.conf.default.accept_ra = 0

# ICMPv6 Redirect и Source Routing
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0

# Forwarding (не включать на серверах)
net.ipv6.conf.all.forwarding = 0

# Privacy Extensions (на серверах — отключены для стабильности)
net.ipv6.conf.all.use_tempaddr = 0

# Логирование подозрительных пакетов
net.ipv6.conf.all.log_martians = 1

# Ограничение количества адресов (защита от RA flood)
net.ipv6.conf.all.max_addresses = 128

# Optimistic DAD (включать только на роуминг-устройствах)
net.ipv6.conf.all.optimistic_dad = 0

# MLD (отключать на серверах, если multicast не используется)
net.ipv6.conf.all.force_mld_version = 0

# Максимальное количество ND-записей в кэше
net.ipv6.neigh.default.gc_thresh3 = 4096
```

**Обоснование:**
- `accept_ra=0` — предотвращает переконфигурацию злоумышленником через ложные RA (RA Spoofing).
- `accept_redirects=0` — защита от атак через ICMPv6 Redirect.
- `accept_source_route=0` — запрет на Source Routing (защита от атак с подменой маршрута).
- `log_martians=1` — логирование пакетов с нестандартными источниками (diagnostics).
- `max_addresses=128` — ограничивает количество адресов на интерфейсе (защита от RA flood с множеством prefix).
- `optimistic_dad=0` — на серверах не нужен роуминг, отключаем для предсказуемости.

### 5. IPv6 Firewall Hardening (nftables)

**Базовый hardened-правила для сервера:**

```bash
# /etc/nftables.conf
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # 1. Loopback
        iif lo accept

        # 2. Established/Related
        ct state established,related accept
        ct state invalid drop

        # 3. Критический ICMPv6 (NDP, MLD, PMTUD)
        icmpv6 type {
            destination-unreachable,
            packet-too-big,
            time-exceeded,
            parameter-problem,
            echo-request,
            echo-reply,
            nd-router-solicit,
            nd-router-advert,
            nd-neighbor-solicit,
            nd-neighbor-advert,
            mld-listener-query,
            mld-listener-report,
            mld-listener-done
        } accept

        # 4. Rate limiting ICMPv6 (защита от flood)
        icmpv6 type echo-request limit rate 10/second burst 20 packets accept
        icmpv6 type nd-router-solicit limit rate 1/second accept
        icmpv6 type nd-neighbor-solicit limit rate 10/second accept

        # 5. SSH
        tcp dport 22 accept

        # 6. HTTP/HTTPS
        tcp dport { 80, 443 } accept

        # 7. Log dropped (ограниченный)
        limit rate 5/second log prefix "IPV6_DROP: " drop
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
```

### 6. Защита от NDP-атак

**NDP Spoofing** — атака, при которой злоумышленник отправляет поддельные Neighbor Advertisement, перехватывая трафик. Защита:

```bash
# 1. RA Guard (на L2-коммутаторе)
# На Cisco/Juniper:_Port Security + RA Guard_
# На Linux (nftables): блокировка RA от клиентских портов
table inet ipv6_guard {
    chain input {
        type filter hook input priority -150;
        # Блокировать RA от не-trusted портов
        iif != { "eth0", "eth1" } icmpv6 type nd-router-advert drop
        iif != { "eth0", "eth1" } udp dport 547 drop
    }
}

# 2. DHCPv6 Guard
table inet dhcpv6_guard {
    chain input {
        type filter hook input priority -150;
        # Блокировать DHCPv6 Advertise/Solicit от клиентов
        iif != { "eth0" } udp dport 546 drop
        iif != { "eth0" } udp dport 547 drop
    }
}

# 3. Статические NDP-записи для критичных хостов
sudo ip -6 neigh add 2001:db8::1 lladdr 00:11:22:33:44:55 dev eth0 nud permanent
sudo ip -6 neigh add 2001:db8::2 lladdr 00:11:22:33:44:56 dev eth0 nud permanent
```

### 7. IPv6-aware应用 (SEND/CGA)

**SEND (Secure Neighbor Discovery, RFC 3971)** — криптографическая защита NDP-сообщений с помощью сертификатов. Редко используется в production из-за сложности PKI.

**CGA (Cryptographically Generated Addresses, RFC 3972)** — генерация IPv6-адреса на основе хеша открытого ключа. Позволяет верифицировать владельца адреса.

**Практическое применение:**
- SEND + CGA — избыточно для большинства production-сред
- Достаточно: RA Guard + DHCPv6 Guard + статические NDP + nftables rate limiting
- На зашумлённых L2-сегментах (500+ хостов) рекомендуется PRIVATE VLAN

### 8. Проверка статуса стека и интерфейсов

```bash
# Проверка, включен ли IPv6 в ядре
cat /proc/net/if_inet6
# Если файл пуст — стек отключен глобально

# Проверка sysctl на интерфейсе
sysctl net.ipv6.conf.eth0.accept_ra
sysctl net.ipv6.conf.eth0.forwarding
sysctl net.ipv6.conf.eth0.disable_ipv6

# Проверка адресов и состояний
ip -6 addr show dev eth0

# tentative — DAD проверка идет
# deprecated — адрес устарел (не для новых соединений)
# dadfailed — конфликт адреса
# permanent — статический адрес
# dynamic — получен через SLAAC/DHCPv6

# Проверка маршрутов
ip -6 route show
```

### 9. Настройка статического адреса (iproute2)

```bash
# Временная настройка (сбрасывается при перезагрузке)
sudo ip -6 addr add 2001:db8::10/64 dev eth0
sudo ip -6 route add default via 2001:db8::1 dev eth0

# Валидация
ip -6 addr show dev eth0
ip -6 route show
ping6 -c 3 2001:db8::1
```

### 10. Настройка MSS Clamping для туннелей

При использовании туннелей (VXLAN, GRE, SIT) уменьшается MTU. Для TCP необходимо настроить MSS Clamping, чтобы избежать фрагментации:

```bash
# VXLAN over IPv4: MTU overhead ~50 байт, рекомендуемый MSS = 1350 (при MTU 1500)
# VXLAN over IPv6: MTU overhead ~70 байт, рекомендуемый MSS = 1410 (при MTU 1500)

# nftables MSS Clamping для IPv6
sudo nft add rule inet filter forward oif "vxlan0" tcp flags syn tcp option maxseg size set 1410

# Или через iptables (legacy)
sudo ip6tables -t mangle -A FORWARD -o vxlan0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1410
```

### 11. Настройка Segment Routing (SRv6)

Пример добавления сегмента пути для трафика к определенной сети:

```bash
# Пакеты к 2001:db8:2::/64 будут инкапсулированы с промежуточным сегментом
sudo ip -6 route add 2001:db8:2::/64 encap seg6 mode encap segs 2001:db8:1::100 dev eth0

# Проверка маршрута
ip -6 route show | grep seg6

# Удаление сегмента
sudo ip -6 route del 2001:db8:2::/64 encap seg6 mode encap segs 2001:db8:1::100 dev eth0
```

### 12. Отключение IPv6

**1. Через sysctl (рекомендуемый способ):**

```bash
# В файле /etc/sysctl.d/99-disable-ipv6.conf
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1

# Применение
sudo sysctl --system

# Проверка
cat /proc/net/if_inet6  # должен быть пуст
```

**2. Через GRUB (полное отключение на уровне ядра):**
Добавить `ipv6.disable=1` в параметры `GRUB_CMDLINE_LINUX` в `/etc/default/grub`, затем:
- `sudo update-grub` (Debian/Ubuntu)
- `sudo grub2-mkconfig -o /boot/grub2/grub.cfg` (RHEL/CentOS)

## Дополнительная информация

### Механизм перехода на IPv6

В Linux для сосуществования с IPv4-сетями используются следующие механизмы:
- **NAT64/DNS64** — доступ к IPv4 ресурсам из IPv6-only сетей (инструменты: `Tayga`, `Jool`). Подробнее: **[Сценарии NAT64](../../../../Networking/Concepts/nat/practical_scenarios.md#технологии-перехода-на-ipv6-nat64)**.
- **SIT (IPv6-in-IPv4)** — туннелирование IPv6 через IPv4 (6to4, 6rd). Протокол 41, overhead 20 байт.
- **464XLAT** — двойная трансляция для работы IPv4-приложений в IPv6-сетях (CLAT на устройстве, PLAT у провайдера).
- **Dual-Stack Lite (DS-Lite)** — инкапсуляция IPv4 в IPv6 (тunnel AFTR).

### Типичные ошибки и диагностика

**Проблема: адрес в статусе `tentative` длительное время:**
- Причина: не отвечает сосед на DAD-запрос или петля L2.
- Решение: проверка `ip -6 addr show`, исключение L2-петель через `tcpdump -i eth0 icmp6`.

**Проблема: `ping6` проходит, но TCP соединение зависает:**
- Причина: PMTUD Black Hole (блокируются ICMPv6 Type 2).
- Решение: настроить MSS Clamping, проверить прохождение ICMPv6.

**Проблема: "Address family not supported":**
- Причина: IPv6 отключен через sysctl или GRUB.
- Решение: проверка `sysctl net.ipv6.conf.all.disable_ipv6`, параметры загрузки `ipv6.disable=1`.

**Проблема: SLAAC не работает:**
- Причины: `accept_ra=0`, `autoconf=0`, неверный префикс на маршрутизаторе, блокировка multicast на коммутаторе.
- Решение: `rdisc6 eth0` (проверка RA), `sysctl net.ipv6.conf.all.accept_ra`.

### См. также

- **[Настройка адресов](./address_configuration.md)** — практические примеры через nmcli и systemd-networkd.
- **[Диагностика IPv6](./diagnostics.md)** — использование `ping6`, `traceroute6` и отладка NDP.
- **[Firewall для IPv6](./firewall.md)** — настройка правил фильтрации через nftables и ip6tables.
- **[Kubernetes Dual-Stack](./kubernetes_dual_stack.md)** — IPv6 в Kubernetes-кластерах.
- **[Мониторинг IPv6](./monitoring.md)** — Prometheus, Blackbox Exporter, alerting для IPv6.
