# Защита от DoS-атак в Angie

**Актуально для:** Angie 1.12.x (включая Angie PRO для cluster zone sync)

## Определения

**DoS (Denial of Service — «отказ в обслуживании»)** — атака на вычислительную систему или сетевую инфраструктуру с целью исчерпания критических ресурсов (CPU, оперативная память, пропускная способность канала, файловые дескрипторы, слоты таблицы conntrack) с единичного источника. На прикладном уровне (L7) выражается в флуде запросов, атаках на медленную передачу данных (Slowloris, Slow POST / R.U.D.Y., Slow Read) или в вызове ресурсоёмких функций бизнес-логики.

**DDoS (Distributed Denial of Service — распределённый отказ в обслуживании)** — скоординированная атака с множества распределённых узлов (ботнет, скомпрометированные серверы, амплификаторы). Из-за распределения трафика по тысячам IP-адресов классические примитивные счетчики на одиночном хосте малоэффективны; требуется многоуровневая фильтрация, кластерная синхронизация счетчиков и поведенческий анализ.

**Rate Limiting (Ограничение интенсивности запросов)** — алгоритмический контроль частоты входящих запросов за единицу времени. В Angie базовым механизмом является алгоритм *Leaky Bucket* («дырявое ведро»). Запросы, поступающие в пределах лимита (`rate`), обрабатываются немедленно; всплески (`burst`) либо временно буферизуются с задержкой, либо обрабатываются без задержки (`nodelay`), либо обслуживаются по двухфазной схеме (`delay`), а избыточные запросы сбрасываются с кодом ответа `429 Too Many Requests`.

**Connection Limiting (Ограничение соединений)** — контроль числа одновременно открытых TCP/TLS-сессий с одного IP-адреса, виртуального хоста или блока локаций. Предотвращает исчерпание пула `worker_connections` и дескрипторов файлов процесса.

**Cluster Zone Sync** — технология синхронизации состояний разделяемой памяти (shared memory) между узлами кластера Angie по протоколу TCP/UDP через блок `stream`. Позволяет применять глобальные агрегированные лимиты против распределённых атак, когда отдельный узел ботнета не превышает локальный порог одного сервера, но суммарно перегружает кластер. Доступна для production в Angie PRO.

**Slowloris** — атака класса Slow HTTP, при которой клиент устанавливает множество TCP-соединений и отправляет HTTP-заголовки крайне малыми частями (по 1 байту каждые несколько секунд), удерживая соединение открытым и исчерпывая лимит воркеров веб-сервера.

**Slow POST (R.U.D.Y. — R U Dead Yet?)** — атака, аналогичная Slowloris, но нацеленная на передачу тела запроса (message body). Клиент объявляет большой `Content-Length` и передаёт тело с минимальной скоростью, удерживая процесс сервера в состоянии ожидания I/O.

**HPACK Bomb** — атака на алгоритм сжатия заголовков HPACK в протоколе HTTP/2. Злоумышленник формирует заголовки, ссылающиеся на одну и ту же динамическую запись таблицы сжатия, что при декомпрессии вызывает лавинообразный расход оперативной памяти (в сотни и тысячи раз превышающий размер переданного пакета).

**Rapid Reset (CVE-2023-44487)** — архитектурная уязвимость в реализациях HTTP/2 и HTTP/3, при которой клиент мультиплексирует тысячи потоков (streams) и немедленно отправляет кадр отмены `RST_STREAM`. Сервер вынужден тратить ресурсы CPU на выделение и очистку структур состояния потока без ограничений по стандартному таймауту.

**QUIC Reflection / Flood** — атака на транспортный протокол UDP, лежащий в основе HTTP/3 (QUIC). Атакующий подделывает IP-адрес источника (IP spoofing) в начальном пакете `Initial`, заставляя сервер отправлять массивные пакеты `Initial + Handshake` жертве. Парируется механизмом `quic_retry on`.

**quic_bpf** — модуль расширения Angie на базе eBPF (Extended Berkeley Packet Filter) для привязки сокетов QUIC к конкретным воркер-процессам (`SO_REUSEPORT`). Предотвращает сброс активных сессий HTTP/3 при бесшовной перезагрузке конфигурации (`angie -s reload`).

**SYN Cookies** — метод защиты сетевого стека ядра Linux от SYN-флуда, при котором состояние незавершённого TCP-соединения не сохраняется в таблице `SYN backlog`, а кодируется в начальном номере последовательности (`Sequence Number`) пакета SYN-ACK.

**conntrack (Connection Tracking)** — подсистема ядра Linux (Netfilter), отслеживающая состояние всех сетевых соединений. Переполнение таблицы conntrack (`nf_conntrack_max`) приводит к автоматическому отбрасыванию даже легитимных новых пакетов до передачи их в Angie.

**Retry-After** — HTTP-заголовок ответа (RFC 6585 / RFC 9110), передаваемый вместе со статусом `429 Too Many Requests` или `503 Service Unavailable`, сообщающий клиенту минимальное время ожидания в секундах перед следующей попыткой запроса.

---

## Базовые концепции и архитектура защиты

### Классификация угроз по уровням модели OSI

Эшелонированная защита строится с учётом того, на каком уровне модели OSI злоумышленник пытается исчерпать ресурсы:

```
[ L3: Сетевой уровень ]    ──> IP Flood, ICMP Flood, BGP Hijacking, Spoofing
        │
[ L4: Транспортный уровень ]──> SYN Flood, UDP/QUIC Flood, ACK Flood, RST Flood
        │
[ L7: Прикладной уровень ] ──> HTTP Flood, Slowloris, Slow POST, Rapid Reset, Smuggling
```

#### Сетевой и транспортный уровни (L3/L4 — волюметрические атаки)

Цель — насыщение полосы пропускания (bandwidth) либо исчерпание таблиц состояний сетевого стека ядра (backlog, conntrack):

*   **UDP Flood / Amplification:** Массовая бомбардировка UDP-пакетами. На on-prem хостах ядро тратит процессорные прерывания на обработку сокетов и генерацию ответов ICMP Port Unreachable. Блокируется до приложения с помощью `nftables` или BGP Flowspec.
*   **SYN Flood:** Злоумышленник отправляет поток TCP SYN-пакетов без завершения трёхстороннего рукопожатия (3-way handshake). Это заполняет очередь `tcp_max_syn_backlog`. Защита: `net.ipv4.tcp_syncookies = 1` и фильтрация в `nftables`.
*   **QUIC / UDP Flood (HTTP/3):** Флуд UDP-пакетами на порт 443. Не блокируется стандартными TCP-фильтрами. Требует включения проверки адреса источника через Stateless Retry Token (`quic_retry on`) и аппаратной разгрузки сегментации (`quic_gso on`).

#### Прикладной уровень (L7 — атаки на ресурсы веб-сервера и бэкендов)

