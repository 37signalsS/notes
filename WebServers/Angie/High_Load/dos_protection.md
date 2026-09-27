# Защита от DoS-атак в Angie

## Определения

**DoS (Denial of Service — «отказ в обслуживании»)** — атака, направленная на исчерпание ресурсов сервера (CPU, RAM, пропускная способность, дескрипторы файлов) с одного источника. На прикладном уровне (L7) проявляется как массовый флуд запросов, медленные атаки (Slowloris, R.U.D.Y.) или атаки на бизнес-логику.

**DDoS (Distributed Denial of Service — распределённый отказ в обслуживании)** — та же цель, но достигается с множества распределённых источников (ботнет). Классические пороговые фильтры по IP часто неэффективны; требуется поведенческий анализ и кластерная синхронизация.

**Rate Limiting (Ограничение скорости)** — механизм управления входящим потоком запросов, использующий алгоритм *Leaky Bucket* (дырявое ведро). Запросы в пределах установленной частоты (`rate`) проходят свободно; всплески (`burst`) обрабатываются с задержкой или отклоняются с кодом `429`.

**Connection Limiting (Ограничение соединений)** — ограничение количества одновременных активных соединений с одного IP или на весь виртуальный сервер. Защищает от исчерпания `worker_connections`.

**Cluster Zone Sync** — технология синхронизации разделяемой памяти (shared memory) между узлами кластера Angie. Позволяет применять «честные» лимиты к распределённым атакам, где каждый отдельный бот не превышает локальный порог, но в сумме они выходят за допустимые рамки.

**Slowloris** — медленная атака, при которой злоумышленник удерживает соединения открытыми, отправляя HTTP-заголовки крайне медленно, что приводит к исчерпанию пула воркеров.

**HPACK Bomb** — атака на декодер HPACK в HTTP/2, при которой сжатая таблица заголовков занимает гигабайты оперативной памяти.

**Rapid Reset** — атака на HTTP/2 и HTTP/3, при которой клиент одновременно открывает множество потоков и сразу их сбрасывает, вынуждая сервер тратить CPU на обработку конечных состояний.

**QUIC Reflection / Flood** — атака на протокол QUIC (HTTP/3), использующая UDP и встроенное шифрование для обхода классических TCP-фильтров.

**Proof-of-Work (PoW) Challenge** — криптографический вызов, заставляющий клиента вычислить хеш с заданной сложностью перед обработкой запроса. Повышает стоимость атаки для злоумышленника без видимого влияния на легитимных пользователей.

**Retry-After** — заголовок ответа `429`, указывающий клиенту время ожидания перед повторным запросом. Упоминается в RFC 6585.

---

## Классификация угроз по уровням OSI

Эффективная защита строится на понимании того, на какой уровень модели OSI направлен удар. Angie работает на прикладном уровне (L7), но его эффективность напрямую зависит от настроек нижележащих уровней.

### Сетевой и транспортный уровни (L3/L4)

Цель атаки — переполнение полосы пропускания (bandwidth) или исчерпание ресурсов сетевого стека ядра.

- **UDP Flood:** Массовая отправка UDP-пакетов на случайные порты. Ядро тратит ресурсы на проверку приложения и отправку ICMP Destination Unreachable. Angie не видит такие пакеты — защита должна быть реализована на уровне nftables или аппаратного фаервола.
- **ICMP Flood:** Заваливание сервера запросами ICMP Echo Request (ping). Аналогично, блокируется до попадания трафика в Angie.
- **SYN Flood:** Отправка SYN-пакетов без завершения трёхэтапного рукопожатия. Забивает очередь `synack` (backlog) ядра. Защита: `sysctl net.ipv4.tcp_syncookies=1`, увеличение `tcp_max_syn_backlog`, nftables `limit rate`.
- **Атаки усиления (Amplification):** Использование публичных сервисов (DNS, NTP, Memcached) для умножения трафика. Защита на уровне провайдера (BCP38/anti-spoofing).
- **QUIC / HTTP/3 Flood:** Относительно новый вектор, использующий UDP. Сложен для фильтрации из-за встроенного шифрования. Angie защищается через `quic_retry on` (вызывает дополнительный round-trip для проверки) и `limit_req`.

### Прикладной уровень (L7)

Цель — исчерпание ресурсов самого Angie и бэкендов (воркеры, память, подключения к БД).

