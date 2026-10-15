# Лучшие практики оптимизации производительности веб-приложений

**Актуально для:** Nginx 1.26+, Angie 1.4+ / 1.12.x, Linux Kernel 5.15+ / 6.x, HTTP/2, HTTP/3 (RFC 9114)

## Определения

- **Лучшие практики оптимизации производительности (Web Performance Best Practices)** — комплекс проверенных архитектурных и инженерных подходов к минимизации задержек доставки данных, устранению блокировок очередей и эффективному использованию вычислительных ресурсов на всех уровнях инфраструктуры (ядро ОС, сетевой стек, обратный прокси/веб-сервер, приложение и транспортные протоколы).
- **Time To First Byte (TTFB)** — время от момента отправки клиентом первого байта HTTP-запроса до получения первого байта тела ответа от сервера. Складывается из сетевой задержки (RTT), времени TCP/TLS рукопожатия, задержки очередей сетевого стека ОС и времени генерации ответа бэкендом.
- **Zero-Copy I/O (`sendfile`, `splice`)** — метод передачи данных с диска в сетевой сокет напрямую через page cache ядра Linux без копирования содержимого в адресное пространство пользовательского процесса (user-space), что устраняет лишнее переключение контекста и разгружает CPU и шину памяти.
- **Kernel TLS (kTLS)** — механизм ядра Linux (начиная с ядер 4.13/4.17+), переносящий симметричное шифрование и дешифрование TLS (AES-GCM, ChaCha20-Poly1305) в ядро ОС. Позволяет веб-серверам использовать системный вызов `sendfile()` совместно с HTTPS.
- **Upstream Connection Pooling (Keepalive Pool)** — пул предварительно открытых и повторно используемых TCP/TLS соединений между обратным прокси (Nginx/Angie) и бэкенд-серверами (upstream), исключающий накладные расходы на постоянные 3-way handshake и TLS-рукопожатия на каждый клиентский запрос.
- **BDP (Bandwidth-Delay Product) и TCP Auto-Tuning** — произведение пропускной способности сетевого канала на время кругового обращения (RTT). Определяет оптимальный объем данных, который должен находиться «в полете» (in flight) для полного насыщения канала. В ядре Linux согласуется через автоматическую подстройку буферов приема и передачи (`tcp_rmem`, `tcp_wmem`).
- **BBR (Bottleneck Bandwidth and RTT)** — алгоритм контроля перегрузки сетевого стека (RFC 9002 для QUIC, модули ядра Linux `tcp_bbr`), регулирующий скорость передачи на основе непрерывного измерения пропускной способности узкого места (bottleneck bandwidth) и минимального RTT, в отличие от алгоритмов на базе потерь (loss-based: Reno, CUBIC), провоцирующих переполнение буферов (bufferbloat).
- **Cache Stampede (Thundering Herd)** — эффект лавинообразной нагрузки, возникающий при одновременном обращении множества параллельных запросов к ресурсу, чей TTL в кэше только что истек. Без взаимной блокировки (`proxy_cache_lock`) все запросы одновременно отправляются на бэкенд, вызывая перегрузку CPU, исчерпание пула соединений БД и каскадный отказ сервиса.
- **Микрокэширование (Microcaching)** — стратегия кэширования динамических ответов на экстремально короткий срок (от 1 до 5 секунд) на уровне обратного прокси. Позволяет выдерживать резкие всплески трафика на динамических эндпоинтах без существенного устаревания данных.
- **Head-of-Line Blocking (HOL Blocking)** — задержка передачи пакетов из-за блокировки или потери предшествующего пакета в очереди:
  - в HTTP/1.1 проявляется на уровне HTTP-запросов в рамках одного TCP-соединения;
  - в HTTP/2 устранена на уровне HTTP-потоков, но сохраняется на уровне транспорта TCP (потеря одного TCP-сегмента замораживает все мультиплексированные стримы соединения);
  - в HTTP/3 (QUIC поверх UDP) полностью устранена на уровне транспорта за счет независимой обработки потоков данных.
- **Early Hints (HTTP 103)** — статус-код предварительного ответа сервера (RFC 8297), отправляемый клиенту до начала генерации основного тела ответа. Содержит заголовки `Link: <...>; rel=preload`, позволяя браузеру параллельно загружать критические ресурсы (стили, шрифты), пока бэкенд выполняет тяжелые вычисления или запросы к БД.
- **Performance Budget (Бюджет производительности)** — набор жестких пороговых ограничений на размеры артефактов (JS, CSS, изображения), время ответа (TTFB, LCP) и системные метрики (latency p95/p99, CPU load), нарушение которых блокирует прохождение CI/CD пайплайна или фиксируется мониторингом как деградация.

## Основные концепции и архитектура

### Стек оптимизации веб-производительности

Высокая производительность веб-инфраструктуры достигается слаженной работой четырех уровней:

