# Конфигурация HTTP/2 и HTTP/3 в Nginx и Angie

**Актуально для:** Nginx 1.26+ / 1.30.x, Angie 1.7+ / 1.11+

---

## Определения

**HTTP/2 (Hypertext Transfer Protocol Version 2)** — вторая мажорная версия протокола HTTP ([RFC 9113](https://datatracker.ietf.org/doc/html/rfc9113)), использующая бинарное фреймирование и мультиплексирование потоков в рамках одного TCP-соединения со сжатием заголовков через HPACK. Подробнее об исторической эволюции протокола см. в [Эволюции протокола HTTP](../../../Networking/Protocols/HTTP/http_versions.md).

**HTTP/3 (Hypertext Transfer Protocol Version 3)** — третья мажорная версия протокола ([RFC 9114](https://datatracker.ietf.org/doc/html/rfc9114)), переносящая семантику HTTP на транспортный протокол QUIC поверх UDP для полного устранения блокировки начала очереди (Head-of-Line blocking) на транспортном уровне.

**QUIC (Quick UDP Internet Connections)** — транспортный протокол ([RFC 9000](https://datatracker.ietf.org/doc/html/rfc9000)) поверх UDP, объединяющий независимое мультиплексирование потоков, контроль потерь и перегрузок, а также встроенное шифрование TLS 1.3 ([RFC 9001](https://datatracker.ietf.org/doc/html/rfc9001)).

**HPACK (Header Compression for HTTP/2)** — алгоритм сжатия заголовков ([RFC 7541](https://datatracker.ietf.org/doc/html/rfc7541)), использующий статический и динамический таблицы-словари. Требует строго упорядоченной доставки пакетов TCP.

**QPACK (Header Compression for HTTP/3)** — алгоритм сжатия заголовков ([RFC 9204](https://datatracker.ietf.org/doc/html/rfc9204)), оптимизированный для независимых потоков QUIC. Использует раздельные однонаправленные потоки управления (Encoder/Decoder streams) для синхронизации динамической таблицы без блокировки прикладных данных.

**ALPN (Application-Layer Protocol Negotiation)** — расширение TLS ([RFC 7301](https://datatracker.ietf.org/doc/html/rfc7301)), позволяющее клиенту и серверу в рамках TLS-рукопожатия (`ClientHello` / `ServerHello`) согласовать протокол прикладного уровня (`h2`, `h3`, `http/1.1`) без дополнительных сетевых RTT.

**Head-of-Line (HoL) Blocking** — задержка обработки пакетов в очереди из-за ожидания потерянного или медленно обрабатываемого предшествующего пакета. В HTTP/1.1 возникает на уровне HTTP-запросов; в HTTP/2 устранена на уровне HTTP, но сохраняется на уровне TCP; в HTTP/3 полностью устранена на уровне транспорта благодаря независимой изоляции потоков в QUIC.

**0-RTT (Zero Round Trip Time / Early Data)** — механизм возобновления TLS 1.3 / QUIC сессии, при котором клиент отправляет зашифрованные прикладные данные в первом же сетевом пакете вместе с запросом на подключение. Устраняет задержку рукопожатия, но делает сервер уязвимым к атакам повторного воспроизведения (Replay Attacks).

**Alt-Svc (Alternative Services)** — HTTP-заголовок ответа сервера ([RFC 7838](https://datatracker.ietf.org/doc/html/rfc7838)), информирующий клиента о наличии альтернативного протокола или сетевого адреса (например, доступности HTTP/3 на UDP-порту 443).

**`quic_bpf`** — механизм ядра Linux (`SO_ATTACH_REUSEPORT_CBPF` / `SO_ATTACH_REUSEPORT_EBPF`), загружающий программу eBPF в группу сокетов `reuseport`. Позволяет ядру маршрутизировать входящие UDP-датаграммы QUIC по идентификатору соединения (Connection ID) строго на тот рабочий процесс Nginx, который создал сессию, предотвращая сброс соединений при `nginx -s reload`.

**`quic_gso` (Generic Segmentation Offload для UDP)** — механизм сетевого стека Linux, позволяющий Nginx передавать в ядро пачки UDP-датаграмм размером до 64 КБ одним системным вызовом `sendmsg()`, делегируя сегментацию на уровень сетевого адаптера (NIC).

**Connection Coalescing** — механизм HTTP/2 и HTTP/3, позволяющий клиенту повторно использовать открытое TLS-соединение для отправки запросов к разным доменным именам, если они разрешаются в один IP-адрес и покрываются одним TLS-сертификатом (через SAN).

**HTTP/2 Rapid Reset (CVE-2023-44487)** — класс DoS-атак на реализации HTTP/2, при котором атакующий массово открывает мультиплексированные потоки (`HEADERS`) и мгновенно отменяет их (`RST_STREAM`), перегружая CPU сервера обработкой создания и уничтожения контекста запросов.

---

## Основные концепции

### Модульная архитектура обработки в Nginx и Angie

Обработка протоколов нового поколения в Nginx и Angie построена на связке специализированных модулей:

```
[Клиентский трафик]
       │
       ├── TCP :443 ──► [ngx_http_ssl_module (TLS 1.2 / 1.3)]
       │                      │
       │                      ├── ALPN "h2" ──────► [ngx_http_v2_module (HPACK, Streams)]
       │                      └── ALPN "http/1.1" ─► [HTTP/1.1 Core Pipeline]
       │
       └── UDP :443 ──► [SO_REUSEPORT + eBPF (quic_bpf)]
                              │
                              └──► [ngx_http_v3_module (QUIC transport, QPACK, TLS 1.3)]
                                     │
                                     └──► [HTTP Core Pipeline] ──► [Upstream / Static / FastCGI]
```

1. **`ngx_http_v2_module`**:
   - Включается директивой `http2 on;` в блоках `http` или `server` (начиная с Nginx 1.25.1 параметр `listen ... http2;` объявлен устаревшим).
   - Управляет парсингом бинарных фреймов, сборкой потоков, сжатием заголовков через HPACK и управлением окном передачи (Flow Control).
   - Включает встроенные защитные механизмы от HTTP/2 DoS и Rapid Reset.
2. **`ngx_http_v3_module`**:
   - Реализует транспортный уровень QUIC и прикладной слой HTTP/3.
   - В Nginx Open Source компилируется при сборке с флагом `--with-http_v3_module` и требует криптографическую библиотеку с поддержкой QUIC API (OpenSSL 3.2+, BoringSSL, QuicTLS или LibreSSL).
   - В Angie модуль встроен нативно во все стандартные сборки, начиная с Angie 1.1+.
   - Обеспечивает работу QPACK, обработку Connection ID, миграцию соединений и шифрование через TLS 1.3.
3. **`ngx_http_ssl_module`**:
   - Управляет TLS-контекстом, сертификатами X.509 и согласованием ALPN для TCP-соединений. Для QUIC библиотека TLS встроена в транспортный протокол, но сертификаты и политики шифрования конфигурируются через стандартные директивы `ssl_*`.

### Сравнительный анализ транспортных уровней

| Характеристика | HTTP/1.1 | HTTP/2 | HTTP/3 (QUIC) |
| :--- | :--- | :--- | :--- |
| **Транспортный протокол** | TCP | TCP | UDP (QUIC) |
| **Формат сообщений** | Текстовый | Бинарные фреймы | Бинарные фреймы |
| **Мультиплексирование** | Нет (1 запрос = 1 TCP) | Да (несколько потоков в 1 TCP) | Да (независимые потоки в UDP) |
| **HoL Blocking на транспорте** | Да (на уровне соединения) | Да (потеря 1 TCP-пакета тормозит все потоки) | **Устранена** (потеря пакета тормозит только свой поток) |
| **Сжатие заголовков** | Нет | HPACK (последовательный словарь) | QPACK (неблокирующий словарь) |
| **Задержка Handshake (Cold)** | 2 RTT (1 TCP + 1 TLS 1.3) | 2 RTT (1 TCP + 1 TLS 1.3) | **1 RTT** (совмещенный QUIC + TLS 1.3) |
| **Повторное подключение** | 1 RTT | 1 RTT | **0-RTT** (Early Data) |
| **Миграция соединения (IP/Port)** | Обрыв сессии | Обрыв сессии | **Бесшовная миграция** (по Connection ID) |
| **Шифрование** | Опционально | Де-факто обязательно (в браузерах) | **Строго обязательно** (TLS 1.3 встроен в QUIC) |

### Механика работы QUIC и многопроцессная модель Nginx

Nginx функционирует по архитектуре независимых рабочих процессов (worker processes). В случае стандартного TCP ядро Linux распределяет входящие SYN-пакеты через `SO_REUSEPORT`. В случае UDP/QUIC возникает критическая проблема: протокол не имеет состояния соединения в ядре ОС. Клиентские пакеты идентифицируются не 4-tuple (IP клиента, порт клиента, IP сервера, порт сервера), а **Connection ID (CID)** в заголовке пакета QUIC.

Когда клиент переключает сеть (например, Wi-Fi на LTE), его IP и порт меняются, но Connection ID сохраняется. Если ядро Linux использует стандартное хеширование по 4-tuple, новый пакет с измененного IP попадет на *другой* рабочий процесс Nginx, что вызовет ошибку и сброс сессии.

```
[QUIC пакет от клиента]
       │
       ▼
 [Ядро Linux: SO_REUSEPORT]
       │
       ├── Без eBPF (хэш 4-tuple):
       │      Пакет с нового IP ──► Воркер B (сессия неизвестна) ──► Сброс / Stateless Reset
       │
       └── С quic_bpf (eBPF программа):
              Анализ CID в пакете ──► Воркер A (владелец сессии) ──► Корректная обработка
```

**Решение проблемы:**
1. Директива `listen 443 quic reuseport;` создает сокеты с флагом `SO_REUSEPORT` для каждого воркера.
2. Директива `quic_bpf on;` (в блоке `events`) загружает в ядро Linux программу eBPF. Она парсит входящий QUIC-пакет, извлекает Connection ID и направляет пакет именно тому воркеру, который изначально создал сессию. При перезагрузке конфигурации (`nginx -s reload`) старые сессии дорабатывают на старых воркерах без обрывов.

### Матрица поддержки возможностей: Nginx Open Source vs Angie

| Функция | Nginx Open Source (1.26 / 1.30) | Angie (1.7+ / 1.11+) |
| :--- | :--- | :--- |
| **HTTP/2 Client-side** | Поддерживается (`http2 on;`) | Поддерживается (`http2 on;`) |
| **HTTP/3 Client-side** | Требует сборки с OpenSSL 3.2+ / QuicTLS | Встроен «из коробки» во все бинарные пакеты |
| **Upstream HTTP/2** | Только gRPC (`grpc_pass`) | Полная поддержка HTTP/2 к бэкендам (`proxy_http_version 2;`) |
| **Upstream HTTP/3** | Не поддерживается | Полная поддержка HTTP/3 к бэкендам (`proxy_http_version 3;`) |
| **eBPF CID Routing (`quic_bpf`)** | Поддерживается (Linux 5.7+) | Поддерживается (Linux 5.7+) |
| **UDP GSO (`quic_gso`)** | Поддерживается | Поддерживается |
| **Метрики HTTP/2 и HTTP/3** | Только через `log_format` и `$server_protocol` | Детальная статистика в модуле `status_zone` и REST API |

---

## Практические сценарии

### Предварительные требования (Linux SRE / Sysadmin)

Перед настройкой HTTP/2 и HTTP/3 на выделенном сервере или виртуальной машине Linux выполните подготовку сетевого стека и фаервола.

#### 1. Тюнинг параметров ядра Linux (sysctl)

QUIC оперирует высокоскоростным UDP. Стандартные системные буферы приема и отправки UDP в Linux недостаточны для высоких нагрузок и вызывают потерю пакетов на уровне сокета (`netstat -s | grep "buffer errors"`).

Создайте файл `/etc/sysctl.d/99-quic.conf`:

```ini
# Максимальный размер буферов сокетов (16 МБ)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# Значения по умолчанию для буферов сокетов
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576

# Минимальные и максимальные буферы UDP в страницах памяти (min, default, max)
net.ipv4.udp_rmem_min = 16384
net.ipv4.udp_wmem_min = 16384

# Длина очереди входящих пакетов сетевой карты
net.core.netdev_max_backlog = 10000

# Таймауты conntrack для UDP сессий (предотвращает разрыв сессий QUIC stateful-фаерволом)
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 120
```

Примените параметры:
```bash
sudo sysctl -p /etc/sysctl.d/99-quic.conf
# → net.core.rmem_max = 16777216
# → net.core.wmem_max = 16777216
# → net.core.netdev_max_backlog = 10000
```

Подробнее о системном тюнинге см. в [Тюнинге параметров ядра (sysctl)](../../../Linux/Core/kernel/sysctl.md) и [Оптимизации TCP в Linux](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md).

#### 2. Настройка Firewall (nftables / iptables)

Необходимо открыть порт 443 по TCP и UDP, а также разрешить сообщения ICMP Type 3 Code 4 (Destination Unreachable, Fragmentation Needed) для корректной работы Path MTU Discovery:

```bash
# nftables: добавление правил в существующую цепочку input
sudo nft add rule inet filter input tcp dport 443 ct state new,established accept
sudo nft add rule inet filter input udp dport 443 ct state new,established accept
sudo nft add rule inet filter input ip icmp type destination-unreachable accept
sudo nft add rule inet filter input ip6 icmpv6 type packet-too-big accept

# iptables: классический синтаксис
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 443 -j ACCEPT
sudo iptables -A INPUT -p icmp --icmp-type destination-unreachable -j ACCEPT
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type packet-too-big -j ACCEPT
```

---

### Сценарий 1: Базовая оптимизированная конфигурация HTTP/2

Используется для веб-сайтов и защищенных API, работающих поверх TCP.

```nginx
# /etc/nginx/conf.d/example_http2.conf

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name example.com;

    # Включение HTTP/2 (современный синтаксис Nginx 1.25.1+ и Angie)
    http2 on;

    # Сертификаты TLS
    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    # Рекомендуемый базовый набор протоколов и шифров для HTTP/2
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Параметры оптимизации и защиты от DoS (HTTP/2 Rapid Reset)
    http2_max_concurrent_streams 128;   # Ограничение параллельных потоков на соединение
    http2_max_requests 10000;           # Максимум запросов в рамках одного TCP-соединения
    http2_recv_buffer_size 512k;        # Буфер приема фреймов
    http2_body_preread_size 64k;        # Буфер предварительного чтения тела запроса

    # Отключение устаревшего Server Push (удален из современных браузеров)
    http2_push off;

    location / {
        root /var/www/example;
        index index.html;
    }
}
```

---

### Сценарий 2: Полнофункциональная конфигурация Dual-Stack HTTP/2 и HTTP/3 (QUIC)

Эталонная конфигурация для публичных высоконагруженных сервисов. Обеспечивает одновременную работу HTTP/1.1, HTTP/2 по TCP и HTTP/3 по UDP.

#### Глобальная конфигурация (`/etc/nginx/nginx.conf`)

```nginx
user www-data;
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 8192;
    use epoll;

    # Активация eBPF-маршрутизации QUIC по Connection ID к воркерам
    # Требует Linux 5.7+ и прав root/CAP_SYS_ADMIN при старте master-процесса
    quic_bpf on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Формат логирования с фиксацией протокола, ALPN и 0-RTT
    log_format quic_combined '$remote_addr - $remote_user [$time_local] '
                            '"$request" $status $body_bytes_sent '
                            '"$http_referer" "$http_user_agent" '
                            'proto=$server_protocol alpn=$ssl_alpn_protocol '
                            'early_data=$ssl_early_data bytes_in=$request_length';

    access_log /var/log/nginx/access.log quic_combined;
    error_log  /var/log/nginx/error.log warn;

    include /etc/nginx/conf.d/*.conf;
}
```

#### Конфигурация виртуального хоста (`/etc/nginx/conf.d/example_dual_stack.conf`)

```nginx
server {
    # 1. TCP-слушатели для HTTP/1.1 и HTTP/2
    listen 443 ssl;
    listen [::]:443 ssl;

    # 2. UDP-слушатели для HTTP/3 (QUIC)
    # Параметр reuseport обязателен на первой директиве listen для данного порта/IP!
    listen 443 quic reuseport;
    listen [::]:443 quic reuseport;

    server_name example.com;

    # Включение протоколов
    http2 on;
    http3 on;

    # Анонсирование поддержки HTTP/3 браузерам через заголовок Alt-Svc
    # ma=86400 указывает клиенту кэшировать маршрут h3 на 24 часа
    # Флаг always гарантирует отправку заголовка даже на кодах ошибок (4xx/5xx)
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # Оптимизация сетевой передачи QUIC
    quic_gso on;           # Включение Generic Segmentation Offload для UDP
    quic_retry on;         # Защита от UDP-амплификации (валидация адреса через Retry-пакет)

    # Настройки TLS (общие для TCP и UDP)
    ssl_certificate     /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    # Для QUIC обязателен TLSv1.3
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    # Контроль 0-RTT (Early Data)
    # По умолчанию выключено во избежание Replay-атак на бэкенд
    ssl_early_data off;

    # Лимиты HTTP/3
    http3_max_concurrent_streams 128;
    http3_stream_buffer_size 256k;

    location / {
        root /var/www/example;
        index index.html;
    }

    # Безопасное использование 0-RTT только для идемпотентных запросов (если early_data включен)
    location /api/read/ {
        # Защита бэкенда от replay-атак: передача статуса в заголовке
        proxy_set_header Early-Data $ssl_early_data;
        proxy_pass http://backend_cluster;
    }
}
```

---

### Сценарий 3: Внутренний HTTP/2 без шифрования (h2c) для микросервисов

В изолированных защищенных периметрах ЦОД (между фронт-прокси и микросервисами или gRPC-демонами) допустимо использовать чистый HTTP/2 без накладных расходов на TLS:

```nginx
# /etc/nginx/conf.d/internal_h2c.conf

server {
    listen 8080;
    server_name internal.local;

    # Включение HTTP/2 на открытом порту без директивы ssl
    http2 on;

    location /grpc.Service/ {
        # Стандартное проксирование gRPC (использует HTTP/2)
        grpc_pass grpc://10.0.10.25:50051;
        grpc_read_timeout 60s;
        grpc_send_timeout 60s;
    }
}
```

---

### Сценарий 4: Проксирование к апстримам по HTTP/2 и HTTP/3 (Angie)

В стандартном Nginx Open Source директива `proxy_pass` поддерживает только протоколы `HTTP/1.0` и `HTTP/1.1`. Если требуется передавать трафик к бэкендам по HTTP/2 или HTTP/3, используется Angie:

```nginx
# Конфигурация в Angie (версии 1.7+ для h2, 1.11+ для h3)

upstream backend_pool {
    server 10.0.20.10:443;
    server 10.0.20.11:443;
    keepalive 64;
}

server {
    listen 443 ssl;
    server_name gateway.example.local;

    ssl_certificate /etc/ssl/certs/gateway.crt;
    ssl_certificate_key /etc/ssl/private/gateway.key;

    # Проксирование к микросервисам по HTTP/2
    location /api/v2/ {
        proxy_http_version 2;
        proxy_pass https://backend_pool;
        proxy_set_header Host $host;
    }

    # Проксирование к удаленному ЦОД по HTTP/3 через ненадежный канал
    location /cross-dc/ {
        proxy_http_version 3;
        proxy_pass https://backend_pool;
        proxy_set_header Host $host;
        quic_gso on;
    }
}
```

---

## Операции и команды

### Валидация сборки и конфигурации

Проверка наличия необходимых модулей и корректности параметров перед запуском:

```bash
# 1. Проверка поддержки модулей HTTP/2 и HTTP/3 в бинарном файле Nginx
nginx -V 2>&1 | grep -oE "http_v2_module|http_v3_module|built with OpenSSL [0-9.]+"
# → http_v2_module
# → http_v3_module
# → built with OpenSSL 3.2.1

# 2. Тестирование синтаксиса конфигурационных файлов
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 3. Бесшовная перезагрузка конфигурации
sudo nginx -s reload
# → (код возврата 0, воркеры перезапущены без разрыва сессий)
```

### Диагностика сетевых сокетов и портов

```bash
# Проверка прослушивания TCP порта 443 (HTTP/1.1 и HTTP/2)
ss -tlpn '( sport = :443 )'
# → LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=24101,fd=6),("nginx",pid=24102,fd=6))

# Проверка прослушивания UDP порта 443 (HTTP/3 / QUIC)
ss -ulpn '( sport = :443 )'
# → UNCONN 0 0 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=24101,fd=8),("nginx",pid=24102,fd=8))

# Проверка аппаратной разгрузки UDP GSO на сетевом интерфейсе
ethtool -k eth0 | grep udp-segmentation-offload
# → tx-udp-segmentation: on [fixed]
```

### Проверка согласования протоколов клиентами

```bash
# 1. Проверка ALPN для HTTP/2 через OpenSSL
openssl s_client -connect example.com:443 -alpn h2 -servername example.com -brief
# → ALPN protocol: h2
# → Verification: OK

# 2. Проверка HTTP/2 через curl
curl -Iv --http2 https://example.com/ 2>&1 | grep -E "ALPN|HTTP/"
# → * ALPN: offers h2,http/1.1
# → * ALPN: server accepted h2
# → < HTTP/2 200

# 3. Проверка обнаружения заголовка Alt-Svc через curl
curl -sI https://example.com/ | grep -i alt-svc
# → alt-svc: h3=":443"; ma=86400

# 4. Проверка подключения напрямую по HTTP/3 через curl (требует curl с поддержкой quiche/ngtcp2)
curl -Iv --http3 https://example.com/ 2>&1 | grep -E "Connected to|HTTP/"
# → * Connected to example.com (198.51.100.10) port 443
# → < HTTP/3 200

# 5. Проверка ALPN для HTTP/3 через OpenSSL (требует OpenSSL 3.2+)
openssl s_client -connect example.com:443 -alpn h3 -servername example.com -brief
# → ALPN protocol: h3
```

### Нагрузочное тестирование протоколов

Для бенчмаркинга и проверки устойчивости к нагрузкам на Linux-сервере:

```bash
# Тестирование HTTP/2 с мультиплексированием 100 потоков через h2load
h2load -n 100000 -c 100 -m 50 https://example.com/
# → finished in 1.42s, 70422.53 req/s, 1.25GB/s
# → requests: 100000 total, 100000 started, 100000 done, 100000 succeeded, 0 failed, 0 errored

# Стресс-тест HTTP/3 через hey (с поддержкой QUIC)
hey -n 10000 -c 50 --http3 https://example.com/
# → Summary:
# → Total: 0.8921 secs
# → Requests/sec: 11209.45
```

---

## Устранение неполадок

### 1. HTTP/2 не согласовывается (клиент откатывается на HTTP/1.1)

**Симптомы:** Запрос `curl -I --http2 https://example.com` возвращает `HTTP/1.1 200`, а в логах `$server_protocol` фиксируется как `HTTP/1.1`.

**Причины и решение:**
1. **Использование устаревшего синтаксиса:** Проверьте конфигурацию. В Nginx 1.25.1+ указание `listen 443 ssl http2;` вместо директивы `http2 on;` в определенных комбинациях с `default_server` приводит к игнорированию HTTP/2. Замените на:
   ```nginx
   listen 443 ssl;
   http2 on;
   ```
2. **Несовместимый набор TLS-шифров:** Спецификация RFC 9113 запрещает использование шифров из «черного списка» (например, CBC-режимы, RSA key exchange). Если в `ssl_ciphers` явно заданы устаревшие шифры, ALPN отклоняет `h2`. Убедитесь, что используются современные GCM или ChaCha20 шифры.
3. **Отсутствие поддержки ALPN в OpenSSL:** Если Nginx собран со старой версией OpenSSL (< 1.1.1), ALPN не поддерживается. Проверьте вывод `nginx -V`.

---

### 2. HTTP/3 недоступен (таймаут соединения по UDP)

**Симптомы:** `curl --http3` выдает ошибку `Failed to connect to ... port 443: Connection timed out` или `QUIC handshake timeout`.

**Причины и решение:**
1. **Порт UDP 443 заблокирован:** Проверьте системный фаервол и внешние маршрутизаторы:
   ```bash
   sudo iptables -L -n -v | grep 443
   sudo nft list ruleset | grep 443
   ```
   Добавьте разрешающее правило для входящего UDP-трафика.
2. **Отсутствие параметра `reuseport`:** Если у Nginx настроено несколько воркеров (`worker_processes > 1`), отсутствие флага `reuseport` на сокете `listen 443 quic` приведет к тому, что пакеты одной сессии будут отбрасываться другими процессами. Обязательно укажите:
   ```nginx
   listen 443 quic reuseport;
   ```
3. **Разрыв сессий при reload из-за отсутствия eBPF:** Если `quic_bpf on;` не включен или ядро Linux старше 5.7, любая перезагрузка Nginx приводит к потере CID-маршрутизации и мгновенному обрыву всех активных клиентов HTTP/3.

---

### 3. Ошибка конфигурации «quic_bpf directive is not allowed here»

**Симптомы:** Команда `nginx -t` завершается с ошибкой:
`nginx: [emerg] "quic_bpf" directive is not allowed here in /etc/nginx/nginx.conf:XX`

**Причина:** Директива `quic_bpf` относится к механизмам цикла обработки событий и сокетов. Она допустима **только в контексте `events {}`**. Размещение её в контексте `main` или `http` является синтаксической ошибкой.

**Решение:** Перенесите директиву в блок `events`:
```nginx
events {
    worker_connections 4096;
    quic_bpf on;
}
```

---

### 4. Браузер не переключается на HTTP/3 (Alt-Svc игнорируется)

**Симптомы:** Веб-сервер работает корректно, но браузеры продолжают обращаться только по HTTP/2.

**Причины и решение:**
1. **Первый визит всегда идет по TCP:** Браузер не может знать о наличии HTTP/3 заранее. Первое подключение всегда выполняется по TCP/TLS. Клиент считывает заголовок `Alt-Svc` и сохраняет его в кэше, пытаясь подключиться по HTTP/3 только со второго запроса.
2. **Отсутствие флага `always` в директиве `add_header`:** Если страница или API вернули код 404, 500 или 301, Nginx по умолчанию не отправляет заголовки, добавленные через `add_header`, если не указан флаг `always`:
   ```nginx
   add_header Alt-Svc 'h3=":443"; ma=86400' always;
   ```
3. **Проброс портов (Port Mapping / NAT):** Если внешний порт маршрутизатора отличается от внутреннего порта Nginx (например, наружу выставлен порт 8443, а Nginx слушает 443), заголовок `h3=":443"` заставит браузер стучаться в закрытый порт. В этом случае указывайте внешний порт: `add_header Alt-Svc 'h3=":8443"; ma=86400' always;`.

---

### 5. Ошибка 421 Misdirected Request

**Симптомы:** Клиент при обращении к сайту внезапно получает ошибку `421 Misdirected Request`.

**Причина:** Эффект **Connection Coalescing**. Если у вас на одном IP-адресе хостятся сайты `a.example.com` и `b.example.com`, и оба домена включены в один wildcard/SAN сертификат, браузер отправляет запрос к `b.example.com` через уже открытое HTTP/2 или HTTP/3 соединение от `a.example.com`. Если блок `server` для `b.example.com` не сконфигурирован для обслуживания этого порта/сертификата, Nginx возвращает код 421.

**Решение:**
1. Убедитесь, что все виртуальные хосты, входящие в общий сертификат, имеют идентичные директивы `listen 443 ssl;` и `http2 on;`.
2. Если требуется строго изолировать трафик разных сервисов, разнесите их на разные IP-адреса либо используйте раздельные TLS-сертификаты без пересекающихся имен SAN.

---

### 6. DoS-атаки HTTP/2 Rapid Reset (CVE-2023-44487) и утечка памяти

**Симптомы:** Резкий всплеск утилизации CPU (100% на всех worker-процессах), исчерпание пула свободных соединений при относительно небольшом объеме входящего сетевого трафика.

**Диагностика и решение:**
1. Обновите Nginx до стабильной версии (>= 1.25.3 / 1.26.x), где введен встроенный rate-limiting на обработку фреймов `RST_STREAM`.
2. Ограничьте число параллельных потоков и объем предварительного чтения:
   ```nginx
   http2_max_concurrent_streams 64; # Снижение со стандартных 128
   http2_recv_buffer_size 256k;
   ```
3. Используйте модуль `limit_req` для ограничения частоты запросов с одного IP:
   ```nginx
   limit_req_zone $binary_remote_addr zone=req_limit_per_ip:10m rate=50r/s;
   server {
       limit_req zone=req_limit_per_ip burst=100 nodelay;
   }
   ```

---

### 7. Риски Replay-атак при использовании 0-RTT (Early Data)

**Симптомы:** Повторные списания баланса, дублирование заказов или сообщений в базе данных при нестабильном мобильном интернете у клиентов.

**Причина:** Злоумышленник перехватывает первый пакет QUIC/TLS 1.3 с полезной нагрузкой (Early Data) и отправляет его копию на сервер спустя некоторое время. Сервер воспринимает его как валидный 0-RTT запрос.

**Решение:**
1. Держите `ssl_early_data off;` глобально.
2. Если 0-RTT необходим для скорости загрузки статических ресурсов, разрешайте его строго для безопасных методов:
   ```nginx
   # Передача статуса Early Data бэкенду
   proxy_set_header Early-Data $ssl_early_data;

   # Запрет неидемпотентных методов в Early Data
   if ($ssl_early_data) {
       set $early_post "";
   }
   if ($request_method = POST) {
       set $early_post "1";
   }
   if ($early_post = "1") {
       return 425; # 425 Too Early: клиент обязан повторить запрос после TLS Handshake
   }
   ```

---

### 8. Зависание передачи больших файлов в HTTP/3 (PMTU Blackholing)

**Симптомы:** Мелкие запросы по HTTP/3 проходят успешно, но скачивание тяжелых файлов или загрузка POST-данных зависает без завершения.

**Причина:** Минимальный размер UDP-пакета Initial в QUIC составляет 1200 байт. Однако при передаче данных размер пакета стремится к размеру Path MTU (обычно 1500 байт). Если на промежуточном маршрутизаторе MTU меньше (например, туннель GRE, WireGuard, PPPoE с MTU 1420), а пакеты ICMP Type 3 Code 4 («Fragmentation Needed») заблокированы фаерволом, клиент и сервер не могут согласовать уменьшение размера датаграммы.

**Решение:**
1. Разрешите прохождение ICMP type 3 code 4 на всех сетевых экранах.
2. Проверьте MTU сетевого интерфейса сервера:
   ```bash
   ip link show eth0
   ```
3. Если сервер находится за туннелем с заниженным MTU, включите адаптацию MSS/MTU на уровне маршрутизатора.

---

## Лучшие практики

### Безопасность

1. **Строгое отключение 0-RTT для API с мутирующими операциями:** Не используйте `ssl_early_data on;` в блоках, обрабатывающих вызовы `POST`, `PUT`, `DELETE` или авторизацию.
2. **Включение валидации адресов через `quic_retry on;`:** Обязательно для публичных серверов во избежание участия вашего Nginx в сценариях отраженного UDP-флуда (DDoS Amplification).
3. **Защита от исчерпания ресурсов соединения:** Всегда ограничивайте `http2_max_concurrent_streams` (рекомендуется `64`–`128`) и `http2_max_requests` (`1000`–`10000`).
4. **Контроль устаревших функций:** Убедитесь, что `http2_push off;` отключен. Технология Server Push признана антипаттерном из-за неэффективного использования кэша и удалена из современных браузеров.

### Эксплуатация и SRE-производительность

1. **Использование `quic_bpf on;` в блоке `events`:** Критично для продуктивных систем на Linux с ядром 5.7+. Без этой директивы каждый `nginx -s reload` в процессе выкатки новой конфигурации обрывает клиентские сессии HTTP/3.
2. **Включение Generic Segmentation Offload (`quic_gso on;`):** Разгружает центральный процессор, агрегируя отправку пакетов UDP и минимизируя системные вызовы ядра.
3. **Синхронизация буферов UDP:** Буферы `net.core.rmem_max` и `net.core.wmem_max` должны составлять не менее 8–16 МБ на узлах с трафиком от 1 Гбит/с.
4. **Настройка заголовка `Alt-Svc`:** Задавайте время жизни `ma=86400` (24 часа) или `ma=604800` (7 дней). Всегда добавляйте атрибут `always`, чтобы заголовок отдавался при любых ответах.

### Архитектурные рекомендации по выбору протоколов

| Зона инфраструктуры | Рекомендуемый протокол | Обоснование |
| :--- | :--- | :--- |
| **Edge / Public Web (Клиент ──► Nginx)** | **HTTP/2 + HTTP/3 (Dual-Stack)** | HTTP/3 дает максимальную скорость на мобильных устройствах с нестабильной связью; HTTP/2 обеспечивает fallback для корпоративных сетей с закрытым UDP |
| **Internal RPC (Nginx ──► Микросервисы)** | **HTTP/2 (h2c) или gRPC** | Высокая пропускная способность за счет мультиплексирования без лишних затрат CPU на шифрование TLS внутри защищенного контура |
| **Edge ──► Backend (Nginx ──► Upstream)** | **HTTP/1.1 с пулом `keepalive`** | Стандартный baseline для Nginx Open Source. Исключает накладные расходы на постоянный handshake |
| **Межкластерный транспорт (Cross-DC)** | **HTTP/3 (в Angie)** | Устойчивость к сетевым потерям (loss-tolerant) и минимизация задержек между удаленными географическими площадками |

---

## Дополнительная информация

### Связанные документы

* [Эволюция протокола HTTP](../../../Networking/Protocols/HTTP/http_versions.md) — фундаментальные спецификации RFC, архитектура кадров и семантика HTTP/1.1, HTTP/2 и HTTP/3.
* [Оптимизация TLS в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md) — детальная настройка TLS 1.3, генерация цепочек сертификатов и защита шифров.
* [Конфигурация виртуальных хостов TLS](../Security/TLS_SSL/nginx_tls_virtual_host_config.md) — шаблоны серверов для SNI, редиректы и валидация конфигурации.
* [Тюнинг производительности Nginx](nginx_performance_tuning.md) — системные аспекты оптимизации воркеров, Zero-Copy и kTLS.
* [Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md) — методология локализации сбоев и runbook-инструкции для инженеров.
* [Тюнинг параметров ядра Linux (sysctl)](../../../Linux/Core/kernel/sysctl.md) — системные лимиты сокетов и дескрипторов файлов.
* [Оптимизация TCP в Linux](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md) — стек TCP, алгоритмы BBR и очередей qdisc.
* [Обзор Angie](../../Angie/angie_overview.md) — архитектура форка, поддержка upstream HTTP/2 и HTTP/3, расширенные метрики.

### Диагностика и мониторинг в контуре SRE

1. **Анализ логов распределения трафика:**
   Используйте переменные `$server_protocol` и `$ssl_alpn_protocol` для расчета процента adoption HTTP/3:
   ```bash
   awk '{print $11}' /var/log/nginx/access.log | sort | uniq -c | sort -nr
   # → 65420 proto=HTTP/3.0
   # → 31200 proto=HTTP/2.0
   # →  3400 proto=HTTP/1.1
   ```
2. **Анализ трафика через `tcpdump`:**
   Для перехвата и отладки QUIC-пакетов на интерфейсе:
   ```bash
   sudo tcpdump -i eth0 -n -s 0 'udp port 443' -c 10
   # → 13:45:01.123456 IP 198.51.100.50.54321 > 192.0.2.1.443: UDP, length 1252
   ```
3. **Метрики в Angie:**
   В Angie статистика по протоколам доступна через встроенную зону общего доступа:
   ```nginx
   status_zone http_traffic;
   ```
   Метрики экспортируются в Prometheus через встроенный модуль или эндпоинт `/status/` в формате JSON.
