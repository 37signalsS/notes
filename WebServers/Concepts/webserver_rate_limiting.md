# Rate Limiting и защита от ботов в веб-серверах

**Актуально для:** Nginx 1.26+, Angie 1.8+, HAProxy 3.0+, Traefik 3.x, Apache 2.4.x

## Определения

**Rate Limiting** — механизм контроля и ограничения интенсивности входящих сетевых запросов от клиента (IP, сессия, токен, API-ключ) за определенный интервал времени для защиты инфраструктуры от перегрузки, исчерпания ресурсов и злоупотреблений.

**Burst (Всплеск)** — допустимое количество запросов сверх базовой установленной ставки (`rate`), которое веб-сервер временно удерживает в очереди или обрабатывает немедленно без возврата ошибки.

**Delay / NoDelay** — стратегия обработки запросов из буфера всплеска: постепенный пропуск запросов с искусственной задержкой по мере высвобождения слотов алгоритма либо мгновенная бесконфликтная передача бэкенду.

**Leaky Bucket (Протекающее ведро)** — алгоритм формирования трафика (traffic shaping), при котором запросы накапливаются в буфере фиксированного размера и уходят на обработку с строго постоянной скоростью. Избыточные запросы сбрасываются. Лежит в основе директив `limit_req` в Nginx и Angie.

**Token Bucket (Ведро с токенами)** — алгоритм, при котором токены непрерывно генерируются с фиксированной скоростью до максимальной емкости корзины. Входящий запрос требует токен; при наличии токенов всплески запросов обрабатываются мгновенно на полной скорости. Используется в Traefik и Envoy.

**Sliding Window (Скользящее окно)** — алгоритм подсчета событий, агрегирующий число запросов за непрерывно смещающийся временной интервал (например, последние 10 секунд). Исключает граничные всплески (boundary burst), характерные для алгоритма фиксированного окна (Fixed Window). Реализован в таблицах состояний HAProxy Stick Tables.

**Stick Table** — высокопроизводительная структура данных в разделяемой оперативной памяти HAProxy, предназначенная для отслеживания счетчиков запросов, ошибок, частоты соединений и метаданных сессий в реальном времени.

**Concurrency / In-Flight Limiting** — ограничение числа одновременно открытых TCP-соединений или параллельно обрабатываемых HTTP-запросов от одного клиента. В Nginx/Angie реализуется модулем `limit_conn`, в Traefik — middleware `inFlightReq`.

**Slab Allocator (Аллокатор slab)** — механизм управления разделяемой памятью (`shm`) в веб-серверах, выделяющий память фиксированными блоками (chunks) для хранения структур состояний (IP-адреса, счетчики). Позволяет обновлять лимиты нескольким воркер-процессам без межпроцессных блокировок операционной системы.

**Dry-Run (Тестовый режим)** — режим инспекции работы правил ограничения, при котором превышение лимитов регистрируется в журналах событий, но реальный сброс клиентских запросов не выполняется (`limit_req_dry_run on` в Nginx/Angie).

**RFC 6585 (HTTP 429 Too Many Requests)** — стандартный статус ответа HTTP, уведомляющий клиента о превышении лимита скорости, сопровождаемый рекомендательным заголовком `Retry-After`.

---

## Архитектура и принципы работы

### Алгоритмы ограничения интенсивности трафика

| Алгоритм | Принцип работы | Поведение при всплеске | Реализация |
| :--- | :--- | :--- | :--- |
| **Leaky Bucket** | Входящие запросы наполняют очередь; обработка идет с жестко заданной фиксированной скоростью. | Всплеск буферизуется до размера очереди (`burst`), остаток сбрасывается. | Nginx (`limit_req`), Angie |
| **Token Bucket** | Корзина пополняется токенами со скоростью $R$. Запрос забирает токен. | Допускается мгновенный взрывной трафик в объеме накопленных токенов. | Traefik (`rateLimit`), Envoy |
| **Sliding Window Counter** | Запросы суммируются за плавающее временное окно с взвешиванием долей предыдущего интервала. | Плавный учет без всплесков на стыке минут/секунд. | HAProxy (`stick-table`) |
| **Fixed Window** | Простой счетчик за календарный период (минута, секунда) со сбросом в ноль. | Уязвим к всплескам двойного объема на границе интервала. | Apache (`mod_evasive`) |