```
[ Клиент / Браузер ] (DOM/CSSOM, Critical Rendering Path, HTTP/2-HTTP/3 Client)
        │  ▲
        │  │ L4: TCP/UDP, BBRv3, TLS 1.3 0-RTT, Fast Open
        ▼  │
[ Сетевой стек ядра Linux ] (Backlog queues, TCP Window Autotuning, qdisc fq, kTLS)
        │  ▲
        │  │ L7: epoll event-loop, Zero-Copy sendfile, aio threads, proxy_cache
        ▼  │
[ Обратный прокси (Nginx/Angie) ] (Microcaching, Zstd/Brotli, Dynamic TLS records)
        │  ▲
        │  │ L7: Upstream Keepalive Connection Pool, Unix domain sockets
        ▼  │
[ Бэкенд-серверы / Приложения ] (FastCGI/uWSGI/HTTP upstream, DB query cache)
```

| Уровень | Компоненты | Ключевые механизмы оптимизации | Зона ответственности |
| :--- | :--- | :--- | :--- |
| **Сетевой стек ОС (L4)** | Драйвер NIC, ядро Linux, TCP/UDP стек, netfilter | `somaxconn`, `tcp_max_syn_backlog`, BBR, TFO, буферы `rmem`/`wmem`, kTLS | SysAdmin / SRE |
| **Обратный прокси (L7)** | Nginx, Angie, HAProxy | `epoll`, `worker_cpu_affinity`, `sendfile`, `aio threads`, кэширование, буферизация | DevOps / SRE |
| **Транспорт L7 / Крипто** | TLS 1.3, HTTP/2, HTTP/3 (QUIC) | Сессионные тикеты, `ssl_buffer_size`, QPACK/HPACK, UDP GSO, eBPF `quic_bpf` | DevOps / SysAdmin |
| **Апстрим-интеграция** | Keepalive-пулы, сокеты, балансировка | `keepalive`, `proxy_cache_lock`, `proxy_cache_use_stale`, round-robin / least_conn | DevOps / SRE |
| **Клиентский рендеринг** | Браузер, Critical Path | 103 Early Hints, Preload, сжатие Zstd/Brotli, исключение блокирующих ресурсов | Frontend / DevOps |

### Механизмы сетевого стека ядра Linux

#### 1. Очереди сокетов и предотвращение потерь при всплесках (SYN/Accept Backlog)

Входящее TCP-соединение проходит через две последовательные очереди ядра:
1. **SYN Queue (очередь полуоткрытых соединений):** хранит сокеты в состоянии `SYN_RECV`, ожидающие финального `ACK` от клиента в рамках 3-way handshake. Размер регулируется параметром `net.ipv4.tcp_max_syn_backlog`. При ее переполнении ядро либо сбрасывает пакеты (рост retransmissions), либо включает механизм `tcp_syncookies`.
2. **Accept Queue (очередь полностью установленных соединений):** хранит сокеты в состоянии `ESTABLISHED`, ожидающие вызова `accept()` рабочим процессом веб-сервера. Лимит вычисляется как `min(backlog_в_listen, net.core.somaxconn)`.
3. Если воркеры Nginx/Angie не успевают вызывать `accept()` (например, из-за блокировки на дисковом вводе-выводе), очередь Accept Queue переполняется. В зависимости от параметра `net.ipv4.tcp_abort_on_overflow`, ядро либо отбрасывает входящие ACK-пакеты (клиент повторяет передачу, вызывая рост задержки), либо немедленно разрывает соединение с флагом `RST`.

#### 2. Контроль перегрузки: BBR против CUBIC

- **CUBIC (Loss-based):** увеличивает размер окна перегрузки (CWND) до тех пор, пока сетевые буферы коммутаторов и маршрутизаторов не переполнятся и не произойдет потеря пакета (packet drop). Это вызывает феномен **Bufferbloat** — искусственный рост RTT в сотни миллисекунд и деградацию интерактивности.
- **BBR / BBRv3 (Model-based):** непрерывно строит математическую модель соединения, измеряя максимальную доступную полосу пропускания (`BtlBw`) и минимальное время оборота пакета (`RTprop`). BBR удерживает объем данных «в полете» точно равным BDP ($BtlBw \times RTprop$), полностью исключая раздувание буферов и обеспечивая минимальный TTFB даже при потерях в канале до 15–20%.

#### 3. Автоматическая подстройка буферов сокетов (BDP Autotuning)

Для передачи данных на максимальной скорости без остановок размер буфера отправки и приема TCP должен быть не менее BDP:
$$\text{BDP} = \text{Bandwidth (бит/с)} \times \text{RTT (с)}$$
Например, при полосе 10 Гбит/с и задержке 20 мс:
$$\text{BDP} = 10 \times 10^9 \times 0.02 = 200 \times 10^6 \text{ бит} \approx 25 \text{ МБ}$$
Параметры `net.ipv4.tcp_rmem` и `net.ipv4.tcp_wmem` задают векторы `min default max`. Ядро автоматически масштабирует буфер под текущий BDP каждого соединения, если верхний предел (`max`) и системные лимиты `net.core.rmem_max` / `net.core.wmem_max` не занижены.

### Архитектура веб-сервера / обратного прокси (Nginx / Angie)

#### 1. Модель событий и изоляция ресурсов процессора
- **Epoll Event Loop:** воркеры работают в неблокирующем цикле событий. Системный вызов `epoll_wait()` сообщает о готовности дескрипторов к чтению/записи без холостых обходов.
- **Привязка к ядрам (`worker_cpu_affinity`):** фиксация рабочего процесса за конкретным ядром процессора исключает миграцию потоков между ядрами ОС, сохраняя горячими кэши первого (L1), второго (L2) и третьего (L3) уровней CPU.

