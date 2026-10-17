# Распределённые атаки типа «отказ в обслуживании» (DDoS)

**Актуально для:** Linux kernel 6.1+ / Nginx 1.25+ / Angie 1.7+ / nftables 1.0+ / fail2ban 1.0+

## Определения

**DDoS (Distributed Denial of Service — Распределённый отказ в обслуживании)** — это целенаправленная атака на информационную систему с целью сделать её недоступной для легитимных пользователей. Атака реализуется путём генерации огромного объёма трафика или ресурсоёмких запросов с множества распределённых источников (обычно ботнетов), что приводит к исчерпанию ресурсов сервера, канала связи или приложения.

**DoS (Denial of Service)** — аналогичная атака с единственного источника.

**Volumetric (Волюметрические) атаки** — атаки, цель которых — переполнить полосу пропускания канала или ресурсы сетевого оборудования (L3/L4).

**Application-layer (L7) атаки** — атаки, цель которых — исчерпать ресурсы самого приложения (CPU, RAM, подключения к БД). Трафик выглядит как легитимный, что делает обнаружение сложным.

**Amplification (Усиление)** — техника, при которой атакующий использует публичные сервисы с большим соотношением ответ/запрос (например, DNS, NTP, Memcached) для многократного увеличения объёма трафика, направленного на жертву.

**Anycast** — метод сетевой маршрутизации, при котором один и тот же IP-адрес назначается нескольким географически распределённым точкам присутствия (PoP). Anycast естественным образом распределяет и "размазывает" DDoS-трафик по нескольким узлам, увеличивая агрегированную пропускную способность.

**SYN Cookies** — метод защиты сетевого стека ядра Linux от SYN-флуда, при котором состояние незавершённого TCP-соединения кодируется в начальном номере последовательности (Sequence Number) пакета SYN-ACK, не расходуя память на хранение полуоткрытых сессий.

**Синхронизация счётчиков (Counter Synchronization)** — техника кластерной защиты, при которой состояние rate-limiting и connlimit синхронизируется между узлами балансировщика (например, `zone_sync` в Angie PRO), предотвращая обход лимитов на одиночном хосте.

**BCP38 (Best Current Practice 38)** — стандарт фильтрации входящего трафика на уровне провайдера (RFC 2827), реализуемый через Unicast Reverse Path Forwarding (uRPF) для предотвращения подделки IP-адресов источника (IP spoofing).

**Defense in Depth (Глубинная защита)** — стратегия многоуровневой защиты, при которой каждый слой сети защищается независимо.

В отличие от DoS (атаки с одного источника), DDoS практически невозможно заблокировать простым ограничением по IP, так как источники географически распределены и легитимно имитируют поведение реальных пользователей. В современных реалиях (2025–2026 гг.) атаки становятся всё более адаптивными, используя эвристические алгоритмы для обхода классических пороговых фильтров и WAF. QUIC (RFC 9000, 2021) и HTTP/3 (RFC 9114, 2022) уже стандартизированы, но их UDP-транспорт и встроенное шифрование создают новые векторы атак.

## Классификация атак по уровням OSI

Эффективная защита требует понимания того, на какой уровень модели OSI направлен удар.

### Сетевой и транспортный уровни (L3/L4 — Волюметрические атаки)

Цель — переполнение полосы пропускания (bandwidth) или ресурсов сетевого оборудования.

- **UDP Flood:** Массовая отправка UDP-пакетов на случайные порты. Сервер тратит ресурсы на проверку приложения и отправку ICMP Destination Unreachable. Защита: фильтрация в `nftables` (DROP вместо ICMP-ответов), BGP Flowspec на edge.
- **ICMP Flood:** Заваливание сервера запросами ICMP Echo Request (ping). Защита: `net.ipv4.icmp_ratelimit`, `net.ipv4.icmp_ratelimit_mask`, частиччное ограничение ICMP (без полного блокирования — нужен для PMTUD).
- **SYN Flood:** Использование особенностей «трёхэтапного рукопожатия» TCP. Злоумышленник шлёт SYN-пакеты, но не отвечает на SYN-ACK, забивая очередь соединений (backlog) сервера. Защита: SYN cookies, увеличение `tcp_max_syn_backlog`, SYN proxy.
- **Атаки усиления (Amplification):** Использование публичных сервисов (DNS, NTP, Memcached, SNMP) для многократного увеличения объёма вредоносного трафика, направленного на жертву. Защита: BCP38 (anti-spoofing на edge-интерфейсах), ограничение ответов на UDP (например, `rate limit` в BIND для DNS), блокировка ответов на подспуненные IP.
- **QUIC / HTTP/3 Flood:** Относительно новый вектор, использующий протокол QUIC (RFC 9000, 2021) на базе UDP. Атаки сложнее фильтровать из-за встроенного шифрования заголовков и возможности обхода классических TCP-фильтров. Защита: `quic_retry on` (Address Validation), `quic_gso on`, мониторинг UDP-трафика на L3/L4.

### Прикладной уровень (L7 — Атаки на приложения)

