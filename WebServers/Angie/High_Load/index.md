# Настройка Angie для высоких нагрузок и защиты от атак

**Актуально для:** Angie 1.12.x (включая Angie PRO для кластерных функций)

## Определения

**Высокая нагрузка (High Load)** — режим функционирования инфраструктуры, при котором объём входящего сетевого трафика, число одновременных соединений или интенсивность вычислений приближаются к физическим пределам пропускной способности аппаратных ресурсов (CPU, RAM, дисковый I/O, сетевой стек ОС и пропускная способность сетевых карт).

**Оптимизация производительности (Performance Optimization)** — комплекс системных мер на уровне ядра Linux, конфигурации Angie и сетевого взаимодействия, направленный на максимизацию пропускной способности (Throughput, RPS) и минимизацию задержек (Latency, TTFB) при контролируемом потреблении системных ресурсов.

**Защита от DoS/DDoS (Denial of Service)** — эшелонированный комплекс механизмов фильтрации и ограничения трафика на уровнях L3/L4 (ядро Linux, nftables, SYN cookies) и L7 (Angie rate limiting, connection limiting, валидация заголовков), предотвращающий деградацию и отказ сервиса при аномальных всплесках нагрузки или вредоносных атаках.

**Пропускная способность (Throughput)** — число запросов или объём полезных данных, успешно обработанных сервером за единицу времени. Измеряется в RPS (Requests Per Second) или битах в секунду (Mbps/Gbps).

**Задержка (Latency / TTFB / TTLB)** — временные интервалы обработки запроса:
- **TTFB (Time To First Byte)** — время от отправки первого байта клиентского запроса до получения первого байта ответа сервера.
- **TTLB (Time To Last Byte)** — полное время доставки ответа до закрытия или завершения передачи тела.

**Событийно-ориентированный цикл (Event Loop)** — архитектурная модель неблокирующей обработки соединений. Воркер Angie регистрирует файловые дескрипторы сокетов в системном вызове `epoll` (Linux) и обрабатывает события ввода-вывода асинхронно в одном потоке без накладных расходов на контекстные переключения потоков ОС.

**Зоны разделяемой памяти (Shared Memory Zones)** — сегменты оперативной памяти (`shm`), выделяемые Angie для синхронизации состояний между всеми независимыми worker-процессами (счётчики `limit_req`, таблицы соединений `limit_conn`, индексы `proxy_cache`, структуры балансировки `upstream` и метрики `status_zone`).

**Zero-Copy & Kernel TLS (kTLS)** — технологии минимизации копирования данных между пространством ядра (kernel space) и пространством пользователя (user space). Механизм `sendfile()` передаёт статические файлы напрямую из кэша страниц ядра в сокет, а kTLS выполняет симметричное шифрование TLS (AES-GCM / ChaCha20-Poly1305) силами ядра без двойного транзита через буферы процесса.

**Inflight Requests** — запросы, принятые прокси-сервером и отправленные на обработку вышестоящим бэкендам, но ещё не получившие окончательного ответа. Контроль inflight-запросов предотвращает лавинообразное исчерпание пулов соединений бэкенда.

**Планирование ёмкости (Capacity Planning)** — расчётный инженерный процесс определения пределов ресурсов (файловые дескрипторы, память под кэш и зоны, сетевые буферы, процессорные ядра), необходимых для бесперебойного пропуска планового и пикового трафика.

**SRE Golden Signals** — четыре ключевые метрики надёжности распределённых систем по классификации Google SRE: задержка (Latency), объём трафика (Traffic), частота ошибок (Errors) и степень насыщения ресурсов (Saturation).

---

## Базовые концепции и архитектура

### Архитектура процессов и управление памятью

Angie использует многопроцессную событийно-ориентированную модель, адаптированную для симметричного масштабирования на современных многоядерных архитектурах:

```
+------------------------------------------------------------------------+
|                          Master Process (root)                         |
|  - Чтение и валидация конфигурации (/etc/angie/angie.conf)             |
|  - Привязка привилегированных портов (80, 443)                         |
|  - Управление жизненным циклом воркеров (сигналы HUP, USR2, WINCH, QUIT)|
+-----------------------------------+------------------------------------+
                                    |
          +-------------------------+-------------------------+
          |                         |                         |
+---------v----------+    +---------v----------+    +---------v----------+
|  Worker Process 0  |    |  Worker Process 1  |    |  Worker Process N  |
|  (epoll event loop)|    |  (epoll event loop)|    |  (epoll event loop)|
+---------+----------+    +---------+----------+    +---------+----------+
          |                         |                         |
+---------v-------------------------v-------------------------v----------+
|                 Разделяемая память (POSIX Shared Memory)               |
|  - limit_req_zone (счётчики rate limit, Leaky Bucket)                  |
|  - limit_conn_zone (активные сессии по IP/Host)                        |
|  - proxy_cache keys_zone (хэш-таблица и метаданные кэша)               |
|  - upstream zone (статусы бэкендов, least_time, динамический API)      |
|  - status_zone / prometheus (атомарные счётчики метрик)                |
+-----------------------------------+------------------------------------+
                                    |
          +-------------------------+-------------------------+
          |                                                   |
+---------v----------+                             +----------v---------+
|   Cache Manager    |                             |    Cache Loader    |
| Очистка устаревших |                             | Первичная загрузка |
| и избыточных ключей|                             | индекса с диска    |
+--------------------+                             +--------------------+
```