Цель — исчерпание пула потоков/воркеров Angie, файловых дескрипторов, буферов памяти или пропускной способности каналов к базам данных:

*   **HTTP GET/POST Flood:** Поток синтаксически корректных запросов к тяжёлым страницам (поиск, экспорт, фильтрация). Защита: `limit_req`, многоуровневое кэширование, GeoIP-фильтры.
*   **Медленные атаки (Slow HTTP):** Удержание ресурсов за счёт минимальной скорости передачи. Защита: агрессивные значения `client_header_timeout`, `client_body_timeout`, `send_timeout`.
*   **Атаки на мультиплексирование (HTTP/2 / HTTP/3):** Открытие десятков тысяч потоков в рамках одного TCP/UDP соединения. Защита: директивы `http2_max_concurrent_streams`, `http3_max_concurrent_streams`.
*   **HTTP Request Smuggling (Контрабанда запросов):** Десинхронизация парсинга границ запросов между фронтендом (Angie) и внутренними бэкендами (RFC 7230 / RFC 9112). Защита: строгая нормализация заголовков и методов в Angie.

---

### Архитектура эшелонированной защиты (Defense in Depth)

Надежная защита bare-metal и виртуализированной инфраструктуры без облачных посредников требует распределения фильтрации по 4 рубежам:

```
[ Входящий Интернет-трафик ]
              │
              ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 1. Периметр сети и BGP-маршрутизация                    │
  │    - BGP Flowspec / RTBH (сброс мусора на upstream)    │
  │    - Аппаратные ACL и anti-spoofing (BCP 38)            │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 2. Сетевой стек Linux (Netfilter / nftables / sysctl)   │
  │    - SYN Cookies, расширенный somaxconn, backlog        │
  │    - Ограничение conntrack, fast drop invalid           │
  │    - Динамические O(1) sets (blackhole, fail2ban)       │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 3. L7-движок Angie (Reverse Proxy & HTTP/QUIC Engine)   │
  │    - Rate Limiting (Leaky Bucket: burst, nodelay, delay)│
  │    - Connection Limiting (limit_conn)                   │
  │    - Таймауты медленных атак (client_header/body)       │
  │    - Cluster Zone Sync (синхронизация лимитов в кластере)│
  │    - Caching (proxy_cache_lock — анти-thundering herd)  │
  │    - GeoIP2 фильтрация и валидация методов              │
  │    - WAF (ModSecurity v3 / NAXSI на L7)                 │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 4. Контур наблюдаемости и автоматизации (SRE Layer)     │
  │    - Angie Prometheus Metrics (`status_zone`, API)      │
  │    - fail2ban / Custom daemons ──> наполнение nftables  │
  │    - Alertmanager: алерты по аномалиям RPS / 429 / 503  │
  └─────────────────────────────────────────────────────────┘
```

---

### Внутреннее устройство Rate Limiting в Angie

#### Алгоритм Leaky Bucket и разделяемая память

Модуль `ngx_http_limit_req_module` использует разделяемую память (shared memory slab). При поступлении запроса:

1.  Вычисляется ключ (обычно `$binary_remote_addr`, занимающий 4 байта для IPv4 или 16 байт для IPv6).
2.  В красно-чёрном дереве (Red-Black Tree) зоны ищется узел, соответствующий ключу.
3.  Каждый узел на 64-битной платформе занимает ровно **160 байт** для IPv4:
    *   1 МБ памяти вмещает: `1 048 576 / 160 ≈ 65 536` уникальных IP-адресов.
    *   Зона размером `20m` вмещает порядка `1.3 миллиона` одновременных состояний клиентов.
4.  Если узел найден, рассчитывается «уровень воды» в ведре с момента последнего запроса. Если уровень превышает лимит частоты (`rate`), оценивается размер накопителя всплеска (`burst`).
5.  Если лимит исчерпан, запрос отклоняется со статусом `limit_req_status` (по умолчанию `503`, в production настраивается на `429`).
6.  Неактивные узлы удаляются по алгоритму LRU (Least Recently Used) при заполнении зоны памяти.

#### Режимы обработки всплесков: burst, nodelay и delay

```
Поток запросов ───> [ Rate: 10r/s (1 запрос в 100 мс) ]
                           │
       ┌───────────────────┴───────────────────┐
       ▼                                       ▼
  Превышение rate                         В пределах rate
       │                                       │
       ▼                                       ▼
 [ Есть burst? ] ─── НЕТ ───> Отклонение 429  Немедленная обработка
       │
      ДА
       ├──────> [ nodelay ] ───────────> Немедленная обработка всплеска
       │
       ├──────> [ delay=N ] ───────────> Первые N без задержки, далее искусственная задержка
       │
       └──────> [ без nodelay/delay ] ─> Очередь с принудительной задержкой каждого запроса
```

*   `rate=10r/s`: базовая скорость протекания (1 запрос каждые 100 мс).
*   `burst=20 nodelay`: разрешает мгновенный пропуск пачки до 20 запросов без искусственной задержки, но дальнейшие запросы сверх этого объема в текущем кванте времени немедленно отклоняются.
*   `burst=20 delay=10`: **двухфазное ограничение**. Первые 10 запросов выполняются мгновенно; запросы с 11 по 20 задерживаются планировщиком так, чтобы сгладить нагрузку на бэкенд; всё, что выше 20 — отбрасывается со статусом `429`.

---

## Практические сценарии и конфигурация

### Системные требования и предварительные условия

Для развёртывания отказоустойчивой защиты на базе Angie требуются следующие минимальные системные параметры хоста:

| Компонент | Минимальные требования | Рекомендуемые требования (High Load / SRE) |
| :--- | :--- | :--- |
| **ОС** | Linux с ядром >= 5.15 (Debian 12, RHEL 9, Ubuntu 24.04) | Ядро Linux >= 6.1+ (LTS с поддержкой eBPF и BBR) |
| **CPU** | 4 ядра x86_64 | 8–16+ ядер с аппаратной поддержкой AES-NI |
| **RAM** | 4 ГБ | 16+ ГБ (под зоны Angie, conntrack, nftables sets) |
| **Сеть** | 1 Гбит/с NIC | 10–25 Гбит/с NIC с очередями RSS и разгрузкой LRO/GRO |
| **ПО** | Angie >= 1.12.0, nftables >= 1.0, fail2ban >= 0.11 | Angie PRO (для cluster zone sync), wrk, slowhttptest |

---

### Сценарий 1: Двухфазный Rate Limiting с защитой API и белыми списками

Реализация строгого лимитирования запросов к API с выделением доверенных клиентов (внутренние сети, офисные IP, мониторинг), раздельными зонами и двухфазным сглаживанием всплесков (`delay`).

