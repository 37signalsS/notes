# Балансировка и проксирование L4-трафика (TCP/UDP) в Nginx

**Актуально для:** Nginx 1.26+ (OSS/Plus) / 1.28+ (Mainline), Angie 1.6+ / 1.12.x

## Определения

**Модуль `stream` в Nginx** — подсистема Nginx (`ngx_stream_core_module`), обеспечивающая проксирование и балансировку сетевой нагрузки на транспортном уровне (L4 модели OSI). Модуль обрабатывает сырые TCP-соединения и UDP-датаграммы без декодирования прикладных протоколов, что позволяет обслуживать реляционные и NoSQL СУБД (PostgreSQL, MySQL, Redis), брокеры сообщений (RabbitMQ, Apache Kafka), службы каталогов (LDAP), DNS-серверы, SSH-бастионы и почтовые сервисы.

**L4 (Transport Layer) проксирование** — метод трансляции сетевого трафика, при котором балансировщик принимает решения о маршрутизации исключительно на основе сетевых заголовков (IP-адреса источника и назначения, TCP/UDP-порты), а также метаданных рукопожатия TLS (SNI/ALPN при использовании механизма Pre-read). Полезная нагрузка сессии пересылается между сокетами клиента и бэкенда в неизменном виде.

**L7 (Application Layer) проксирование** — метод обработки трафика (реализованный в блоке `http`), при котором сервер полностью разбирает прикладной протокол (HTTP/1.1, HTTP/2, HTTP/3, gRPC, WebSocket), анализирует URI, заголовки, куки и тело запроса. Подробнее: [Обзор и концепции балансировки](./Load_Balancing/overview_concepts.md).

**SNI (Server Name Indication)** — расширение протокола TLS, позволяющее клиенту передавать имя целевого хоста в открытом виде на этапе рукопожатия (`Client Hello`). Начиная с Nginx 1.25.5, блок `stream` поддерживает виртуальные серверы через директиву `server_name` для нативной маршрутизации TCP-сессий по SNI.

**SSL/TLS Pre-read (`ssl_preread`)** — механизм анализа первых байтов входящего TCP-соединения (`Client Hello`) модулем `ngx_stream_ssl_preread_module` без терминации шифрования и без владения приватным ключом. Позволяет извлекать имя хоста SNI (`$ssl_preread_server_name`), поддерживаемые версии протоколов (`$ssl_preread_protocol`) и список ALPN (`$ssl_preread_alpn_protocols`).

**PROXY Protocol (v1 / v2)** — сетевой протокол (разработанный HAProxy), позволяющий передавать метаданные исходного клиентского подключения (реальный IP-клиента, клиентский порт, IP-балансировщика) внутри специального префиксного заголовка в начале TCP-потока. Подробнее: [Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md).

**Прозрачное проксирование (`transparent`)** — режим работы (`proxy_bind ... transparent`), при котором исходящее соединение к бэкенду открывается с исходным IP-адресом клиента в качестве IP-отправителя. Требует прав ядра `CAP_NET_ADMIN`, поддержки TPROXY в сетевом стеке Linux и особой маршрутизации ответных пакетов. Подробнее: [Прозрачное проксирование в Linux](../../../Networking/Concepts/nat/transparent_proxy.md).

**Upstream-пул (L4)** — именованная группа целевых серверов в контексте `stream`, между которыми распределяются входящие TCP/UDP-сессии на основе алгоритмов балансировки и механизмов контроля доступности (`max_fails`, `fail_timeout`).

**Зона разделяемой памяти (`zone`)** — сегмент оперативной памяти, доступный всем рабочим процессам (`worker processes`) Nginx. Хранит конфигурацию группы и динамическое состояние серверов (счетчики активных соединений, веса, статусы доступности). Необходима для корректной работы алгоритма `least_conn` в многопроцессной архитектуре.

**Модуль `ngx_stream_pass_module`** — модуль Nginx (появился в версии 1.25.5), позволяющий передавать входящее соединение из контекста `stream` напрямую в слушающий сокет другого блока (например, `http`) внутри того же экземпляра Nginx без оверхеда сетевого стека.

---

## Основные концепции и архитектура

### Сравнение L4 и L7 проксирования

| Характеристика | L4 (Модуль `stream`) | L7 (Модуль `http`) |
| :--- | :--- | :--- |
| **Уровень модели OSI** | Layer 4 (Транспортный: TCP, UDP) | Layer 7 (Прикладной: HTTP, HTTPS, gRPC, WebSocket) |
| **Единица обработки** | Байтовый поток (TCP) или датаграмма (UDP) | Дискретный запрос (Request) и ответ (Response) |
| **Инспекция содержимого** | Отсутствует (кроме TLS SNI/ALPN при Pre-read) | Полный синтаксический анализ структуры заголовков, URI, Cookies и тела |
| **Накладные расходы CPU/RAM** | Минимальные (потоковая трансляция через сокетные буферы ядра) | Существенные (выделение памяти под структуры HTTP, разбор заголовков, сжатие) |
| **Пропускная способность** | Максимальная (сотни тысяч сессий/сек на узел) | Ограничена вычислительной мощностью разбора протокола |
| **Модификация данных** | Невозможна (за исключением вставки заголовка PROXY Protocol) | Полная трансформация запроса/ответа на лету (rewrite, add_header, sub_filter) |
| **Кэширование данных** | Не поддерживается | Встроенное кэширование ответов бэкенда (`proxy_cache`) |
| **Контроль доступа** | Ограничение по IP (`allow`/`deny`), лимит сессий (`limit_conn`) | `allow`/`deny`, HTTP Basic/Digest, `auth_request`, JWT, WAF |
| **Безопасность TLS** | TLS Passthrough (сквозной) или L4 TLS Termination | Терминация TLS с анализом HTTP, валидация mTLS |