- **HTTP Flood:** Массовые GET/POST запросы к тяжёлым эндпоинтам. Защита: `limit_req`, `limit_conn`, GeoIP-блокировка.
- **Slowloris / Slow POST:** Удержание соединений открытыми путём медленной отправки заголовков или тела. Защита: агрессивные `client_header_timeout` и `client_body_timeout`.
- **Атаки на бизнес-логику:** Массовые попытки авторизации (brute-force), тяжёлые запросы к API. Защита: `auth_request` + `limit_req` на `/login`, интеграция с fail2ban.
- **HPACK Bomb (HTTP/2):** Атака на декöder сжатия заголовков. Защита: `max_headers`, ограничение размера буферов.
- **Rapid Reset (HTTP/2/3):** Каскадное открытие и сброс потоков. Защита: `http2_max_concurrent_streams`, `http3_max_concurrent_streams`, мониторинг `http2_reset_count`.

---

## Архитектура эшелонированной защиты

Защита от DoS/DDoS должна быть многоуровневой (Defense in Depth). В контексте on-premises инфраструктуры с Angie акцент делается на четырёх уровнях.

### 1. Периметр сети (Edge)

Фильтрация максимально близко к источнику трафика до его попадания в сервер Angie:
- **BGP Flowspec / RTBH:** Передача правил фильтрации на апстрим-провайдера для блокировки атаки на_edge_роутере.
- **L4 Балансировщики (LVS / Katran):** Использование eBPF для сверхбыстрой балансировки и сброса мусорных пакетов.
- **nftables / iptables raw:** Фильтрация на уровне `netfilter` до передачи пакетов приложению. Использование `sets` для O(1) проверки тысяч блокируемых IP.

### 2. Инфраструктурный слой (Load Balancer)

Если перед Angie стоит L4-балансировщик, на этом уровне реализуются:
- **SYN Cookies:** Защита от SYN-флуда на уровне ядра.
- **XDP (eXpress Data Path):** Сброс миллионов пакетов в секунду на уровне драйвера NIC.
- **Connection Tracking:** Ограничение количества одновременно отслеживаемых соединений (`nf_conntrack_max`).

### 3. Слой приложения (Angie)

Ключевые механизмы:
- **Rate Limiting:** `limit_req_zone` с алгоритмом Leaky Bucket. В Angie доступна кластерная синхронизация (`sync`).
- **Connection Limiting:** `limit_conn_zone` с защитой от исчерпания воркеров.
- **Timeout Tuning:** Агрессивные таймауты для защиты от Slowloris.
- **QUIC Retry:** Защита от UDP-спуфинга в HTTP/3.
- **Caching:** `proxy_cache` + `proxy_cache_lock` для снижения нагрузки на бэкенд.
- **GeoIP-фильтрация:** Отсечение трафика из нецелевых регионов.

### 4. Мониторинг и автоматизация (SRE Layer)

- **Метрики:** `status_zone`, модуль `metrics`, stub_status.
- **Логи:** JSON-формат для ingestion в Loki/ELK.
- **Авто-блокировка:** fail2ban + nftables `sets` для O(1) блокировок.
- **Оповещения:** Prometheus Alertmanager на аномальные всплески RPS и ошибок 429/503.

---

## Механизмы защиты в Angie

### Rate Limiting (limit_req)

Директива `limit_req_zone` создаёт зону в разделяемой памяти для хранения состояния запросов по ключу (обычно `$binary_remote_addr`). Алгоритм Leaky Bucket работает следующим образом:
1. Каждый запрос «заполняет» ведро на 1 единицу.
2. Ведро «протекает» со скоростью `rate` (например, `10r/s` = 100мс на запрос).
3. Если ведро переполнено (запросы приходят быстрее, чем ведро протекает), запрос либо задерживается, либо отклоняется.

**Ключевые параметры:**
- `burst=N`: размер ведра в единицах запросов. При `burst=20` разрешается всплеск до 20 запросов сверх предела `rate`.
- `nodelay`: обрабатывает burst-запросы немедленно, без искусственной задержки.
- `dry_run`: тестирование конфигурации без фактической блокировки.

```nginx
limit_req_zone $binary_remote_addr zone=api_limit:20m rate=10r/s;
limit_req_status 429;
limit_req_log_level warn;

server {
    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
    }
}
```

### Connection Limiting (limit_conn)

Директива `limit_conn_zone` создаёт зону для подсчёта активных соединений. В отличие от `limit_req`, соединение учитывается на весь его жизненный цикл (от установки до закрытия).