### Механизмы работы Leaky Bucket и фазы всплесков в Nginx и Angie

Директива `limit_req_zone` задает базовую частоту: значение `rate=10r/s` математически означает выделение **одного слота каждые 100 миллисекунд**, а не произвольные 10 запросов в любую секунду.

```
Входящий запрос
      │
      ▼
[ Есть свободный слот rate? ] ──(Да)──> [ Мгновенная обработка бэкендом ]
      │
     (Нет)
      ▼
[ Настроен burst? ]
   ├── (Нет) ─────────────────────────> [ Отклонение: 429 Too Many Requests ]
   └── (Да)
        ▼
   [ Заполнен буфер burst? ] ─────────> [ Отклонение: 429 Too Many Requests ]
        │
       (Есть место)
        ▼
   [ Проверка директив nodelay / delay ]
        ├── Без параметров: запрос засыпает и ждет своего слота (100мс, 200мс...)
        ├── nodelay: запрос выполняется сразу, но слот burst помечается занятым
        └── delay=N: первые N запросов идут мгновенно, остальные N+1..burst задерживаются
```

*   **Классический режим (без `nodelay`):** При `rate=10r/s burst=5` клиент, приславший 5 запросов одновременно, получит первый ответ сразу, второй — через 100 мс, третий — через 200 мс, четвертый — через 300 мс, пятый — через 400 мс. Это сглаживает трафик (traffic shaping), но повышает задержку для интерактивных веб-страниц.
*   **Режим `nodelay`:** Запросы из буфера `burst` обслуживаются немедленно. Если буфер исчерпан, все последующие запросы отклоняются с кодом 429 до момента освобождения слотов по ставке `rate`.
*   **Двухфазный режим (`delay=N`):** Появился в Nginx 1.15.7+. Первые $N$ запросов всплеска пропускаются мгновенно, а последующие запросы всплеска (до предела `burst`) искусственно замедляются.

### Управление памятью и структура данных (Slab Allocator, RB-Tree, LRU)

В Nginx и Angie состояние лимитов хранится в разделяемой памяти (shared memory):

1.  **Красно-черное дерево (Red-Black Tree):** Обеспечивает быстрый поиск структуры клиента по ключу (бинарный IP) за время $O(\log N)$.
2.  **LRU-очередь (Least Recently Used):** Связывает узлы в порядке давности обращения. При нехватке памяти удаляются самые старые неактивные узлы.
3.  **Потребление памяти:** 
    *   При использовании ключа `$binary_remote_addr` размер структуры для IPv4 составляет 64 байта (на 64-битной архитектуре) или 128 байт (с учетом служебных заголовков аллокатора slab).
    *   Зона объемом **10 МБ** способна хранить состояние примерно **160 000 уникальных IPv4-адресов** или 80 000 IPv6-адресов.
    *   Использование строковой переменной `$remote_addr` вместо бинарной `$binary_remote_addr` увеличивает расход памяти в 2–4 раза.

### Stick Tables и распределенное состояние в HAProxy

HAProxy использует внутренние таблицы `stick-table` в оперативной памяти:
*   Каждая запись связывает ключ (IPv4, IPv6, целочисленный ID, строка) с набором счетчиков: `http_req_rate(10s)`, `conn_rate(3s)`, `http_err_rate(10s)`, `gpc0` (общий счетчик инцидентов).
*   Таблицы могут реплицироваться между независимыми нодами балансировщика через сетевой протокол **HAProxy Peers** без участия внешних баз данных или Redis, обеспечивая согласованный кластерный rate limiting на голом железе и виртуальных машинах.

### Идентификация клиента: Client IP, заголовки и доверенные прокси

Если веб-сервер размещен за L4/L7-балансировщиком, ingress-контроллером или корпоративным прокси, переменная сетевого адреса сокета (`$remote_addr` в Nginx или `src` в HAProxy) содержит адрес промежуточного узла. Без настройки восстановления реального адреса все клиенты попадут под один глобальный счетчик:

