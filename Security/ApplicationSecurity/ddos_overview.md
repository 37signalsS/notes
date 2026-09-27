# Распределённые атаки типа «отказ в обслуживании» (DDoS)

## Определение

**DDoS (Distributed Denial of Service — Распределённый отказ в обслуживании)** — это целенаправленная атака на информационную систему с целью сделать её недоступной для легитимных пользователей. Атака реализуется путём генерации огромного объёма трафика или ресурсоёмких запросов с множества распределённых источников (обычно ботнетов), что приводит к исчерпанию ресурсов сервера, канала связи или приложения.

В отличие от DoS (атаки с одного источника), DDoS практически невозможно заблокировать простым ограничением по IP, так как источники географически распределены и легитимно имитируют поведение реальных пользователей. В современных реалиях (2025–2026 гг.) атаки становятся всё более адаптивными, используя эвристические алгоритмы для обхода классических пороговых фильтров и WAF.

## Классификация атак по уровням OSI

Эффективная защита требует понимания того, на какой уровень модели OSI направлен удар.

### Сетевой и транспортный уровни (L3/L4 — Волюметрические атаки)

Цель — переполнение полосы пропускания (bandwidth) или ресурсов сетевого оборудования.

- **UDP Flood:** Массовая отправка UDP-пакетов на случайные порты. Сервер тратит ресурсы на проверку приложения и отправку ICMP Destination Unreachable.
- **ICMP Flood:** Заваливание сервера запросами ICMP Echo Request (ping).
- **SYN Flood:** Использование особенностей «трёхэтапного рукопожатия» TCP. Злоумышленник шлёт SYN-пакеты, но не отвечает на SYN-ACK, забивая очередь соединений (backlog) сервера.
- **Атаки усиления (Amplification):** Использование публичных сервисов (DNS, NTP, Memcached, SNMP) для многократного увеличения объёма вредоносного трафика, направленного на жертву.
- **QUIC / HTTP/3 Flood:** Относительно новый вектор (стандарт 2026), использующий протокол QUIC на базе UDP. Атаки сложнее фильтровать из-за встроенного шифрования заголовков и возможности обхода классических TCP-фильтров.

### Прикладной уровень (L7 — Атаки на приложения)

Цель — исчерпание ресурсов самого приложения (CPU, RAM, подключения к БД). Эти атаки наиболее сложны для обнаружения, так как трафик выглядит как легитимный.

- **HTTP Flood:** Массовые GET или POST запросы к тяжёлым страницам, API-эндпоинтам или поисковым механизмам.
- **Slowloris:** Удержание HTTP-соединений открытыми максимально долго путём крайне медленной отправки заголовков.
- **Slow POST (R.U.D.Y):** Медленная отправка тела запроса, что заставляет сервер держать соединение активным в ожидании данных.
- **Атаки на бизнес-логику:** Массовые попытки авторизации (Brute-force), тяжёлые запросы к БД, имитация процесса оформления заказа или бронирования для исчерпания пула соединений.
- **Атаки на DNS-инфраструктуру:** Амплификация через открытые резолверы, flood-атаки на authoritative серверы для исчерпания UDP-порта 53.

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
| **Web-сервер** | Nginx 1.25+ / Angie 1.4+ / Apache 2.4+ |
| **Firewall** | nftables (рекомендуется) или iptables с ipset |
| **IDS/IPS** | fail2ban 0.11.x (с nftables backend) |
| **Мониторинг** | Prometheus + node_exporter, Loki, Grafana |
| **Сетевые утилиты** | `hping3`, `nftables`, `ipset`, `conntrack-tools`, `tcpdump` |
| **Тестирование** | `wrk`, `ab` (ApacheBench), `siege`, `slowhttptest` |

## Архитектура эшелонированной защиты

Защита от DDoS должна быть многоуровневой (**Defense in Depth**). В контексте on-premises инфраструктуры акцент делается на периметре сети, сетевом стеке ядра и уровне приложения.

### Периметр сети (Edge)
- **BGP Flowspec / RTBH:** Передача правил фильтрации на уровень апстрим-провайдера для блокировки атаки максимально близко к источнику.
- **L4 Балансировщики (LVS / Katran):** Использование eBPF для сверхбыстрой балансировки и сброса мусорных пакетов. Принципы работы описаны в разделе **[Продвинутые алгоритмы балансировки](../../Concepts/High_Availability/ha_clustering_and_load_balancing.md)**.
- **nftables / iptables raw:** Фильтрация на уровне netfilter до передачи пакетов приложению.