- **HTTP Flood:** Массовые GET или POST запросы к тяжёлым страницам, API-эндпоинтам или поисковым механизмам. Защита: rate limiting на L7, behavioral analysis, WAF.
- **Slowloris:** Удержание HTTP-соединений открытыми максимально долго путём крайне медленной отправки заголовков. Защита: `client_header_timeout`, `limit_conn`.
- **Slow POST (R.U.D.Y):** Медленная отправка тела запроса, что заставляет сервер держать соединение активным в ожидании данных. Атака нацелена на исчерпание пула воркеров через удержание дескрипторов файлов и буферов ввода-вывода. Защита: `client_body_timeout`, `client_max_body_size`.
- **Атаки на бизнес-логику:** Массовые попытки авторизации (Brute-force), тяжёлые запросы к БД, имитация процесса оформления заказа или бронирования для исчерпания пула соединений. Защита: rate limiting на auth-эндпоинты, API-ключи, circuit breakers.
- **Rapid Reset (CVE-2023-44487):** HTTP/2 и HTTP/3 атака, при которой клиент мультиплексирует тысячи потоков (streams) и немедленно отправляет кадр отмены `RST_STREAM`, вынуждая сервер тратить CPU на выделение и очистку структур состояния потока. Защита: `http2_max_concurrent_streams` / `http3_max_concurrent_streams`, rate limiting на L7, мониторинг `RST_STREAM`-ответов в access log.
- **Атаки на DNS-инфраструктуру:** Амплификация через открытые резолверы, flood-атаки на authoritative серверы для исчерпания UDP-порта 53. Защита: BCP38, response rate limiting (RRL) в BIND, ограничение рекурсии на authoritative серверах, блокировка UDP-ответов на подспуненные IP.

## Предпосылки и системные требования

### Железо и ОС

Защита от DDoS на уровне bare-metal требует запасов по ресурсам, чтобы пережить время до срабатывания автоматических средств очистки.

| Компонент | Минимум (SRE) | Рекомендация (Production) |
| :--- | :--- | :--- |
| **CPU** | 4 ядра x86_64 | 8+ ядер, предпочтительно с поддержкой AES-NI / AVX2 |
| **RAM** | 4 GB | 16+ GB (для nftables sets, conntrack, shared memory зон) |
| **Диск** | 20 GB SSD | 100+ GB SSD NVMe (логи, базы fail2ban, метрики) |
| **Сеть** | 1 Gbps NIC | 10 Gbps NIC с поддержкой XDP / AF_XDP |
| **ОС** | RHEL 9 / Debian 12 / Ubuntu 22.04 | RHEL 9 / Debian 12 (ядро 5.15+ для nftables) |
| **Ядро** | 5.4+ | 6.1+ (полная поддержка nftables, XDP, SYN cookies) |

### Программный стек

| Компонент | Версия / Примечание |
| :--- | :--- |
| **Web-сервер** | Nginx 1.25+ (stable 1.26) / Angie 1.7+ (latest 1.10) / Apache 2.4+ |
| **Firewall** | nftables (рекомендуется) или iptables с ipset |
| **IDS/IPS** | fail2ban 1.0+ (с nftables backend) |
| **Мониторинг** | Prometheus + node_exporter, Loki, Grafana |
| **Сетевые утилиты** | `hping3`, `nftables`, `ipset`, `conntrack-tools`, `tcpdump` |
| **Тестирование** | `wrk`, `ab` (ApacheBench), `siege`, `slowhttptest` |

## Архитектура эшелонированной защиты

Защита от DDoS должна быть многоуровневой (**Defense in Depth**). В контексте on-premises инфраструктуры акцент делается на периметре сети, сетевом стеке ядра и уровне приложения.

### Периметр сети (Edge)
- **BGP Flowspec / RTBH:** Передача правил фильтрации на уровень апстрим-провайдера для блокировки атаки максимально близко к источнику.
- **Anycast:** Распределение трафика по географически разбросанным PoP через один и тот же IP-адрес. Естественно «размазывает» volumetric атаки по нескольким узлам, увеличивая агрегированную пропускную способность. См. также: **[Anycast в frontend WAF/DDoS](../../CI-CD/Frontend_CI_CD/frontend_waf_ddos_rate_limiting.md)**.
- **BCP38 / uRPF:** Фильтрация подспуненного трафика (IP spoofing) на edge-интерфейсах. Блокирует ~50% volumetric и amplification атак, где злоумышленник подменяет IP-адрес источника.
- **L4 Балансировщики (LVS / Katran):** Использование eBPF для сверхбыстрой балансировки и сброса мусорных пакетов. Принципы работы описаны в разделе **[Продвинутые алгоритмы балансировки](../../Concepts/High_Availability/ha_clustering_and_load_balancing.md)**.
- **nftables / iptables raw:** Фильтрация на уровне netfilter до передачи пакетов приложению.
- **Traffic Control (tc / HTB):** Полicing и shaping на уровне L3, ограничение полосы пропускания для конкретных IP или протоколов. Работает вне conntrack.