*   **Nginx / Angie:** Требуется модуль `ngx_http_realip_module`, директивы `set_real_ip_from <CIDR>` и `real_ip_header X-Forwarded-For` (или `proxy_protocol`).
*   **HAProxy:** Использование выражений `req.hdr_ip(X-Forwarded-For,-1)` вместо `src` при работе за внешними терминаторами TLS.
*   **Пустые ключи (Empty Keys):** В Nginx и Angie, если вычисленное значение ключа в `limit_req_zone` оказывается пустой строкой `""`, учет запроса не производится. Это основа для создания динамических белых списков.

### Стандартные заголовки RFC 6585 и IETF RateLimit

При отклонении запроса сервер должен возвращать код `429 Too Many Requests` (а не `503` или `403`) и сопровождать его информационными заголовками:

*   `Retry-After: <seconds>` — время в секундах, по истечении которого клиент может повторить попытку (RFC 6585).
*   `RateLimit-Limit: <number>` — предельное число запросов за квотируемый период (проект стандарта IETF).
*   `RateLimit-Remaining: <number>` — оставшееся количество запросов в текущем окне.
*   `RateLimit-Reset: <seconds>` — число секунд до полного сброса счетчика.

---

## Практические сценарии и конфигурация

### Сценарий 1: Двухфазный Rate Limiting с задержкой и всплеском (Nginx и Angie)

Сценарий реализует защиту публичного API: базовая ставка — 10 запросов в секунду, допускается резкий всплеск до 20 запросов. Первые 10 запросов всплеска идут без задержки, запросы с 11 по 20 плавно притормаживаются, сверх 20 — мгновенно сбрасываются с кодом 429.

```nginx
http {
    # 20 МБ выделено под хранение ~320 000 IP-адресов
    limit_req_zone $binary_remote_addr zone=api_limit_zone:20m rate=10r/s;

    # Возвращать стандартный статус 429 вместо устаревшего 503
    limit_req_status 429;
    limit_req_log_level warn;

    server {
        listen 80;
        listen 443 ssl;
        server_name api.example.com;

        # Восстановление реального IP от балансировщика
        set_real_ip_from 192.168.1.0/24;
        set_real_ip_from 10.10.0.0/16;
        real_ip_header X-Forwarded-For;
        real_ip_recursive on;

        location /api/v1/ {
            # burst=20: размер буфера очереди
            # delay=10: первые 10 запросов сверх rate пропускаются мгновенно
            limit_req zone=api_limit_zone burst=20 delay=10;

            # Информационный заголовок для клиентов
            add_header Retry-After 1 always;

            proxy_pass http://api_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
    }
}
```

### Сценарий 2: Защита эндпоинтов аутентификации от Brute-Force перебора

Строгий лимит на чувствительные адреса (`/login`, `/auth`, `/reset-password`) с отдачей структурированного JSON-ответа при превышении.

```nginx
http {
    # 1 запрос в 2 секунды (30 запросов в минуту) на учетную запись или IP
    limit_req_zone $binary_remote_addr zone=login_zone:10m rate=30r/m;

    server {
        listen 443 ssl;
        server_name id.example.com;

        location = /api/auth/login {
            limit_req zone=login_zone burst=3 nodelay;
            limit_req_status 429;

            # Перехват ошибки и возврат кастомного JSON
            error_page 429 = @rate_limited_json;

            proxy_pass http://auth_cluster;
        }

        location @rate_limited_json {
            default_type application/json;
            add_header Retry-After 2 always;
            return 429 '{"error":"too_many_requests","message":"Превышен лимит попыток входа. Повторите через 2 секунды."}\n';
        }
    }
}
```

### Сценарий 3: Динамический Rate Limiting с белыми списками (Whitelisting через geo и map)

Исключение доверенных сетей мониторинга, офисных подсетей и внутренних сервисов из-под ограничений с дифференциацией лимитов для авторизованных клиентов.