```nginx
# /etc/angie/http.d/rate_limiting.conf

# 1. Формирование ключа: для доверенных IP ключ пустой (лимит не применяется)
geo $whitelist_client {
    default        0;
    127.0.0.1/32   1;
    10.0.0.0/8     1;
    192.168.1.0/24 1;
    198.51.100.10  1; # Сервер мониторинга
}

map $whitelist_client $limit_key {
    0       $binary_remote_addr;
    1       "";
}

# 2. Определение зон в разделяемой памяти
# 20 МБ хранят около 1.3 млн состояний клиентов
limit_req_zone $limit_key zone=api_general:20m rate=10r/s;
limit_req_zone $limit_key zone=login_strict:10m rate=1r/s;

# 3. Настройка кодов и журналирования
limit_req_status 429;
limit_req_log_level warn;

server {
    listen 443 ssl;
    server_name api.example.internal;

    # SSL-сертификаты опущены для лаконичности

    # Кастомная страница ошибки 429 с передачей заголовка Retry-After
    error_page 429 = @rate_limited;

    location @rate_limited {
        add_header Retry-After 5 always;
        add_header Content-Type application/json always;
        return 429 '{"error":"Too Many Requests","message":"Rate limit exceeded. Retry in 5 seconds."}\n';
    }

    # Общие эндпоинты API: burst 20, первые 10 без задержки, далее сглаживание
    location /api/v1/ {
        limit_req zone=api_general burst=20 delay=10;
        proxy_pass http://backend_api_upstream;
    }

    # Критичные эндпоинты (аутентификация): burst 3 nodelay
    location /api/v1/auth/login {
        limit_req zone=login_strict burst=3 nodelay;
        proxy_pass http://backend_auth_upstream;
    }
}
```

**Валидация и проверка:**

```bash
# 1. Проверка синтаксиса и перезагрузка
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
systemctl reload angie

# 2. Тестирование сглаживания запросов через curl (30 быстрых запросов)
for i in {1..25}; do curl -s -o /dev/null -w "%{http_code}\n" https://api.example.internal/api/v1/status; done | sort | uniq -c
# →     20 200
# →      5 429

# 3. Проверка заголовка Retry-After
curl -i https://api.example.internal/api/v1/auth/login
# → HTTP/1.1 429 Too Many Requests
# → Retry-After: 5
# → Content-Type: application/json
```

---

### Сценарий 2: Ограничение соединений (limit_conn)

Защита пула дескрипторов и памяти воркеров от исчерпания при открытии тысяч параллельных соединений с одного адреса или лавины соединений на виртуальный хост.

```nginx
# /etc/angie/http.d/conn_limiting.conf

# Зона perip: 10 МБ (~650 тыс. IPv4) для учета соединений с одного IP
limit_conn_zone $binary_remote_addr zone=addr_conn_limit:10m;

# Зона perserver: 2 МБ для ограничения суммарных одновременных сессий к серверу
limit_conn_zone $server_name zone=vhost_conn_limit:2m;

limit_conn_status 429;
limit_conn_log_level warn;

server {
    listen 443 ssl;
    server_name app.example.internal;

    # Максимум 30 одновременных активных соединений с одного IP
    limit_conn addr_conn_limit 30;

    # Максимум 10 000 суммарных активных соединений на весь виртуальный сервер
    limit_conn vhost_conn_limit 10000;

    location / {
        proxy_pass http://backend_app;
    }
}
```

**Валидация и проверка:**

```bash
# Проверка текущего количества открытых соединений процессами Angie
ss -tan state established '( dport = :443 or sport = :443 )' | wc -l
# → 142

# Тест блокировки при попытке открыть параллельные постоянные соединения
seq 1 40 | xargs -n 1 -P 40 curl -s -o /dev/null -w "%{http_code}\n" https://app.example.internal/
# → Большая часть вернет 200, превышающие 30 параллельных потоков получат 429
```

---

### Сценарий 3: Кластерная синхронизация лимитов (Angie PRO)

В кластере из нескольких нод Angie без синхронизации атакующий может распределять запросы между серверами, кратно превышая порог безопасности. Модуль `zone_sync` в блоке `stream` реплицирует счетчики лимитов между узлами в реальном времени.

```nginx
# /etc/angie/angie.conf

stream {
    # Включение механизма кластерной синхронизации зон
    zone_sync;

    server {
        # Порт для межкластерного обмена (строго закрывать фаерволом от внешней сети!)
        listen 10.0.0.1:9000;

        # Список партнерских нод кластера
        zone_sync_server 10.0.0.1:9000;
        zone_sync_server 10.0.0.2:9000;
        zone_sync_server 10.0.0.3:9000;

        # Буферы и таймауты кластерного протокола
        zone_sync_buffers 256 4k;
        zone_sync_timeout 5s;
    }
}

http {
    # Параметр sync предписывает реплицировать счетчики зоны
    limit_req_zone $binary_remote_addr zone=cluster_api:20m rate=15r/s sync;
    limit_conn_zone $binary_remote_addr zone=cluster_conn:10m sync;

    server {
        listen 443 ssl;
        server_name api.example.internal;

        location /api/ {
            limit_req zone=cluster_api burst=30 nodelay;
            limit_conn cluster_conn 20;
            proxy_pass http://backend;
        }
    }
}
```

**Валидация и проверка статуса синхронизации:**

```bash
# Запрос статуса кластера через Angie Console / REST API
curl -s http://127.0.0.1:8000/api/v1/stream/zone_sync | jq .
# → {
# →   "zones": {
# →     "cluster_api": { "records_pending": 0, "records_total": 4512 },
# →     "cluster_conn": { "records_pending": 0, "records_total": 128 }
# →   },
# →   "status": { "nodes_online": 3 }
# → }
```

---

### Сценарий 4: Защита от медленных атак (Slowloris, Slow POST, Slow Read)

Медленные атаки удерживают воркер-процессы Angie в ожидании заголовков или фрагментов тела запроса. Защита реализуется через жесткое сокращение таймаутов без ущерба для пользователей мобильных сетей.

```nginx
# /etc/angie/http.d/slow_attacks_tuning.conf

http {
    # 1. Таймаут на получение всего заголовка запроса (10 секунд достаточно для любого клиента)
    client_header_timeout 10s;

    # 2. Таймаут между двумя последовательными операциями чтения тела запроса
    # Если за 10 секунд клиент ничего не передал — соединение обрывается со статусом 408
    client_body_timeout 10s;

    # 3. Таймаут передачи ответа клиенту (защита от медленно читающих атакующих)
    send_timeout 10s;

    # 4. Тюнинг Keep-Alive: удерживать соединение не более 65 секунд
    # Закрывать сессию после 1000 последовательных запросов во избежание утечек
    keepalive_timeout 65s 20s;
    keepalive_requests 1000;

    # 5. Сброс зависших сокетов по таймауту (TCP RST вместо ожидания FIN/TIME_WAIT)
    reset_timedout_connection on;
}
```

**Валидация защищенности с помощью slowhttptest:**

