# Настройка файрвола для IPv6 в Linux

## Определения

**IPv6 Firewall** — механизм фильтрации сетевого трафика для адресов длиной 128 бит. В Linux реализуется через фреймворк **Netfilter**.

**ICMPv6 (Internet Control Message Protocol for IPv6)** — фундаментальный протокол, обеспечивающий работу базовых функций IPv6 (обнаружение соседей, согласование MTU, многоадресная рассылка). В отличие от IPv4, полное блокирование ICMPv6 делает работу сети невозможной.

## Основные концепции

### Эволюция инструментов

1.  **nftables (Рекомендуется)**: современный стандарт. Использует семейство `inet` для управления правилами IPv4 и IPv6 в рамках единой таблицы. Позволяет эффективно фильтровать трафик по специфичным для IPv6 полям (например, Extension Headers).
2.  **firewalld / UFW**: высокоуровневые оболочки (front-ends), использующие `nftables` в качестве бэкенда в современных дистрибутивах.
3.  **ip6tables (Legacy)**: классический инструмент. Управляет правилами IPv6 отдельно от IPv4. Требует ручного дублирования политик безопасности и менее эффективен при работе с наборами данных (sets).

В современных дистрибутивах (Debian 12+, RHEL 9+, Ubuntu 22.04+) `ip6tables` является оберткой над `nftables` (nf_tables backend). Это означает, что команды `ip6tables` продолжают работать, но фактически используют nftables. Для новых конфигураций рекомендуется использовать родной синтаксис nftables.

### Критическая роль ICMPv6

Для корректной работы стека IPv6 **необходимо** разрешать следующие типы сообщений:

| Тип | Название | Функция | Последствия блокировки |
| :--- | :--- | :--- | :--- |
| **1-4** | Error Messages | Сообщения об ошибках | Невозможность диагностики и работы протоколов |
| **2** | Packet Too Big | **PMTUD** | "Зависание" сессий при передаче больших пакетов |
| **133-136** | NDP Messages | **Neighbor Discovery** | Хосты не видят друг друга и шлюз (аналог ARP) |
| **130-132** | MLD Messages | Multicast Discovery | Нарушение работы Multicast и IPv6-групп |
| **128-129** | Echo Req/Reply | Ping | Невозможность базовой проверки связности |

### Conntrack и особенности IPv6

В отличие от IPv4, в "чистом" IPv6 нет NAT. Это означает, что таблица `conntrack` (nf_conntrack) испытывает меньшее давление от пакетов с подменой адресов. Однако conntrack все равно критически важен:

- **Stateful-фильтрация** (`ct state established,related accept`) работает одинаково для IPv4 и IPv6.
- При использовании **NAT64** (переходные механизмы) или **NPTv6** (RFC 6294) conntrack отслеживает трансляции.
- В контейнерных средах (Docker, Podman) с включенным `bridge-nf-call-ip6tables=1` трафик проходит через conntrack.

```bash
# Проверка лимитов conntrack
sysctl net.netfilter.nf_conntrack_max
cat /proc/sys/net/netfilter/nf_conntrack_count

# Рекомендуемые значения для серверов с высокой нагрузкой
sysctl -w net.netfilter.nf_conntrack_max=2097152
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=86400
sysctl -w net.netfilter.nf_conntrack_udp_timeout_stream=180
```

### Sysctl-параметры усиления стека IPv6

Параметры ядра,Complementing правила файрвола:

```bash
# /etc/sysctl.d/99-ipv6-hardening.conf

# Запретить перенаправление (Redirect) — аналог ICMPv4 Redirect
net.ipv6.conf.all.accept_redirects=0
net.ipv6.conf.default.accept_redirects=0

# Запретить source routing
net.ipv6.conf.all.accept_source_route=0
net.ipv6.conf.default.accept_source_route=0

# Отключить автонастройку адресов через Router Advertisements на серверах
net.ipv6.conf.all.accept_ra=0
net.ipv6.conf.default.accept_ra=0

# Отключить forwarding (если не маршрутизатор)
net.ipv6.conf.all.forwarding=0

# Логирование подозрительных пакетов (martians)
net.ipv6.conf.all.log_martians=1

# Ограничить количество concurrent Router Solicitations
net.ipv6.conf.all.max_addresses=128
```