### Инфраструктурный слой (Load Balancer)
- **Rate Limiting:** Ограничение частоты запросов (RPS) на уровне IP, сессии или API-ключа. Подробнее: **[DDoS mitigation в HTTP](../../Networking/Protocols/HTTP/http_security_hardening.md)**.
- **Connection Limiting:** Ограничение количества одновременных активных сессий.
- **Health Checks:** Автоматическое исключение перегруженных или упавших узлов из балансировки.

### Слой ОС и ядра (Kernel)
- **SYN Cookies:** Защита от SYN-флуда на уровне ядра Linux, позволяющая устанавливать соединения без хранения состояния до завершения рукопожатия.
- **XDP (eXpress Data Path) / eBPF:** Высокопроизводительный сброс пакетов на уровне драйвера сетевой карты, до их обработки сетевым стеком ядра. См. подробнее: **[eBPF — системный уровень защиты](../../Linux/Core/kernel/ebpf.md)**.
- **nf_conntrack:** Отслеживание состояния соединений. При исчерпании таблицы `nf_conntrack_max` новые соединения отбрасываются. Критически важно для Docker-хостов и high-load систем. Оптимизация описана в **[Оптимизация Docker](../../Docker/Docker_performance_tuning.md)**.

### Слой приложения (L7)
- **WAF (Web Application Firewall):** Анализ L7 трафика, блокировка известных паттернов атак, проверка сигнатур и поведенческая фильтрация. См. подробнее: **[WAF: Web Application Firewall](./waf.md)**.
- **fail2ban:** Автоматический анализ логов и блокировка IP нарушителей. См. подробнее: **[fail2ban — Инструменты защиты](../../Linux/Security/Tools/fail2ban.md)**.
- **Angie/Nginx:** Rate limiting, connection limiting, Slowloris protection, QUIC retry. См. подробнее: **[Защита от DoS в Angie/Nginx](../../WebServers/Angie/High_Load/dos_protection.md)**.

## Методы и инструменты защиты

| Уровень | Метод / Инструмент | Описание |
| :--- | :--- | :--- |
| **L3/L4** | **SYN Cookies** | `net.ipv4.tcp_syncookies=1`. Устойчивость к переполнению SYN-очереди. |
| **L3/L4** | **XDP (eXpress Data Path)** | Сброс миллионов пакетов в секунду на уровне NIC с минимальной нагрузкой на CPU. |
| **L3/L4** | **nftables rate limit** | `limit rate` в `inet filter` table. Защита от brute-force и flood на L3/L4. |
| **L3/L4** | **ipset hash:ip** | Хранение тысяч блокируемых IP в памяти с O(1) доступом. |
| **L7** | **Rate Limiting** | Модули Nginx/Angie (`limit_req`). Ограничение интенсивности запросов. |
| **L7** | **Connection Limiting** | Модули Nginx/Angie (`limit_conn`). Ограничение числа одновременных соединений. |
| **L7** | **Challenge (JS/Captcha)** | Проверка "человечности". Современные WAF используют невидимые JS-челленджи. |
| **L7** | **Behavioral Analysis** | Анализ цепочек запросов и отпечатков (fingerprinting) для выявления ботов. |
| **API** | **Schema Validation** | Блокировка запросов, не соответствующих OpenAPI/gRPC спецификации. |

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

# Защита от spoofing (anti-spoofing)
sysctl -w net.ipv4.conf.all.rp_filter=1
sysctl -w net.ipv4.conf.default.rp_filter=1

# Ограничение переадресации ICMP
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
        flags timeout
        timeout 60s
        size 65536
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Легитимный трафик
        ct state established,related accept
        iif "lo" accept

        # Защита от SYN flood: лимит 10 новых SYN в секунду с одного IP
        tcp flags syn tcp dport 80,443 limit rate over 10/second accept
        tcp flags syn tcp dport 80,443 add @ddos_limits { ip saddr }

        # SSH brute-force protection: 6 новых соединений в минуту
        tcp dport 22 limit rate over 6/minute accept
        tcp dport 22 add @ddos_limits { ip saddr }

        # Блокировка IP из blackhole (fail2ban, ручные баны)
        ip saddr @blackhole drop

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

### Настройка Rate Limiting в Nginx / Angie

Комплексная настройка с защитой от всплесков. Angie поддерживает кластерную синхронизацию лимитов (`sync`).