```nginx
limit_conn_zone $binary_remote_addr zone=perip:10m sync;
limit_conn_zone $server_name zone=perserver:1m;
limit_conn_status 429;

server {
    limit_conn perip 20;
    limit_conn perserver 5000;
}
```

**Важно:** Синхронизация `sync` в `limit_conn_zone` требует модуля `zone_sync` в блоке `stream` и доступна только в Angie PRO для production-использования. В OSS-версии лимиты действуют только в пределах одного узла.

### Cluster Zone Sync

Для работы кластерной синхронизации необходимо:
1. Включить модуль `zone_sync` в блоке `stream`.
2. Задать внутренний адрес для обмена состоянием.
3. Добавить параметр `sync` в определяемые зоны.

```nginx
stream {
    zone_sync;
    server {
        listen 127.0.0.1:9000;
        zone_sync_server 10.0.0.1:9000;
        zone_sync_server 10.0.0.2:9000;
    }
}

http {
    limit_req_zone $binary_remote_addr zone=api_cluster:20m rate=10r/s sync;
    limit_conn_zone $binary_remote_addr zone=perip:10m sync;
}
```

**Ограничения OSS:** В Open Source версии Angie параметр `sync` поддерживается на уровне кода, но для production-использования кластерной синхронизации требуется лицензия Angie PRO. В противном случае лимиты будут работать в локальном режиме на каждом узле независимо.

### Slowloris и медленные атаки

Защита реализуется через агрессивные таймауты. Важно понимать, что таймауты должны быть меньше времени, которое злоумышленник может поддерживать соединение открытым, но достаточными для легитимных пользователей с плохим подключением.

```nginx
http {
    client_header_timeout 10s;
    client_body_timeout   10s;
    send_timeout          10s;
    keepalive_timeout     65s 20s;
    keepalive_requests    1000;
}
```

**Пояснение параметров:**
- `client_header_timeout`: время ожидания полного набора заголовов. При Slowloris атаке злоумышленник отправляет по одному заголовку раз в несколько секунд. Значение `10s` достаточно для мобильных сетей, но обрывает медленные атаки.
- `client_body_timeout`: время ожидания тела запроса. Защита от Slow POST (R.U.D.Y.).
- `send_timeout`: время ожидания отправки ответа клиенту. Защищает от атак, при которых клиент медленно читает ответ (Slow Read).
- `keepalive_requests`: максимальное количество запросов в одном keep-alive соединении. Ограничивает время удержания соединения злоумышленником.

### HTTP/2 и HTTP/3 (QUIC)

Современные протоколы требуют специфических настроев. Angie 1.12 поддерживает стабильный HTTP/3 с eBPF (`quic_bpf`) для предотвращения разрывов соединений при `reload`.

```nginx
server {
    listen 443 quic reuseport;
    listen 443 ssl;
    http2 on;
    http3 on;

    quic_retry on;
    quic_gso on;

    http2_max_concurrent_streams 64;
    http3_max_concurrent_streams 64;
}
```

**Пояснение:**
- `quic_retry on`: сервер требует Retry пакет перед выделением ресурсов. Защищает от UDP-спуфинга, так как атакующий должен принимать ответы на поддельный IP.
- `quic_gso on`: Generic Segmentation Offload для UDP. Снижает нагрузку на CPU при обработке больших UDP-пакетов, что важно при UDP-флуде.
- `http2_max_concurrent_streams`: ограничивает количество параллельных потоков в одном соединении. Защищает от исчерпания памяти при открытии тысяч потоков.
- `http3_max_concurrent_streams`: аналогично для QUIC.

### Географическая и поведенческая блокировка (GeoIP2)

Использование GeoIP2 для отсечения трафика из нецелевых регионов. Angie поддерживает модуль `ngx_http_geoip2_module` с базой данных MaxMind GeoLite2.

```nginx
http {
    geoip2 /etc/angie/geo/Country.mmdb {
        $geoip2_country_code default=RU country iso_code;
    }

    map $geoip2_country_code $is_blocked {
        default 0;
        CN      1;
        US      1;
    }

    server {
        if ($is_blocked) {
            return 403;
        }
    }
}
```

### Ограничение пропускной способности

Директивы `limit_rate` и `limit_rate_after` ограничивают скорость отдачи данных клиенту. Защищают от исчерпания полосы пропускания при загрузке тяжелого контента.

```nginx
location /downloads/ {
    limit_rate_after 10m;
    limit_rate 500k;
}
```