```bash
# Тест уязвимости к Slowloris (попытка удержать 500 соединений медленными заголовками)
slowhttptest -H -c 500 -g -o slowloris_report -i 10 -r 100 -t GET -u https://api.example.internal/ -x 24 -p 3

# Результат в консоли slowhttptest:
# → Test ended: service is NOT vulnerable (connections dropped by timeout)
# → Closed connections: 500 (по истечении client_header_timeout)
```

---

### Сценарий 5: Защита HTTP/2 и HTTP/3 (QUIC) от Rapid Reset и UDP Flood

Оптимизация протоколов HTTP/2 и HTTP/3 с устранением уязвимостей мультиплексирования и использованием eBPF-модуля `quic_bpf` для стабильности сессий.

```nginx
# /etc/angie/http.d/http2_http3_hardening.conf

server {
    # HTTP/3 через UDP
    listen 443 quic reuseport;
    # HTTP/2 и HTTP/1.1 через TCP/TLS
    listen 443 ssl;

    http2 on;
    http3 on;

    # 1. Защита от UDP Amplification/Spoofing в HTTP/3:
    # Сервер отправляет Stateless Retry пакет, проверяя владение IP-адресом
    quic_retry on;

    # 2. Разгрузка сегментации UDP на сетевую карту (GSO)
    quic_gso on;

    # 3. Привязка QUIC-потоков к воркерам через eBPF (предотвращает обрывы при reload)
    quic_bpf on;

    # 4. Ограничение одновременных потоков в одном соединении:
    # Защита от Rapid Reset (CVE-2023-44487) и исчерпания памяти таблицей потоков
    http2_max_concurrent_streams 64;
    http3_max_concurrent_streams 64;

    # 5. Лимит на размер фрейма заголовка в HTTP/2
    http2_max_field_size 8k;
    http2_max_header_size 32k;

    # Добавление заголовка Alt-Svc для объявления поддержки HTTP/3
    add_header Alt-Svc 'h3=":443"; ma=86400' always;
}
```

**Валидация и проверка:**

```bash
# Проверка доступности порта UDP/443
ss -ulnp | grep 443
# → UNCONN 0 0 0.0.0.0:443 0.0.0.0:* users:(("angie",pid=1234,fd=12))

# Проверка соединения по HTTP/3 с принудительным флагом
curl -I --http3-only https://api.example.internal/
# → HTTP/3 200
# → alt-svc: h3=":443"; ma=86400
```

---

### Сценарий 6: Тюнинг буферов и ограничение заголовков

Защита от переполнения оперативной памяти при атаках типа HPACK Bomb, Large Body Flood и Cookie/Header Stuffing.

```nginx
# /etc/angie/http.d/buffers_hardening.conf

http {
    # Базовый буфер для заголовков клиента
    client_header_buffer_size 2k;

    # Максимальное количество и размер дополнительных буферов для больших заголовков
    # (до 4 буферов по 8 КБ)
    large_client_header_buffers 4 8k;

    # Лимит максимального количества заголовков в одном запросе
    # Защищает от атак на алгоритм разбора заголовков
    max_headers 50;

    # Ограничение размера тела запроса (предотвращает заливку больших объемов мусора)
    client_max_body_size 10m;

    # Буфер для чтения тела запроса в память (всё, что больше, пишется во временный файл)
    client_body_buffer_size 128k;
}
```

---

### Сценарий 7: Географическая фильтрация и поведенческие белые списки (GeoIP2)

Отсечение трафика из нецелевых географических регионов на базе локальных бинарных баз данных MaxMind GeoLite2 (`.mmdb`) без внешних сетевых вызовов.

```nginx
# /etc/angie/http.d/geoip_filtering.conf

http {
    # Загрузка локальной базы GeoLite2 Country
    geoip2 /etc/angie/geo/GeoLite2-Country.mmdb {
        auto_reload 1h;
        $geoip2_country_code default=XX country iso_code;
    }

    # Белый список стран (разрешены только целевые рынки)
    map $geoip2_country_code $access_allowed {
        default 0;
        RU      1;
        BY      1;
        KZ      1;
    }

    # Исключение для поисковых ботов и внутренних подсетей
    geo $bypass_geo {
        default        0;
        10.0.0.0/8     1;
        198.51.100.0/24 1;
    }

    server {
        listen 443 ssl;
        server_name portal.example.internal;

        location / {
            # Если IP не в белом списке и страна не разрешена — возврат 403
            if ($bypass_geo = 0) {
                set $rule_check "G${access_allowed}";
            }
            if ($rule_check = "G0") {
                return 403 '{"error":"Forbidden","message":"Access restricted by geographical policy"}\n';
            }

            proxy_pass http://backend_portal;
        }
    }
}
```

---

### Сценарий 8: Защита от HTTP Request Smuggling и нормализация запросов

Защита от рассинхронизации парсинга HTTP между обратным прокси Angie и upstream-серверами (CL.TE, TE.CL, TE.TE уязвимости).

```nginx
# /etc/angie/http.d/request_smuggling_defense.conf

http {
    # 1. Запрет подчеркиваний в заголовках (защита от спуфинга заголовков в CGI/WSGI)
    underscores_in_headers off;

    # 2. Нормализация URI: схлопывание множественных слэшей //path -> /path
    merge_slashes on;

    # 3. Игнорирование недопустимых заголовков
    ignore_invalid_headers on;

    server {
        listen 443 ssl;
        server_name secure.example.internal;

        # 4. Строгая фильтрация разрешенных HTTP-методов
        # Блокировка TRACE, CONNECT, DEBUG и неизвестных команд
        if ($request_method !~ ^(GET|HEAD|POST|PUT|DELETE|PATCH|OPTIONS)$) {
            return 405;
        }

        location / {
            # Принудительная передача HTTP/1.1 на бэкенд
            proxy_http_version 1.1;

            # Очистка заголовка Connection для предотвращения скрытого туннелирования
            proxy_set_header Connection "";

            # Передача строго одного заголовка Host
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_pass http://internal_backend;
        }
    }
}
```

---

### Сценарий 9: Кэширование как барьер от DoS и предотвращение Thundering Herd

При DoS-атаке на динамические эндпоинты тысячи запросов могут пробить бэкенд (эффект Thundering Herd). Директива `proxy_cache_lock` гарантирует, что к бэкенду за объектом обратится только один запрос, а остальные будут ожидать его ответа в shared memory.

```nginx
# /etc/angie/http.d/caching_shield.conf

# Создание зоны кэша в разделяемой памяти и на диске
proxy_cache_path /var/cache/angie/dos_shield
                 levels=1:2
                 keys_zone=shield_cache:50m
                 max_size=5g
                 inactive=30m
                 use_temp_path=off;

server {
    listen 443 ssl;
    server_name catalog.example.internal;

    location /catalog/ {
        proxy_cache shield_cache;
        proxy_cache_key "$scheme$request_method$host$request_uri";
        proxy_cache_valid 200 302 5m;
        proxy_cache_valid 404 1m;

        # Анти-лавина (Thundering Herd Protection):
        # Только один запрос уходит на бэкенд при промахе кэша
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_lock_age 10s;

        # Отдача устаревшего кэша при отказе или перегрузке бэкенда
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;

        # Заголовок для отладки статуса кэша (HIT/MISS/BYPASS/UPDATING)
        add_header X-Cache-Status $upstream_cache_status always;

        proxy_pass http://backend_catalog;
    }
}
```