```nginx
# Определение зон для RPS и соединений
limit_req_zone $binary_remote_addr zone=api_limit:20m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=addr_limit:20m;

server {
    listen 443 ssl http2;
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

### Защита QUIC / HTTP/3 (2026)

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

### fail2ban: Защита от DDoS на уровне приложения

fail2ban анализирует логи Nginx/Angie и автоматически вносит IP нарушителей в nftables sets.

**Фильтр для HTTP-flood и сканирования (`/etc/fail2ban/filter.d/nginx-ddos.conf`):**
```ini
[Definition]
failregex = ^<HOST> -.* "(GET|POST|HEAD).*" (403|429|404) .*$
            ^<HOST> -.* "(GET|POST|HEAD).*" 200 .* "(php|admin|wp-login)" .*$
            ^<HOST> -.* ".*(\.\./|etc/passwd|cmd\.exe|SELECT.*FROM).*" .*$

ignoreregex =

datepattern = {^LN-BEG}%%ExY(?P<_sep>[-/.])%%m(?P=_sep)%%d[T ]%%H:%%M:%%S(?:[.,]%%f)?(?!(?:[^<]*?</script>|[^<]*?</style>))
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
```

**Валидация:**
```bash
# Тест фильтра
sudo fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/nginx-ddos.conf

# Проверка статуса jail
sudo fail2ban-client status nginx-ddos

# Проверка блокировок
sudo fail2ban-client banned 192.0.2.100
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
| `node_netstat_Udp{...}` | node_exporter | Рост входящих UDP без ответа (UDP flood) |

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
| QUIC flood не детектируется | Защита только на L3/L4 | Добавить `quic_retry on`, мониторинг UDP-трафика, `limit_req` для QUIC. |
| Пропуск трафика при amplification | Не настроен BCP38 | Настроить anti-spoofing (`rp_filter=1`) на edge-интерфейсах. |

## Лучшие практики (Checklist)

1.  **Kernel Hardening:** Включить SYN cookies, настроить `nf_conntrack_max` с запасом 30–50%, отключить ICMP redirects, включить `rp_filter`.
2.  **Rate Limiting на всех уровнях:** L3/L4 (nftables/iptables) + L7 (Nginx/Angie `limit_req`/`limit_conn`) + приложение (API gateway).
3.  **Fail2ban + nftables:** Использовать `nftables-multiport` banaction с `sets` для O(1) блокировок. Настроить отдельные jails для SSH, HTTP, API.
4.  **Monitoring & Alerting:** Настроить алерты на аномальные всплески RPS, рост 429/503 ошибок, заполнение conntrack, TCP RST.
5.  **Capacity Planning:** Иметь запас по CPU (минимум 30%) и полосе пропускания. Использовать `wrk`/`ab` для определения baseline.
6.  **Incident Response:** Иметь playbook для DDoS: проверка `fail2ban-client status`, `nft list sets`, `ss -s`, `conntrack -S`.
7.  **QUIC Readiness:** Включить `quic_retry`, настроить `http3_max_concurrent_streams`, мониторить UDP-трафик.
8.  **Origin Protection:** Никогда не выставлять реальный IP сервера в интернет без фильтрации на edge.

## Дополнительная информация

### Внутренние ссылки
- **[WAF: Web Application Firewall](./waf.md)** — глубокая инспекция L7 трафика и защита API.
- **[fail2ban — Инструменты защиты](../../Linux/Security/Tools/fail2ban.md)** — автоматизация блокировок на уровне IP.
- **[Защита от DoS в Angie/Nginx](../../WebServers/Angie/High_Load/dos_protection.md)** — продвинутые сценарии и кластерная синхронизация.
- **[eBPF/XDP — системный уровень защиты](../../Linux/Core/kernel/ebpf.md)** — архитектура сверхбыстрой фильтрации.
- **[DDoS mitigation в HTTP](../../Networking/Protocols/HTTP/http_security_hardening.md)** — rate limiting и Slowloris на уровне прокси.
- **[Продвинутые алгоритмы балансировки](../../Concepts/High_Availability/ha_clustering_and_load_balancing.md)** — LVS, Katran, Maglev.
- **[Оптимизация Docker](../../Docker/Docker_performance_tuning.md)** — conntrack и сетевые тюнинги для контейнерных хостов.

### Внешние ресурсы
- **[OWASP DDoS Attack Protection Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Prevention_Cheat_Sheet.html)**
- **[Cilium XDP Documentation](https://docs.cilium.io/en/stable/network/ebpf/xdp/)** — защита в Linux-средах.
- **[IETF BCP 38 (Anti-Spoofing)](https://www.rfc-editor.org/rfc/rfc2827.html)** — фильтрация на входе провайдера для предотвращения amplification.