**Важно:** `limit_rate` работает на уровне воркера и влияет на все соединения, обслуживаемые этим воркером. Для тонкого контроля в 2026 году рекомендуется использовать `proxy_upload_rate` и `proxy_download_rate` в L4-блоке `stream` или реализовывать rate limiting на уровне TC (Traffic Control) в ядре Linux.

### Защита от контрабанды запросов (HTTP Request Smuggling)

**Суть атаки:** несоответствие между интерпретацией границ запроса frontend'ом (Angie) и backend'ом. Классические варианты — `CL.TE` (route by `Content-Length`, backend by `Transfer-Encoding: chunked`) и `TE.CL` (наоборот). Последствия: обход WAF, отравление кэша, перехват чужих сессий. Полная теория и классификация — [Безопасность HTTP в проде](../../../Networking/Protocols/HTTP/http_security_hardening.md).

**Поведение Angie и базовые меры:**

*   Angie декларировано нормализует запросы: множественные `Content-Length` обрабатываются строго, `Transfer-Encoding` в комбинации с `Content-Length` отклоняется по RFC 7230. Не полагайтесь на это как на единственную защиту — проверяйте конкретную версию Angie.
*   Не разрешайте `TRACE`/`CONNECT` и лишние методы: `if ($request_method !~ ^(GET|HEAD|POST|PUT|DELETE|OPTIONS)$) { return 405; }`.
*   Не пропускайте дублирующиеся заголовки `Content-Length` на бэкенд — при `proxy_pass` нормализация выполняется, но на уровне обратного прокси к внешним CDN всегда валидируйте ожидаемое поведение.
*   `merge_slashes on;` и декодирование `%XX` предотвращают обход проверок на пути (подробнее в [Директивы location](../angie_location_directives.md)).
*   Ограничивайте число запросов на одно keepalive-соединение: `keepalive_requests 1000;` — снижает окно для сцепливания «прилипающих» запросов.

```nginx
http {
    # Отклоняем нестандартные методы
    server {
        listen 443 ssl;
        if ($request_method !~ ^(GET|HEAD|POST|PUT|DELETE|PATCH|OPTIONS)$) {
            return 405;
        }
    }
}
```

При подозрении на smuggling в логируемую оркестрацию добавьте в `log_format` `$request_length`, `$bytes_in` и `$request` для анализа аномальных тел.

### Интеграция с WAF (ModSecurity / NAXSI)

WAF перехватывает запрос до передачи бэкенду и применяет правила (SQLi/XSS/LFI/RFI). Теория WAF/RASP/NAXSI — [WAF (Security)](../../../Security/ApplicationSecurity/waf.md), там же описан обход (`evasion`) и false positives.

**Варианты для Angie:**

*   **ModSecurity v3** (модуль `ngx_http_modsecurity_module`) — загружается как динамический модуль, доступен в сборках с расширенным набором модулей. Правила — через `modsecurity_rules_file`:
    ```nginx
    # /etc/angie/angie.conf
    load_module modules/ngx_http_modsecurity_module.so;

    server {
        location / {
            modsecurity on;
            modsecurity_rules_file /etc/modsecurity/modsecurity.conf;
            proxy_pass http://backend;
        }
    }
    ```
    Для production-правил используется партнёрский набор **OWASP CRS**: он содержит готовые правила для SQLi, XSS, обхода путей (path traversal) и т.д. Производительность: ModSecurity добавляет латентность на каждый запрос; при RPS > 10k предпочитайте NAXSI или вынос WAF на внешний контур.
*   **NAXSI** — «лёгкий» WAF c собственным движком и правилами; хорошо подходит для высоконагруженных фронтов.
*   **Внешний WAF/CDN** — для edge-защиты до Angie (реализация на уровне сетевого контура).

**Эксплуатационные требования:**

*   WAF-модуль должен быть собран под ту же версию Angie, что и установленная (динамические модули двоично-совместимы только в пределах серии).
*   Начинайте WAF в режиме `DetectionOnly` (лог-мод), затем включайте активную блокировку, чтобы избежать массовых false positives.
*   Мониторинг блокировок ведите по отдельной метрике/логу от WAF и связывайте с `status_zone` Angie.

---

## Системный hardening (ядро и ОС)

Angie работает в пользовательском пространстве, но его устойчивость к DoS-атакам напрямую зависит от настроек ядра Linux и ограничений ОС. Ниже приведён набор параметров, актуальных для 2026 года.

### sysctl: защита сетевого стека