---

### Сценарий 10: Ограничение пропускной способности (Bandwidth Limiting)

Предотвращение атак на полосу пропускания при выкачивании крупных файлов или медиа-контента.

```nginx
# /etc/angie/http.d/bandwidth_limiting.conf

server {
    listen 443 ssl;
    server_name files.example.internal;

    location /downloads/ {
        # Первые 10 МБ передаются на максимальной скорости канала
        limit_rate_after 10m;

        # Далее скорость отдачи жестко ограничивается до 500 КБ/с на соединение
        limit_rate 500k;

        # Ограничение входящего потока данных при загрузке файлов клиентом
        client_body_timeout 15s;

        alias /data/public_files/;
    }
}
```

---

### Сценарий 11: Системный hardening ядра Linux (sysctl) и лимиты ulimit

Отказоустойчивость Angie под нагрузкой опирается на тюнинг параметров сетевого стека Linux и лимиты файловых дескрипторов.

#### Конфигурация ядра `/etc/sysctl.d/99-security-highload.conf`

```ini
# Включение SYN Cookies (защита от SYN Flood без расхода памяти под полуоткрытые сокеты)
net.ipv4.tcp_syncookies = 1

# Увеличение длины очереди полуоткрытых соединений (SYN backlog)
net.ipv4.tcp_max_syn_backlog = 16384

# Увеличение максимальной очереди входящих соединений на сокете (somaxconn)
net.core.somaxconn = 65535

# Увеличение длины очереди пакетов сетевого интерфейса до обработки ядром
net.core.netdev_max_backlog = 16384

# Сокращение таймаута удержания сокетов в состоянии FIN-WAIT-2
net.ipv4.tcp_fin_timeout = 15

# Ограничение повторов SYN+ACK пакетов (сокращает время удержания полуоткрытых соединений)
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_syn_retries = 2

# Защита от спуфинга IP-адресов на базе строгой обратной маршрутизации (BCP 38)
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# Отключение обработки ICMP Redirect (предотвращает спуфинг маршрутизации)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0

# Игнорирование широковещательных ICMP эхо-запросов (защита от Smurf-атак)
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Тюнинг таблицы отслеживания соединений Netfilter (conntrack)
# Рассчитано на системы с 16+ ГБ RAM
net.netfilter.nf_conntrack_max = 2097152
net.netfilter.nf_conntrack_buckets = 524288
net.netfilter.nf_conntrack_tcp_timeout_established = 600
net.netfilter.nf_conntrack_tcp_timeout_syn_recv = 15
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 15

# Глобальный лимит дескрипторов файлов в системе
fs.file-max = 2097152
```

Применение параметров:

```bash
sysctl --system
# → net.ipv4.tcp_syncookies = 1
# → net.ipv4.tcp_max_syn_backlog = 16384
# → net.core.somaxconn = 65535
# → net.netfilter.nf_conntrack_max = 2097152
```

#### Настройка ulimit и systemd для процессов Angie

Для обслуживания 100 000+ одновременных сессий воркеры Angie должны обладать расширенным лимитом открытых файлов.

```bash
# 1. Создание systemd drop-in файла
mkdir -p /etc/systemd/system/angie.service.d/
cat <<'EOF' > /etc/systemd/system/angie.service.d/override.conf
[Service]
LimitNOFILE=262144
LimitNPROC=262144
EOF

# 2. Обновление systemd и директива в angie.conf
systemctl daemon-reload
```

В секции `events` файла `/etc/angie/angie.conf`:

```nginx
worker_processes auto;
worker_rlimit_nofile 262144;

events {
    worker_connections 65535;
    use epoll;
    multi_accept on;
}
```

Проверка реального лимита работающего воркера:

```bash
PID=$(pgrep -f "angie: worker" | head -n 1)
grep "open files" /proc/$PID/limits
# → Max open files            262144               262144               files
```

---

### Сценарий 12: Фильтрация пакетов на L3/L4 через nftables (O(1) sets)

Использование `nftables` с динамическими `sets` позволяет отбрасывать пакеты атакующих с минимальной задержкой до их попадания в сокеты Angie.

```nft
# /etc/nftables.conf

flush ruleset

table inet filter {
    # Сет для динамической блокировки хостов (fail2ban, ручной бан)
    set blackhole {
        type ipv4_addr
        flags timeout
        size 65536
    }

    # Сет для ограничения частоты новых TCP SYN-соединений
    set syn_flooders {
        type ipv4_addr
        flags timeout
        timeout 60s
        size 65536
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить трафик локальной петли
        iif "lo" accept

        # Разрешить установленные и связанные соединения
        ct state established,related accept

        # Немедленный сброс невалидных пакетов (защита от сканеров и мусорных флагов)
        ct state invalid drop

        # Блокировка адресов из сета blackhole со счетчиком сброшенных пакетов
        ip saddr @blackhole counter drop

        # Защита от SYN Flood: лимит 25 новых соединений в секунду с одного IP на веб-порты
        tcp dport { 80, 443 } tcp flags syn meter syn_meter { ip saddr limit rate over 25/second } add @blackhole { ip saddr timeout 10m } counter drop

        # Разрешить легитимный веб-трафик к Angie
        tcp dport { 80, 443 } accept

        # Разрешить SSH с ограничением частоты подключений
        tcp dport 22 ct state new limit rate 5/minute accept

        # Разрешить безопасный ICMP (echo-request с лимитом)
        icmp type echo-request limit rate 5/second accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
```

**Проверка и управление правилами:**

```bash
# Валидация и загрузка конфигурации
nft -c -f /etc/nftables.conf
nft -f /etc/nftables.conf

# Просмотр содержимого сета blackhole
nft list set inet filter blackhole
# → table inet filter {
# →     set blackhole {
# →         type ipv4_addr
# →         flags timeout
# →         elements = { 198.51.100.55 timeout 9m42s }
# →     }
# → }
```

---

### Сценарий 13: Автоматическая блокировка нарушителей через fail2ban

Связка `fail2ban` и `nftables` анализирует лог доступа Angie и автоматически вносит IP-адреса, генерирующие всплески статусов `429`, `403` или `404`, в сет `blackhole`.

#### 1. Фильтр `/etc/fail2ban/filter.d/angie-dos.conf`