### Архитектура и жизненный цикл L4-сессии в Nginx

Архитектура модуля `stream` построена на неблокирующем вводе-выводе и мультиплексировании событий (`epoll` в Linux) в рамках пула рабочих процессов (`worker_processes`).

```
[ Клиент: TCP / UDP ]
         │
         ▼ (1. TCP SYN / UDP Datagram)
┌─────────────────────────────────────────────────────────────────────────┐
│ Nginx Master Process                                                    │
│   └── Worker Process (epoll loop, non-blocking I/O)                     │
│        ├── 2. Listen Socket (reuseport, backlog, TCP_DEFER_ACCEPT)       │
│        ├── 3. Pre-read Phase (ssl_preread: парсинг SNI / ALPN)           │
│        ├── 4. Access Phase (limit_conn, allow / deny по CIDR)            │
│        ├── 5. Upstream Selection (Shared Memory zone: RR, least_conn)    │
│        ├── 6. Upstream Connect (non-blocking connect, proxy_connect_timeout) │
│        ├── 7. Data Relaying (двунаправленный стриминг, кольцевые буферы)│
│        └── 8. Session Close & Logging (сброс в stream access_log)       │
└─────────────────────────────────────────────────────────────────────────┘
         │
         ▼ (PROXY Protocol v1/v2 + Payload)
[ Upstream Сервер: PostgreSQL / MySQL / Redis / DNS ]
```

#### Этапы жизненного цикла TCP-сессии:

1. **Прием соединения (Accept):** Воркер извлекает соединение из очереди `listen`. При включении директивы `listen ... reuseport` ядро Linux распределяет входящие SYN-пакеты между воркерами на уровне сетевого стека по 4-tuple хэшу (`src_ip`, `src_port`, `dst_ip`, `dst_port`), исключая конкуренцию за блокировки сокета.
2. **Фаза предварительного анализа (Pre-read Phase):** Если включен `ssl_preread on;`, Nginx не инициирует соединение с бэкендом немедленно, а считывает первые байты входящего потока (`Client Hello`) в буфер `proxy_buffer_size`. Из пакета извлекаются переменные `$ssl_preread_server_name` и `$ssl_preread_alpn_protocols`.
3. **Фаза контроля доступа (Access Phase):** Проверяются правила `allow` и `deny`. Оценивается счетчик открытых соединений в зоне `limit_conn`. Если лимит превышен, соединение сбрасывается (`TCP RST`) или закрывается (`TCP FIN`).
4. **Выбор бэкенда (Upstream Selection):** На основе настроенного алгоритма (Round Robin, `least_conn`, `hash`) и состояния серверов в `zone` выбирается целевой сервер.
5. **Установка соединения с бэкендом (Connect Phase):** Воркер выполняет системный вызов `connect()` к адресу бэкенда. Если соединение не устанавливается за время `proxy_connect_timeout`, сервер помечается сбойным, и при включенном `proxy_next_upstream` предпринимается попытка подключения к следующему узлу.
6. **Двунаправленная ретрансляция данных (Relaying Phase):** После соединения Nginx пересылает байты между сокетом клиента и сокетом бэкенда. Буферизация на диск не выполняется; данные передаются через сокетные буферы ядра и локальные кольцевые буферы памяти `proxy_buffer_size`. Если включена директива `proxy_protocol on;`, перед клиентскими данными передается заголовок PROXY Protocol.
7. **Завершение сессии (Close & Log):** При закрытии сокета одной из сторон или по истечении таймаута неактивности `proxy_timeout` сессия финализируется. Время сессии, переданные байты и статус записываются в `access_log`.

#### Особенности обработки UDP-трафика:
В силу отсутствия состояния соединения в протоколе UDP, Nginx эмулирует **виртуальную сессию**. 
- Сессия инициируется при получении первого пакета на порт `listen ... udp`.
- Nginx привязывает виртуальную сессию к конкретному бэкенду.
- Завершение виртуальной сессии происходит по получению заданного числа пакетов от бэкенда (`proxy_responses`) либо по таймауту неактивности (`proxy_timeout`).
- Для сервисов типа DNS (один запрос — один ответ) указание `proxy_responses 1;` и короткого `proxy_timeout 3s;` обязательно для предотвращения утечки файловых дескрипторов.

### Конфигурационная структура блока `stream`

Контекст `stream` объявляется на корневом уровне конфигурации `/etc/nginx/nginx.conf`, наряду с контекстами `events` и `http`:

```nginx
# /etc/nginx/nginx.conf
user nginx;
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 16384;
    use epoll;
    multi_accept on;
}

# L7 HTTP-контекст
http {
    include /etc/nginx/mime.types;
    # ... http-директивы ...
}

# L4 TCP/UDP-контекст
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time "$upstream_addr" '
                     '"$upstream_bytes_sent" "$upstream_bytes_received" "$upstream_connect_time"';

    access_log /var/log/nginx/stream_access.log basic;
    error_log  /var/log/nginx/stream_error.log warn;

    include /etc/nginx/stream.d/*.conf;
}
```