Применить: `sudo sysctl -p /etc/sysctl.d/99-ipv6-hardening.conf`

### MSS Clamping и взаимодействие с PMTUD

В IPv6 маршрутизаторы не фрагментируют пакеты. Если пакет превышает MTU интерфейса, маршрутизатор отбрасывает его и отправляет ICMPv6 Type 2 (Packet Too Big). Блокировка этого типа на файрволе создает "MTU Black Hole".

Для туннелей (VXLAN, GRE, SIT, WireGuard) overhead увеличивает размер заголовка, снижая эффективный MTU. MSS Clamping принудительно снижает Maximum Segment Size для TCP-соединений:

```bash
# nftables — снизить MSS до 1400 для трафика через туннель
table inet filter {
    chain forward {
        type filter hook forward priority 0; policy drop;
        # Принудительное снижение MSS для новых SYN-пакетов
        tcp flags syn tcp option maxseg size set 1400
    }
}
```

```bash
# ip6tables legacy
ip6tables -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
```

### Проверка обратного пути (uRPF) для IPv6

В отличие от IPv4, где есть `sysctl net.ipv4.conf.all.rp_filter`, для IPv6 в Linux uRPF настраивается через файрвол:

```bash
# Пример для nftables
table inet filter {
    chain prerouting {
        type filter hook prerouting priority -150;
        # Проверка, что адрес отправителя доступен через тот же интерфейс, с которого пришел пакет
        fib saddr . iif oif exists accept
        drop
    }
}
```

### Обработка Extension Headers

Злоумышленники могут использовать Extension Headers для обхода файрволов или DoS-атак. `nftables` позволяет фильтровать пакеты с избыточными заголовками:

```bash
# Пример: ограничение длины Hop-by-Hop или фильтрация специфичных заголовков
ip6 extension header hop-by-hop drop
```

### RA Guard и DHCPv6 Guard

В локальных сегментах L2 злоумышленник может отправить поддельный Router Advertisement (RA) или DHCPv6 Advertise, перенаправив трафик через себя. В Linux защита реализуется через nftables:

```bash
table inet ipv6_guard {
    chain input {
        type filter hook input priority -150;
        # Блокировать RA (Type 134) и DHCPv6 Solicit/Advertise от клиентских портов
        # Исключение: доверенные интерфейсы (например, uplink к роутеру)
        iif != { "eth0" } icmpv6 type nd-router-advert drop
        iif != { "eth0" } udp dport 547 drop
    }
}
```

Для аппаратных коммутаторов Cisco/Juniper существуют специализированные функции **RA Guard** и **DHCPv6 Guard**, проверяющие целостность и доверенные источники RA/DHCPv6 пакетов.

### Rate Limiting и flood-защита

ICMPv6 и NDP-трафик уязвим к flood-атакам. Ограничение частоты сохраняет диагностическую функциональность:

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Ограничение echo-request (ping): 10 пакетов в секунду, burst 20
        icmpv6 type echo-request limit rate 10/second burst 20 packets accept

        # Ограничение Router Solicitations: 1 в секунду
        icmpv6 type nd-router-solicit limit rate 1/second accept

        # Ограничение Neighbor Solicitations: 10 в секунду
        icmpv6 type nd-neighbor-solicit limit rate 10/second accept
    }
}
```

## Практические сценарии

### 1. nftables (Современный стандарт)

Использование семейства `inet` позволяет создать универсальный файрвол.

```bash
# /etc/nftables.conf

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # 1. Разрешить Loopback
        iif lo accept

        # 2. Разрешить установленные и связанные соединения
        ct state established,related accept

        # 3. Сбросить некорректные пакеты
        ct state invalid drop

        # 4. Разрешить критический ICMPv6
        icmpv6 type {
            destination-unreachable, packet-too-big, time-exceeded,
            parameter-problem, echo-request, echo-reply,
            nd-router-solicit, nd-router-advert,
            nd-neighbor-solicit, nd-neighbor-advert,
            mld-listener-query, mld-listener-report, mld-listener-done
        } accept

        # 5. Ограничение ICMPv6 (защита от flood)
        icmpv6 type echo-request limit rate 10/second burst 20 packets accept

        # 6. Ограничение Router Advertisements (защита от ложных роутеров)
        # Принимать RA только от доверенного Link-Local адреса шлюза (пример)
        # ip6 saddr fe80::1 icmpv6 type nd-router-advert accept

        # 7. Разрешить стандартные сервисы
        tcp dport { 22, 80, 443 } accept

        # 8. Логирование блокированных пакетов (с ограничением)
        limit rate 5/second log prefix "DROP: "
    }
}
```

### 2. ip6tables (Legacy)

Синтаксис для старых систем, где nftables не доступен или требуется совместимость:

```bash
# Очистка правил
ip6tables -F
ip6tables -X