#### 2. Zero-Copy I/O, Thread Pools и kTLS
- **`sendfile on;`**: при отдаче статики данные копируются напрямую из page cache ядра в сокетный кольцевой буфер NIC, минуя буферы пользовательского пространства.
- **`aio threads=default;`**: если запрашиваемого файла нет в оперативной памяти (page cache miss), синхронное чтение с диска NVMe/SSD замораживает весь event loop воркера на несколько миллисекунд, блокируя тысячи других соединений. Директива передает операцию чтения пулу потоков ядра, оставляя главный цикл обработки событий свободным.
- **`tcp_nopush on;` и `tcp_nodelay on;`**: `tcp_nopush` заставляет сервер накапливать HTTP-заголовки и начало пакета `sendfile`, отправляя их полными сетевыми пакетами размера MSS. После завершения передачи файла директива `tcp_nodelay` немедленно отсылает завершающие байты в сокет, отключая задерживающий алгоритм Нагла (Nagle's algorithm).
- **Kernel TLS (kTLS):** стандартный HTTPS запрещает использовать чистый `sendfile()`, так как данные перед отправкой должны быть зашифрованы в user-space библиотекой OpenSSL. При включении kTLS OpenSSL инициализирует ключ сессии, а само симметричное AES-GCM шифрование выполняется непосредственно ядром Linux в момент работы `sendfile()`, снижая нагрузку на CPU на 25–40%.

### Транспорт и протоколы: HTTP/2, HTTP/3 и TLS 1.3

1. **HTTP/2 Multiplexing:** передача сотен запросов и ответов по одному TCP-соединению в бинарных фреймах. Устраняет необходимость создания множества параллельных TCP-сокетов (антипаттерн Domain Sharding больше не требуется).
2. **HTTP/3 (QUIC):**
   - Работает поверх протокола UDP.
   - Каждый стрим передается независимо: потеря одного UDP-пакета задерживает только тот стрим, данные которого находились в пакете, полностью исключая HOL-блокировку.
   - **UDP GSO (Generic Segmentation Offload):** позволяет веб-серверу передавать пачку UDP-пакетов ядру Linux за один системный вызов `sendmsg()`, снижая нагрузку на процессор при отдаче высокоскоростных потоков.
   - **eBPF-маршрутизация (`quic_bpf`):** в HTTP/3 соединение идентифицируется по Connection ID (CID), а не IP/порту. Директива `quic_bpf on;` загружает в ядро BPF-программу, направляющую входящие UDP-датаграммы конкретному воркеру Nginx/Angie по CID, гарантируя нулевой разрыв клиентских сессий при выполнении `nginx -s reload`.
3. **Оптимизация размера записей TLS (`ssl_buffer_size`):**
   - По умолчанию размер блока TLS равен 16 КБ. Пока клиент не получит все 16 КБ, он не может расшифровать ни одного байта.
   - Уменьшение `ssl_buffer_size` до `4k` (или использование динамического размера) позволяет браузеру расшифровывать и отображать критический HTML/CSS немедленно, значительно снижая TTFB и FCP.

### Кэширование, Microcaching и Upstream Connection Pooling

1. **Микрокэширование (Microcaching):** кэширование динамических страниц на 1–2 секунды:
   - При нагрузке в 10 000 RPS бэкенд получает всего 1 запрос в секунду для генерации страницы; остальные 9 999 запросов мгновенно отдаются из памяти или быстрого диска прокси.
2. **Защита от Cache Stampede (`proxy_cache_lock`):**
   - При истечении срока действия кэша только **один** запрос отправляется к бэкенду. Все остальные параллельные клиенты ждут ответа в очереди и получают свежие данные сразу из кэша.
   - Директива `proxy_cache_use_stale updating` отдает ожидающим клиентам старую копию ресурса в момент, пока единственный фоновый запрос обновляет кэш.
3. **Upstream Connection Pooling (Keepalive):**
   - По умолчанию Nginx/Angie открывает и закрывает TCP-соединение к бэкенду на каждый клиентский запрос (Connection: close).
   - Пул `keepalive` держит соединения открытыми. При 10 000 RPS сохранение пула исключает генерацию 10 000 сокетов в секунду в состоянии `TIME_WAIT`, снижает нагрузку на CPU бэкенда и экономит 1–2 RTT на каждый запрос.

---

## Практические сценарии и конфигурация

### Сценарий 1: Тюнинг сетевого стека ядра Linux для веб-сервера под высокой нагрузкой

Конфигурационный файл настраивается в `/etc/sysctl.d/99-web-performance.conf` и рассчитан на серверы с сетевыми интерфейсами 10G/25G/40G+.

```ini
# /etc/sysctl.d/99-web-performance.conf

# 1. Очереди сокетов и входящих пакетов
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.core.netdev_max_backlog = 65535

# 2. Алгоритм контроля перегрузки BBR и планировщик очередей fq
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# 3. Ускорение TCP-рукопожатий и утилизация портов
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.ip_local_port_range = 10240 65535

# 4. Автоматическая подстройка буферов TCP (BDP Auto-tuning)
# Значения: min default max (в байтах). Максимум до 16 МБ или 32 МБ для BDP
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# 5. Буферы приема для UDP (критично для HTTP/3 QUIC)
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576

# 6. Отключение медленного старта после простоя
net.ipv4.tcp_slow_start_after_idle = 0

# 7. Лимиты открытых файлов на уровне системы
fs.file-max = 2097152
```

Применение параметров и проверка лимитов:

```bash
# Применение параметров sysctl без перезагрузки
sudo sysctl --system

# Проверка активного алгоритма контроля перегрузки
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr

# Проверка очереди listen-сокетов
sysctl net.core.somaxconn
# → net.core.somaxconn = 65535
```

Настройка лимитов дескрипторов файлов в systemd для Nginx/Angie (`/etc/systemd/system/nginx.service.d/override.conf`):

```ini
[Service]
LimitNOFILE=1048576
LimitMEMLOCK=infinity
```

```bash
# Перезагрузка демона systemd для применения оверрайда
sudo systemctl daemon-reload
sudo systemctl restart nginx

# Проверка фактических лимитов запущенного процесса воркера
cat /proc/$(pgrep -f "nginx: worker" | head -n1)/limits | grep "open files"
# → Max open files            1048576              1048576              files
```

---

### Сценарий 2: Комплексная продакшен-конфигурация Nginx / Angie (L7 Reverse Proxy & Static)

Конфигурация включает в себя Zero-Copy, Thread Pools (`aio threads`), kTLS, TLS 1.3, HTTP/2 и HTTP/3 (QUIC + GSO + eBPF), буферизацию прокси, сжатие (Zstd, Brotli, Gzip) и защиту от Cache Stampede.

```nginx
# /etc/nginx/nginx.conf или /etc/angie/angie.conf

user www-data;
worker_processes auto;
worker_cpu_affinity auto;
worker_rlimit_nofile 1048576;
pcre_jit on;

events {
    worker_connections 65535;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # 1. Логирование производительности с замером задержек
    log_format perf '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" "$http_user_agent" '
                    'rt=$request_time uct="$upstream_connect_time" '
                    'uht="$upstream_header_time" urt="$upstream_response_time" '
                    'cs=$upstream_cache_status proto=$server_protocol alpn=$ssl_alpn';

    access_log /var/log/nginx/access.log perf buffer=64k flush=5s;
    error_log /var/log/nginx/error.log warn;

    # 2. Оптимизация дискового ввода-вывода (Zero-Copy и Thread Pools)
    sendfile on;
    sendfile_max_chunk 512k;
    tcp_nopush on;
    tcp_nodelay on;
    aio threads=default;

    # Кэширование файловых дескрипторов в памяти воркера
    open_file_cache max=50000 inactive=30s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # 3. Тайм-ауты и буферы соединений
    keepalive_timeout 65s;
    keepalive_requests 10000;
    reset_timedout_connection on;
    client_body_timeout 10s;
    client_header_timeout 10s;
    send_timeout 10s;

    client_body_buffer_size 128k;
    client_max_body_size 50m;
    client_header_buffer_size 4k;
    large_client_header_buffers 4 16k;

    # 4. Буферизация ответов бэкенда (предотвращает зависание соединений)
    proxy_buffering on;
    proxy_buffer_size 32k;
    proxy_buffers 128 16k;
    proxy_busy_buffers_size 64k;
    proxy_temp_file_write_size 64k;
    proxy_connect_timeout 5s;
    proxy_send_timeout 10s;
    proxy_read_timeout 10s;

    # 5. Оптимизация TLS, kTLS и сессионного кэша
    ssl_protocols TLSv1.3 TLSv1.2;
    ssl_prefer_server_ciphers off;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    
    ssl_session_cache shared:SSL:50m;
    ssl_session_timeout 1d;
    ssl_session_tickets on;
    ssl_buffer_size 4k;                  # Динамический/уменьшенный размер блока для снижения TTFB

    # Включение Kernel TLS (требует OpenSSL 3.0+ и ядра Linux 5.10+)
    # ssl_conf_command Options KTLS;

    # 6. Кэш прокси и защита от Cache Stampede
    proxy_cache_path /var/cache/nginx/proxy levels=1:2 keys_zone=STATIC_CACHE:100m inactive=7d max_size=20g use_temp_path=off;
    proxy_cache_path /var/cache/nginx/micro levels=1:2 keys_zone=MICRO_CACHE:10m inactive=1m max_size=1g use_temp_path=off;

    # 7. Сжатие контента: предварительное (статическое) и динамическое
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 4;
    gzip_min_length 256;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;

    # Поддержка предварительно сжатых файлов (Sendfile Zero-Copy)
    gzip_static on;
    # brotli_static on;                  # При наличии ngx_brotli
    # zstd_static on;                    # При наличии ngx_zstd / Angie

    # 8. Пул соединений к апстриму (Upstream Keepalive)
    upstream backend_pool {
        server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
        server 127.0.0.1:8081 max_fails=3 fail_timeout=10s;
        
        keepalive 64;                    # Пул idle-соединений на каждого воркера
        keepalive_requests 10000;
        keepalive_time 1h;
    }

    server {
        # Порт TCP для HTTP/1.1 и HTTP/2
        listen 443 ssl default_server reuseport;
        # Порт UDP для HTTP/3 (QUIC)
        listen 443 quic reuseport;

        server_name example.com;

        ssl_certificate /etc/ssl/certs/example.com.crt;
        ssl_certificate_key /etc/ssl/private/example.com.key;

        # 9. Информирование клиента о поддержке HTTP/3
        add_header Alt-Svc 'h3=":443"; ma=86400' always;
        add_header X-Content-Type-Options "nosniff" always;

        # Включение UDP Generic Segmentation Offload и eBPF для HTTP/3
        quic_gso on;
        quic_bpf on;

        # 10. Статический контент с максимальным кэшированием браузера
        location ~* \.(?:css|js|woff2|avif|webp|svg|png|jpg|ico)$ {
            root /var/www/static;
            expires 1y;
            add_header Cache-Control "public, immutable";
            add_header Alt-Svc 'h3=":443"; ma=86400' always;
            access_log off;
            try_files $uri =404;
        }

        # 11. Динамический бэкенд с защитой от Cache Stampede и микрокэшем
        location / {
            proxy_pass http://backend_pool;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Микрокэш для снятия пиков нагрузки
            proxy_cache MICRO_CACHE;
            proxy_cache_valid 200 301 302 2s;
            proxy_cache_valid 404 10s;

            # Гарантия от Cache Stampede
            proxy_cache_lock on;
            proxy_cache_lock_timeout 5s;
            proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
            proxy_cache_background_update on;

            add_header X-Cache-Status $upstream_cache_status always;
            add_header Alt-Svc 'h3=":443"; ma=86400' always;
        }
    }
}
```

---

### Сценарий 3: Сквозное профилирование задержки и изоляция узких мест (End-to-End Latency Profiling)

Методология SRE для пошаговой локализации источников задержки при деградации TTFB:

#### Шаг 1: Декомпозиция времени сетевого ответа через curl

```bash
# Форматированный вывод этапов запроса
curl -o /dev/null -s -w "\
DNS Lookup:        %{time_namelookup} s\n\
TCP Handshake:     %{time_connect} s\n\
TLS Handshake:     %{time_appconnect} s\n\
Pre-transfer:      %{time_pretransfer} s\n\
Start Transfer:    %{time_starttransfer} s (TTFB)\n\
Total Time:        %{time_total} s\n" https://example.com/api/v1/data
# → DNS Lookup:        0.002154 s
# → TCP Handshake:     0.015243 s
# → TLS Handshake:     0.038411 s
# → Pre-transfer:      0.038510 s
# → Start Transfer:    0.089124 s (TTFB)
# → Total Time:        0.092431 s
```

*Интерпретация:*
- Задержка на этапе `TCP Handshake` выше ожидаемого RTT указывает на переполнение очередей `SYN/Accept backlog` или дропы пакетов в сети.
- Разница между `Pre-transfer` и `Start Transfer` (здесь ~50 мс) отражает чистое время ожидания ответа бэкенда (upstream latency) и задержку очередей прокси.

#### Шаг 2: Проверка очередей слушающих сокетов и сетевого драйвера

```bash
# Проверка заполнения очереди Accept Queue для портов 80 и 443
ss -lnt '( sport = :443 or sport = :80 )'
# → State  Recv-Q Send-Q Local Address:Port  Peer Address:PortProcess
# → LISTEN 0      65535        0.0.0.0:443        0.0.0.0:*    users:(("nginx",pid=1234,fd=6))
```

*Критический индикатор:* Если `Recv-Q` приближается к `Send-Q` или равен ему — сокет переполнен, воркеры не успевают обрабатывать вызовы `accept()`.

```bash
# Проверка счетчиков переполнения очереди слушающих сокетов ядра
netstat -s | grep -i "listen"
# → 0 times the listen queue of a socket overflowed
# → 0 SYNs to LISTEN sockets dropped
```

#### Шаг 3: Проверка потерь на уровне кольцевых буферов сетевой карты (NIC Ring Buffers)

```bash
# Проверка счетчиков отброшенных пакетов сетевой карты
ethtool -S eth0 | grep -iE "drop|miss|over|err"
# → rx_dropped: 0
# → rx_missed_errors: 0
# → rx_over_errors: 0
```

При обнаружении роста `rx_dropped` следует увеличить кольцевые буферы драйвера:
```bash
# Просмотр текущих и максимальных размеров кольцевых буферов
ethtool -g eth0
# Увеличение буферов до максимума (например, 4096)
sudo ethtool -G eth0 rx 4096 tx 4096
```

---

## Операции и команды

### 1. Валидация сетевого стека ядра Linux

```bash
# Проверка текущих параметров BDP и перегрузки
sysctl net.ipv4.tcp_congestion_control net.core.default_qdisc net.ipv4.tcp_rmem net.ipv4.tcp_wmem
# → net.ipv4.tcp_congestion_control = bbr
# → net.core.default_qdisc = fq
# → net.ipv4.tcp_rmem = 4096	87380	16777216
# → net.ipv4.tcp_wmem = 4096	65536	16777216

# Проверка метрик сокета конкретного соединения (RTT, CWND, Retransmissions)
ss -ti '( dport = :443 )' | head -n 4
# → ESTAB 0 0 192.168.1.10:443 192.168.1.50:52344
# → bbr wscale:7,7 rto:200 rtt:12.45/1.2 cwnd:30 ssthresh:20 bytes_acked:14520 retrans:0/0
```

### 2. Валидация протоколов HTTP/2, HTTP/3 и TLS 1.3

```bash
# Проверка протокола ALPN (HTTP/2)
openssl s_client -connect example.com:443 -alpn h2 -servername example.com -brief
# → CONNECTION ESTABLISHED
# → Protocol version: TLSv1.3
# → Ciphersuite: TLS_AES_128_GCM_SHA256
# → ALPN protocol: h2

# Проверка поддержки HTTP/3 (QUIC) через curl
curl -I --http3 https://example.com/ | grep -iE "http/|alt-svc"
# → HTTP/3 200
# → alt-svc: h3=":443"; ma=86400

# Проверка статуса сокетов UDP для HTTP/3
ss -ulpn | grep :443
# → UNCONN 0 0 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1234,fd=8),("nginx",pid=1235,fd=9))
```

### 3. Проверка эффективности кэширования и сжатия

```bash
# Проверка сжатия Zstd / Brotli и статуса кэша
curl -sI -H "Accept-Encoding: zstd, br, gzip" https://example.com/style.css | grep -iE "content-encoding|cache-control|x-cache|age"
# → content-encoding: zstd
# → cache-control: public, immutable, max-age=31536000
# → x-cache-status: HIT
# → age: 43200

# Проверка отправки 103 Early Hints
curl -sI -H "Prefer: safe" https://example.com/ | head -n 8
# → HTTP/2 103 
# → link: </css/main.css>; rel=preload; as=style, </fonts/inter.woff2>; rel=preload; as=font; type=font/woff2; crossorigin
# → HTTP/2 200 
# → content-type: text/html; charset=UTF-8
```

### 4. Нагрузочное тестирование с замером перцентилей задержки

```bash
# Нагрузочный тест HTTP/2 с мультиплексированием стримов через h2load
h2load -n 100000 -c 200 -m 50 --warm-up-time 3 https://example.com/api/v1/health
# → finished in 1.15s, 86956.52 req/s, 12.87MB/s
# → requests: 100000 total, 100000 started, 100000 done, 100000 succeeded, 0 failed
# → status codes: 100000 2xx, 0 3xx, 0 4xx, 0 5xx
# → traffic: 14.80MB total, 2.10MB headers, 10.70MB data
# → time for request: 
# →   min: 0.85ms, max: 14.23ms, mean: 2.15ms, sd: 0.95ms
# → time for connect: 
# →   min: 1.20ms, max: 22.45ms, mean: 5.30ms, sd: 2.10ms
```

```bash
# Замер перцентилей задержки (p50, p95, p99) через wrk
wrk -t8 -c200 -d30s --latency https://example.com/
# → Running 30s test @ https://example.com/
# →   8 threads and 200 connections
# →   Thread Stats   Avg      Stdev     Max   +/- Stdev
# →     Latency     2.45ms    1.12ms  28.40ms   88.50%
# →     Req/Sec    10.25k     1.15k   14.20k    72.10%
# →   Latency Distribution
# →      50%    2.10ms
# →      75%    2.80ms
# →      90%    3.90ms
# →      99%    7.85ms
# →   2451200 requests in 30.05s, 1.45GB read
# → Requests/sec:  81570.71
```

---

## Диагностика и устранение неисправностей

| Проблема | Симптом | Инструмент диагностики | Первопричина | Инженерное решение |
| :--- | :--- | :--- | :--- | :--- |
| **Высокий TTFB (>500 мс) на динамических эндпоинтах** | Задержка до первого байта; очереди на бэкенде | `curl -w "%{time_starttransfer}\n"`, логи со временем `urt` | Отсутствие keepalive к бэкенду; блокировка медленными запросами к БД | Включить `upstream keepalive`; настроить микрокэширование (`proxy_cache MICRO_CACHE`); оптимизировать запросы в БД |
| **Сброс соединений на этапе SYN (SYN drops)** | Ошибки `Connection timed out` или `Connection reset by peer` под всплеском | `netstat -s \| grep -i "listen"`, `dmesg \| grep -i "syn"` | Переполнение `net.core.somaxconn` или `net.ipv4.tcp_max_syn_backlog` | Увеличить `somaxconn=65535` и `tcp_max_syn_backlog=65535`; задать `listen 443 backlog=65535` |
| **Исчерпание портов и ошибки сокетов** | `Cannot assign requested address` в логах Nginx/Angie | `ss -s`, `cat /proc/sys/net/ipv4/tcp_tw_reuse` | Лавинообразный рост сокетов в `TIME_WAIT` из-за закрытия соединений с бэкендом | Включить `keepalive` в секции `upstream`; выставить `net.ipv4.tcp_tw_reuse = 1`; расширить `ip_local_port_range` |
| **Cache Stampede (Thundering Herd)** | Внезапный скачок CPU до 100% и отказ бэкенда при истечении TTL кэша | Метрики CPU бэкенда; всплеск 502/504 Bad Gateway | Тысячи запросов одновременно пытаются обновить устаревший кэш | Добавить `proxy_cache_lock on;`, `proxy_cache_lock_timeout 5s;` и `proxy_cache_use_stale updating` |
| **Разрыв соединений HTTP/3 при reload сервера** | Прерывание активных сессий HTTP/3 клиентов при `nginx -s reload` | Логи ошибок Angie/Nginx: `quic connection closed`, `ss -ulpn` | Смена процесса воркера без сохранения соответствия CID сокету | Включить `quic_bpf on;` (требует Linux Kernel 5.7+); настроить `quic_gso on;` |
| **Блокировка воркеров дисковым I/O** | Рост задержки всех запросов воркера при отдаче больших файлов | `iostat -xz 1`, `pidstat -d 1`, `perf top` | Синхронный дисковый ввод-вывод замораживает event loop воркера | Включить `aio threads=default;`, `sendfile on;`, оптимизировать `open_file_cache` |
| **Превышение лимита файловых дескрипторов** | `24: Too many open files` в `error.log` | `cat /proc/$PID/limits`, `lsof -p $PID \| wc -l` | Занижен `worker_rlimit_nofile` или `LimitNOFILE` в systemd | Выставить `worker_rlimit_nofile 1048576;` в конфиге и `LimitNOFILE=1048576` в systemd override |
| **Переполнение буферов прокси** | `an upstream response is buffered to a temporary file` в логах | `grep "buffered to a temporary file" error.log` | Ответ бэкенда превышает размер `proxy_buffers` и сбрасывается на диск | Увеличить `proxy_buffers 128 16k;` и `proxy_buffer_size 32k;`, устранить лишний payload бэкенда |
| **Высокая нагрузка на CPU при сжатии** | Утилизация процессора воркерами >90% при относительно низком RPS | `top -b -n1`, `perf top` | Слишком высокий уровень динамического сжатия (Brotli 6–11 или Gzip 8–9) | Снизить уровень динамического сжатия до Brotli 4 / Zstd 3 / Gzip 4; перевести статику на `gzip_static` / `brotli_static` |

---

## Рекомендации и лучшие практики

### Чек-лист по уровням инфраструктуры

#### 1. Сетевой стек и ядро Linux
- [ ] Алгоритм контроля перегрузки переведен на `bbr` с дисциплиной очередей `fq`.
- [ ] Очереди `net.core.somaxconn` и `net.ipv4.tcp_max_syn_backlog` увеличены до `65535`.
- [ ] Параметры автоподстройки TCP-буферов (`net.ipv4.tcp_rmem` и `net.ipv4.tcp_wmem`) увеличены с максимумом не менее `16777216` байт.
- [ ] Включен `net.ipv4.tcp_tw_reuse = 1`, диапазон портов `ip_local_port_range` расширен до `10240 65535`.
- [ ] Настроены кольцевые буферы сетевой карты через `ethtool -G <iface> rx 4096 tx 4096`.

#### 2. Архитектура и ввод-вывод веб-сервера
- [ ] Процессы воркеров (`worker_processes auto;`) жестко привязаны к ядрам CPU (`worker_cpu_affinity auto;`).
- [ ] Лимит дескрипторов файлов процесса `worker_rlimit_nofile` и лимит systemd `LimitNOFILE` согласованы и составляют не менее `1048576`.
- [ ] Для отдачи статики активированы `sendfile on;`, `sendfile_max_chunk 512k;`, `tcp_nopush on;` и `tcp_nodelay on;`.
- [ ] Асинхронный дисковый ввод-вывод пула потоков `aio threads=default;` активирован для предотвращения задержек на page cache miss.
- [ ] Включено кэширование дескрипторов файлов через `open_file_cache`.

#### 3. Криптография и сетевые протоколы
- [ ] Устаревшие протоколы TLS 1.0 и TLS 1.1 полностью отключены; используется TLS 1.3 и TLS 1.2.
- [ ] Размер буфера TLS-записи `ssl_buffer_size` снижен до `4k` для ускорения первого рендеринга и уменьшения TTFB.
- [ ] Настроен разделяемый кэш сессий `ssl_session_cache shared:SSL:50m;` с тайм-аутом не менее 1 суток.
- [ ] Активирован Kernel TLS (kTLS) на поддерживаемых ядрах Linux (5.10+) для разгрузки CPU при отдаче HTTPS-трафика через `sendfile`.
- [ ] Поддержка HTTP/3 активирована через `listen 443 quic reuseport;` совместно с директивами `quic_gso on;` и `quic_bpf on;`.

#### 4. Кэширование и интеграция с апстримами
- [ ] Все upstream-группы бэкендов имеют настроенный пул `keepalive` (не менее 32–64 соединений на воркер) с обязательной передачей `proxy_http_version 1.1;` и `proxy_set_header Connection "";`.
- [ ] Настроена буферизация прокси (`proxy_buffering on;`, `proxy_buffers 128 16k;`) для защиты бэкендов от медленных клиентов.
- [ ] Для всех кэшируемых зон активирована защита от Cache Stampede: `proxy_cache_lock on;`, `proxy_cache_lock_timeout 5s;`, `proxy_cache_use_stale updating`.
- [ ] Для часто запрашиваемых динамических API-эндпоинтов реализовано микрокэширование со сроком жизни 1–2 секунды.

---

### Антипаттерны производительности (чего делать НЕЛЬЗЯ)

1. **Использовать Domain Sharding в HTTP/2 и HTTP/3:**
   *Разделение статики по доменам (`static1.example.com`, `static2.example.com`) вынуждает браузер выполнять дополнительные DNS-запросы, устанавливать новые TCP/UDP соединения и проходить несколько TLS-рукопожатий, полностью разрушая преимущества мультиплексирования.*
2. **Отключать буферизацию прокси без крайней необходимости (`proxy_buffering off`):**
   *При отключенной буферизации поток данных передается от бэкенда клиенту синхронно. Медленный клиент на 3G/LTE сети удерживает воркер или поток бэкенда (PHP-FPM, Gunicorn, Node.js) на протяжении всего времени передачи, вызывая быстрое исчерпание пула рабочих процессов бэкенда.*
3. **Оставлять секцию `upstream` без директивы `keepalive`:**
   *Создает эффект «шторма TCP-соединений»: каждое обращение к приложению порождает 3-way handshake, транслирует задержки и заполняет системную таблицу соединений сокетами в состоянии `TIME_WAIT`.*
4. **Задавать максимальные уровни динамического сжатия «на лету»:**
   *Выставление уровня Brotli 11 или Gzip 9 для динамических JSON/HTML ответов приводит к мгновенной 100% утилизации CPU при незначительном выигрыше в размере ответа (1–3%). Экстремальные уровни допустимы только для предварительного статического сжатия на этапе CI/CD (`gzip_static`, `brotli_static`, `zstd_static`).*
5. **Использовать синхронный I/O для тяжелых файлов без `aio threads`:**
   *Чтение с диска файла, отсутствующего в page cache, блокирует весь рабочий процесс Nginx/Angie, приводя к росту задержек всех остальных клиентов, обслуживаемых данным воркером.*
6. **Оставлять дефолтные лимиты `net.core.somaxconn = 128` и `worker_rlimit_nofile = 1024`:**
   *Сервер теряет соединения и начинает возвращать `Connection refused` и `Too many open files` при первом же всплеске трафика, несмотря на наличие свободных ресурсов процессора и оперативной памяти.*

---

## Дополнительная информация

### Связанные темы в базе знаний

- [Обзор производительности веб-приложений](./overview.md) — фундаментальные уровни и метрики производительности.
- [Ключевые метрики Web Vitals](./web_vitals.md) — инженерные детали оптимизации метрик LCP, INP, CLS и TTFB.
- [Протоколы HTTP/2 и HTTP/3](./http2_http3.md) — детальный разбор транспорта QUIC, UDP GSO и мультиплексирования.
- [Компрессия контента на веб-сервере](./server_compression.md) — алгоритмы Brotli, Zstandard, Gzip, статическое и динамическое сжатие.
- [Оптимизация TLS](./tls_optimization.md) — настройка TLS 1.3, сессионного кэша, билетов и Kernel TLS.
- [Кэширование как инструмент веб-производительности](./caching.md) — заголовки Cache-Control, ETag, stale-while-revalidate и инвалидация.
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — тонкая настройка пулов соединений к бэкендам.
- [Принципы тестирования производительности](./testing_principles.md) — методология нагрузочного тестирования и бенчмаркинга.
- [Диагностика веб-серверов](../webserver_troubleshooting.md) — поиск и устранение аварийных ситуаций веб-серверов.
- [Настройка Angie для высоких нагрузок](../../Angie/High_Load/index.md) — детальный системный тюнинг Angie под high-load.
- [Оптимизация производительности Nginx](../../Nginx/Performance/nginx_performance_tuning.md) — системная оптимизация Nginx.
- [Алгоритмы контроля перегрузки TCP](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md) — глубокий разбор BBR, CUBIC, Reno.
- [Очереди TCP-соединений в Linux](../../../Linux/Networking/Concepts/tcp_tuning/tcp_connection_queues.md) — работа SYN backlog и Accept backlog.

### Внешняя документация и стандарты

- [RFC 9114: HTTP/3](https://datatracker.ietf.org/doc/html/rfc9114) — спецификация протокола HTTP/3 поверх QUIC.
- [RFC 9000: QUIC: A UDP-Based Multiplexed and Secure Transport](https://datatracker.ietf.org/doc/html/rfc9000) — архитектура и транспорт QUIC.
- [RFC 8297: An HTTP Status Code for Indicating Hints (103 Early Hints)](https://datatracker.ietf.org/doc/html/rfc8297) — стандарт механизма 103 Early Hints.
- [Linux Kernel Documentation: IP Sysctl](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt) — официальное руководство по сетевым параметрам ядра Linux.
- [Nginx Documentation: Performance Tuning](https://nginx.org/en/docs/) — официальное руководство по настройке параметров производительности Nginx.
- [Angie Web Server Documentation](https://angie.software/en/) — официальная документация веб-сервера Angie.