### Алгоритмы балансировки L4

1. **Взвешенный Round Robin (по умолчанию):**
   Соединения распределяются поочередно с учетом весов `weight`. Не требует объявления дополнительных директив.
2. **Наименьшее число соединений (`least_conn`):**
   Новое соединение направляется серверу с наименьшим количеством текущих активных сессий.
   > [!IMPORTANT]
   > Для корректной работы `least_conn` в многопроцессной среде (при `worker_processes > 1`) **обязательно** наличие директивы `zone` внутри `upstream`. Без `zone` каждый воркер ведет собственный изолированный учет соединений, что приводит к неравномерному распределению.
3. **Хэширование ключа (`hash`):**
   Обеспечивает привязку клиента к бэкенду. Синтаксис: `hash $remote_addr [consistent];`. Параметр `consistent` активирует алгоритм консистентного хэширования Ketama, минимизируя сброс сессий при масштабировании пула бэкендов.
4. **Случайный выбор (`random`):**
   Директива `random [two [least_conn]];` выбирает бэкенд случайно либо выбирает два случайных узла и отправляет соединение на узел с наименьшим числом активных сессий (Power of Two Random Choices).
5. **Наименьшее время отклика (`least_time`):**
   Доступен в Angie и Nginx Plus (коммерческая подписка). Выбирает сервер с минимальным временем соединения (`least_time connect`) или первого байта (`least_time first_byte`).

### Оптимизация ядра Linux (Sysctl) для L4-балансировщика

L4-проксирование создает повышенную нагрузку на сетевой стек Linux, удерживая два сокета на каждое клиентское соединение. Ниже приведен базовый профиль тюнинга `/etc/sysctl.d/99-nginx-l4.conf`:

```ini
# /etc/sysctl.d/99-nginx-l4.conf

# Расширение диапазона эфемерных портов для исходящих соединений к бэкендам
net.ipv4.ip_local_port_range = 10240 65535

# Повторное использование сокетов в состоянии TIME_WAIT для исходящих TCP-соединений
net.ipv4.tcp_tw_reuse = 1

# Максимальный размер очереди не полностью установленных соединений (SYN backlog)
net.ipv4.tcp_max_syn_backlog = 16384

# Максимальный размер очереди ожидания сокета listen (somaxconn)
net.core.somaxconn = 16384

# Максимальное число открытых сокетов в состоянии TIME_WAIT
net.ipv4.tcp_max_tw_buckets = 262144

# Защита от SYN-флуда
net.ipv4.tcp_syncookies = 1

# Тюнинг буферов приема и отправки сокетов (min, default, max в байтах)
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# Очередь сетевой карты для входящих пакетов
net.core.netdev_max_backlog = 16384
```

Применение параметров:
```bash
sysctl -p /etc/sysctl.d/99-nginx-l4.conf
# → net.ipv4.ip_local_port_range = 10240 65535
# → net.ipv4.tcp_tw_reuse = 1
# → ...
```

### Логирование и переменные модуля `stream`

В модуле `stream` директива `access_log` оперирует сессиями. Доступные системные переменные:

| Переменная | Описание |
| :--- | :--- |
| `$remote_addr` / `$remote_port` | IP-адрес и порт клиента. |
| `$protocol` | Транспортный протокол (`TCP` или `UDP`). |
| `$status` | Код завершения сессии (`200` — успешно завершена, `400` — ошибка декодирования/pre-read, `403` — отклонено access-контролем, `500` — внутренняя ошибка, `502` — сбой бэкенда, `503` — сервис недоступен/лимиты, `504` — таймаут). |
| `$session_time` | Полная продолжительность сессии в секундах с миллисекундной точностью. |
| `$bytes_sent` / `$bytes_received` | Количество байтов, переданных клиенту и полученных от клиента. |
| `$upstream_addr` | IP-адрес и порт выбранного бэкенда (или список через запятую при повторах). |
| `$upstream_connect_time` | Время установления TCP-соединения с бэкендом (в секундах с миллисекундной точностью). |
| `$upstream_first_byte_time` | Время ожидания первого байта ответа от бэкенда (TTFB на уровне L4). |
| `$upstream_session_time` | Время взаимодействия с бэкендом. |
| `$upstream_bytes_sent` / `$upstream_bytes_received` | Объем переданных бэкенду и принятых от бэкенда данных. |
| `$ssl_preread_server_name` | Доменное имя из расширения SNI (требует `ssl_preread on;`). |
| `$ssl_preread_protocol` | Версия TLS, предложенная клиентом в `Client Hello`. |
| `$ssl_preread_alpn_protocols` | Список протоколов ALPN через запятую (например, `h2,http/1.1`). |

---

## Практические сценарии и конфигурация

### 1. Отказоустойчивое проксирование PostgreSQL (TCP) с разделением пулов Master и Read-Only

Сценарий обеспечивает маршрутизацию трафика на запись (порт 5433) на единственный Master-узел, а трафика на чтение (порт 5434) — с балансировкой `least_conn` между репликами.