```nginx
http {
    # 1. Проверка адреса клиента по гео-карте
    geo $whitelist_ip {
        default        0;
        127.0.0.1/32   1; # Localhost
        10.0.0.0/8     1; # Внутренняя сервисная сеть
        192.168.10.50  1; # Сервер Prometheus / синтетического мониторинга
    }

    # 2. Если IP в белом списке — ключ пустой (лимит отключен)
    # Если передан заголовок авторизации — лимит считается по токену, иначе — по IP
    map $whitelist_ip $rate_key {
        1       "";
        default $client_identifier;
    }

    map $http_authorization $client_identifier {
        ""      $binary_remote_addr;
        default $http_authorization;
    }

    limit_req_zone $rate_key zone=dynamic_zone:20m rate=20r/s;

    server {
        listen 443 ssl;
        server_name service.example.com;

        location / {
            limit_req zone=dynamic_zone burst=40 nodelay;
            limit_req_status 429;

            proxy_pass http://app_upstream;
        }
    }
}
```

### Сценарий 4: Ограничение параллельных соединений и медленных атак (limit_conn)

Защита от исчерпания пула соединений воркеров (`worker_connections`) отдельными клиентами и медленных атак (Slowloris, Slow POST).

```nginx
http {
    # Зона соединений по IP
    limit_conn_zone $binary_remote_addr zone=conn_ip_zone:10m;
    # Зона соединений на весь виртуальный хост
    limit_conn_zone $server_name zone=conn_vhost_zone:10m;

    limit_conn_status 429;
    limit_conn_log_level warn;

    server {
        listen 443 ssl;
        server_name downloads.example.com;

        # Не более 10 одновременных TCP-сессий с одного IP
        limit_conn conn_ip_zone 10;
        # Не более 5000 одновременных TCP-сессий на весь сервер
        limit_conn conn_vhost_zone 5000;

        # Защита от Slowloris: агрессивные таймауты чтения заголовков и тела
        client_header_timeout 10s;
        client_body_timeout   10s;
        send_timeout          10s;
        keepalive_timeout     30s 15s;

        location /files/ {
            # Ограничение скорости отдачи трафика (500 КБ/с на поток после первого мегабайта)
            limit_rate_after 1m;
            limit_rate 500k;

            root /data/storage;
        }
    }
}
```

### Сценарий 5: Высокоточный Rate Limiting в HAProxy на базе Stick Tables

Конфигурация отслеживания частоты запросов за скользящее 10-секундное окно с отдачей 429 и заголовка `Retry-After`.

```haproxy
global
    stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners
    stats timeout 30s

defaults
    mode http
    timeout connect 5s
    timeout client  30s
    timeout server  30s

# Вспомогательный бэкенд, хранящий таблицу состояний
backend st_rates
    stick-table type ip size 200k expire 2m store http_req_rate(10s),http_err_rate(10s),conn_cur

frontend fe_main
    bind *:80
    bind *:443 ssl crt /etc/haproxy/certs/site.pem alpn h2,http/1.1

    # Регистрация IP в счетчике sc0 таблицы st_rates
    http-request track-sc0 src table st_rates

    # Ограничение: не более 50 соединений с одного IP
    http-request deny deny_status 429 content-type text/plain lf-string "Too many connections\n" if { sc0_conn_cur(st_rates) gt 50 }

    # Ограничение: не более 100 запросов за 10 секунд (в среднем >10 rps)
    http-request deny deny_status 429 hdr Retry-After 5 content-type text/plain lf-string "Rate limit exceeded. Try again in 5 seconds.\n" if { sc0_http_req_rate(st_rates) gt 100 }

    default_backend be_app

backend be_app
    balance roundrobin
    server web01 192.168.1.11:8080 check
    server web02 192.168.1.12:8080 check
```

### Сценарий 6: Кластерная репликация счетчиков HAProxy через peers (без внешнего хранилища)

Организация распределенного rate limiting между двумя серверами балансировки без обращения к Redis.

```haproxy
peers lb_cluster
    peer lb01 192.168.1.21:1024
    peer lb02 192.168.1.22:1024

backend st_cluster_rates
    # Синхронизация записей между пирами кластера
    stick-table type ip size 500k expire 5m store http_req_rate(10s) peers lb_cluster

frontend fe_cluster_in
    bind *:443 ssl crt /etc/haproxy/certs/site.pem
    http-request track-sc0 src table st_cluster_rates

    # Превышение общего лимита на любом из узлов блокируется на обоих
    http-request deny deny_status 429 if { sc0_http_req_rate(st_cluster_rates) gt 200 }

    default_backend be_app
```