```bash
# Включение SYN Cookies (защита от SYN flood)
sysctl -w net.ipv4.tcp_syncookies=1

# Увеличение очереди SYN-пакетов
sysctl -w net.ipv4.tcp_max_syn_backlog=8192

# Уменьшение времени ожидания закрытия соединения (TIME_WAIT)
sysctl -w net.ipv4.tcp_fin_timeout=15

# Ограничение повторных попыток SYN+ACK
sysctl -w net.ipv4.tcp_synack_retries=2

# Защита от ICMP Redirect spoofing
sysctl -w net.ipv4.conf.all.accept_redirects=0
sysctl -w net.ipv4.conf.default.accept_redirects=0
sysctl -w net.ipv6.conf.all.accept_redirects=0
sysctl -w net.ipv6.conf.default.accept_redirects=0

# Увеличение лимитов conntrack (для Docker и high-load)
sysctl -w net.netfilter.nf_conntrack_max=1048576
sysctl -w net.netfilter.nf_conntrack_buckets=262144
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=600
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_close_wait=15
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_fin_wait=15

# Anti-spoofing (BCP38)
sysctl -w net.ipv4.conf.all.rp_filter=1
sysctl -w net.ipv4.conf.default.rp_filter=1

# Ограничение ICMP
sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=1
sysctl -w net.ipv4.icmp_ignore_bogus_error_responses=1

# Увеличение лимита открытых файлов
sysctl -w fs.file-max=200000
```

**Валидация:**
```bash
sysctl net.ipv4.tcp_syncookies net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
dmesg | grep -i conntrack
# → nf_conntrack: table full, dropping packet  (если переполнено)
```

### ulimit и дескрипторы файлов

Angie-воркеры должны иметь достаточно дескрипторов для одновременного обслуживания тысяч соединений.

```bash
# /etc/security/limits.d/angie.conf
angie soft nofile 65536
angie hard nofile 200000

# В angie.conf:
worker_rlimit_nofile 200000;
```

**Проверка:**
```bash
# PID живого воркера
PID=$(pgrep -x angie | head -1)
cat /proc/$PID/limits | grep "open files"
# → Max open files            65536                200000              files
```

### nftables: фильтрация на L3/L4

nftables с `sets` обеспечивает O(1) проверку IP и эффективен при высоких нагрузках. Рекомендуется как для RHEL 9+, так и для Debian 12+.

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

        ct state established,related accept
        iif "lo" accept

        # Защита от SYN flood: 10 новых SYN/сек на порт 443
        tcp flags syn tcp dport 80,443 limit rate over 10/second accept
        tcp flags syn tcp dport 80,443 add @ddos_limits { ip saddr }

        # SSH brute-force: 6 новых соединений в минуту
        tcp dport 22 limit rate over 6/minute accept
        tcp dport 22 add @ddos_limits { ip saddr }

        # Блокировка IP из blackhole (fail2ban, ручные баны)
        ip saddr @blackhole drop

        accept
    }

    chain forward { type filter hook forward priority 0; policy drop; }
    chain output { type filter hook output priority 0; policy accept; }
}
```

**Валидация:**
```bash
nft -c -f /etc/nftables.conf
nft -f /etc/nftables.conf
nft list set inet filter ddos_limits
watch -n 1 'nft list set inet filter ddos_limits | wc -l'
```

---

## Интеграция с fail2ban

fail2ban автоматически анализирует логи Angie и вносит IP нарушителей в nftables `sets`. Это закрывает пробел между обнаружением атаки и реагированием.

### Фильтр для Angie (`/etc/fail2ban/filter.d/angie-ddos.conf`)

```ini
[Definition]
failregex = ^<HOST> -.* "(GET|POST|HEAD).*" (403|429|404) .*$
            ^<HOST> -.* "(GET|POST|HEAD).*" 200 .* "(wp-login|admin|graphql)" .*$
            ^<HOST> -.* ".*(\.\./|etc/passwd|cmd\.exe|SELECT.*FROM).*" .*$

ignoreregex =

datepattern = {^LN-BEG}%%ExY(?P<_sep>[-/.])%%m(?P=_sep)%%d[T ]%%H:%%M:%%S(?:[.,]%%f)?(?!(?:[^<]*?</script>|[^<]*?</style>))
```

### Jail (`/etc/fail2ban/jail.d/angie-ddos.conf`)

```ini
[angie-ddos]
enabled  = true
port     = http,https
protocol = tcp
filter   = angie-ddos
logpath  = /var/log/angie/access.log
maxretry = 50
findtime = 60
bantime  = 3600
banaction = nftables-multiport
backend  = systemd
```

### SRE-интеграция с Prometheus

```bash
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