```nginx
# /etc/nginx/stream.d/postgresql.conf

# Upstream для записи (Master)
upstream pg_cluster_write {
    zone pg_write_zone 64k;
    server 192.168.10.11:5432 max_fails=2 fail_timeout=10s;
    server 192.168.10.12:5432 backup; # Резервный узел при переключении роли
}

# Upstream для аналитики и чтения (Replicas)
upstream pg_cluster_read {
    zone pg_read_zone 128k;
    least_conn;
    server 192.168.10.12:5432 weight=2 max_fails=3 fail_timeout=15s;
    server 192.168.10.13:5432 weight=2 max_fails=3 fail_timeout=15s;
    server 192.168.10.14:5432 weight=1 max_fails=3 fail_timeout=15s;
}

# Ограничение параллельных соединений с одного IP-адреса
limit_conn_zone $binary_remote_addr zone=pg_conn_limit:10m;

# Сервер приема транзакций на запись
server {
    listen 5433 so_keepalive=on;
    proxy_pass pg_cluster_write;

    # Таймауты для СУБД: короткий коннект и длительное удержание сессии
    proxy_connect_timeout 3s;
    proxy_timeout 8h; # Защита от разрыва долгих транзакций и дампов
    proxy_socket_keepalive on;
    tcp_nodelay on;

    limit_conn pg_conn_limit 50;

    # Белый список доверенных подсетей приложения
    allow 192.168.0.0/16;
    allow 10.10.0.0/16;
    deny all;
}

# Сервер приема запросов на чтение
server {
    listen 5434 so_keepalive=on;
    proxy_pass pg_cluster_read;

    proxy_connect_timeout 2s;
    proxy_timeout 1h;
    proxy_socket_keepalive on;
    tcp_nodelay on;

    limit_conn pg_conn_limit 100;

    allow 192.168.0.0/16;
    allow 10.10.0.0/16;
    deny all;
}
```

### 2. Балансировка Redis / Key-Value хранилищ с консистентным хэшированием

При отсутствии Redis Cluster балансировка пула серверов кэширования выполняется методом консистентного хэширования по IP-адресу клиента (`hash $remote_addr consistent`).

```nginx
# /etc/nginx/stream.d/redis.conf

upstream redis_cache_pool {
    zone redis_pool_zone 128k;
    hash $remote_addr consistent;

    server 10.20.1.21:6379 max_fails=2 fail_timeout=5s;
    server 10.20.1.22:6379 max_fails=2 fail_timeout=5s;
    server 10.20.1.23:6379 max_fails=2 fail_timeout=5s;
}

server {
    listen 6380;
    proxy_pass redis_cache_pool;

    proxy_connect_timeout 1s;
    proxy_timeout 30s;
    tcp_nodelay on;

    allow 10.20.0.0/16;
    deny all;
}
```

### 3. Проксирование DNS (UDP и TCP на порту 53)

DNS-трафик требует одновременной поддержки UDP (для стандартных запросов размером до 512/4096 байт) и TCP (для больших ответов EDNS0 и зонных трансферов AXFR/IXFR).

```nginx
# /etc/nginx/stream.d/dns.conf

upstream dns_backend_udp {
    zone dns_udp_zone 64k;
    server 10.50.0.10:53;
    server 10.50.0.11:53;
}

upstream dns_backend_tcp {
    zone dns_tcp_zone 64k;
    least_conn;
    server 10.50.0.10:53;
    server 10.50.0.11:53;
}

# UDP DNS-прокси
server {
    listen 53 udp reuseport;
    proxy_pass dns_backend_udp;

    # Для UDP: завершать сессию после получения 1 ответа от резолвера
    proxy_responses 1;
    proxy_timeout 2s;
    proxy_connect_timeout 1s;
}

# TCP DNS-прокси
server {
    listen 53 reuseport;
    proxy_pass dns_backend_tcp;

    proxy_timeout 10s;
    proxy_connect_timeout 2s;
    tcp_nodelay on;
}
```

### 4. Защищенный SSH-бастион с лимитом сессий и логированием

Использование Nginx перед кластером серверов Jump Host / Bastion позволяет скрыть реальные IP-адреса хостов, логировать продолжительность сессий и блокировать попытки перебора соединений.

```nginx
# /etc/nginx/stream.d/ssh_bastion.conf

upstream ssh_servers {
    zone ssh_zone 64k;
    server 172.16.1.10:22 max_fails=2 fail_timeout=30s;
    server 172.16.1.11:22 max_fails=2 fail_timeout=30s;
    server 172.16.1.12:22 backup;
}

limit_conn_zone $binary_remote_addr zone=ssh_per_ip:10m;

server {
    listen 2222;
    proxy_pass ssh_servers;

    proxy_connect_timeout 5s;
    proxy_timeout 4h;
    proxy_socket_keepalive on;
    tcp_nodelay on;

    # Не более 3 одновременных SSH-соединений с одного внешнего IP
    limit_conn ssh_per_ip 3;

    allow 198.51.100.0/24; # Офисная подсеть
    deny all;
}
```

### 5. SSL/TLS Passthrough с маршрутизацией по SNI и ALPN (Nginx 1.25.5+)

Сквозная передача шифрованного трафика без расшифровки на Nginx. Маршрутизация выполняется на основе SNI (`server_name` или `$ssl_preread_server_name`), сохраняя E2E-шифрование вплоть до бэкендов.