### Сценарий 7: Rate Limiting и контроль параллелизма (In-Flight) в Traefik

Файл динамической конфигурации Traefik 3.x для ограничения вызовов API и одновременных сессий.

```yaml
http:
  routers:
    api-router:
      rule: "Host(`api.example.local`) && PathPrefix(`/v2`)"
      service: api-service
      entryPoints:
        - websecure
      middlewares:
        - mw-ratelimit
        - mw-inflight

  middlewares:
    # Ограничение частоты запросов (Token Bucket)
    mw-ratelimit:
      rateLimit:
        average: 50
        period: 1s
        burst: 100
        sourceCriterion:
          ipStrategy:
            depth: 1
            excludedIPs:
              - "10.0.0.0/8"
              - "192.168.1.0/24"

    # Ограничение параллельно обрабатываемых запросов на клиента
    mw-inflight:
      inFlightReq:
        amount: 20
        sourceCriterion:
          ipStrategy:
            depth: 1

  services:
    api-service:
      loadBalancer:
        servers:
          - url: "http://10.10.1.15:8080"
          - url: "http://10.10.1.16:8080"
```

### Сценарий 8: Защита от перегрузок и ограничение скорости в Apache HTTPD (mod_evasive и mod_ratelimit)

Комплексная защита сервера Apache: отражение HTTP-флуда через `mod_evasive`, ограничение скорости отдачи контента через `mod_ratelimit` и противодействие медленным соединениям через `mod_reqtimeout`.

```apacheconf
# /etc/apache2/mods-available/evasive.conf
<IfModule mod_evasive20.c>
    # Размер хеш-таблицы IP-адресов
    DOSHashTableSize    3097
    # Не более 5 запросов к одной странице за 1 секунду
    DOSPageCount        5
    DOSPageInterval     1
    # Не более 50 запросов ко всему сайту за 1 секунду
    DOSSiteCount        50
    DOSSiteInterval     1
    # Блокировка на 10 секунд (сброс 403 Forbidden)
    DOSBlockingPeriod   10
    DOSLogDir           "/var/log/apache2/mod_evasive"
    # Системная команда при срабатывании бана (интеграция с firewall)
    DOSSystemCommand    "/usr/local/bin/ban_ip.sh %s"
</IfModule>

# /etc/apache2/conf-available/timeouts-and-limits.conf
# Защита от Slowloris: таймаут чтения заголовков (10-20с) и тела (10-30с)
<IfModule mod_reqtimeout.c>
    RequestReadTimeout header=10-20,MinRate=500 body=10-30,MinRate=500
</IfModule>

# Ограничение скорости отдачи трафика (модуль mod_ratelimit)
<Location /downloads>
    SetOutputFilter RATE_LIMIT
    # Ограничение: 400 КБ/с (в Кбит/с: 400 * 8 = 3200)
    SetEnv rate-limit 3200
    SetEnv rate-initial-burst 6400
</Location>
```

### Сценарий 9: L7-фильтрация вредоносных ботов и сканеров

Блокировка автоматизированных сканеров уязвимостей, парсеров и пустых User-Agent до попадания в тяжелые зоны лимитов и бэкенды. Подробное руководство по поведенческой защите представлено в [Защите веб-серверов от ботов](./bot_protection.md).

```nginx
http {
    # Сопоставление нежелательных User-Agent
    map $http_user_agent $bad_bot_detected {
        default         0;
        ""              1; # Запросы без User-Agent
        ~*(nikto|sqlmap|nmap|acunetix|masscan|hydra) 1; # Сканеры безопасности
        ~*(bytespider|gptbot|claudebot|semrush)      2; # Агрессивные скраперы (отдельный лимит)
    }

    # Жесткий лимит для агрессивных парсеров
    limit_req_zone $binary_remote_addr zone=scraper_zone:10m rate=1r/s;

    server {
        listen 443 ssl;
        server_name example.com;

        location / {
            # Мгновенная блокировка сканеров
            if ($bad_bot_detected = 1) {
                return 403;
            }

            # Сдерживание парсеров жестким лимитом
            if ($bad_bot_detected = 2) {
                set $limit_scraper $binary_remote_addr;
            }

            limit_req zone=scraper_zone burst=2 nodelay;
            proxy_pass http://web_backend;
        }
    }
}
```