**Валидация:**
```bash
sudo fail2ban-regex /var/log/angie/access.log /etc/fail2ban/filter.d/angie-ddos.conf
sudo fail2ban-client status angie-ddos
sudo fail2ban-client banned 192.0.2.100
```

---

## Практические сценарии

### 1. Ограничение частоты запросов с кластерной синхронизацией

В отличие от Nginx OSS, Angie позволяет синхронизировать счетчики `limit_req` между узлами кластера.

```nginx
stream {
    zone_sync;
    server {
        listen 127.0.0.1:9000;
        zone_sync_server node1.internal:9000;
        zone_sync_server node2.internal:9000;
    }
}

http {
    limit_req_zone $binary_remote_addr zone=api_cluster:20m rate=10r/s sync;
    limit_req_status 429;
    limit_req_log_level warn;

    server {
        location /api/v2/ {
            limit_req zone=api_cluster burst=20 nodelay;
        }
    }
}
```

**Валидация:**
```bash
for i in $(seq 1 30); do curl -s -o /dev/null -w "%{http_code}\n" https://example.com/api/v2/; done
# → большинство: 200, часть: 429
curl http://localhost/api/v1/http/limit_reqs/api_cluster
```

### 2. Ограничение одновременных соединений (limit_conn)

```nginx
http {
    limit_conn_zone $binary_remote_addr zone=perip:10m sync;
    limit_conn_zone $server_name zone=perserver:1m;
    limit_conn_status 429;

    server {
        limit_conn perip 20;
        limit_conn perserver 5000;
    }
}
```

### 3. Защита от медленных атак (Slowloris) и тюнинг таймаутов

```nginx
http {
    client_header_timeout 10s;
    client_body_timeout   10s;
    send_timeout          10s;
    keepalive_timeout     65s 20s;
    keepalive_requests    1000;
}
```

### 4. Защита протоколов HTTP/2 и HTTP/3 (QUIC)

```nginx
http {
    server {
        listen 443 quic reuseport;
        listen 443 ssl;
        http2 on;
        http3 on;

        quic_retry on;
        quic_gso on;
        http2_max_concurrent_streams 64;
        http3_max_concurrent_streams 64;
    }
}
```

### 5. Тюнинг буферов и заголовков

```nginx
http {
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;
    max_headers 50;
    client_max_body_size 10m;
}
```

### 6. Географическая и поведенческая блокировка (GeoIP2)

```nginx
http {
    geoip2 /etc/angie/geo/Country.mmdb {
        $geoip2_country_code default=RU country iso_code;
    }

    map $geoip2_country_code $is_blocked {
        default 0;
        CN      1;
        US      1;
    }

    server {
        if ($is_blocked) {
            return 403;
        }
    }
}
```

### 7. Наблюдаемость и мониторинг защиты

```nginx
http {
    server {
        status_zone server_stats;
        location /api/ {
            api;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Переменные состояния лимитов:**
- `$limit_req_status`: `passed`, `delayed`, `rejected`, `delayed_dry_run`, `rejected_dry_run`.
- `$limit_conn_status`: `passed`, `rejected`.

**Проверка через API:**
```bash
curl http://localhost/api/v1/http/limit_reqs/api_cluster
```

### 8. Кэширование как защита от DoS

`proxy_cache` снижает нагрузку на бэкенд, превращая повторяющиеся запросы в чтение из shared memory. `proxy_cache_lock` предотвращает thundering herd при MISS-объектах.

```nginx
proxy_cache_path /var/cache/angie levels=1:2 keys_zone=api_cache:50m inactive=60m use_temp_path=off;

server {
    location /api/ {
        proxy_cache api_cache;
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_lock_age 10s;
        proxy_cache_use_stale error timeout updating;
        proxy_pass http://backend_api;
    }
}
```

**Пояснение:**
- `proxy_cache_lock on`: при MISS только один воркер отправляет запрос к бэкенду, остальные ждут результата. Предотвращает каскадную перегрузку.
- `proxy_cache_use_stale error timeout updating`: при ошибке или таймауте бэкенда отдаётся устаревший контент из кэша вместо 502/504.

### 9. Ограничение пропускной способности (Bandwidth Limiting)

```nginx
location /downloads/ {
    limit_rate_after 10m;
    limit_rate 500k;
}
```

### 10. Системный мониторинг и диагностика

#### Проверка дескрипторов и shared memory

```bash
# Текущие лимиты воркера
PID=$(pgrep -x angie | head -1)
cat /proc/$PID/limits | grep "open files"