```nginx
# /etc/nginx/stream.d/tls_passthrough.conf

upstream k8s_api_cluster {
    zone k8s_api_zone 64k;
    server 10.100.0.1:6443;
    server 10.100.0.2:6443;
}

upstream gitlab_ssh_cluster {
    zone gitlab_ssh_zone 64k;
    server 10.100.0.10:22;
}

upstream web_ingress_cluster {
    zone web_ingress_zone 64k;
    server 10.100.0.20:443;
    server 10.100.0.21:443;
}

# Вариант А: Использование нативных виртуальных серверов (Nginx 1.25.5+)
server {
    listen 443;
    ssl_preread on;
    server_name api.infra.local;
    proxy_pass k8s_api_cluster;
    proxy_connect_timeout 3s;
    proxy_timeout 1h;
}

server {
    listen 443;
    ssl_preread on;
    server_name git.infra.local;
    proxy_pass web_ingress_cluster;
    proxy_connect_timeout 3s;
    proxy_timeout 1h;
}

# Вариант Б: Мультиплексирование через map (поддерживает ALPN и не-TLS трафик)
map $ssl_preread_server_name $tls_target_upstream {
    api.infra.local     k8s_api_cluster;
    git.infra.local     web_ingress_cluster;
    default             web_ingress_cluster;
}

server {
    listen 8443;
    ssl_preread on;
    proxy_pass $tls_target_upstream;
    proxy_connect_timeout 3s;
    proxy_timeout 1h;
}
```

### 6. SSL/TLS-терминация на L4 с взаимной аутентификацией (mTLS)

Nginx принимает зашифрованное соединение, валидирует клиентский сертификат (mTLS), расшифровывает поток и передает открытый TCP-трафик в защищенный внутренний контур.

```nginx
# /etc/nginx/stream.d/tls_termination_mtls.conf

upstream internal_legacy_db {
    server 127.0.0.1:5432;
}

server {
    listen 9443 ssl;

    # Серверный сертификат
    ssl_certificate     /etc/ssl/certs/db-proxy.crt;
    ssl_certificate_key /etc/ssl/private/db-proxy.key;

    # Настройки криптографии
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_session_cache shared:StreamSSL:20m;
    ssl_session_timeout 4h;

    # Взаимная аутентификация клиентов (mTLS)
    ssl_client_certificate /etc/ssl/certs/internal_ca.crt;
    ssl_verify_client on;
    ssl_verify_depth 2;

    proxy_pass internal_legacy_db;
    proxy_timeout 2h;
    proxy_connect_timeout 2s;
    tcp_nodelay on;
}
```

### 7. Использование PROXY Protocol (генерация и прием)

Когда Nginx работает перед бэкендом, скрывая реальный IP-адрес клиента за NAT/проксированием, PROXY Protocol позволяет передать адрес клиента в заголовке соединения.

#### Передача PROXY Protocol на бэкенд:
```nginx
# /etc/nginx/stream.d/frontend_lb.conf

upstream backend_servers {
    zone backend_zone 64k;
    server 10.0.5.10:8000;
    server 10.0.5.11:8000;
}

server {
    listen 80;
    proxy_pass backend_servers;

    # Включение отправки заголовка PROXY Protocol v2 (или v1)
    proxy_protocol on;
    proxy_connect_timeout 3s;
}
```

#### Прием PROXY Protocol бэкендом (другим Nginx):
```nginx
# /etc/nginx/conf.d/backend_receiver.conf (контекст http или stream)
server {
    listen 8000 proxy_protocol;

    # Доверенные IP-адреса L4-балансировщиков
    set_real_ip_from 10.0.5.0/24;
    set_real_ip_from 192.168.1.5;

    # Источник извлечения IP
    real_ip_header proxy_protocol;

    # Теперь в $remote_addr будет содержаться исходный IP клиента
}
```

### 8. Прозрачное L4-проксирование (TPROXY / `proxy_bind transparent`)

Позволяет целевому серверу видеть реальный IP-адрес клиента на уровне TCP/IP без изменений со стороны протоколов (без PROXY Protocol). Требует специальной настройки маршрутизации и iptables на хосте балансировщика.

#### 1. Конфигурация Nginx:
```nginx
# /etc/nginx/stream.d/transparent_proxy.conf

upstream raw_backend {
    server 192.168.20.50:3306;
}

server {
    listen 3306;

    # Подмена адреса отправителя на реальный IP клиента
    proxy_bind $remote_addr transparent;
    proxy_pass raw_backend;

    proxy_connect_timeout 2s;
    proxy_timeout 1h;
}
```

#### 2. Настройка прав процесса Nginx (Linux Capabilities):
Воркеры Nginx (работающие не от `root`) должны обладать правами на связывание с нелокальными сокетами:
```bash
setcap 'cap_net_admin,cap_net_raw=+ep' /usr/sbin/nginx
# → подтверждение применения прав
getcap /usr/sbin/nginx
# → /usr/sbin/nginx = cap_net_admin,cap_net_raw+ep
```

#### 3. Настройка сетевого стека Linux (iptables / nftables и policy routing):
Ответные пакеты от бэкенда должны возвращаться через балансировщик (балансировщик выступает шлюзом либо пакеты перенаправляются правилами policy routing):