1. **Master-процесс:** Не участвует в обработке клиентских запросов. Обеспечивает безопасный запуск от имени `root`, открытие сокетов, трансляцию сигналов и бесшовную перезагрузку воркеров.
2. **Worker-процессы (`worker_processes auto;`):** Функционируют от непривилегированного пользователя (обычно `angie` или `www-data`). Каждый воркер привязывается к выделенному ядру CPU через директиву `worker_cpu_affinity auto;`, исключая межъядерные переключения контекста и деградацию кэша L1/L2/L3.
3. **Разделяемая память (Shared Memory):** Angie не использует межпроцессную блокировку через файлы для отслеживания состояния. Все зоны создаются с фиксированным размером через директивы `zone` в соответствующих модулях.

### Сквозной тракт обработки трафика (L4 → L7)

При высоких нагрузках узким местом может стать любой уровень стека. В архитектуре Angie взаимодействие распределено по эшелонам:

1. **Сетевой интерфейс (NIC):** Механизм RSS (Receive Side Scaling) раскладывает входящие пакеты по аппаратным очередям сетевой карты (RX-очереди), прерывания которых привязаны к ядрам CPU.
2. **Сетевой стек ядра Linux:** Пакет проходит через подсистемы netfilter/nftables, таблицу отслеживания соединений (`conntrack`), очередь полуоткрытых соединений (`tcp_max_syn_backlog`) и очередь `listen()`-сокета (`somaxconn`).
3. **Событийный цикл Angie:** Механизм `SO_REUSEPORT` позволяет каждому воркеру иметь собственный слушающий сокет на одном порту, где ядро распределяет новые TCP-соединения между воркерами без конкуренции за единый мьютекс.
4. **Проксирование и апстримы:** Пул предварительно открытых TCP-соединений (`keepalive` в блоке `upstream`) исключает накладные расходы на трёхстороннее рукопожатие TCP (3-way handshake) и TLS-хэндшейки к бэкендам на каждый клиентский запрос.

### Ключевые архитектурные преимущества Angie 1.12+ для High Load

- **Сохранение индекса кэша (Cache Index Persistence):** Возможность сохранять структуру индекса кэша в разделяемой памяти на диск при перезапуске. Сервер готов отдавать терабайты кэшированных данных сразу после старта без периода деградации диска и бэкендов («разогрев кэша»).
- **Балансировка `least_time` с учётом Inflight:** Доступный в базовой версии Angie алгоритм направляет запрос узлу с наименьшим временем ответа (`header` или `last_byte`), непрерывно корректируя приоритет с учётом числа запросов, уже находящихся в обработке (`inflight`).
- **Плавный старт (Slow Start):** Директива `slow_start` плавно увеличивает вес восстановленного сервера от нуля до номинала, исключая падение бэкенда от мгновенного наплыва запросов после перезагрузки.
- **Привязка сессий без внешних хранилищ (Sticky Learn):** Нативная сессионная привязка через перехват идентификатора (cookie или заголовок) из ответов бэкенда без использования сторонних кэшей (Redis/Memcached).
- **HTTP/3 и QUIC с поддержкой eBPF:** Модуль `quic_bpf` привязывает UDP-сокеты соединений QUIC к конкретным процессам воркеров, гарантируя стабильность сессий пользователей даже при выполнении команды `angie -s reload`.
- **Нативное сжатие Zstandard (zstd):** Обеспечивает на 15–30% меньший объём трафика по сравнению с gzip при сопоставимой или меньшей нагрузке на процессор.
- **Встроенная телеметрия без сайдкаров:** Модуль `prometheus` экспортирует метрики нативно в формате OpenMetrics, а модуль `otel` формирует трассировки через протокол gRPC/OTLP.

### Различия Angie OSS и Angie PRO в условиях экстремальной нагрузки

| Возможность | Angie Open Source (OSS) | Angie PRO | Применение в SRE / High Load |
| :--- | :--- | :--- | :--- |
| **Очереди к бэкендам (`queue`)** | Отсутствуют (при `max_conns` возвращается 502/503) | Встроены (буферизация всплесков в RAM) | Защита медленных баз данных и приложений от перегрузки |
| **Кластерная синхронизация зон (`zone_sync`)** | Нет (лимиты считаются изолированно на каждом сервере) | Нативная синхронизация через TCP/Stream | Единый глобальный rate limit и connection limit на ферму серверов |
| **Балансировка по обратной связи (`feedback`)** | Нет | Нативная адаптивная балансировка | Динамическая подстройка под текущую утилизацию CPU/RAM бэкендов |
| **Дренаж соединений (`drain`)** | Нет | Полноценный режим вывода из ротации | Бесшовный вывод серверов на регламентные работы без сброса активных сессий |

---

## Практические сценарии и конфигурация

### Предварительные требования и сайзинг ресурсов (Capacity Planning)

#### Программные компоненты и совместимость