### Сценарий 10: Интеграция L7 Rate Limiting с Host IPS (Fail2ban и nftables)

При масштабных атаках генерация ответов 429 в Nginx по-прежнему расходует CPU и файловые дескрипторы. Данный сценарий передает повторяющихся нарушителей на уровень сетевого фильтра ядра Linux.

1.  **Формат логирования ошибок в Nginx:**
    Nginx при срабатывании `limit_req` пишет в `error.log`:
    `limiting requests, excess: 20.450 by zone "api_limit_zone", client: 198.51.100.25, server: api.example.com...`

2.  **Фильтр Fail2ban (`/etc/fail2ban/filter.d/nginx-limit-req.conf`):**

    ```ini
    [Definition]
    failregex = ^\s*\[error\] \d+#\d+: \*\d+ limiting requests, excess: .* by zone "[^"]*", client: <HOST>,
    ignoreregex =
    ```

3.  **Конфигурация джейла (`/etc/fail2ban/jail.d/nginx-ratelimit.local`):**

    ```ini
    [nginx-ratelimit]
    enabled  = true
    port     = http,https
    filter   = nginx-limit-req
    logpath  = /var/log/nginx/*error.log
    maxretry = 10
    findtime = 60
    bantime  = 600
    banaction = nftables-multiport
    ```

---

## Операции и верификация

### Тестирование лимитов скорости и заголовков с помощью cURL

Проверка срабатывания политики `rate=5r/s burst=5 nodelay`:

```bash
# Выполнение серии из 10 параллельных запросов
for i in {1..10}; do
    curl -s -o /dev/null -w "%{http_code} | %{time_total}s\n" https://api.example.com/api/v1/test &
done; wait
# → 200 | 0.012s
# → 200 | 0.014s
# → 200 | 0.015s
# → 200 | 0.017s
# → 200 | 0.018s
# → 200 | 0.019s
# → 429 | 0.005s
# → 429 | 0.005s
# → 429 | 0.006s
# → 429 | 0.006s
```

Инспекция служебных заголовков в ответе 429:

```bash
curl -I -s https://api.example.com/api/v1/test
# → HTTP/2 429
# → server: nginx
# → date: Wed, 15 Oct 2026 10:15:00 GMT
# → content-type: application/json
# → retry-after: 2
```

### Нагрузочное тестирование с профилированием (инструмент vegeta)

Проверка устойчивости и точности отсечения трафика:

```bash
# Генерация нагрузки 30 rps в течение 5 секунд
echo "GET https://api.example.com/api/v1/test" | vegeta attack -rate=30 -duration=5s | vegeta report -type=text
# → Requests      [total, rate, throughput]         150, 30.00, 10.20
# → Duration      [total, attack, wait]             5.02s, 4.97s, 50.12ms
# → Latencies     [min, mean, 50, 90, 95, 99, max]  4.1ms, 12.3ms, 8.5ms, 25.1ms, 30.4ms, 45.0ms, 52.3ms
# → Success       [ratio]                           34.00%
# → Status Codes  [code:count]                      200:51  429:99
```

### Инспекция Stick Tables в HAProxy через Runtime API

Управление и оперативный мониторинг таблиц состояний без перезапуска сервиса:

```bash
# Просмотр общей информации о таблице
echo "show table st_rates" | socat stdio /run/haproxy/admin.sock
# → # table: st_rates, type: ip, size:204800, used:14
# → 0x7f83a40026e0: key=198.51.100.12 use=0 exp=112000 http_req_rate(10000)=145 http_err_rate(10000)=2
# → 0x7f83a40028a0: key=203.0.113.88 use=0 exp=98000 http_req_rate(10000)=12

# Фильтрация клиентов с высокой частотой запросов
echo "show table st_rates data.http_req_rate gt 50" | socat stdio /run/haproxy/admin.sock
# → 0x7f83a40026e0: key=198.51.100.12 use=0 exp=110000 http_req_rate(10000)=145

# Снятие блокировки / ручной сброс счетчика для конкретного IP
echo "clear table st_rates key 198.51.100.12" | socat stdio /run/haproxy/admin.sock
# → Entry cleared.
```