```bash
# Создание таблицы маршрутизации для локальной доставки
ip rule add fwmark 1 lookup 100
ip route add local 0.0.0.0/0 dev lo table 100

# Маркировка транзитных пакетов через iptables (TPROXY)
iptables -t mangle -A PREROUTING -p tcp -s 192.168.20.50 --sport 3306 -j MARK --set-mark 1
```

### 9. Межмодульная передача через `ngx_stream_pass_module` (Nginx 1.25.5+)

Позволяет принимать зашифрованный L4-трафик на одном внешнем порту (например, 443), выполнять предварительный анализ или фильтрацию в `stream`, после чего передавать соединение в блок `http` без оверхеда локальных TCP-сокетов (`loopback`).

```nginx
# /etc/nginx/nginx.conf
stream {
    server {
        listen 443;
        ssl_preread on;

        # Если SNI совпадает с внутренним веб-сервисом, передаем в HTTP
        server_name web.example.com;
        pass 127.0.0.1:8443;
    }

    server {
        listen 443;
        ssl_preread on;

        # Остальные запросы проксируются как сырой TCP на внешний хост
        server_name db.example.com;
        proxy_pass 10.0.0.5:5432;
    }
}

http {
    server {
        listen 127.0.0.1:8443 ssl;
        ssl_certificate     /etc/ssl/certs/web.crt;
        ssl_certificate_key /etc/ssl/private/web.key;

        location / {
            return 200 "Served by HTTP module via Stream pass!\n";
        }
    }
}
```

---

## Операции и команды

### Валидация и перезагрузка без даунтайма

```bash
# 1. Проверка синтаксиса конфигурации с раскрытием всех include
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Перезагрузка конфигурации без обрыва активных соединений (Graceful Reload)
nginx -s reload
# → отправлен сигнал HUP мастер-процессу Nginx

# 3. Контроль выхода старых рабочих процессов при наличии долгоживущих TCP-сессий
ps aux | grep "nginx: worker process is shutting down"
# → nginx: worker process is shutting down (сессия удерживается клиентом)
```

> [!TIP]
> При использовании `nginx -s reload` в среде с долгоживущими L4-сессиями (БД, SSH) старые воркеры остаются в памяти до завершения всех подключений. Для принудительного ограничения времени их жизни используйте директиву `worker_shutdown_timeout 1h;` на уровне `main` в `nginx.conf`.

### Анализ сетевых соединений и сокетов (Linux CLI)

```bash
# Проверка слушающих L4-портов Nginx (TCP и UDP)
ss -lntup | grep nginx
# → tcp  LISTEN 0 16384 0.0.0.0:5433  0.0.0.0:* users:(("nginx",pid=14201,fd=8))
# → udp  UNCONN 0 16384 0.0.0.0:53    0.0.0.0:* users:(("nginx",pid=14201,fd=9))

# Подсчет активных установленных соединений к конкретному upstream-пулу
ss -nt state established '( dport = :5432 )' | wc -l
# → 142

# Мониторинг соединений в состоянии TIME_WAIT для портов СУБД
ss -nt state time-wait '( dport = :5432 or sport = :5432 )' | wc -l
# → 28

# Анализ размера очередей сокетов Recv-Q и Send-Q на балансировщике
ss -lnt '( sport = :5433 )'
# → State  Recv-Q  Send-Q  Local Address:Port  Peer Address:Port
# → LISTEN 0       16384   0.0.0.0:5433        0.0.0.0:*
```

### Анализ логов сессий и метрик L4

```bash
# Топ-10 клиентов по количеству открытых L4-сессий
awk '{print $1}' /var/log/nginx/stream_access.log | sort | uniq -c | sort -rn | head -n 10
# → 14200 192.168.1.105
# →  8900 192.168.1.112

# Распределение сессий по upstream-серверам (балансировочный баланс)
awk '{print $(NF-3)}' /var/log/nginx/stream_access.log | tr -d '"' | sort | uniq -c | sort -rn
# → 45120 192.168.10.12:5432
# → 44980 192.168.10.13:5432
# → 22510 192.168.10.14:5432

# Поиск сессий с аномально долгим временем установления коннекта к бэкенду (> 100 мс)
awk '$NF > 0.100 {print "Client:", $1, "Time:", $2, "Upstream:", $(NF-3), "ConnectTime:", $NF}' /var/log/nginx/stream_access.log | head -n 10
# → Client: 192.168.1.55 Time: [17/Oct/2026:15:30:12] Upstream: 192.168.10.12:5432 ConnectTime: 0.145

# Анализ ошибок подключения в error.log
grep -E "upstream|connect\(\) failed|connection refused|limit_conn" /var/log/nginx/stream_error.log | tail -n 20
```

### Тестирование пропускной способности и отказоустойчивости (Failover)

```bash
# 1. Замер пропускной способности TCP через Nginx с помощью iperf3
# На бэкенде:
iperf3 -s -p 5201
# На клиенте через балансировщик (порт 5202):
iperf3 -c 192.168.1.10 -p 5202 -t 10
# → [ ID] Interval           Transfer     Bitrate         Retr
# → [  5] 0.00-10.00 sec  11.4 GBytes  9.81 Gbits/sec    0             sender

# 2. Имитация аварии узла upstream (сброс пакетов через RST)
iptables -A INPUT -p tcp --dport 5432 -j REJECT --reject-with tcp-reset

# 3. Проверка переключения Nginx на резервный сервер в stream_access.log
tail -f /var/log/nginx/stream_access.log | grep "5432"
# → 192.168.1.50 [17/Oct/2026:15:40:01] TCP 200 450 1200 0.012 "192.168.10.11:5432, 192.168.10.12:5432"
# В логе видно: первый узел дал ошибку, сессия прозрачно переведена на второй узел

# 4. Восстановление узла
iptables -D INPUT -p tcp --dport 5432 -j REJECT --reject-with tcp-reset
```