| Компонент | Минимальная версия | Рекомендуемая версия | Роль в высоконагруженном контуре |
| :--- | :--- | :--- | :--- |
| **Angie** | 1.12.0 | 1.12.x+ | Веб-сервер, обратный прокси, терминатор TLS |
| **Linux Kernel** | 5.15 LTS | 6.1+ LTS / 6.6+ LTS | Поддержка kTLS, eBPF `quic_bpf`, BBR congestion control |
| **OpenSSL / BoringSSL**| OpenSSL 3.0.0 | OpenSSL 3.2+ | Аппаратное ускорение TLS 1.3, kTLS |
| **nftables** | 1.0.0 | 1.0.8+ | Высокопроизводительная фильтрация пакетов L3/L4 через O(1) sets |
| **wrk2 / k6** | — | Последние стабильные | Инструменты нагрузочного аудита без эффекта Coordinated Omission |

#### Инженерные формулы расчёта лимитов

1. **Файловые дескрипторы (`worker_rlimit_nofile`):**
   Каждое клиентское соединение в режиме прокси использует два сокета (клиентский + апстримный) плюс дескрипторы для статических файлов, логов и разделяемой памяти:
   $$\text{worker\_rlimit\_nofile} \ge \text{worker\_connections} \times 2 + 10000$$
   Для сервера с `worker_connections 65535;` параметр `worker_rlimit_nofile` должен составлять не менее `150000` (рекомендуется `262144` или `1048576`).

2. **Оперативная память под Shared Memory Zones:**
   - Зона `limit_req_zone` на ключе `$binary_remote_addr` (16 байт IPv6 или 4 байта IPv4): состояние одной сессии в структуре красно-чёрного дерева занимает 128 байт. Зона объёмом 32 MB способна удерживать около 260 000 уникальных активных IP-адресов.
   - Зона кэша `keys_zone` в `proxy_cache_path`: метаданные одного объекта кэша занимают 256 байт. Зона объёмом 128 MB вмещает метаданные 524 000 файлов на диске.

#### Первичная валидация готовности хоста

```bash
# Проверка версии Angie и доступных скомпилированных модулей
angie -V 2>&1 | grep -o -E "angie/[0-9.]+|with-[a-z0-9_]+"
# → angie/1.12.2
# → with-http_v2_module
# → with-http_v3_module
# → with-http_ssl_module

# Проверка поддержки kTLS в ядре
modprobe tls
ls -d /sys/kernel/tls/ 2>/dev/null && echo "kTLS supported"
# → /sys/kernel/tls/
# → kTLS supported

# Проверка доступности алгоритма перегрузки BBR
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr

# Проверка текущего системного лимита дескрипторов
ulimit -n
# → 1048576
```

---

### Сценарий 1: Эталонный производственный конфигурационный файл Angie High Load

Ниже приведена самодостаточная эталонная конфигурация `/etc/angie/angie.conf`, объединяющая все ключевые параметры высокой производительности, защиты от атак и наблюдаемости.