# Размер shared memory
ls -la /dev/shm/
# → angie_api_shm  angie_cache_...  (размеры зон)

# Статистика conntrack
conntrack -S
# → entries     98304
# → dropped      0
# → insert_failed 0
```

#### Диагностика DoS-атаки

```bash
# 1. Baseline RPS
grep -c "GET /" /var/log/angie/access.log

# 2. Топ аномальных IP
awk '{print $1}' /var/log/angie/access.log | sort | uniq -c | sort -nr | head -20

# 3. Распределение по статус-кодам
awk '{print $9}' /var/log/angie/access.log | sort | uniq -c | sort -nr

# 4. Проверка состояния лимитов
curl http://localhost/api/v1/http/limit_reqs/

# 5. Экспресс-блокировка через nftables (временная мера)
nft add element inet filter blackhole { 192.0.2.100 }
```

### 11. Нагрузочное тестирование и валидация

```bash
# wrk: тест RPS и latency (Co-ordinated Omission aware)
wrk -t12 -c400 -d30s --latency https://example.com/api/health
# → p95, p99 latency; после burst ожидаем 429

# ab (ApacheBench): простой тест на превышение burst
ab -n 100 -c 25 https://example.com/api/health
# → 429 Too Many Requests после превышения burst

# slowhttptest: тест Slowloris
sudo apt install slowhttptest
slowhttptest -H -c 1000 -g -o slowloris_test -i 10 -r 200 -t GET -u https://example.com/health -x 24 -p 3
# → Angie должен разрывать соединения по client_header_timeout

# Проверка QUIC
curl -I --http3-only https://example.com/
# → HTTP/3 200
ss -u -l | grep :443
```

### 12. Экстренные процедуры реагирования

При подтверждённой DDoS-атаке выполняйте действия в следующей последовательности:

```bash
# 1. Перевести Angie в режим блокировки всех новых запросов (кроме локального мониторинга)
sudo iptables -A INPUT -p tcp --dport 80,443 -j DROP
sudo iptables -A INPUT -s 127.0.0.1 -p tcp --dport 80,443 -j ACCEPT

# 2. Или через nftables (предпочтительно)
nft add rule inet filter input tcp dport {80,443} drop
nft add rule inet filter input ip saddr 127.0.0.1 tcp dport {80,443} accept

# 3. Включить максимально агрессивные таймауты временно
sudo sed -i 's/client_header_timeout .*/client_header_timeout 5s;/' /etc/angie/angie.conf
sudo sed -i 's/client_body_timeout .*/client_body_timeout 5s;/' /etc/angie/angie.conf
sudo angie -s reload

# 4. Анализ логов в реальном времени
tail -f /var/log/angie/access.log | awk '{print $1}' | sort | uniq -c | sort -nr | head -20

# 5. Включить debug-логирование (временно!)
# error_log /var/log/angie/error.log debug;

# 6. После купирования атаки — восстановить конфигурацию
git checkout /etc/angie/angie.conf
sudo angie -s reload
```

---

## Мониторинг и оповещения

### Метрики Prometheus (stub_status + metrics)

```yaml
# /etc/prometheus/rules/ddos_rules.yml
groups:
  - name: ddos_alerts
    rules:
      - alert: HighRequestRate
        expr: rate(angie_http_requests_total[5m]) > 200
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Аномальный рост запросов на {{ $labels.server }}"
          description: "RPS вырос до {{ $value }} (baseline ~50)"

      - alert: RateLimitRejected
        expr: rate(angie_http_429_responses_total[5m]) > 100
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
```

### Loki LogQL

```logql
# Топ-10 IP по запросам за 5 минут
topk(10, sum by (client_ip) (rate({job="angie"} |= " " [5m])))

# Паттерны сканирования
{job="angie"} |= "admin" |= "wp-login" | line_format "{{.client_ip}}"