```ini
[Definition]
# Поиск повторяющихся статусов 429, 403, 404, а также сканирования уязвимостей
failregex = ^<HOST> -.* "(GET|POST|HEAD).*" (429|403) .*$
            ^<HOST> -.* "(GET|POST|HEAD) /.*(\.env|\.git|wp-login|actuator).*" 404 .*$

ignoreregex =
```

#### 2. Конфигурация джейла `/etc/fail2ban/jail.d/angie-dos.local`

```ini
[angie-dos]
enabled   = true
port      = http,https
filter    = angie-dos
logpath   = /var/log/angie/access.log
backend   = auto

# Если клиент получает 50 ошибок 429/403 в течение 60 секунд — блокировка на 1 час
maxretry  = 50
findtime  = 60
bantime   = 3600

# Использование прямого добавления в nftables set вместо создания цепочек iptables
banaction = nftables[type=multiport, table=filter, set_name=blackhole]
```

**Валидация регулярного выражения и проверка:**

```bash
# Проверка регулярных выражений на реальном логе
fail2ban-regex /var/log/angie/access.log /etc/fail2ban/filter.d/angie-dos.conf
# → Lines evaluated: 10450
# → Matched: 142

# Проверка статуса джейла
fail2ban-client status angie-dos
# → Status for the jail: angie-dos
# → |- Currently failed: 4
# → |- Total failed:     312
# → `- Currently banned: 2
# →    `- Banned IP list: 198.51.100.20 203.0.113.88
```

---

### Сценарий 14: Интеграция с локальным WAF (ModSecurity v3 / NAXSI)

Использование встроенного WAF на уровне Angie для выявления сигнатур сложных L7-атак без облачных сервисов.

```nginx
# /etc/angie/http.d/waf.conf

# Загрузка динамического модуля ModSecurity v3 (должен быть собран под текущую версию Angie)
load_module modules/ngx_http_modsecurity_module.so;

server {
    listen 443 ssl;
    server_name secure-portal.example.internal;

    # Включение WAF
    modsecurity on;
    modsecurity_rules_file /etc/angie/modsec/main.conf;

    location / {
        proxy_pass http://backend_portal;
    }
}
```

Файл базовых правил `/etc/angie/modsec/main.conf`:

```apache
# На этапе отладки: DetectionOnly. В production: On
SecRuleEngine On
SecRequestBodyAccess On
SecResponseBodyAccess Off

SecResponseBodyLimit 524288
SecRequestBodyLimit 13107200

# Логирование атак
SecAuditEngine RelevantOnly
SecAuditLogParts ABIJDEFHZ
SecAuditLogType Serial
SecAuditLog /var/log/angie/modsec_audit.log