### Инфраструктурный слой (Load Balancer)
- **Rate Limiting:** Ограничение частоты запросов (RPS) на уровне IP, сессии или API-ключа. Подробнее: **[DDoS mitigation в HTTP](../../Networking/Protocols/HTTP/http_security_hardening.md)**.
- **Connection Limiting:** Ограничение количества одновременных активных сессий.
- **Health Checks:** Автоматическое исключение перегруженных или упавших узлов из балансировки.

### Слой ОС и ядра (Kernel)
- **SYN Cookies:** Защита от SYN-флуда на уровне ядра Linux, позволяющая устанавливать соединения без хранения состояния до завершения рукопожатия.
- **SYN Proxy:** Активная проверка TCP-рукопожатия на уровне netfilter (nftables/iptables) перед передачей соединения приложению. Перехватывает и восстанавливает handshake, защищая от SYN-флуда с подменой IP. См. также: **[SYN proxy в NAT-сценариях](../../Networking/Concepts/nat/practical_scenarios.md#syn-proxy-полная-проверка-handshake)**.
- **XDP (eXpress Data Path) / eBPF:** Высокопроизводительный сброс пакетов на уровне драйвера сетевой карты, до их обработки сетевым стеком ядра. См. подробнее: **[eBPF — системный уровень защиты](../../Linux/Core/kernel/ebpf.md)**.
- **nf_conntrack:** Отслеживание состояния соединений. При исчерпании таблицы `nf_conntrack_max` новые соединения отбрасываются. Критически важно для Docker-хостов и high-load систем. Оптимизация описана в **[Оптимизация Docker](../../Docker/Docker_performance_tuning.md)**.
- **TCP challenge ACK rate limiting:** `net.ipv4.tcp_challenge_ack_limit` (по умолчанию 100) защищает от обратного сканирования сети через TCP RST injection.

### Слой приложения (L7)
- **WAF (Web Application Firewall):** Анализ L7 трафика, блокировка известных паттернов атак, проверка сигнатур и поведенческая фильтрация. См. подробнее: **[WAF: Web Application Firewall](./waf.md)**.
- **fail2ban:** Автоматический анализ логов и блокировка IP нарушителей. См. подробнее: **[fail2ban — Инструменты защиты](../../Linux/Security/Tools/fail2ban.md)**.
- **Angie/Nginx:** Rate limiting, connection limiting, Slowloris protection, QUIC retry. См. подробнее: **[Защита от DoS в Angie/Nginx](../../WebServers/Angie/High_Load/dos_protection.md)**.

## Методы и инструменты защиты

| Уровень | Метод / Инструмент | Описание |
| :--- | :--- | :--- |
| **L3/L4** | **SYN Cookies** | `net.ipv4.tcp_syncookies=1`. Устойчивость к переполнению SYN-очереди. |
| **L3/L4** | **SYN Proxy** | Активная проверка TCP-рукопожатия в netfilter перед передачей приложению. |
| **L3/L4** | **BCP38 / uRPF** | Фильтрация подспуненного трафика на edge. `net.ipv4.conf.all.rp_filter=1`. |
| **L3/L4** | **XDP (eXpress Data Path)** | Сброс миллионов пакетов в секунду на уровне NIC с минимальной нагрузкой на CPU. |
| **L3/L4** | **Traffic Control (tc/HTB)** | Полicing и shaping на уровне L3, ограничение полосы пропускания для IP/протоколов. |
| **L3/L4** | **nftables rate limit** | `limit rate` в `inet filter` table. Защита от brute-force и flood на L3/L4. |
| **L3/L4** | **ipset hash:ip** | Хранение тысяч блокируемых IP в памяти с O(1) доступом. |
| **L3/L4** | **Anycast** | Распределение volumetric трафика по PoP через один IP-адрес. |
| **L7** | **Rate Limiting** | Модули Nginx/Angie (`limit_req`). Ограничение интенсивности запросов. |
| **L7** | **Connection Limiting** | Модули Nginx/Angie (`limit_conn`). Ограничение числа одновременных соединений. |
| **L7** | **Challenge (JS/Captcha)** | Проверка "человечности". Современные WAF используют невидимые JS-челленджи. |
| **L7** | **Behavioral Analysis** | Анализ цепочек запросов и отпечатков (fingerprinting) для выявления ботов. |
| **L7** | **Request Size / Body Limit** | `client_max_body_size`, `client_header_timeout`. Защита от memory-exhaustion. |
| **L7** | **Rapid Reset Protection** | `http2_max_concurrent_streams` / `http3_max_concurrent_streams`. Ограничение параллельных потоков. |
| **API** | **Schema Validation** | Блокировка запросов, не соответствующих OpenAPI/gRPC спецификации. |
| **API** | **API Key / Rate Limits** | Ограничение RPS на уровне API-ключа или JWT-токена. |

## Практические сценарии и конфигурация

### Тюнинг ядра Linux для защиты от DoS (sysctl)

Актуальные параметры для современных высоконагруженных систем:

```bash
# Включение SYN Cookies
sysctl -w net.ipv4.tcp_syncookies=1

# Увеличение очереди SYN-пакетов
sysctl -w net.ipv4.tcp_max_syn_backlog=8192

# Уменьшение времени ожидания закрытия соединения (защита от забивания таблицы)
sysctl -w net.ipv4.tcp_fin_timeout=15

# Быстрое освобождение портов TIME_WAIT (защита от port exhaustion)
sysctl -w net.ipv4.tcp_tw_reuse=1
sysctl -w net.ipv4.tcp_max_tw_buckets=200000

# Ограничение повторных попыток SYN+ACK
sysctl -w net.ipv4.tcp_synack_retries=2

# Защита от атак через изменение маршрутов (ICMP Redirect)
sysctl -w net.ipv4.conf.all.accept_redirects=0
sysctl -w net.ipv4.conf.default.accept_redirects=0
sysctl -w net.ipv6.conf.all.accept_redirects=0
sysctl -w net.ipv6.conf.default.accept_redirects=0

# Включение маршрутизации (если сервер шлюз)
sysctl -w net.ipv4.ip_forward=1

# Увеличение лимитов на количество открытых соединений (conntrack)
sysctl -w net.netfilter.nf_conntrack_max=1048576
sysctl -w net.netfilter.nf_conntrack_buckets=262144
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=600
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_close_wait=15
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_fin_wait=15

# Защита от spoofing (anti-spoofing) — BCP38
sysctl -w net.ipv4.conf.all.rp_filter=1
sysctl -w net.ipv4.conf.default.rp_filter=1
# rp_filter=2 (Loose mode) для асимметричной маршрутизации
# sysctl -w net.ipv4.conf.all.rp_filter=2

# Ограничение TCP challenge ACK (защита от обратного сканирования)
sysctl -w net.ipv4.tcp_challenge_ack_limit=100

# Аборт при переполнении SYN backlog (вместо молчаливого дропа)
sysctl -w net.ipv4.tcp_abort_on_overflow=1

# Ограничение ICMP broadcast
sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=1
sysctl -w net.ipv4.icmp_ignore_bogus_error_responses=1
```

**Валидация:**
```bash
# Проверка параметров
sysctl net.ipv4.tcp_syncookies
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max

# Проверка ошибок conntrack
dmesg | grep -i conntrack
# → nf_conntrack: table full, dropping packet
```

### nftables: Rate Limiting и фильтрация (SSoT)

Современный подход (RHEL 9+, Debian 12+). nftables использует нативные `sets` для O(1) проверки IP.

```nft
table inet filter {
    set blackhole {
        type ipv4_addr
        flags timeout
        timeout 1h
        size 65536
    }

    set ddos_limits {
        type ipv4_addr
        flags dynamic, timeout
        timeout 60s
        size 65536
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Легитимный трафик
        ct state established,related accept
        iif "lo" accept

        # Блокировка IP из blackhole (fail2ban, ручные баны)
        ip saddr @blackhole drop

        # Защита от SYN flood: лимит 10 новых SYN в секунду с одного IP
        tcp flags syn tcp dport 80,443 ct state new limit rate 10/second accept
        tcp flags syn tcp dport 80,443 ct state new add @ddos_limits { ip saddr }
        ip saddr @ddos_limits drop

        # SSH brute-force protection: 6 новых соединений в минуту
        tcp dport 22 ct state new limit rate 6/minute accept
        tcp dport 22 ct state new add @ddos_limits { ip saddr }

        # Иначе — разрешить (если прошёл rate limit)
        accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
```

**Валидация:**
```bash
# Проверка конфигурации
nft -c -f /etc/nftables.conf
# → no errors

# Применение
nft -f /etc/nftables.conf

# Статус sets
nft list set inet filter ddos_limits
nft list set inet filter blackhole

# Мониторинг в реальном времени
watch -n 1 'nft list set inet filter ddos_limits'
```

### BCP38 / uRPF через nftables (anti-spoofing на edge)

Фильтрация подспуненного трафика на уровне netfilter — реализация BCP38 непосредственно на хосте.

```nft
table inet filter {
    set bogon_prefixes {
        type ipv4_prefix
        flags interval
        elements = {
            0.0.0.0/8,
            10.0.0.0/8,
            100.64.0.0/10,
            127.0.0.0/8,
            169.254.0.0/16,
            172.16.0.0/12,
            192.0.0.0/24,
            192.0.2.0/24,
            192.88.99.0/24,
            192.168.0.0/16,
            198.18.0.0/15,
            198.51.100.0/24,
            203.0.113.0/24,
            224.0.0.0/4,
        }
    }

    chain preraw {
        type filter hook prerouting priority -300; policy accept;
        # Drop packets from bogon source IPs on external interface
        iifname "eth0" ip saddr @bogon_prefixes drop
    }
}
```

**Валидация:**
```bash
# Проверка: bogon-адреса не должны проходить на eth0
nft list chain inet filter preraw
```

### Traffic Control (tc/HTB) — полисинг policed traffic

Дополнение к nftables: ограничение полосы пропускания на уровне L3 с помощью `tc` + HTB. Работает вне conntrack, защищает при исчерпании таблицы conntrack.

```bash
# Создаём qdisc на входном интерфейсе
tc qdisc add dev eth0 root handle 1: htb default 30

# Корневая HTB-очередь (общая полоса)
tc class add dev eth0 parent 1: classid 1:1 htb rate 1gbit ceil 1gbit

# Лимит на UDP-трафик (защита от UDP flood) — 100 Mbit
tc class add dev eth0 parent 1:1 classid 1:10 htb rate 100mbit ceil 200mbit

# Лимит на TCP соединения на 80/443 — 800 Mbit
tc class add dev eth0 parent 1:1 classid 1:20 htb rate 800mbit ceil 900mbit

# Лимит на ICMP — 10 Mbit
tc class add dev eth0 parent 1:1 classid 1:30 htb rate 10mbit ceil 20mbit

# Фильтры: классификация трафика по протоколу и порту
tc filter add dev eth0 protocol ip parent 1:0 prio 1 u32 match ip protocol 17 0xff flowid 1:10  # UDP
tc filter add dev eth0 protocol ip parent 1:0 prio 2 u32 match ip dport 80 0xffff flowid 1:20  # HTTP
tc filter add dev eth0 protocol ip parent 1:0 prio 2 u32 match ip dport 443 0xffff flowid 1:20  # HTTPS
tc filter add dev eth0 protocol ip parent 1:0 prio 3 u32 match ip protocol 1 0xff flowid 1:30  # ICMP
```

**Валидация:**
```bash
# Просмотр qdisc и классов
tc qdisc show dev eth0
tc class show dev eth0

# Статистика по классам (проверка на превышение лимита)
tc -s class show dev eth0
```

### Настройка Rate Limiting в Nginx / Angie

Комплексная настройка с защитой от всплесков. Angie поддерживает кластерную синхронизацию лимитов (`sync`).

```nginx
# Определение зон для RPS и соединений
limit_req_zone $binary_remote_addr zone=api_limit:20m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=addr_limit:20m;

server {
    listen 443 ssl;
    http2 on;
    server_name api.example.com;

    # Slowloris protection
    client_header_timeout 10s;
    client_body_timeout   10s;
    send_timeout          10s;
    keepalive_timeout     65s;
    keepalive_requests    1000;

    location /api/ {
        # Лимит 10 зап/сек с всплеском (burst) до 30
        limit_req zone=api_limit burst=30 nodelay;
        limit_req_status 429;
        limit_req_log_level warn;

        # Ограничение до 15 одновременных соединений с одного IP
        limit_conn addr_limit 15;
        limit_conn_status 429;

        proxy_pass http://backend_api;
    }
}
```

**Валидация:**
```bash
# Проверка заголовков
curl -I https://api.example.com/api/health

# Нагрузочное тестирование (должен получать 429 после burst)
ab -n 100 -c 25 https://api.example.com/api/health
# → 429 Too Many Requests после превышения burst

# Проверка статистики лимитов (Angie)
curl http://localhost/api/v1/http/limit_reqs/api_limit
```

### Защита QUIC / HTTP/3

QUIC-флуд использует UDP и встроенное шифрование заголовков, что усложняет классическую фильтрацию.

```nginx
server {
    listen 443 quic reuseport;
    listen 443 ssl;
    http2 on;
    http3 on;

    # Обязательный Retry для защиты от UDP-spoofing
    quic_retry on;
    quic_gso on;

    # Ограничение параллельных потоков (защита от исчерпания ресурсов)
    http2_max_concurrent_streams 64;
    http3_max_concurrent_streams 64;

    # Ограничение тела запроса
    client_max_body_size 10m;
}
```

### SYN Proxy (nftables) — активная проверка TCP-рукопожатия

SYN proxy перехватывает TCP-рукопожатие на уровне netfilter и проходит его полностью, прежде чем передать соединение приложению. Защищает от SYN-флуда с подменой IP-адреса. Требует nftables 1.0+ и ядра Linux 5.6+.

```nft
table ip raw {
    chain prerouting {
        type filter hook prerouting priority -300; policy accept;

        # SYN proxy для входящих соединений на 80/443
        tcp dport { 80, 443 } ct state { invalid, untracked } \
            synproxy mss 1460 wscale 7 sack-perm

        # Bypass conntrack для SYN-пакетов (SYN proxy обрабатывает handshake)
        tcp dport { 80, 443 } tcp flags syn notrack
    }
}
```

**Валидация:**
```bash
# Проверка: количество отслеживаемых соединений через SYN proxy
conntrack -L | wc -l
# → Рост при активном SYN-флуде, стабильно при штатном трафике

# Проверка правила
nft list chain ip raw prerouting
```

fail2ban анализирует логи Nginx/Angie и автоматически вносит IP нарушителей в nftables sets.

**Фильтр для HTTP-flood и сканирования (`/etc/fail2ban/filter.d/nginx-ddos.conf`):**
```ini
[Definition]
failregex = ^<HOST> -.* "(GET|POST|HEAD).*" (403|429|404) .*$
            ^<HOST> -.* "(GET|POST|HEAD).*" 200 .* "(php|admin|wp-login)" .*$
            ^<HOST> -.* ".*(\.\./|etc/passwd|cmd\.exe|SELECT.*FROM).*" .*$

ignoreregex =

datepattern = {^LN-BEG}%%Y-%%m-%%d[T ]%%H:%%M:%%S(?:[.,]%%f)?%%z
```

**Jail (`/etc/fail2ban/jail.d/nginx-ddos.conf`):**
```ini
[nginx-ddos]
enabled  = true
port     = http,https
protocol = tcp
filter   = nginx-ddos
logpath  = /var/log/nginx/access.log
maxretry = 50
findtime = 60
bantime  = 3600
banaction = nftables-multiport
backend  = systemd
# Автоувеличение ban-time для repeat offenders
bantime.increment = true
#bantime.factor = 2
```

**Валидация:**
```bash
# Тест фильтра
sudo fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/nginx-ddos.conf

# Проверка статуса jail
sudo fail2ban-client status nginx-ddos
# → Banned IP list: <ip1> <ip2> ...

# Проверка статуса jail (включая список забаненных IP)
sudo fail2ban-client status nginx-ddos
# → Status: ... Banned IP list: <ip1> <ip2> ...
```

**SRE-интеграция с мониторингом:**
```bash
# Экспорт метрик в Prometheus (через textfile collector)
cat <<'EOF' > /etc/fail2ban/prometheus_exporter.sh
#!/bin/bash
JAILS=$(sudo fail2ban-client status | grep "Jail list" | cut -f2- -d: | tr ',' '\n' | sed 's/^ *//;s/ *$//')
for JAIL in $JAILS; do
    BANNED=$(sudo fail2ban-client status "$JAIL" | grep "Currently banned" | awk '{print $4}')
    echo "fail2ban_banned_ip{ jail=\"$JAIL\" } $BANNED"
done
EOF
chmod +x /etc/fail2ban/prometheus_exporter.sh
```

### Мониторинг и оповещения

| Метрика | Источник | Порог (SRE) |
| :--- | :--- | :--- |
| `nginx_http_requests_total` | Nginx/Angie stub_status | Рост > 200% от baseline за 5m |
| `nginx_http_429_responses_total` | Nginx/Angie log | > 100/мин |
| `node_netstat_Tcp_ActiveOpens` | node_exporter | Рост > 500/сек |
| `node_netstat_Tcp_OutRsts` | node_exporter | Рост > 100/сек (SYN flood indicator) |
| `node_nf_conntrack_count` | node_exporter | > 80% от `nf_conntrack_max` |
| `node_netstat_Udp_InErrors` | node_exporter | Рост входящих UDP без ответа (UDP flood) |
| `node_netstat_Icmp_InErrors` | node_exporter | Рост ICMP ошибок (ICMP flood) |
| `node_sockstat_TCP_inuse` | node_exporter | > 80% от `net.core.somaxconn` |
| `rate(node_cpu_seconds_total{mode="softirq"}[5m])` | node_exporter | > 50% (сетевая перегрузка на уровне ядра) |
| `fail2ban_banned_ip` | fail2ban exporter | Рост количества забаненных IP > 100 за 5m |

**Prometheus Recording Rules:**
```yaml
# /etc/prometheus/rules/ddos_rules.yml
groups:
  - name: ddos_alerts
    rules:
      - alert: HighRequestRate
        expr: rate(nginx_http_requests_total[5m]) > 200
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Аномальный рост запросов на {{ $labels.server }}"
          description: "RPS вырос до {{ $value }} (baseline ~50)"

      - alert: RateLimitRejected
        expr: rate(nginx_http_429_responses_total[5m]) > 100
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Массовые отклонения 429 на {{ $labels.server }}"
          description: "Возможна L7 DDoS-атака или сломанный клиент."

      - alert: ConntrackTableNearFull
        expr: node_nf_conntrack_count / node_nf_conntrack_max > 0.8
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Таблица conntrack заполнена на {{ $value | humanizePercentage }}"
          description: "Увеличить nf_conntrack_max или искать источник flood."

      - alert: SynFloodIndicator
        expr: rate(node_netstat_Tcp_OutRsts[5m]) > 100
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Возможен SYN flood на {{ $labels.instance }}"
          description: "TCP RST/SYN-ACK отбрасывается."

      - alert: UdpFloodIndicator
        expr: rate(node_netstat_Udp_InErrors[5m]) > 50
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Возможен UDP flood на {{ $labels.instance }}"
          description: "Рост входящих UDP-пакетов без ответа."

      - alert: IcmpFloodIndicator
        expr: rate(node_netstat_Icmp_InErrors[5m]) > 30
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Возможен ICMP flood на {{ $labels.instance }}"
          description: "Рост ICMP-запросов без ответа."

      - alert: KernelSoftirqSaturation
        expr: rate(node_cpu_seconds_total{mode="softirq"}[5m]) > 0.5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Сетевая перегрузка ядра на {{ $labels.instance }}"
          description: "softirq > 50% — вероятен volumetric L3/L4 flood."
```

**Loki LogQL (анализ логов Nginx):**
```logql
# Топ-10 IP по количеству запросов за 5 минут
topk(10, sum by (client_ip) (rate({job="nginx"} |= " " [5m])))

# Поиск паттернов сканирования
{job="nginx"} |= "admin" |= "wp-login" | line_format "{{.client_ip}}"

# Количество 429 за последний час
sum_over_time({job="nginx"} |= " 429 " [1h])
```

### Валидация и нагрузочное тестирование

```bash
# Тест SYN flood (hping3) — запускать ТОЛЬКО на собственных системах
sudo hping3 -S --flood -p 80 <target_ip>
# → Должен наблюдаться рост Tcp_OutRsts и защита через SYN cookies

# Тест Slowloris (slowhttptest)
sudo apt install slowhttptest
slowhttptest -H -c 1000 -g -o slowloris_test -i 10 -r 200 -t GET -u https://api.example.com/health -x 24 -p 3
# → Nginx должен разрывать соединения по client_header_timeout

# Нагрузочное тестирование (wrk)
wrk -t12 -c400 -d30s --latency https://api.example.com/api/health
# → После burst должен получать 429

# Проверка SYN cookies
cat /proc/sys/net/ipv4/tcp_syncookies
# → 1

# Проверка nftables sets
nft list set inet filter ddos_limits | wc -l
# → Количество заблокированных IP

# Проверка fail2ban
sudo fail2ban-client status nginx-ddos
# → Currently banned: X
```

### Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `nf_conntrack: table full, dropping packet` | Исчерпание таблицы conntrack | Увеличить `nf_conntrack_max` (до 2M+), сократить таймауты. Проверить Docker DNAT. |
| `kernel: TCP: request_sock_TCP: Possible SYN flooding` | SYN-флуд | Убедиться, что `tcp_syncookies=1`, увеличить `tcp_max_syn_backlog`. |
| `Too many open files` | Исчерпание ulimit | `ulimit -n 65535` для nginx worker, `fs.file-max` в sysctl. |
| Неточный rate limiting (NAT) | Много клиентов за одним NAT | Использовать `$binary_remote_addr` или `$connection_serial` вместо IP. |
| fail2ban не банит | Неверный failregex | `fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/nginx-ddos.conf` |
| Замедление при nftables | Большой набор правил без sets | Использовать `sets` вместо цепочек `if`/`match`. |
| Пропуск трафика при amplification | Не настроен BCP38 | Настроить anti-spoofing (`rp_filter=1`) на edge-интерфейсах. |
| tc policed traffic drops legit | Слишком агрессивный лимит | Увеличить `rate`/`ceil` в HTB-классах через `tc class change`. |
| SYN proxy не работает | Конфликтует с `tcp_syncookies` или `notrack` | Проверить `nft list ruleset`, убедиться что `synproxy` в таблице `raw` с приоритетом `prerouting -300`. |

### Incident Response Playbook (SRE)

Краткая процедура действий при подозрении на DDoS-атаку:

**Этап 1 — Идентификация (0–5 мин):**
```bash
# 1. Проверка сетевой нагрузки
ss -s                          # состояние всех сокетов
ss -tan state syn-recv | wc -l # количество SYN_RECEIVED
iftop -i eth0                  # текущий входящий трафик в реальном времени

# 2. Проверка conntrack
cat /proc/sys/net/netfilter/nf_conntrack_count
# → близко к nf_conntrack_max?

# 3. Проверка аномалий в логах
tail -F /var/log/nginx/access.log | grep -E " (403|429|502|503) " | head -20
```

**Этап 2 — Триаж (5–15 мин):**
```bash
# Классификация атаки:
# L3/L4 (volumetric) — рост node_netstat_Udp_InErrors, Tcp_OutRsts, softirq
# L7 (application) — рост 429/503, запросы с одинакового паттерна

# Проверка активных блокировок
nft list set inet filter blackhole  # роутинг-сайд блокировки
nft list set inet filter ddos_limits # rate-limit срабатывания
sudo fail2ban-client status nginx-ddos

# Проверка топ-источников трафика
ss -tn state established | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -10
```

**Этап 3 — Реакция (15–60 мин):**
```bash
# 1. Жёсткое rate-limiting на проблемном endpoint
nft add rule inet filter input tcp dport 80,443 \
    ip saddr @ddos_limits { ip saddr limit rate over 5/second } \
    drop

# 2. Автоматическая блокировка IP в blackhole (1h)
#    (fail2ban добавляет в @blackhole, либо вручную:)
nft add element inet filter blackhole { 192.0.2.100 }

# 3. При необходимости — upstream RTBH/BGP Flowspec
#    (координация с провайдером)
```

**Этап 4 — Восстановление (60+ мин):**
```bash
# 1. Снятие блокировок после окончания атаки
nft flush set inet filter ddos_limits  # очистить временные лимиты

# 2. Анализ логов для post-mortem
#    - Топ атакующих IP
#    - Типы запросов
#    - Время и продолжительность
#    - Какие защитные слои сработали

# 3. Корректировка порогов в Prometheus AlertManager
#    и в fail2ban jails
```

**Связанные процедуры:**
- **BGP Flowspec / RTBH** — только при поддержке upstream-провайдера. Координатизация через NOC.
- **Anycast** — если используется, трафик распределяется автоматически по PoP.

## Лучшие практики (Checklist)

1.  **Kernel Hardening:** Включить SYN cookies, настроить `nf_conntrack_max` с запасом 30–50%, отключить ICMP redirects, включить `rp_filter=1` (или `=2` для асимметричной маршрутизации).
2.  **Anti-Spoofing на edge (BCP38):** Фильтрация bogon-префиксов на входе через nftables `set` в таблице `raw` (priority -300).
3.  **Rate Limiting на всех уровнях:** L3/L4 (nftables `limit rate`, tc/HTB для полисинга полосы) + L7 (Nginx/Angie `limit_req`/`limit_conn`) + приложение (API gateway).
4.  **SYN Proxy:** Активная проверка TCP-рукопожатия для серверов, не защищённых upstream-фильтром.
5.  **Fail2ban + nftables:** Использовать `nftables-multiport` banaction с `sets` для O(1) блокировок. Настроить отдельные jails для SSH, HTTP, API. Включить `bantime.increment = true`.
6.  **Monitoring & Alerting:** Настроить алерты на аномальные всплески RPS, рост 429/503 ошибок, заполнение conntrack, TCP RST, UDP/ICMP ошибки, softirq > 50%.
7.  **Capacity Planning:** Иметь запас по CPU (минимум 30%) и полосе пропускания. Использовать `wrk`/`ab`/`hping3` для определения baseline.
8.  **Incident Response:** Иметь playbook для DDoS: проверка `fail2ban-client status`, `nft list sets`, `ss -s`, `conntrack -S`. Документировать процедуру координации с провайдером (BGP Flowspec/RTBH).
9.  **QUIC / HTTP/3 Readiness:** Включить `quic_retry on`, настроить `http3_max_concurrent_streams`, мониторить UDP-трафик.
10. **Origin Protection:** Никогда не выставлять реальный IP сервера в интернет без фильтрации на edge. Использовать Anycast или scrubbing center для volumetric атак.
11. **Anycast:** Для сервисов с глобальной аудиторией использовать Anycast для естественного распределения volumetric трафика.

## Дополнительная информация

### Внутренние ссылки
- **[WAF: Web Application Firewall](./waf.md)** — глубокая инспекция L7 трафика и защита API.
- **[fail2ban — Инструменты защиты](../../Linux/Security/Tools/fail2ban.md)** — автоматизация блокировок на уровне IP.
- **[Защита от DoS в Angie/Nginx](../../WebServers/Angie/High_Load/dos_protection.md)** — продвинутые сценарии и кластерная синхронизация.
- **[eBPF/XDP — системный уровень защиты](../../Linux/Core/kernel/ebpf.md)** — архитектура сверхбыстрой фильтрации.
- **[DDoS mitigation в HTTP](../../Networking/Protocols/HTTP/http_security_hardening.md)** — rate limiting и Slowloris на уровне прокси.
- **[Транспортный уровень (L4)](../../Networking/OSI_TCP_IP_Model/transport_layer.md)** — L4 атаки (SYN Flood, UDP Flood, TCP RST) и защита в Linux.
- **[Модель TCP/IP](../../Networking/OSI_TCP_IP_Model/tcp_ip_model.md)** — классификация DDoS-атак по уровням TCP/IP.
- **[Защита DNAT-сервисов от DDoS](../../Networking/Concepts/nat/practical_scenarios.md)** — conntrack exhaustion, SYN proxy, rate limiting через NAT.
- **[Frontend WAF и DDoS](../../CI-CD/Frontend_CI_CD/frontend_waf_ddos_rate_limiting.md)** — Anycast, CDN, challenge pages для frontend.
- **[Продвинутые алгоритмы балансировки](../../Concepts/High_Availability/ha_clustering_and_load_balancing.md)** — LVS, Katran, Maglev.
- **[Оптимизация Docker](../../Docker/Docker_performance_tuning.md)** — conntrack и сетевые тюнинги для контейнерных хостов.

### Внешние ресурсы
- **[OWASP DDoS Attack Protection Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Prevention_Cheat_Sheet.html)**
- **[RFC 9000 — QUIC](https://www.rfc-editor.org/rfc/rfc9000)** — транспортный протокол для HTTP/3 (май 2021).
- **[RFC 9114 — HTTP/3](https://www.rfc-editor.org/rfc/rfc9114)** — прикладной протокол поверх QUIC.
- **[Cilium XDP Documentation](https://docs.cilium.io/en/stable/network/ebpf/xdp/)** — защита в Linux-средах.
- **[IETF BCP 38 (Anti-Spoofing)](https://www.rfc-editor.org/rfc/rfc2827.html)** — фильтрация на входе провайдера для предотвращения amplification.
- **[Linux tc Wiki](https://wiki.linuxfoundation.org/networking/netperf#traffic_control)** — документация Traffic Control и HTB-очередей.