---

## Диагностика и устранение неполадок

### Таблица типичных неисправностей L4

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `111: Connection refused` при коннекте к бэкенду | Бэкенд-сервис остановлен, слушает только `127.0.0.1` или блокируется файрволом хоста бэкенда | Проверить доступность порта утилитой `nc -zv <backend_ip> <port>`. Проверить `ss -lntp` на бэкенде. Проверить правила `iptables` / `nftables` на бэкенде. |
| `110: Connection timed out` в `stream_error.log` | Сетевой packet drop, маршрут недоступен, превышен `proxy_connect_timeout` | Проверить маршрут `ip route get <backend_ip>`. Снять дамп `tcpdump -nn -i any port <backend_port>`. Увеличить `proxy_connect_timeout` с 1s до 3s-5s при задержках в WAN. |
| Сессия СУБД / SSH обрывается ровно через 10 минут | Срабатывает дефолтный `proxy_timeout 10m;` при паузе в передаче данных | Увеличить `proxy_timeout` в блоке `server` до `1h` или `8h`. Включить `proxy_socket_keepalive on;` и `so_keepalive=on` для отправки периодических TCP Keep-Alive зондов. |
| `worker_connections are not enough` в error.log | Превышен лимит соединений на процесс Nginx | На каждое проксируемое соединение расходуется 2 дескриптора (клиент + бэкенд). Увеличить `worker_connections` в `events` (до 16384+) и установить `worker_rlimit_nofile` минимум в 2.5× от `worker_connections`. |
| Неравномерная нагрузка в пуле при `least_conn` | Отсутствует директива `zone` в блоке `upstream` при нескольких рабочих процессах | Добавить `zone <name> 64k;` внутри `upstream`. Без `zone` воркеры не координируют счетчики активных сессий между собой. |
| `bind() to 0.0.0.0:... failed (98: Address already in use)` | Конфликт портов с другим сервисом (например, локальный PostgreSQL занял 5432) | Найти конкурирующий процесс: `ss -lntp '( sport = :<port> )'`. Изменить порт в конфигурации Nginx либо привязать локальный демон к конкретному внутреннему IP. |
| Ошибка `bind() failed (13: Permission denied)` при `proxy_bind transparent` | Процесс Nginx не имеет системных capabilities Linux для нелокального биндинга | Выдать бинарнику права: `setcap 'cap_net_admin,cap_net_raw=+ep' /usr/sbin/nginx`. Проверить статус SELinux / AppArmor (`audit2why` / `aa-status`). |
| Бэкенд разрывает соединение сразу после рукопожатия | Включен `proxy_protocol on;`, но бэкенд не сконфигурирован на прием заголовка PROXY Protocol | Отключить `proxy_protocol on;` в Nginx либо включить поддержку PROXY Protocol на бэкенде (например, в PostgreSQL `proxy_protocol=on` или в Nginx `listen ... proxy_protocol;`). |
| Потеря UDP-пакетов при пиковой нагрузке (DNS/Syslog) | Переполнение сокетных буферов приема UDP в ядре Linux | Увеличить параметры `net.core.rmem_max` и `net.core.rmem_default` через sysctl. Проверить дропы: `netstat -su \| grep "receive errors"`. В Nginx убедиться в наличии `proxy_responses` и `reuseport`. |
| `403 Forbidden` в `stream_access.log` | Клиентский IP отклонен директивами `allow` / `deny` либо исчерпан `limit_conn` | Проверить `$remote_addr` клиента в логе. Сверить CIDR маски в блоке `server`. Проверить алерты лимитов в `stream_error.log` по слову `limiting connections`. |

### Диагностические команды SRE / Sysadmin

```bash
# 1. Трассировка TCP-рукопожатия между Nginx и бэкендом
tcpdump -nn -i any "port 5432 and (tcp-syn != 0 or tcp-fin != 0 or tcp-rst != 0)"
# → 15:42:01.102 IP 192.168.1.10.45231 > 192.168.10.11.5432: Flags [S]
# → 15:42:01.103 IP 192.168.10.11.5432 > 192.168.1.10.45231: Flags [S.]

# 2. Мониторинг системных лимитов файловых дескрипторов процесса воркера Nginx
PID=$(pgrep -f "nginx: worker process" | head -n 1)
cat /proc/$PID/limits | grep -E "Max open files|Max processes"
# → Max processes             128120               128120               processes 
# → Max open files            65535                65535                files     

# 3. Проверка фактического количества открытых файловых сокетов воркера
ls -l /proc/$PID/fd | grep socket | wc -l
# → 2341

# 4. Проверка дропов пакетов в очереди UDP сокета
netstat -su | grep -E "packet receive errors|receive buffer errors"
# → 0 packet receive errors
# → 0 receive buffer errors
```

---

## Лучшие практики

### Производительность и сайзинг