# Подключение OWASP ModSecurity Core Rule Set (CRS)
Include /etc/angie/modsec/owasp-crs/crs-setup.conf
Include /etc/angie/modsec/owasp-crs/rules/*.conf
```

---

### Сценарий 15: Наблюдаемость, метрики и алертинг (Prometheus, Grafana, Loki)

#### 1. Метрики Angie (`status_zone` и API)

```nginx
# /etc/angie/http.d/monitoring.conf

http {
    # Сбор агрегированных метрик по виртуальным хостам
    server {
        listen 443 ssl;
        server_name api.example.internal;

        status_zone api_vhost;

        location / {
            proxy_pass http://backend;
        }
    }

    # Эндпоинт мониторинга для скрейпинга Prometheus (только локальный доступ)
    server {
        listen 127.0.0.1:8000;
        server_name localhost;

        location /status/ {
            status;
        }

        location /api/ {
            api;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

#### 2. Правила Prometheus Alertmanager (`/etc/prometheus/rules/dos_alerts.yml`)

```yaml
groups:
  - name: angie_dos_alerts
    rules:
      # 1. Всплеск отклоненных запросов по Rate Limiting (429)
      - alert: AngieRateLimitHighRejections
        expr: sum(rate(angie_http_responses_total{status="429"}[2m])) > 50
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Аномальный всплеск 429 Too Many Requests на {{ $labels.instance }}"
          description: "Частота отклонений превысила 50 rps (текущее: {{ $value }} rps). Возможна L7 DoS-атака."

      # 2. Исчерпание таблицы отслеживания соединений conntrack
      - alert: HostConntrackTableAlmostFull
        expr: (node_nf_conntrack_entries / node_nf_conntrack_entries_limit) > 0.85
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Таблица conntrack заполнена более чем на 85%"
          description: "Текущее заполнение: {{ $value | humanizePercentage }}. Риск отбрасывания пакетов ядром."

      # 3. Аномальный рост RPS входящего трафика
      - alert: AngieAbnormalTrafficSpike
        expr: sum(rate(angie_http_requests_total[5m])) > 5000
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Трафик вырос сверх порогового базового уровня (5000 rps)"
          description: "Текущая нагрузка {{ $value }} rps."
```

#### 3. LogQL-запросы для Loki

```logql
# Топ 10 IP-адресов, получающих ответы 429
topk(10, sum by (client_ip) (rate({job="angie_access"} |= " 429 " [5m])))

# Детекция сканирования путей и аномалий
sum by (status) (rate({job="angie_access"} |= "wp-login" or "actuator" [5m]))
```

---

### Сценарий 16: Стресс-тестирование и валидация политик защиты

Инженер SRE обязан протестировать срабатывание ограничений перед сдачей сервиса в эксплуатацию.

```bash
# 1. Тестирование Rate Limiting через wrk (400 одновременных соединений в течение 30 сек)
wrk -t8 -c400 -d30s --latency https://api.example.internal/api/v1/status

# Ожидаемый вывод:
# → Running 30s test @ https://api.example.internal/api/v1/status
# →   8 threads and 400 connections
# →   Thread Status:
# →     200 OK:           3150
# →     429 Too Many Req: 48920
# →   Latency 95%: 12.4ms, 99%: 18.2ms (сервер не деградировал)

# 2. Быстрая проверка предела burst через ab (ApacheBench)
ab -n 100 -c 20 https://api.example.internal/api/v1/auth/login
# → Complete requests:      100
# → Failed requests:        97 (Non-2xx responses: 97)
# → HTML transferred:       429 responses verified

# 3. Проверка поведения при медленных заголовках
slowhttptest -H -u https://api.example.internal/ -c 100 -r 20 -i 5 -t GET
# → Connections closed by server: 100 within 10 seconds
```

---

### Сценарий 17: Экстренный Runbook SRE при активной DDoS-атаке

Пошаговый регламент действий дежурного инженера при нештатном росте нагрузки и деградации бэкендов:

```
[ Шаг 1: Оценка симптомов ]
  ├── 1.1 Анализ текущего RPS и статус-кодов в реальном времени
  └── 1.2 Выявление IP-источников флуда через awk по access.log
            │
            ▼
[ Шаг 2: Экспресс-блокировка на L3/L4 ]
  ├── 2.1 Добавление атакующих сетей/IP в nftables set blackhole
  └── 2.2 Проверка состояния conntrack (dmesg | grep conntrack)
            │
            ▼
[ Шаг 3: Активация аварийного профиля Angie ]
  ├── 3.1 Переключение таймаутов на аварийные 5s (sed / include emergency.conf)
  ├── 3.2 Включение принудительного proxy_cache_lock и отдачи stale
  └── 3.3 Применение конфигурации: angie -t && angie -s reload
            │
            ▼
[ Шаг 4: Нормализация и расследование ]
  └── 4.1 Снятие дампов через tcpdump при необходимости
```

Команды экстренного реагирования:

```bash
# 1. Мониторинг распределения статус-кодов в реальном времени (по 1000 строк)
tail -n 1000 /var/log/angie/access.log | awk '{print $9}' | sort | uniq -c | sort -nr
# → 850 429
# → 120 200
# →  30 502

# 2. Поиск топ-20 агрессивных IP-адресов
awk '{print $1}' /var/log/angie/access.log | sort | uniq -c | sort -nr | head -n 20
# → 15420 198.51.100.99
# → 12110 203.0.113.14

# 3. Мгновенная блокировка топ-IP на уровне ядра (O(1) nftables set)
nft add element inet filter blackhole { 198.51.100.99 timeout 4h }
nft add element inet filter blackhole { 203.0.113.14 timeout 4h }

# 4. Активация аварийного профиля таймаутов в angie.conf
cat <<'EOF' > /etc/angie/http.d/00-emergency.conf
client_header_timeout 5s;
client_body_timeout 5s;
send_timeout 5s;
reset_timedout_connection on;
EOF

angie -t && systemctl reload angie
# → angie: configuration file test is successful
```

---

## Операции и команды

Справочник оперативных команд SRE и системного администратора для контроля состояния подсистем защиты.

| Область | Команда | Назначение | Ожидаемый результат / вывод |
| :--- | :--- | :--- | :--- |
| **Angie API** | `curl -s http://127.0.0.1:8000/api/v1/http/limit_reqs/` | Просмотр состояния всех зон `limit_req` | JSON с полями `passed`, `delayed`, `rejected` |
| **Angie API** | `curl -s http://127.0.0.1:8000/api/v1/http/limit_conns/` | Просмотр состояния зон `limit_conn` | JSON с текущим числом активных соединений |
| **Angie API** | `curl -s http://127.0.0.1:8000/api/v1/stream/zone_sync` | Мониторинг кластерной синхронизации (PRO) | JSON со статусом связности нод и очередей |
| **nftables** | `nft list set inet filter blackhole` | Просмотр списка активных банов | Перечень заблокированных IP с остаточным таймаутом |
| **nftables** | `nft add element inet filter blackhole { 192.0.2.1 timeout 1h }` | Ручной бан подозрительного IP на 1 час | Элемент добавлен в сет без перезагрузки правил |
| **nftables** | `nft delete element inet filter blackhole { 192.0.2.1 }` | Досрочный ручной разбан IP | Элемент удалён из сета |
| **fail2ban** | `fail2ban-client status angie-dos` | Проверка счетчиков блокировок джейла | Количество активных банов и список IP |
| **fail2ban** | `fail2ban-client set angie-dos unbanip 192.0.2.1` | Разблокировка IP через fail2ban | `192.0.2.1 unbanned` |
| **Ядро / Сокеты** | `ss -s` | Сводная статистика сокетов Linux | Число сокетов в `estab`, `synrecv`, `timewait` |
| **Ядро / conntrack** | `conntrack -S` | Статистика подсистемы отслеживания соединений | Счетчики `entries`, `searched`, `dropped` |
| **Ядро / conntrack** | `cat /proc/sys/net/netfilter/nf_conntrack_count` | Текущее количество записей conntrack | Число активных сессий (например, `85412`) |
| **Процессы** | `cat /proc/$(pgrep -f "angie: worker" \| head -1)/limits` | Проверка реальных лимитов ulimit воркера | `Max open files: 262144` |
| **Логи** | `tail -f /var/log/angie/error.log \| grep -E "limiting requests\|limiting connections"` | Просмотр срабатываний лимитов в реальном времени | `... limiting requests, excess: 20.450 by zone "api_general" ...` |

---

## Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Метод диагностики | Пошаговое решение |
| :--- | :--- | :--- | :--- |
| `nf_conntrack: table full, dropping packet` в `dmesg` | Исчерпана таблица отслеживания соединений ядра из-за SYN/UDP-флуда или Docker DNAT | `dmesg \| grep conntrack`<br>`conntrack -C` | 1. Немедленно увеличить: `sysctl -w net.netfilter.nf_conntrack_max=2097152`.<br>2. Сократить таймауты: `net.netfilter.nf_conntrack_tcp_timeout_established=600`.<br>3. Перевести мусорный трафик в `notrack` в таблице `raw` nftables. |
| `TCP: request_sock_TCP: Possible SYN flooding on port 443. Sending cookies.` | Переполнение очереди SYN backlog ядра при входящем SYN-флуде | `dmesg \| grep "SYN flooding"`<br>`netstat -s \| grep -i cookie` | 1. Убедиться, что включены куки: `sysctl -w net.ipv4.tcp_syncookies=1`.<br>2. Увеличить размер backlog: `sysctl -w net.ipv4.tcp_max_syn_backlog=16384` и `net.core.somaxconn=65535`.<br>3. Включить ограничение SYN-пакетов в `nftables`. |
| `24: Too many open files` в `error.log` Angie | Воркер исчерпал системный лимит файловых дескрипторов | `cat /proc/$PID/limits`<br>`lsof -p $PID \| wc -l` | 1. Добавить `LimitNOFILE=262144` в systemd override.<br>2. Задать `worker_rlimit_nofile 262144;` в `angie.conf`.<br>3. Проверить `fs.file-max` в `sysctl`. |
| Массовые жалобы легитимных клиентов на `429 Too Many Requests` | Офисная сеть или мобильный провайдер использует один публичный NAT IP | Анализ логов: `awk '$9==429 {print $1}' access.log \| sort \| uniq -c` | 1. Увеличить `burst` и добавить `delay=N` для сглаживания всплесков.<br>2. При наличии авторизации переключить ключ зоны с `$binary_remote_addr` на комбинацию IP + токен: `$binary_remote_addr$http_authorization`. |
| `ngx_slab_alloc() failed: no memory in limit_req_zone` | Закончилась выделенная разделяемая память (shared memory) зоны | `grep "no memory" /var/log/angie/error.log` | 1. Увеличить размер зоны в конфиге: с `zone=name:10m` до `zone=name:40m`.<br>2. Проверить, не используется ли текстовая строковая переменная вместо `$binary_remote_addr` (бинарный IP экономит до 75% памяти). |
| `zone_sync: connection to ... failed` (Angie PRO) | Ноды кластера не могут синхронизировать разделяемую память | `journalctl -u angie \| grep zone_sync`<br>`nc -zv 10.0.0.2 9000` | 1. Проверить сетевую связность и правила фаервола на порту 9000.<br>2. Убедиться, что имена зон в директивах `http` и размеры разделяемой памяти строго совпадают на всех нодах. |
| Клиент не видит, когда можно повторить запрос после 429 | Отсутствует заголовок `Retry-After` в ответе веб-сервера | `curl -i https://example.com/api` (проверка заголовков ответа) | Настроить `error_page 429 = @rate_limited;` с директивой `add_header Retry-After 5 always;` (согласно RFC 6585). |
| Ошибка `408 Request Timeout` у пользователей с медленным каналом | Слишком агрессивные таймауты `client_body_timeout` | Логи ошибок Angie с кодом 408 | Увеличить `client_body_timeout` до 15–20с для эндпоинтов загрузки медиа-файлов, изолировав их в отдельный `location`. |
| Всплеск задержки (Latency) при включении WAF ModSecurity | Парсинг тяжелых тел запросов или статических ответов правилами CRS | Мониторинг TTFB в Angie API и `modsec_audit.log` | 1. Отключить `SecResponseBodyAccess Off`.<br>2. Исключить статические пути (`/static/`, `/images/`) из проверки WAF.<br>3. Отрегулировать `SecRequestBodyLimit`. |

---

## Лучшие практики

### Архитектурные принципы защиты

1.  **Принцип разделения зон ответственности:** Фильтруйте мусорные пакеты максимально низко по стеку. Волюметрический флуд (UDP/ICMP/SYN) должен гаситься в `nftables` и ядре Linux, а Angie должен получать только семантически валидные TCP/TLS соединения.
2.  **Использование `$binary_remote_addr` вместо `$remote_addr`:** Всегда используйте бинарное представление IP-адреса в директивах `limit_req_zone` и `limit_conn_zone`. Для IPv4 это требует 4 байта вместо 7–15 байт, что экономит мегабайты shared memory в моменты атак.
3.  **Плавное ограничение (Two-stage rate limiting):** Избегайте использования жесткого `nodelay` без достаточного `burst`. Комбинация `burst=N delay=M` обеспечивает идеальный баланс: легитимные пользователи не получают ошибок при переходе между страницами приложения, а ботнеты эффективно замедляются и отсекаются.
4.  **Асинхронная отдача устаревшего кэша (`proxy_cache_use_stale`):** Кэш — лучший щит бэкенда. При падении бэкенда от DoS включение `proxy_cache_use_stale updating` позволяет Angie отдавать сохраненный контент легитимным клиентам со скоростью памяти, пока инженеры локализуют атаку.
5.  **Защита сокетов управления:** Эндпоинты Angie API, консоли и метрик (`/api/`, `/status/`, `/metrics`) должны быть привязаны строго к интерфейсу локальной петли (`127.0.0.1`) или выделенному изолированному VLAN управления и защищены взаимным TLS (mTLS) либо директивами `allow/deny`.
6.  **Безопасный откат конфигурации (Rollback Plan):** Держите версионированную конфигурацию в Git. Перед каждым применением боевых изменений обязательно проводите проверку синтаксиса `angie -t`. При блокировке критичных пользователей предусмотрите возможность быстрого сброса сета `nft flush set inet filter blackhole`.

### Чек-лист аудита безопасности и защиты от DoS (2026)

- [ ] **Ядро Linux:** Включены ли `tcp_syncookies = 1` и настроен ли `tcp_max_syn_backlog >= 16384`?
- [ ] **Сетевой стек:** Увеличен ли `net.core.somaxconn` до 65535, а `net.netfilter.nf_conntrack_max` — до 2 000 000+?
- [ ] **Лимиты дескрипторов:** Установлен ли `worker_rlimit_nofile >= 100000` в `angie.conf` и проверен ли `LimitNOFILE` в systemd?
- [ ] **Rate Limiting:** Настроен ли статус ответа `limit_req_status 429` (согласно стандарту RFC 6585) вместо дефолтного 503?
- [ ] **Сглаживание всплесков:** Настроены ли адекватные значения `burst` и `delay` для защиты API от ложных срабатываний?
- [ ] **Cluster Zone Sync:** Активирован ли модуль `zone_sync` (в Angie PRO) для горизонтально масштабируемых кластеров?
- [ ] **Защита от Slowloris:** Сокращены ли `client_header_timeout` и `client_body_timeout` до значений `<= 10s`?
- [ ] **Защита HTTP/3 (QUIC):** Включен ли параметр `quic_retry on` для защиты от UDP Amplification и настроен ли `quic_bpf on`?
- [ ] **Мультиплексирование:** Ограничено ли количество параллельных потоков HTTP/2 и HTTP/3 (`http2_max_concurrent_streams <= 128`)?
- [ ] **Thundering Herd:** Настроена ли директива `proxy_cache_lock on` на кэширующих прокси-серверах?
- [ ] **Пакетная фильтрация:** Настроен ли фаервол `nftables` с использованием динамических O(1) сетов со сроком жизни (`timeout`)?
- [ ] **Автоматизация:** Интегрирован ли `fail2ban` для автоматического бана хостов, вызывающих массовые ошибки 429/403?
- [ ] **Гео-блокировка:** Настроена ли фильтрация нецелевого трафика через локальные базы `GeoLite2` без обращения к внешним облакам?
- [ ] **Контрабанда запросов:** Включены ли `merge_slashes on;`, `underscores_in_headers off;` и жесткая валидация HTTP-методов?
- [ ] **Наблюдаемость:** Настроены ли алерты Prometheus по всплескам статусов 429/503 и заполнению таблицы conntrack?

---

## Дополнительная информация

*   **[Оптимизация производительности Angie](./performance_optimization.md)** — глубокая настройка воркеров, события epoll, kTLS и параметров throughput/latency.
*   **[Логирование в Angie](../angie_logging.md)** — форматирование структурированных JSON-логов для SIEM и систем анализа безопасности.
*   **[Директивы location в Angie](../angie_location_directives.md)** — приоритеты сопоставления путей, нормализация URI и директивы `status_zone`.
*   **[Настройка TLS в Angie](../angie_tls_setup.md)** — безопасная конфигурация шифров, OCSP Stapling и HTTP/3 (QUIC).
*   **[Обзор DoS/DDoS атак](../../../Security/ApplicationSecurity/ddos_overview.md)** — фундаментальная теория атак, классификация угроз и общая методология отражения.
*   **[Межсетевой экран веб-приложений (WAF)](../../../Security/ApplicationSecurity/waf.md)** — сигнатурный и поведенческий анализ прикладного уровня L7 (ModSecurity, NAXSI, OWASP CRS).
*   **[Безопасность HTTP в продакшене](../../../Networking/Protocols/HTTP/http_security_hardening.md)** — противодействие Request Smuggling, строгий парсинг RFC и защита заголовков.