```nginx
# /etc/angie/angie.conf
user  angie;
worker_processes  auto;
worker_cpu_affinity  auto;

# Лимит дескрипторов файлов для процессов worker
worker_rlimit_nofile 262144;

# Уровень логирования: warn для предотвращения деградации диска от I/O
error_log  /var/log/angie/error.log warn;
pid        /run/angie.pid;

events {
    # Число одновременных соединений на один worker-процесс
    worker_connections  65535;
    
    # Принятие всех готовых соединений за один цикл epoll
    multi_accept        on;
    
    # Использование наиболее производительного механизма мультиплексирования
    use                 epoll;
}

http {
    include       /etc/angie/mime.types;
    default_type  application/octet-stream;

    # ---------------------------------------------------------
    # Оптимизация дискового и сетевого ввода-вывода (I/O)
    # ---------------------------------------------------------
    sendfile                  on;
    tcp_nopush                on;
    tcp_nodelay               on;
    aio                       threads=default;
    directio                  8m;

    # Кэширование дескрипторов открытых статических файлов
    open_file_cache           max=50000 inactive=60s;
    open_file_cache_valid     30s;
    open_file_cache_min_uses  2;
    open_file_cache_errors    on;

    # Ускорение обработки регулярных выражений
    pcre_jit                  on;

    # ---------------------------------------------------------
    # Буферы и таймауты (защита от Slowloris и утечек памяти)
    # ---------------------------------------------------------
    client_body_buffer_size      128k;
    client_header_buffer_size    2k;
    large_client_header_buffers  4 8k;
    client_max_body_size         20m;

    client_header_timeout        10s;
    client_body_timeout          10s;
    send_timeout                 10s;
    keepalive_timeout            65s;
    keepalive_requests           10000;
    reset_timedout_connection    on;

    # ---------------------------------------------------------
    # Сжатие данных (Zstandard и Gzip)
    # ---------------------------------------------------------
    zstd               on;
    zstd_comp_level    3;
    zstd_types         text/plain text/css application/json application/javascript
                       text/xml application/xml application/xml+rss text/javascript
                       image/svg+xml;

    gzip               on;
    gzip_comp_level    5;
    gzip_min_length    256;
    gzip_proxied       any;
    gzip_types         text/plain text/css application/json application/javascript
                       text/xml application/xml application/xml+rss text/javascript
                       image/svg+xml;

    # ---------------------------------------------------------
    # Оптимизация SSL/TLS и kTLS
    # ---------------------------------------------------------
    ssl_protocols             TLSv1.2 TLSv1.3;
    ssl_ciphers               ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers off;
    ssl_session_cache         shared:SSL:64m;
    ssl_session_timeout       1d;
    ssl_session_tickets       off;
    ssl_conf_command          Options +KTLS;

    # ---------------------------------------------------------
    # Зоны разделяемой памяти для защиты от DoS (Rate & Conn Limiting)
    # ---------------------------------------------------------
    # Белый список для исключения мониторинга и внутренних сетей из лимитов
    geo $apply_limit {
        default        1;
        127.0.0.1/32   0;
        10.0.0.0/8     0;
        192.168.0.0/16 0;
    }

    map $apply_limit $limit_key {
        1 $binary_remote_addr;
        0 "";
    }

    # Ограничение частоты запросов (10 r/s на IP, зона 32 MB)
    limit_req_zone  $limit_key  zone=req_general:32m  rate=10r/s;
    limit_req_zone  $limit_key  zone=req_api:32m      rate=5r/s;
    limit_req_status 429;

    # Ограничение числа параллельных соединений (30 соединений на IP)
    limit_conn_zone $limit_key  zone=conn_ip:32m;
    limit_conn_status 429;

    # ---------------------------------------------------------
    # Кэширование проксируемых ответов с сохранением индекса
    # ---------------------------------------------------------
    proxy_cache_path /var/cache/angie/proxy
                     levels=1:2
                     keys_zone=cache_main:128m
                     max_size=20g
                     inactive=24h
                     use_temp_path=off;

    # ---------------------------------------------------------
    # Формат логирования с буферизацией в память
    # ---------------------------------------------------------
    log_format highload '$remote_addr - $remote_user [$time_local] "$request" '
                        '$status $body_bytes_sent "$http_referer" '
                        '"$http_user_agent" rt=$request_time '
                        'uct="$upstream_connect_time" uht="$upstream_header_time" '
                        'urt="$upstream_response_time"';

    # Запись в лог через буфер 64KB с интервалом сброса 5s
    access_log /var/log/angie/access.log highload buffer=64k flush=5s;

    # Скрытие версии сервера
    server_tokens off;

    # ---------------------------------------------------------
    # Пул вышестоящих серверов (Upstream)
    # ---------------------------------------------------------
    upstream backend_pool {
        # Зона разделяемой памяти для апстрима (обязательна для least_time и API)
        zone backend_zone 64m;

        # Балансировка по минимальному времени отклика последнего байта с учётом inflight
        least_time last_byte inflight;

        # Пул постоянных keepalive-соединений к каждому воркеру
        keepalive 128;
        keepalive_requests 10000;
        keepalive_timeout 60s;

        server 10.0.1.11:8080 max_fails=3 fail_timeout=10s slow_start=30s;
        server 10.0.1.12:8080 max_fails=3 fail_timeout=10s slow_start=30s;
    }

    # ---------------------------------------------------------
    # Виртуальный хост: Сервер по умолчанию (сброс невалидных запросов)
    # ---------------------------------------------------------
    server {
        listen 80 default_server;
        listen [::]:80 default_server;
        server_name _;
        # Немедленный сброс соединения без отправки HTTP-заголовков
        return 444;
    }

    # ---------------------------------------------------------
    # Виртуальный хост: Основной рабочий трафик
    # ---------------------------------------------------------
    server {
        listen 443 ssl default_server reuseport;
        listen [::]:443 ssl default_server reuseport;
        # HTTP/3 (QUIC) на UDP-порту
        listen 443 quic reuseport;
        listen [::]:443 quic reuseport;

        server_name example.com;

        ssl_certificate     /etc/ssl/certs/example.com.crt;
        ssl_certificate_key /etc/ssl/private/example.com.key;

        # Привязка eBPF для QUIC-сокетов
        quic_bpf on;
        quic_retry on;
        add_header Alt-Svc 'h3=":443"; ma=86400';

        # Метрики статус-зоны
        status_zone main_host;

        # Базовые лимиты на всё приложение
        limit_conn conn_ip 50;
        limit_req zone=req_general burst=20 nodelay;

        # Отдача статики с агрессивным кэшированием
        location /static/ {
            root /var/www/example;
            expires 30d;
            add_header Cache-Control "public, immutable";
            access_log off;
        }

        # Проксирование критичного API с выделенным лимитом
        location /api/ {
            limit_req zone=req_api burst=10 delay=5;

            proxy_pass http://backend_pool;
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Таймауты взаимодействия с апстримом
            proxy_connect_timeout 2s;
            proxy_send_timeout    5s;
            proxy_read_timeout    10s;

            # Буферизация ответов бэкенда
            proxy_buffering       on;
            proxy_buffer_size     8k;
            proxy_buffers         64 8k;
            proxy_busy_buffers_size 32k;
        }

        # Проксирование веб-страниц с кэшированием
        location / {
            proxy_pass http://backend_pool;
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            proxy_cache cache_main;
            proxy_cache_valid 200 302 10m;
            proxy_cache_valid 404 1m;
            proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
            proxy_cache_lock on;
            proxy_cache_lock_timeout 5s;

            add_header X-Cache-Status $upstream_cache_status;
        }
    }

    # ---------------------------------------------------------
    # Виртуальный хост: Внутренний мониторинг и метрики (Loopback)
    # ---------------------------------------------------------
    server {
        listen 127.0.0.1:8088;
        server_name localhost;

        # Нативный эндпоинт метрик Prometheus (Angie 1.12+)
        location /metrics {
            prometheus all;
            allow 127.0.0.1;
            deny all;
        }

        # REST API для контроля состояния и сброса кэша
        location /api/ {
            api on;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

---

### Сценарий 2: Системная интеграция и тюнинг Linux (sysctl и systemd)

Высокопроизводительный сервер не может функционировать на дефолтных параметрах ядра. Сетевой стек Linux требует расширения очередей и буферов.

#### 1. Системные параметры ядра `/etc/sysctl.d/99-angie-highload.conf`

```ini
# Максимальное число открытых дескрипторов в системе
fs.file-max = 2097152