# Количество 429 за последний час
sum_over_time({job="angie"} |= " 429 " [1h])
```

### Статус зон через API

```bash
curl http://localhost/api/v1/http/limit_reqs/api_cluster | jq .
# → {"zone":"api_cluster","passes":1024,"delayed":512,"rejected":128,...}
```

---

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `nf_conntrack: table full, dropping packet` | Исчерпание таблицы conntrack | Увеличить `nf_conntrack_max` (до 2M+), сократить таймауты. Проверить Docker DNAT. |
| `kernel: TCP: request_sock_TCP: Possible SYN flooding` | SYN-флуд | Убедиться, что `tcp_syncookies=1`, увеличить `tcp_max_syn_backlog`. |
| `Too many open files` | Исчерпание ulimit | `ulimit -n 65535` для angie worker, `fs.file-max` в sysctl. |
| Неточный rate limiting за NAT | Много клиентов за одним IP | Использовать `$binary_remote_addr` или комбинировать с `$connection_serial`. |
| fail2ban не банит | Неверный failregex | `fail2ban-regex /var/log/angie/access.log /etc/fail2ban/filter.d/angie-ddos.conf` |
| Замедление при nftables | Большой набор правил без sets | Использовать `sets` вместо цепочек `if`/`match`. |
| QUIC flood не детектируется | Защита только на L3/L4 | Добавить `quic_retry on`, мониторинг UDP-трафика, `limit_req`. |
| Пропуск трафика при amplification | Не настроен BCP38 | Настроить anti-spoofing (`rp_filter=1`) на edge-интерфейсах. |
| 429/503 при нормальной нагрузке | Слишком низкий `rate` или `burst` | Увеличить `burst` или использовать `nodelay` для плавного обслуживания. |
| `limit_req` не работает в кластере | `sync` не активен или PRO лицензия | Проверить `zone_sync` статус через API; убедиться в наличии PRO-лицензии. |
| Аномальные запросы проходят в обход правил | Не согласована интерпретация тела (smuggling) | Валидировать `Content-Length`/`Transfer-Encoding`, включить WAF, отключить лишние методы (см. подраздел про контрабанду). |
| WAF блокирует легитимный трафик | Ложные срабатывания правил | Перевести WAF в DetectionOnly, добавить исключения, сверять с OWASP CRS exceptions. |
| WAF-модуль не загружается при старте | Версия модуля не совпадает с версией Angie | Пересобрать/переустановить динамический модуль под установленную версию Angie. |

---

## Чек-лист аудита безопасности (2026)

- [ ] Включена ли кластерная синхронизация `sync` для горизонтально масштабируемых систем?
- [ ] Настроен ли `quic_retry` для защиты от UDP-спуфинга в HTTP/3?
- [ ] Установлен ли код ответа `429` для лимитов (согласно RFC 6585)?
- [ ] Ограничены ли таймауты `client_header_timeout` и `client_body_timeout` до значений < 15s?
- [ ] Настроен ли мониторинг `status_zone` или Prometheus экспорт для отслеживания атак в реальном времени?
- [ ] Включены ли SYN cookies (`tcp_syncookies=1`) и увеличен ли `tcp_max_syn_backlog`?
- [ ] Настроен ли `nf_conntrack_max` с запасом 30–50% от ожидаемого пика соединений?
- [ ] Установлен ли `worker_rlimit_nofile` >= 100000 и соответствующее значение в `/etc/security/limits.conf`?
- [ ] Включен ли `server_tokens off;` для сокрытия версии Angie?
- [ ] Настроен ли `proxy_cache_lock` для критичных API-эндпоинтов?
- [ ] Интегрирован ли fail2ban с nftables `sets` для автоматической блокировки?
- [ ] Настроены ли алерты Prometheus на аномальный рост RPS, 429/503 ошибок и заполнение conntrack?
- [ ] Проведено ли нагрузочное тестирование `wrk2`/`k6` с percentile-анализом (p95, p99, p99.9)?
- [ ] Включено ли `rp_filter=1` (anti-spoofing) на всех edge-интерфейсах?
- [ ] Ограничены ли методы HTTP (`TRACE`, `CONNECT`) и проверена историческая ветка на вариант request smuggling?
- [ ] Развернут ли WAF (ModSecurity/NAXSI) в режиме DetectionOnly, с планом перехода в блокирующий режим?

---

## См. также

*   **[Обзор DoS/DDoS атак](../../../Security/ApplicationSecurity/ddos_overview.md)** — теоретическая база, классификация угроз, ядерный hardening.
*   **[Оптимизация производительности Angie](./performance_optimization.md)** — настройка для работы под экстремальной нагрузкой.
*   **[Логирование в Angie](../angie_logging.md)** — настройка JSON-логов для систем анализа (SIEM/ELK).