1. **Используйте `listen ... reuseport` на многоядерных серверах.** Опция позволяет каждому рабочему процессу Nginx иметь собственный слушающий сокет. Ядро распределяет входящие TCP SYN-пакеты по сокетам без блокировок, кардинально снижая задержку на ядрах CPU при высоком RPS.
2. **Всегда объявляйте `zone` для групп `upstream`.** Без разделяемой памяти балансировка `least_conn` изолирована внутри воркеров, а динамическое изменение состояния узлов при пассивных health checks (`max_fails`) не синхронизируется между процессами.
3. **Рассчитывайте файловые дескрипторы по формуле:**
   $$\text{worker\_rlimit\_nofile} \ge \text{worker\_connections} \times 2 + 1024$$
   Каждая L4-сессия занимает сокет входящего клиента и сокет исходящего подключения к бэкенду.
4. **Отключайте алгоритм Нагла (`tcp_nodelay on;`).** Для интерактивных протоколов (СУБД, Redis, SSH) задержка отправки малых пакетов (Nagle algorithm buffering) недопустима. Опция `tcp_nodelay` включена в Nginx по умолчанию, но должна явно фиксироваться в production-конфигурациях.
5. **Настраивайте буферы сокетов под пропускную способность.** Если через Nginx передаются большие объемы бинарных данных или потоковое видео/дампы, настройте директиву `proxy_buffer_size 64k;` (по умолчанию 16k).

### Эксплуатация (SRE)

1. **Разделяйте таймауты под специфику сервисов.**
   - Для OLTP СУБД (PostgreSQL, MySQL): `proxy_connect_timeout 2s;`, `proxy_timeout 8h;`, `proxy_socket_keepalive on;`.
   - Для DNS (UDP): `proxy_responses 1;`, `proxy_timeout 2s;`.
   - Для микросервисов с короткими сессиями: `proxy_timeout 60s;`.
2. **Включайте TCP Keep-Alive на обоих концах соединения.** Используйте параметр `listen ... so_keepalive=on` со стороны клиента и директиву `proxy_socket_keepalive on;` со стороны бэкенда. Это предотвращает silent drop соединений промежуточными межсетевыми экранами (stateful firewall conntrack timeout).
3. **Контролируйте Graceful Reload долгоживущих сессий.** Задавайте `worker_shutdown_timeout` в контексте `main`. Это гарантирует, что после перезагрузки конфигурации старые воркеры не зависнут бесконечно, удерживая память и файловые дескрипторы.
4. **Структурируйте конфигурационные файлы.** Разделяйте сервисы по отдельным файлам в `/etc/nginx/stream.d/*.conf`, логически изолируя сетевые сервисы (БД, SSH, DNS, брокеры сообщений).

### Безопасность

1. **Принцип наименьших привилегий для воркеров.** Рабочие процессы Nginx должны работать от непривилегированного пользователя (обычно `nginx`). Для связывания с низкими портами (< 1024) или использования `transparent` проксирования выдавайте специфичные Linux Capabilities (`cap_net_bind_service`, `cap_net_admin`), не запуская процессы от `root`.
2. **Эшелонированная защита от DoS/DDoS.** Сочетайте ограничение параллельных сессий на уровне Nginx (`limit_conn_zone` + `limit_conn`) с сетевыми фильтрами ядра Linux (`iptables -m connlimit`, `nftables`, `net.ipv4.tcp_syncookies = 1`).
3. **Явная изоляция бэкендов по CIDR.** Всегда ограничивайте доступ к критическим портам L4 (базы данных, бастионы) директивами `allow <subnet>; deny all;`, предотвращая несанкционированный доступ из публичных сетей.
4. **Изолируйте интерфейсы управления.** Любые эндпоинты телеметрии (`stub_status`, Angie `status_zone` API) размещайте на локальном интерфейсе (`127.0.0.1`) либо на выделенном VLAN управления с жесткими ACL.

---

## Дополнительная информация

### См. также

- [Установка и базовая настройка Nginx](../Core/nginx_setup.md) — общая структура конфигурации, контекст `main`, `events` и лимиты ОС.
- [Обзор веб-сервера Nginx](../Core/nginx_overview.md) — архитектура событийного цикла, воркеры, обработка ввода-вывода.
- [Диагностика и устранение неполадок Nginx](../Operations/nginx_troubleshooting.md) — анализ системных ошибок ядра, исчерпания сокетов и памяти.
- [Тюнинг производительности Nginx](../Performance/nginx_performance_tuning.md) — глубокая оптимизация сетевого стека, параметров TCP и ядра Linux.
- [Обзор и концепции балансировки Nginx](./Load_Balancing/overview_concepts.md) — теоретические основы балансировки, зоны памяти и алгоритмы распределения.
- [Практическая конфигурация балансировки](./Load_Balancing/practical_configuration.md) — расширенные сценарии настройки upstream-групп и failover.
- [Балансировка и проксирование L4 в Angie](../../Angie/l4_balancing_and_proxying.md) — специфика Angie: нативная `status_zone`, MQTT Pre-read, slow start и активные проверки probe.
- [Сетевой протокол PROXY Protocol](../../../Networking/Protocols/proxy_protocol.md) — спецификация формата v1 (текстовый) и v2 (бинарный), трансляция клиентских IP.
- [Прозрачное проксирование в Linux](../../../Networking/Concepts/nat/transparent_proxy.md) — механизм TPROXY, правила iptables/nftables и таблицы маршрутизации.