# Политика по умолчанию
ip6tables -P INPUT DROP
ip6tables -P FORWARD DROP
ip6tables -P OUTPUT ACCEPT

# Разрешить loopback
ip6tables -A INPUT -i lo -j ACCEPT

# Разрешить установленные соединения
ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Разрешить критический ICMPv6
ip6tables -A INPUT -p icmpv6 --icmpv6-type destination-unreachable -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type packet-too-big -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type time-exceeded -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type parameter-problem -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type echo-request -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type echo-reply -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-router-solicit -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-router-advert -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-neighbor-solicit -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-neighbor-advert -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type 130 -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type 131 -j ACCEPT
ip6tables -A INPUT -p icmpv6 --icmpv6-type 132 -j ACCEPT

# Блокировать Redirect и остальной ICMPv6
ip6tables -A INPUT -p icmpv6 --icmpv6-type redirect -j DROP
ip6tables -A INPUT -p icmpv6 -j DROP

# Разрешить SSH и HTTP
ip6tables -A INPUT -p tcp --dport 22 -j ACCEPT
ip6tables -A INPUT -p tcp --dport 80 -j ACCEPT
ip6tables -A INPUT -p tcp --dport 443 -j ACCEPT

# Сохранить правила
service netfilter-persistent save
```

### 3. UFW (Ubuntu / Debian)

UFW автоматически настраивает базовые правила для IPv6, если в `/etc/default/ufw` параметр `IPV6=yes`.

```bash
# Проверка статуса IPv6 в UFW
grep "IPV6=" /etc/default/ufw

# Разрешить порт для обоих протоколов (IPv4 и IPv6)
sudo ufw allow 22/tcp

# Разрешить конкретную сеть IPv6
sudo ufw allow from 2001:db8:1::/64

# Ограничение для SSH (только IPv6): не более 6 соединений в минуту
sudo ufw limit 22/tcp comment 'Rate limit SSH IPv6'

# Проверить статус
sudo ufw status numbered
```

### 4. firewalld (RHEL / Fedora)

Управление через зоны. Команды без флага `--ipv6` применяются к обоим стекам.

```bash
# Разрешить сервис (IPv4 + IPv6)
sudo firewall-cmd --permanent --add-service=http

# Разрешить специфический порт только для IPv6 через Rich Rules
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv6" port port="8080" protocol="tcp" accept'

# Блокировать Router Advertisements от внешних интерфейсов (если поддерживается)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv6" icmpv6-type="router-advertisement" drop'

# Применить
sudo firewall-cmd --reload
```

### 5. Фильтрация мостов (Bridges) для IPv6

При использовании Linux Bridge трафик IPv6 между портами моста не проходит через `filter` таблицу по умолчанию. Необходимо включить `bridge-nf-call-ip6tables`:

```bash
# Включить фильтрацию IPv6 на мостах
sysctl -w net.bridge.bridge-nf-call-ip6tables=1

# Постоянно — в /etc/sysctl.d/99-bridge.conf
echo "net.bridge.bridge-nf-call-ip6tables=1" >> /etc/sysctl.d/99-bridge.conf
sysctl -p /etc/sysctl.d/99-bridge.conf