# Максимальная длина очереди сокетов listen()
net.core.somaxconn = 65535

# Максимальное число пакетов в очереди сетевого интерфейса до передачи в стек
net.core.netdev_max_backlog = 65535

# Максимальный размер буферов приёма и отправки сокетов (16 MB)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 262144
net.core.wmem_default = 262144

# Автотюнинг TCP-буферов: min, default, max
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Очередь неполных соединений (SYN-пакеты)
net.ipv4.tcp_max_syn_backlog = 65535

# Защита от SYN-флуда при переполнении очереди
net.ipv4.tcp_syncookies = 1

# Повторное использование сокетов в состоянии TIME_WAIT для исходящих соединений
net.ipv4.tcp_tw_reuse = 1

# Сокращение времени удержания сокета в состоянии FIN-WAIT-2
net.ipv4.tcp_fin_timeout = 15

# Диапазон локальных портов для исходящих соединений к апстримам (более 60k портов)
net.ipv4.ip_local_port_range = 1024 65535

# Контроль перегрузки TCP (BBR)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Лимиты таблицы отслеживания соединений conntrack (при активном firewall)
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_tcp_timeout_established = 600
```

Применение параметров ядра:

```bash
sysctl --system
# → Applying /etc/sysctl.d/99-angie-highload.conf ...
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_congestion_control = bbr
```

#### 2. Конфигурация службы systemd `/etc/systemd/system/angie.service.d/override.conf`

Создайте каталог и файл переопределения ограничений процесса:

```ini
[Service]
# Снятие ограничений на количество открытых файлов процессом
LimitNOFILE=1048576

# Снятие ограничений на количество процессов/потоков
LimitNPROC=512000

# Запрет сброса дампов памяти при падении (защита закрытых ключей TLS)
LimitCORE=0