### Мониторинг разделяемой памяти Angie Console / API

Проверка счетчиков зон rate limiting через встроенный JSON API Angie:

```bash
curl -s http://127.0.0.1:8888/status/http/limit_reqs/ | jq .
# → {
# →   "api_limit_zone": {
# →     "passed": 482910,
# →     "delayed": 12040,
# →     "rejected": 3410,
# →     "exhausted": 0
# →   }
# → }
```

---

## Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`ngx_slab_alloc() failed: no memory in limit_req_zone`** | Закончилась выделенная разделяемая память (`shm`) для хранения новых ключей IP. | `grep "no memory" /var/log/nginx/error.log`<br>Счетчик `exhausted > 0` в Angie API. | 1. Увеличить объем зоны: `zone=name:40m`.<br>2. Убедиться, что используется `$binary_remote_addr`, а не `$remote_addr`. |
| **Все пользователи попадают под блокировку 429 одновременно** | Сервер находится за LB/WAF/CDN, и лимит рассчитывается по IP-адресу балансировщика. | Проверить логи доступа: поле `$remote_addr` содержит один и тот же приватный IP шлюза. | Настроить `set_real_ip_from` и директиву `real_ip_header X-Forwarded-For; real_ip_recursive on;`. |
| **Легитимные браузеры получают 429 при первом открытии сайта** | Страница запрашивает 40+ CSS/JS/картинок параллельно, превышая низкий `burst`. | В `access.log` код 429 возвращается на статические ресурсы `.js`, `.css`, `.png`. | 1. Исключить статику из зоны или вынести ее в отдельный `location`.<br>2. Настроить `delay=N` для мягкого сглаживания всплесков. |
| **Сервер возвращает 503 Service Unavailable вместо 429** | По умолчанию в Nginx/Angie директива `limit_req_status` имеет значение 503. | Код ответа в браузере и логах 503 при наличии записи `limiting requests` в `error.log`. | Явно объявить `limit_req_status 429;` в блоке `http` или `server`. |
| **Поисковые краулеры (Google, Yandex) выпадают из индекса** | Роботы сканирования попали под общий rate limit для обычных клиентов. | В логах частые 429 для User-Agent `Googlebot` или `YandexBot`. | Настроить верификацию ботов через FCrDNS или добавить официальные диапазоны подсетей поисковиков в `geo`-белый список. |
| **Службы мониторинга (Prometheus, Consul) помечают бэкенд нерабочим** | Эндпоинты health check (`/healthz`, `/metrics`) попали под действие глобального лимита. | Мониторинг фиксирует флапание статуса сервиса; в логах 429 на `/healthz`. | Вынести `/healthz` в отдельный `location` без директивы `limit_req` либо добавить IP скрапера в белый список. |
| **Рассинхронизация счетчиков в кластере из нескольких серверов** | Каждый сервер балансировки считает лимиты изолированно в локальной RAM. | Клиент может отправить в $N$ раз больше запросов, распределяя их между нодами. | Использовать репликацию `peers` в HAProxy либо директиву `sync` в Angie PRO. |

---

## Лучшие практики

### Расчет объема разделяемой памяти

Перед развертыванием в production рассчитывайте размер зоны памяти по формуле:

$$M = \frac{N_{active} \times S_{node}}{1024 \times 1024} \times K_{overhead}$$

*   $N_{active}$ — максимальное число уникальных клиентов за интервал очистки зоны (обычно пиковый суточный онлайн).
*   $S_{node}$ — размер структуры (64 байта для IPv4 в 64-битной системе).
*   $K_{overhead}$ — служебный коэффициент аллокатора slab (рекомендуется $2.0$).
*   *Практическое правило:* **1 МБ памяти вмещает $\approx 16\,000$ состояний IPv4** или $\approx 8\,000$ состояний IPv6. Для сервиса с миллионом уникальных посетителей в сутки резервируйте не менее **64 МБ** памяти на зону (`zone=api_limit:64m`).

### Эшелонирование лимитов (Defense in Depth)