# nftables — фильтрация на уровне моста
sudo nft add table bridge filter
sudo nft add chain bridge filter forward { type filter hook forward priority 0; policy accept; }
sudo nft add rule bridge filter forward ip6 saddr fe80::/10 drop
```

### 6. Fail2ban с IPv6

Fail2ban автоматически блокирует IP после нескольких неудачных попыток. Для IPv6 использует `nftables` sets:

```bash
# /etc/fail2ban/jail.local
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 3600
findtime = 600
# Fail2ban автоматически определяет backend (nftables/iptables)
```

Fail2ban создает наборы в nftables и добавляет в них адреса. Убедитесь, что используете `nftables` backend (по умолчанию в современных дистрибутивах).

## Безопасность и защита

### Фильтрация по Scope ID и Link-Local

Пакеты с адресами Link-Local (`fe80::/10`) не должны покидать пределы L2-сегмента. На маршрутизаторах рекомендуется блокировать такие адреса на внешних интерфейсах в цепочке `forward`.

### Проверка обратного пути (uRPF) для IPv6

В отличие от IPv4, где есть `sysctl net.ipv4.conf.all.rp_filter`, для IPv6 в Linux uRPF настраивается через файрвол:

```bash
# Пример для nftables
table inet filter {
    chain prerouting {
        type filter hook prerouting priority -150;
        # Проверка, что адрес отправителя доступен через тот же интерфейс, с которого пришел пакет
        fib saddr . iif oif exists accept
        drop
    }
}
```

### Обработка Extension Headers

Злоумышленники могут использовать Extension Headers для обхода файрволов или DoS-атак. `nftables` позволяет фильтровать пакеты с избыточными заголовками:

```bash
# Пример: ограничение длины Hop-by-Hop или фильтрация специфичных заголовков
ip6 extension header hop-by-hop drop
```

## Диагностика и проверка

### Проверка активных правил

```bash
# nftables (показать весь набор)
sudo nft list ruleset

# firewalld (показать настройки текущей зоны)
sudo firewall-cmd --list-all

# ufw (статус и пронумерованные правила)
sudo ufw status numbered
```

### Проверка параметров ядра

```bash
# Проверка sysctl для IPv6
sysctl net.ipv6.conf.all.accept_redirects
sysctl net.ipv6.conf.all.accept_source_route
sysctl net.ipv6.conf.all.accept_ra
sysctl net.ipv6.conf.all.forwarding

# Проверка conntrack
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
```

### Тестирование связности

```bash
# Использование netcat (флаг -6 для IPv6)
nc -6 -zv 2001:db8::1 80

# Сканирование через nmap с указанием интерфейса для Link-Local
nmap -6 -p 22 fe80::215:5dff:fe1e:81e%eth0

# Проверка прохождения NDP
sudo ndisc6 -1 2001:db8::1 eth0

# Перехват ICMPv6 Packet Too Big
sudo tcpdump -i eth0 'icmp6 and icmp6[0] == 2' -nn
```

### Проверка корректности правил

```bash
# Проверить, что ICMPv6 Type 2 разрешен
sudo nft list ruleset | grep -i packet-too-big

# Проверить, что NDP разрешен
sudo nft list ruleset | grep nd-neighbor

# Проверить счетчики пакетов
sudo nft list ruleset -a
# → tcp dport 22 accept # packets 1542 bytes 98720
```

## Дополнительная информация

### Типичные ошибки

- **Блокировка ICMPv6 Type 2 (Packet Too Big)**: разрушает механизм Path MTU Discovery. Симптом: мелкие пакеты проходят, большие сессии (например, передача файлов) "зависают".
- **Асимметрия правил**: ситуация, когда `iptables` настроен, а `ip6tables` оставлен с политикой `ACCEPT` по умолчанию (или наоборот, всё закрыто, включая NDP).
- **NDP на мостах (Bridges)**: при использовании `ebtables` или `nftables bridge` случайная блокировка Multicast-адресов приводит к потере связи между узлами в одном сегменте.
- **Забытый `bridge-nf-call-ip6tables`**: трафик IPv6 между портами моста не фильтруется.
- **Отсутствие MSS Clamping в туннелях**: PMTUD не работает из-за усеченного MTU туннеля.
- **Переполнение conntrack**: при высокой нагрузке новые соединения дропаются. Симптом: `nf_conntrack: table full, dropping packet` в `dmesg`.

### См. также

- **[Общие вопросы сохранения правил](../tools/firewall_common.md)** — персистентность конфигурации.
- **[Настройка адресов IPv6](./address_configuration.md)** — подготовка сетевых интерфейсов.
- **[Диагностика сети](./diagnostics.md)** — инструменты проверки связности и поиска ошибок NDP.
- **[nftables: практические сценарии](../tools/nftables/practical_scenarios.md)** — глубокое погружение в синтаксис `nft`.
- **[Мониторинг IPv6](./monitoring.md)** — Prometheus, Blackbox Exporter, alerting для IPv6.