# Политика планировщика задач для максимального приоритета обработки I/O
CPUSchedulingPolicy=other
Nice=-5
```

Применение переопределений службы:

```bash
systemctl daemon-reload
systemctl restart angie
systemctl show angie.service | grep -E "LimitNOFILE|LimitNPROC"
# → LimitNOFILE=1048576
# → LimitNOFILESoft=1048576
# → LimitNPROC=512000
```

---

### Сценарий 3: Архитектура кэширования и разгрузка ввода-вывода (I/O Offload)

Кэширование на обратном прокси выступает первым и наиболее эффективным барьером от перегрузки бэкендов при всплесках трафика:

- **Защита от эффекта Thundering Herd («собачья свора»):** Директива `proxy_cache_lock on;` гарантирует, что при истечении срока жизни кэшированного объекта только один первичный запрос будет отправлен к вышестоящему бэкенду. Все остальные одновременные клиенты ожидают ответа в памяти прокси и получают заполненный кэш без нагрузки на приложение.
- **Сохранение индекса разделяемой памяти:** Директива `proxy_cache_path` в Angie 1.12+ оптимизирована для сверхбыстрой инициализации.
- **Аппаратная разгрузка через kTLS:** При отдаче статических файлов с диска по протоколу HTTPS связка `sendfile on;` и `ssl_conf_command Options +KTLS;` исключает этап чтения зашифрованных данных процессором веб-сервера. Ядро ОС передаёт страницы файлового кэша напрямую сетевому контроллеру.

> Подробная архитектура, профилирование и оптимизация кэширования: [Оптимизация производительности Angie](./performance_optimization.md).
> Специализированная трансформация и кэширование медиа-контента: [Модуль image_filter в Angie](./image_filter/overview.md) и [Кэширование image_filter](./image_filter/caching.md).

---

### Сценарий 4: Эшелонированная защита от DoS-атак

Защита от отказа в обслуживании делится на функциональные эшелоны:

1. **Эшелон L3/L4 (Сетевой стек и ядро Linux):**
   - Блокировка невалидных комбинаций TCP-флагов, фрагментированных пакетов и поддельных адресов (IP Spoofing) через `nftables`.
   - Защита от SYN-флуда через `net.ipv4.tcp_syncookies = 1` без сохранения состояния в памяти ядра.
   - Фильтрация UDP Amplification и отражённых атак на протокол QUIC через директиву `quic_retry on;`.

2. **Эшелон L7 (Уровень приложения в Angie):**
   - **Алгоритм Leaky Bucket (`limit_req`):** Плавное сглаживание всплесков трафика через буфер `burst` с обработкой `nodelay` или двухфазным замедлением `delay`.
   - **Защита от медленных атак (Slowloris / Slow POST):** Агрессивные таймауты `client_header_timeout 10s;` и `client_body_timeout 10s;` в сочетании с директивой `reset_timedout_connection on;`, немедленно отправляющей пакет TCP RST вместо долгого ожидания четырёхфазного закрытия сокета.
   - **Изоляция неизвестных хостов:** Сервер по умолчанию с директивой `return 444;` сбрасывает TCP-соединения сканеров уязвимостей и ботов без передачи байт в ответ.

> Исчерпывающее руководство по защите, алгоритмам Leaky Bucket, правилам nftables и fail2ban: [Защита от DoS-атак в Angie](./dos_protection.md).

---

### Сценарий 5: Наблюдаемость, SRE Golden Signals и Health Checks

В условиях высокой нагрузки веб-сервер должен непрерывно экспортировать телеметрию для отслеживания состояния в реальном времени.

#### 1. Мониторинг ключевых сигналов SRE через Prometheus

Эндпоинт `/metrics` в Angie 1.12+ отдает метрики в нативном формате OpenMetrics без использования внешних экспортеров (например, `nginx-prometheus-exporter`):

```bash
# Получение системных метрик Angie
curl -s http://127.0.0.1:8088/metrics | grep -E "angie_http_requests_total|angie_connections_active|angie_upstreams" | head -n 15
# → # TYPE angie_http_requests_total counter
# → angie_http_requests_total{status_zone="main_host",code="200"} 4529301
# → angie_http_requests_total{status_zone="main_host",code="429"} 142
# → angie_http_requests_total{status_zone="main_host",code="502"} 3
# → # TYPE angie_connections_active gauge
# → angie_connections_active 1845
```

#### 2. Формулы вычисления SRE Golden Signals

| Сигнал SRE | Источник метрики в Angie | Метод вычисления / Порог алерта |
| :--- | :--- | :--- |
| **Traffic (RPS)** | `angie_http_requests_total` | `sum(rate(angie_http_requests_total[1m]))` |
| **Errors (5xx rate)** | `angie_http_requests_total{code=~"5.."}` | `sum(rate(angie_http_requests_total{code=~"5.."}[1m])) / sum(rate(angie_http_requests_total[1m])) > 0.01` (порог 1%) |
| **Latency (p99)** | `highload` access_log (`$request_time`) | Гистограммы Prometheus или логирование через OTel |
| **Saturation** | `angie_connections_active` | `angie_connections_active / (worker_processes * worker_connections) > 0.8` (порог 80%) |

> Полное руководство по метрикам и Prometheus: [Мониторинг Angie через Prometheus](../angie_monitoring/angie_monitoring_prometheus.md) и [REST API мониторинга Angie](../angie_monitoring/angie_monitoring_api.md).

---

## Операции и команды

### Управление сигналами master-процесса

Angie поддерживает стандартные UNIX-сигналы для безопасного управления процессами без разрыва соединений:

| Сигнал | Команда POSIX | Действие мастера | Применение в SRE / High Load |
| :--- | :--- | :--- | :--- |
| `HUP` | `kill -HUP $(cat /run/angie.pid)` | Бесшовная перечитка конфигурации (`reload`) | Применение новых зон, лимитов, TLS-сертификатов |
| `USR1` | `kill -USR1 $(cat /run/angie.pid)` | Переоткрытие файлов логов | Ротация логов без остановки сервера (`logrotate`) |
| `USR2` | `kill -USR2 $(cat /run/angie.pid)` | Запуск нового исполняемого файла | Обновление версии Angie на лету (Zero Downtime Binary Upgrade) |
| `WINCH` | `kill -WINCH $(cat /run/angie.pid)` | Грациозная остановка воркеров старого мастера | Второй этап бинарного обновления версии |
| `QUIT` | `kill -QUIT $(cat /run/angie.pid)` | Грациозное завершение работы мастера и воркеров | Остановка после обслуживания текущих соединений |
| `TERM` / `INT` | `kill -TERM $(cat /run/angie.pid)` | Немедленное завершение работы | Аварийная остановка сервиса |

### Практические команды администрирования

```bash
# 1. Валидация синтаксиса конфигурации перед применением
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Вывод полной объединённой конфигурации со всеми include (аудит)
angie -T | grep -E "worker_processes|least_time" | head -n 5
# → worker_processes  auto;
# → least_time last_byte inflight;

# 3. Бесшовная перезагрузка конфигурации (Graceful Reload)
angie -s reload
# → [notice] ... signal process started

# 4. Проверка состояния очередей сокетов на уровне ядра (Send-Q и Recv-Q)
ss -ltni '( sport = :443 or sport = :80 )'
# → State  Recv-Q Send-Q Local Address:Port  Peer Address:Port
# → LISTEN 0      65535        *:443               *:*

# 5. Проверка состояния пула апстримов через REST API
curl -s http://127.0.0.1:8088/api/v1/http/upstreams/backend_pool | grep -E "server|weight|state"
# → "server": "10.0.1.11:8080", "state": "up", "active": 24
# → "server": "10.0.1.12:8080", "state": "up", "active": 21