Не полагайтесь на единую точку ограничения. Распределяйте контроль по уровням:

```
[ Уровень 1: L3/L4 Ядро Linux (nftables/iptables/conntrack) ]
   └── Защита от SYN/UDP-флуда, блокировка жестких атак через Fail2ban/CrowdSec
          │
[ Уровень 2: L7 Edge Балансировщик (HAProxy / Ingress) ]
   └── Глобальные лимиты соединений (limit_conn), защита от Slowloris, отсечение сканеров
          │
[ Уровень 3: L7 Веб-сервер / Reverse Proxy (Nginx / Angie) ]
   └── Дифференцированный rate limiting (по IP, сессиям, эндпоинтам /login, /api)
          │
[ Уровень 4: Приложение / Бэкенд ]
   └── Бизнес-лимиты (квоты тарифных планов, лимиты на транзакции в базе данных)
```

### Безопасное тестирование лимитов в Production (Dry-Run)

В Nginx (начиная с 1.17.1) и Angie используйте тестовый запуск перед вводом строгих ограничений:

```nginx
location /api/ {
    limit_req zone=api_limit_zone burst=20 nodelay;
    # Запросы не отклоняются, но факты превышения пишутся в журнал
    limit_req_dry_run on;
}
```

Анализируйте журнал ошибок на протяжении нескольких дней: если под правило попадают легитимные бизнес-сценарии или внутренние сервисы, скорректируйте `rate` и `burst` до отключения dry-run.

### Требования к метрикам и мониторингу SRE

*   **Golden Signals:** Отслеживайте соотношение ответов `HTTP 429` к общему числу запросов (`Rate429 / TotalRequests`). Значение выше 1% в обычном режиме свидетельствует о неверно выбранном пороге.
*   **Алертинг по исчерпанию памяти:** Настройте оповещение при появлении в логах сообщений `no memory in limit_req_zone` или росте метрики `exhausted > 0`.
*   **Идемпотентность и заголовок Retry-After:** Всегда передавайте клиенту точное или среднее время ожидания, чтобы автоматизированные SDK не инициировали шторм повторных попыток (Retry Storm).

---

## Дополнительная информация

### См. также

- **[Защита веб-серверов от ботов](./bot_protection.md)** — архитектура защиты от парсеров, FCrDNS, проверка JA3/JA4 и поведенческий анализ.
- **[Защита от DoS-атак в Angie](../Angie/High_Load/dos_protection.md)** — противодействие медленным атакам, cluster zone sync и защита на L3–L7.
- **[Rate Limiting в Traefik](../Traefik/traefik-rate-limiting-deep.md)** — углубленное руководство по Token Bucket, middleware и multi-tenant политикам.
- **[Circuit Breaker и деградация сервисов](./web_performance/circuit_breaker_and_degradation.md)** — предотвращение каскадных сбоев зависимостей.
- **[Rate Limiting и устойчивость HTTP-сервисов](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — теоретические основы алгоритмов и математика распределенных систем.
- **[Обзор архитектуры и балансировки HAProxy](../haproxy_overview.md)** — руководство по режимам работы, таймаутам и мониторингу HAProxy.
- **[Защита от DDoS](../../Security/ApplicationSecurity/ddos_overview.md)** — эшелонированная защита веб-приложений и инфраструктуры.

### Официальная документация

- [Nginx: ngx_http_limit_req_module](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html) — официальная документация модуля ограничения запросов.
- [Nginx: ngx_http_limit_conn_module](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html) — официальная документация модуля ограничения соединений.
- [Angie: HTTP Limit Req Module](https://angie.software/en/http_limit_req/) — документация модуля с поддержкой cluster zone sync.
- [HAProxy: Stick Tables Configuration](https://docs.haproxy.org/3.0/configuration.html#stick-table) — документация таблиц состояний и счетчиков.
- [Traefik: RateLimit Middleware](https://doc.traefik.io/traefik/middlewares/http/ratelimit/) — официальная документация Traefik.
- [Apache HTTPD: mod_ratelimit](https://httpd.apache.org/docs/2.4/mod/mod_ratelimit.html) — официальная документация модуля шейпинга пропускной способности.