# 6. Проверка статистики сброса запросов по Rate Limiting
curl -s http://127.0.0.1:8088/api/v1/http/limit_reqs/req_general
# → {"passed":4510200,"rejected":142,"delayed":890}
```

---

## Диагностика и устранение неисправностей

### Матрица симптомов и причин деградации под нагрузкой

| Симптом | Возможная причина | Инструмент диагностики | Метод устранения |
| :--- | :--- | :--- | :--- |
| **`[alert] worker_connections are not enough`** | Исчерпан пул `worker_connections` воркера | `grep -i "worker_connections" /var/log/angie/error.log` | Увеличить `worker_connections` и `worker_rlimit_nofile`; включить `keepalive` к бэкендам |
| **Всплеск ответов 502 Bad Gateway** | Бэкенд перегружен, исчерпал `listen backlog` или упал | `ss -ti` к бэкенду; анализ логов приложения | Настроить `slow_start`, увеличить количество экземпляров приложения, ограничить `max_conns` |
| **Рост p99 latency при низком CPU (<20%)** | Задержки на дисковом I/O (синхронные логи/кэш); блокировка DNS | `iostat -xz 1`, `pidstat -d 1` | Перевести логи в `buffer=64k`, настроить `open_file_cache`, вынести кэш на NVMe/tmpfs |
| **Перекос нагрузки по ядрам CPU** | Прерывания сетевой карты сходятся на одно ядро; нет `worker_cpu_affinity` | `mpstat -P ALL 1`, `cat /proc/interrupts` | Настроить `irqbalance`, включить `worker_cpu_affinity auto;`, активировать `reuseport` |
| **Ошибки `Possible SYN flooding on port 443`** | Переполнение очереди `tcp_max_syn_backlog` | `dmesg -T \| grep -i "syn"` | Увеличить `net.ipv4.tcp_max_syn_backlog`, проверить `net.core.somaxconn` |
| **Дроп пакетов `nf_conntrack: table full`** | Таблица conntrack ядра переполнена | `conntrack -S`, `sysctl net.netfilter.nf_conntrack_count` | Увеличить `nf_conntrack_max`, перевести trusted-трафик в `NOTRACK` (raw table) |

### Пошаговые сценарии диагностики

#### Сценарий 1: Экспресс-анализ очередей и насыщенности сокетов

```bash
# 1. Проверка наличия переполненных очередей сокетов
ss -ltni | awk 'NR==1 || $2 > 0 || $3 > 0'
# → Recv-Q > 0 означает, что Angie не успевает вызывать accept() из очереди ядра
# → Send-Q > 0 на слушающем сокете показывает установленный предел somaxconn

# 2. Проверка процента утилизации CPU воркерами Angie
top -b -n 1 -H -p $(pgrep -d',' -f "angie: worker")
# → Равномерное распределение %CPU по всем потокам воркеров свидетельствует об успешной работе SO_REUSEPORT и affinity

# 3. Проверка счётчиков отброшенных пакетов сетевой карты
ethtool -S eth0 | grep -E "drop|miss|error" | head -n 10
# → rx_dropped: 0
# → rx_missed_errors: 0 (рост значений указывает на переполнение кольцевого буфера RX ring buffer)
```

#### Сценарий 2: Локализация аномального источника запросов (L7 Flood)

```bash
# Топ-10 клиентских IP по частоте запросов за последние 10 000 строк лога
tail -n 10000 /var/log/angie/access.log | awk '{print $1}' | sort | uniq -c | sort -nr | head -n 10
# →  4521 203.0.113.45   <-- Очевидный признак агрессивного сканирования/атаки
# →   312 198.51.100.12
# →   180 192.0.2.88

# Экстренная изоляция атакующего IP через nftables без перезапуска Angie
nft add element inet filter blackhole { 203.0.113.45 }
# → Правило немедленно блокирует трафик в ядре до попадания в стек Angie
```

---

## Рекомендации и лучшие практики

### Чек-лист готовности к высокой нагрузке (Production Readiness Checklist)

- [ ] **Процессы:** `worker_processes auto;` и `worker_cpu_affinity auto;` активированы.
- [ ] **Файловые лимиты:** `worker_rlimit_nofile` равен сумме соединений всех воркеров с запасом (`>= 262144`).
- [ ] **Событийная модель:** `events { worker_connections >= 32768; multi_accept on; use epoll; }`.
- [ ] **Ядро Linux:** `somaxconn` и `tcp_max_syn_backlog` увеличены до `65535`; включён алгоритм `bbr`.
- [ ] **Сетевой стек:** Включены `sendfile on;`, `tcp_nopush on;`, `tcp_nodelay on;`.
- [ ] **HTTPS:** Включен kTLS (`ssl_conf_command Options +KTLS;`), настроен `ssl_session_cache shared:SSL:64m;`.
- [ ] **HTTP/3:** Открыт порт UDP/443, включены `quic_bpf on;` и `quic_retry on;`.
- [ ] **Апстримы:** Настроен пул `keepalive 64;` (или выше), алгоритм `least_time` и `slow_start`.
- [ ] **Защита L7:** Настроены зоны `limit_req_zone` и `limit_conn_zone` с исключением белых списков через `geo/map`.
- [ ] **Логирование:** Включена буферизация логов (`buffer=64k flush=5s`) либо отключен `access_log` для статики.
- [ ] **Мониторинг:** Настроен экспорт в Prometheus (`/metrics`) и аудит через `/api/`.

### Архитектурные антипаттерны в High Load

1. **Синхронная запись логов на диск на каждый запрос:** При 50 000+ RPS синхронный `access_log` блокирует воркеры на дисковых операциях записи (I/O wait). Обязательно используйте параметры `buffer=64k flush=5s` или отправку логов по сети через rsyslog/vector.
2. **Отсутствие Keep-Alive к бэкендам:** По умолчанию proxy_pass закрывает TCP-соединение после каждого запроса (HTTP/1.0). Без директив `proxy_http_version 1.1;` и `proxy_set_header Connection "";` сервер мгновенно исчерпывает диапазон локальных портов (`ip_local_port_range`) и генерирует задержки на открытие TCP-сокетов.
3. **Завышенные клиентские таймауты:** Установка `client_header_timeout` или `client_body_timeout` более 60 секунд позволяет злоумышленникам исчерпать память и воркеры сервера с помощью нескольких сотен медленных сессий (Slowloris).
4. **Использование gzip с уровнем компрессии выше 5–6:** Сжатие gzip на уровнях 7–9 утилизирует колоссальные ресурсы CPU с приростом сжатия не более 1–2%. В современных системах стандартом является Zstandard (`zstd_comp_level 3;`).

### Процедура отката (Rollback Runbook)

Если после применения оптимизаций наблюдается деградация сервиса:

1. Немедленный возврат к резервной копии конфигурации:
   ```bash
   cp /etc/angie/angie.conf.bak /etc/angie/angie.conf
   angie -t && angie -s reload
   ```
2. В случае зависания воркеров под аномальной нагрузкой — грациозная принудительная перезагрузка:
   ```bash
   systemctl reload angie || systemctl restart angie
   ```
3. Сброс системных тюнингов sysctl при нестабильности ядра:
   ```bash
   mv /etc/sysctl.d/99-angie-highload.conf /etc/sysctl.d/99-angie-highload.conf.disabled
   sysctl --system
   ```

---

## Границы применимости и ограничения

### Ограничения Angie Open Source (OSS)

- **Очереди запросов (Queue):** В версии OSS при достижении предела соединений `max_conns` в блоке `server` апстрима запросы сбрасываются с ошибкой 502 Bad Gateway. Очередь ожидания `queue` доступна в Angie PRO.
- **Кластерный обмен состояниями (Cluster Sync):** Модуль `zone_sync` доступен только в коммерческой редакции Angie PRO. В Angie OSS счётчики `limit_req` и `limit_conn` рассчитываются изолированно на каждом сервере.
- **Дренаж соединений (Graceful Drain):** Механизм перевода сервера в состояние `drain` без сброса существующих сессий пользователей ограничен в базовой редакции.

### Ограничения протокола HTTP/3 (QUIC)

- Для работы требуется обязательное открытие порта UDP/443 на всех внешних сетевых шлюзах и хостовых фаерволах.
- Технология `quic_bpf` требует ядра Linux версии не ниже 5.7 и наличия прав `CAP_BPF` / `CAP_NET_ADMIN`.
- Некоторые корпоративные прокси-серверы и мобильные операторы принудительно блокируют или дросселируют исходящий трафик UDP/443, что требует обязательного наличия резервного протокола HTTP/2 по TCP/443.

---

## Дополнительная информация

### См. также

- [Оптимизация производительности Angie](./performance_optimization.md) — исчерпывающее руководство по детальному тюнингу сетевого стека, сжатию Zstd и кэшированию.
- [Защита от DoS-атак в Angie](./dos_protection.md) — математика Leaky Bucket, скрипты fail2ban, правила nftables и защита от HTTP/2 Rapid Reset.
- [Модуль image_filter в Angie: обзор возможностей](./image_filter/overview.md) — оптимизация и трансформация медиа-контента под нагрузкой.
- [Кэширование результатов image_filter](./image_filter/caching.md) — архитектура двухуровневого кэширования графических ресурсов.
- [Минимальная продакшен-конфигурация Angie](../angie-baseline-config.md) — стартовый базовый шаблон конфигурации веб-сервера.
- [Настройка TLS в Angie](../angie_tls_setup.md) — конфигурация сертификатов, mTLS и шифров.
- [Мониторинг Angie через Prometheus](../angie_monitoring/angie_monitoring_prometheus.md) — сбор и визуализация метрик производительности.
- [REST API мониторинга Angie](../angie_monitoring/angie_monitoring_api.md) — программное управление и аудит состояния веб-сервера.
- [Graceful Reload и Binary Upgrade в Angie](../angie-graceful-reload.md) — методология обновления бинарных файлов без простоя сервиса.
- [Динамические апстримы в Angie](../dynamic_upstreams.md) — управление серверами бэкенда через API на лету.
- [Настройка параметров ядра (sysctl)](../../../Linux/Core/kernel/sysctl.md) — руководство по системному тюнингу подсистем Linux.
- [Обзор DoS/DDoS атак](../../../Security/ApplicationSecurity/ddos_overview.md) — классификация угроз прикладного и сетевого уровней.
- [Инструменты для бенчмаркинга веб-серверов](../../webserver_benchmarking.md) — методология тестирования производительности wrk, wrk2, k6.
