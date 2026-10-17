# Балансировка нагрузки L7 (HTTP/HTTPS) в Nginx: Обзор и концепции

**Актуально для:** Nginx 1.26+ (OSS/Plus) / 1.28+ (Mainline), Angie 1.6+ / 1.12.x

## Определения

**Балансировка нагрузки L7 (Application Layer Load Balancing)** — метод интеллектуального распределения входящего трафика на уровне протокола приложения (HTTP/HTTPS, HTTP/2, HTTP/3, gRPC). В отличие от L4, балансировщик выполняет полный синтаксический анализ запроса, включая URI, метод, HTTP-заголовки, cookies и тело запроса.

**Обратный прокси (Reverse Proxy)** — архитектурная роль Nginx, при которой сервер выступает пограничным шлюзом (Edge Gateway) для внешних клиентов, принимает входящие сетевые соединения, терминирует TLS, валидирует запросы и проксирует их на внутренние целевые серверы (бэкенды). Подробнее: [Обзор Nginx](../../Core/nginx_overview.md).

**Upstream-группа (Upstream Pool)** — логический именованный пул бэкенд-серверов, объявленный директивой `upstream` в контексте `http`. Для пула задаются алгоритм распределения, параметры отказоустойчивости, ограничения соединений и кэширование сокетов. Детальный разбор алгоритмов: [Алгоритмы балансировки](./algorithms.md).

**Зона разделяемой памяти (Shared Memory Zone, `zone`)** — сегмент оперативной памяти, выделяемый master-процессом Nginx в контексте IPC (`shm`), доступный всем рабочим процессам (`worker processes`). Необходим для разделения динамического состояния пула: счетчиков сбоев, весов, очередей запросов, метрик и таблиц липких сессий.

**Пул соединений Upstream (Upstream Keepalive Pool)** — пул открытых незанятых (idle) TCP/TLS-соединений между рабочими процессами Nginx и бэкенд-серверами. Кэширование сокетов исключает накладные расходы на постоянное трехстороннее рукопожатие TCP (3-way handshake) и TLS-сессию при обработке потока запросов.

**Буферизация ответов (Response Buffering)** — механизм, при котором Nginx считывает HTTP-ответ от бэкенда в оперативную память (или во временные файлы на диске) на максимальной скорости бэкенда, немедленно освобождая ресурсы приложения, после чего самостоятельно передает данные клиенту с доступной для клиента скоростью.

**Пассивная проверка состояния (Passive Health Check / Circuit Breaker)** — механизм контроля жизнеспособности узлов на основе анализа результатов обработки реальных пользовательских запросов (`max_fails`, `fail_timeout`). При фиксации порогового числа сбоев узел временно изолируется от трафика. Подробнее: [Health Checks и мониторинг](./health_checks_and_monitoring.md).

**Активная проверка состояния (Active Health Check / Synthetic Probing)** — упреждающая периодическая отправка балансировщиком синтетических тестовых запросов к бэкендам независимо от клиентского трафика (нативно доступна в Angie и Nginx Plus).

**Протокол PROXY (PROXY Protocol v1/v2)** — сетевой протокол инкапсуляции метаданных клиентского соединения (исходный IP, исходный порт, статус TLS), передаваемый в начале TCP-потока перед полезной нагрузкой. Позволяет L7-прокси получать реальный адрес клиента при работе за внешними L4-балансировщиками без модификации заголовков HTTP. Подробнее: [PROXY Protocol](../../../../Networking/Protocols/proxy_protocol.md).

**Каскадный отказ (Cascading Failure / Retry Storm)** — аварийный сценарий в распределенной системе, при котором сбой одного узла приводит к лавинообразному падению остальных серверов кластера из-за неконтролируемого перераспределения нагрузки и шторма повторных запросов (`proxy_next_upstream`).

---

## Архитектура и основные концепции

### Событийно-ориентированная модель L7 и Worker-процессы

Nginx построен на асинхронной событийно-ориентированной архитектуре (Event-Driven Architecture) с разделением на один привилегированный master-процесс и группу непривилегированных worker-процессов (`worker_processes`).

```
                Входящие клиентские запросы (TCP/TLS)
                                 │
                                 ▼
                     ┌──────────────────────┐
                     │ Nginx Master Process │ (Чтение конфига, открытие сокетов,
                     └──────────┬───────────┘  управление воркерами)
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│ Worker Proc 1 │       │ Worker Proc 2 │       │ Worker Proc N │
│ (epoll loop)  │       │ (epoll loop)  │       │ (epoll loop)  │
└───────┬───────┘       └───────┬───────┘       └───────┬───────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                ▼
               ┌─────────────────────────────────┐
               │ Shared Memory Zone (IPC, 'zone')│
               │ (Счетчики сбоев, веса, сессии)  │
               └────────────────┬────────────────┘
                                │ Keepalive сокеты
                                ▼
                   Upstream Бэкенд-кластер (L7)
```

1. **Неблокирующий I/O (`epoll`):** Каждый рабочий процесс выполняет единый цикл обработки событий (`Event Loop`), мультиплексируя десятки тысяч одновременных L7-соединений в одном потоке ОС без создания отдельных тредов на запрос и без накладных расходов на переключение контекста процессора.
2. **Изоляция соединений:** Рабочий процесс держит два независимых набора сокетов: клиентский (downstream) и серверный (upstream). Балансировщик выступает терминатором протокола: клиент общается с Nginx, а Nginx по отдельному соединению опрашивает бэкенд.
3. **Привязка к ядрам (CPU Affinity):** Для предотвращения межъядерной миграции потоков и промахов кэша процессора (L1/L2/L3) воркеры жестко привязываются к ядрам CPU директивой `worker_cpu_affinity auto`.

### Жизненный цикл L7-запроса

Обработка запроса балансировщиком проходит строгую последовательность фаз:

1. **Клиентская фаза (Downstream):**
   - Завершение TCP 3-way handshake на слушающем сокете воркера.
   - Терминация TLS (согласование шифров, SNI, ALPN `h2`/`http/1.1`).
   - Парсинг HTTP-заголовков и маршрутизация в целевой блок `server` и `location`.
2. **Фаза выбора Upstream (Балансировка):**
   - Определение целевого пула `upstream` из директивы `proxy_pass`.
   - Проверка состояния узлов в разделяемой памяти (`zone`).
   - Применение алгоритма балансировки (Round Robin, Least Conn, Hash, IP Hash, Random).
3. **Фаза соединения с бэкендом (Upstream):**
   - Поиск свободного соединения в локальном пуле `keepalive` текущего воркера.
   - Если пул пуст — инициализация нового TCP-соединения (`connect()`) к выбранному IP:Port бэкенда.
   - Если проксирование идет по HTTPS — выполнение TLS handshake с бэкендом (`proxy_ssl_*`).
4. **Фаза проксирования и буферизации:**
   - Модификация заголовков запроса (`proxy_set_header Host`, `X-Forwarded-For`, `Connection ""`).
   - Передача тела запроса бэкенду.
   - Считывание заголовков ответа бэкенда в буфер `proxy_buffer_size`.
   - Если включена буферизация (`proxy_buffering on`) — чтение тела ответа в цепочку буферов `proxy_buffers`.
5. **Фаза завершения и очистки:**
   - Отправка ответа клиенту.
   - Возврат TCP-сокета к бэкенду в пул `keepalive` (если соединение не закрыто и лимит запросов не исчерпан) либо закрытие сокета (`close()`).

### Роль разделяемой памяти (`zone`) в L7-балансировке

Директива `zone <name> <size>` в блоке `upstream` является фундаментом отказоустойчивости и корректной балансировки в многопроцессной архитектуре Nginx:

| Характеристика | Без директивы `zone` (Локальная память) | С директивой `zone` (Shared Memory IPC) |
| :--- | :--- | :--- |
| **Хранение счетчиков сбоев (`max_fails`)** | В локальной памяти каждого воркера независимо. | Единый счетчик в разделяемой памяти, доступный всем воркерам. |
| **Реакция на отказ узла (например, 16 воркеров, `max_fails=3`)** | Требуется до $16 \times 3 = 48$ сбоев клиентов, прежде чем все воркеры изолируют узел. | Ровно 3 сбоя суммарно любыми воркерами — узел мгновенно помечается `DOWN`. |
| **Алгоритм `least_conn`** | Каждый воркер считает соединения независимо; распределение искажается. | Воркеры видят глобальное число активных соединений кластера. |
| **Динамическое управление (API / DNS)** | Невозможно изменять состав серверов без полного перезапуска/reload. | Поддерживается динамическое обновление состояния узлов через API (Angie/Plus) и резолвер. |

> [!IMPORTANT]
> В производственных средах любая upstream-группа обязана содержать директиву `zone`. Отсутствие `zone` в многоядерных системах приводит к «просачиванию» ошибок клиентам и многократному затягиванию изоляции сбойных серверов.

### Механика и архитектура Upstream Keepalive

По умолчанию Nginx обращается к бэкендам по протоколу HTTP/1.0 и закрывает TCP-соединение после каждого выполненного запроса заголовком `Connection: close`. Это порождает:
- Высокую нагрузку на CPU из-за постоянных TCP-рукопожатий и TLS-согласований.
- Исчерпание диапазона эфемерных портов (`ephemeral ports`) на балансировщике при высоком RPS.
- Накопление десятков тысяч сокетов в состоянии `TIME_WAIT` в сетевом стеке ядра Linux.

```nginx
upstream backend_app {
    zone backend_app_zone 256k;
    server 10.0.0.11:8080 weight=1 max_fails=3 fail_timeout=10s;
    server 10.0.0.12:8080 weight=1 max_fails=3 fail_timeout=10s;

    # Размер пула свободных (idle) соединений на один рабочий процесс
    keepalive 64;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}

server {
    listen 80;
    location / {
        proxy_pass http://backend_app;
        
        # Критически важные директивы для активации keepalive:
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

#### Ключевые архитектурные правила Keepalive:
1. **Параметр `keepalive N` — это не лимит одновременных соединений:** Это емкость кэша свободных (`idle`) открытых сокетов **для каждого отдельного воркера**. При наличии 8 воркеров и значении `keepalive 64`, суммарно в резерве может находиться до $8 \times 64 = 512$ открытых TCP-сокетов.
2. **Активные соединения не ограничиваются:** Если в пике поступает 500 одновременных запросов, воркер откроет 500 сокетов к бэкенду. Но после завершения запросов воркер сохранит в кэше только 64 сокета, а остальные закроет.
3. **Обязательность HTTP/1.1 и очистки заголовка `Connection`:** Директива `proxy_http_version 1.1;` переключает протокол взаимодействия с HTTP/1.0 на HTTP/1.1. Директива `proxy_set_header Connection "";` удаляет заголовок `Connection: close`, который Nginx отправляет по умолчанию. Без этих двух строк директива `keepalive` в блоке `upstream` игнорируется.

### Управление потоком данных и буферизация (`proxy_buffering`)

Буферизация — фундаментальный защитный механизм Nginx, реализующий шаблон проектирования «Асинхронный буфер» между быстрым производителем (бэкендом приложения) и медленным потребителем (клиентом с мобильной связью или высокой задержкой сети).

```
[Клиент (Медленный)] <─── (Медленная отдача) ─── [Буферы Nginx] <═══ (Быстрый сброс) ═══ [Бэкенд App]
 (RTT 150ms, 1 Mbps)                                (RAM / SSD)                            (RTT 0.5ms, 10 Gbps)
                                                                                            *Поток воркера App
                                                                                             немедленно свободен!*
```

#### Структура буферов Nginx:
- `proxy_buffer_size`: буфер для считывания первой части ответа — HTTP-заголовков бэкенда. Должен вмещать все заголовки (включая крупные `Set-Cookie` или токены авторизации). По умолчанию равен размеру страницы памяти (4k или 8k).
- `proxy_buffers <число> <размер>`: пул буферов для считывания тела ответа от бэкенда для одного соединения (например, `proxy_buffers 8 16k;` = 128 КБ).
- `proxy_busy_buffers_size`: максимальный суммарный объем буферов, которые могут быть заняты одновременной передачей данных клиенту, пока остальные буферы продолжают считывать данные от бэкенда (рекомендуется устанавливать в 2 размера одного буфера).
- `proxy_max_temp_file_size`: предельный размер временного файла на диске (`proxy_temp_path`), если тело ответа не помещается в выделенные буферы оперативной памяти.

#### Когда отключать буферизацию (`proxy_buffering off`):
- **Потоковые HTTP-соединения:** Server-Sent Events (SSE), где события должны поступать клиенту моментально.
- **Интерактивные WebSocket-сессии:** где задержка передачи сообщений критична.
- **gRPC-стриминг (Bidirectional / Server Streaming):** где задержка буферизации нарушает семантику протокола (используется `grpc_buffering off`).

### Мультиплексирование и терминация современных протоколов

1. **HTTP/2 и HTTP/3 (QUIC) на клиенте:** Nginx выступает терминатором мультиплексированных потоков. Клиент открывает единственное TCP- или UDP-соединение к Nginx, внутри которого передаются десятки параллельных потоков данных. Nginx преобразует эти потоки в стандартные высокопроизводительные HTTP/1.1 keepalive-соединения к локальным бэкендам, снимая с бэкендов вычислительную нагрузку по разбору фреймов HTTP/2/HTTP/3 и TLS.
2. **gRPC на уровне L7:** В отличие от L4-балансировки, где все gRPC-вызовы внутри одного долгоживущего TCP-соединения HTTP/2 принудительно уходят на один и тот же сервер, L7-балансировщик Nginx (`grpc_pass`) анализирует отдельные gRPC-фреймы и балансирует каждый RPC-вызов независимо между узлами upstream-пула.

### Сохранение клиентской идентичности в On-Prem архитектурах

В многоуровневых инфраструктурах бэкенды получают соединения от локального IP-адреса Nginx. Для корректной аутентификации, логирования, геолокации и rate limiting необходимо сохранять оригинальный IP клиента:

```
[Клиент: 203.0.113.195]
           │
           ▼
[Внешний L4 Балансировщик (Keepalived/IPVS): 198.51.100.1]
           │ PROXY Protocol v2 (или прямой проброс)
           ▼
[L7 Nginx Proxy: 10.0.0.2]
           │
           │ proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           │ proxy_set_header X-Real-IP       $remote_addr;
           ▼
[Бэкенд Приложения: 10.0.0.11]
```

1. **Восстановление IP модуля `real_ip`:** Если перед Nginx установлен L4-балансировщик или внешний шлюз, директивы `set_real_ip_from` и `real_ip_header` перезаписывают внутреннюю переменную `$remote_addr` реальным адресом клиента:
   ```nginx
   # Доверенные адреса внутренних L4-балансировщиков
   set_real_ip_from 10.0.0.0/24;
   real_ip_header proxy_protocol; # или X-Forwarded-For при наличии L7-шлюза
   real_ip_recursive on;
   ```
2. **Передача заголовков бэкенду:**
   ```nginx
   proxy_set_header Host $host;
   proxy_set_header X-Real-IP $remote_addr;
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   proxy_set_header X-Forwarded-Proto $scheme;
   ```

### Сравнение уровней балансировки L4 и L7

| Критерий | L4 Балансировка (`stream`) | L7 Балансировка (`http`) |
| :--- | :--- | :--- |
| **Уровень модели OSI** | Транспортный (TCP / UDP) | Прикладной (HTTP / HTTPS / gRPC) |
| **Инспекция трафика** | Только IP, порты, TLS SNI (`ssl_preread`) | Полный разбор: URI, Headers, Cookies, JSON |
| **Терминация TLS** | Опционально (поддерживается SSL Passthrough) | Обязательна для инспекции и модификации |
| **Потребление CPU / RAM** | Минимальное (перекладка TCP-пакетов) | Выше (парсинг HTTP, буферы, сжатие) |
| **Маршрутизация** | Только по портам/SNI | По путям (`/api`, `/static`), заголовкам, методам |
| **Модификация данных** | Невозможна | Вставка/удаление заголовков, перезапись ответов |
| **Применение** | Базы данных (PostgreSQL, MySQL), DNS, почта, чистый TCP. Подробнее: [L4-проксирование](../nginx_l4_proxying.md) | Веб-приложения, микросервисы, REST API, WebSockets |

### Сравнение возможностей (Nginx OSS vs Nginx Plus vs Angie)

| Функция балансировки L7 | Nginx OSS (1.26 / 1.28) | Nginx Plus (R32+) | Angie (1.6+ / 1.12.x) |
| :--- | :--- | :--- | :--- |
| **Базовые алгоритмы (Round Robin, Least Conn, Hash, IP Hash, Random)** | Да | Да | Да |
| **Разделяемая память (`zone`)** | Да | Да | Да |
| **Upstream Keepalive к бэкендам** | Да | Да | Да |
| **Активные Health Checks (`health_check` / `check`)** | Нет (требуются сторонние модули) | **Да** (нативно) | **Да** (нативно директивой `check`) |
| **Динамическое разрешение DNS в Upstream (`resolve`)** | Да (начиная с 1.27.3+) | **Да** | **Да** (нативно директивой `resolve`) |
| **Липкие сессии (Sticky Cookie / Learn / Route)** | Нет (только `ip_hash` / `hash`) | **Да** | **Да** (нативно директивой `sticky`) |
| **Адаптивный алгоритм `least_time`** | Нет | **Да** | **Да** |
| **Алгоритм обратной связи `feedback`** | Нет | Нет | **Да** (в Angie PRO) |
| **Очередь запросов при перегрузке (`queue`)** | Нет | **Да** | **Да** |
| **Дренаж соединений (`drain`)** | Нет (только `down`) | **Да** | **Да** |
| **Runtime API / Prometheus телеметрия без reload** | Нет (только `stub_status`) | **Да** (REST API) | **Да** (REST API и нативный Prometheus `/metrics`) |

---

## Конфигурация и практические сценарии

### Сценарий 1: Производственный отказоустойчивый L7-балансировщик (Production-Ready Edge Proxy)

Конфигурация оптимизирована для On-Prem инсталляций, содержит жесткие защитные таймауты, разделяемую память, keepalive-пул, ограничение шторма повторов и безопасные заголовки.

```nginx
# /etc/nginx/nginx.conf
user nginx;
worker_processes auto;
worker_rlimit_nofile 65535;
pid /var/run/nginx.pid;

events {
    worker_connections 8192;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Логирование с детальной декомпозицией времени для SRE-аналитики
    log_format upstream_perf '$remote_addr - $remote_user [$time_local] '
                             '"$request" $status $body_bytes_sent '
                             '"$http_referer" "$http_user_agent" '
                             'rt=$request_time uct="$upstream_connect_time" '
                             'uht="$upstream_header_time" urt="$upstream_response_time" '
                             'uaddr="$upstream_addr" ustatus="$upstream_status"';

    access_log /var/log/nginx/access.log upstream_perf buffer=32k flush=5s;
    error_log /var/log/nginx/error.log warn;

    # Системные оптимизации передачи данных
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    # Пулы бэкенд-серверов
    upstream backend_api {
        zone backend_api_zone 512k;

        # Балансировка по наименьшему числу активных соединений
        least_conn;

        # Основные узлы с пассивным Circuit Breaker
        server 10.0.0.11:8080 weight=3 max_fails=3 fail_timeout=15s;
        server 10.0.0.12:8080 weight=2 max_fails=3 fail_timeout=15s;
        server 10.0.0.13:8080 weight=1 max_fails=3 fail_timeout=15s;

        # Аварийный резервный узел (включается только при отказе всех основных)
        server 10.0.0.14:8080 backup;

        # Настройка пула свободных сокетов к бэкендам (на один worker-процесс)
        keepalive 64;
        keepalive_requests 2000;
        keepalive_timeout 65s;
    }

    server {
        listen 80;
        listen [::]:80;
        server_name api.example.local;

        # Редирект на защищенный протокол
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl default_server;
        listen [::]:443 ssl default_server;
        server_name api.example.local;

        # Настройки TLS 1.2 / TLS 1.3
        ssl_certificate /etc/ssl/certs/api.example.local.crt;
        ssl_certificate_key /etc/ssl/private/api.example.local.key;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
        ssl_prefer_server_ciphers off;
        ssl_session_cache shared:SSL:20m;
        ssl_session_timeout 1d;
        ssl_session_tickets off;

        # Буферизация ответов бэкенда
        proxy_buffering on;
        proxy_buffer_size 16k;
        proxy_buffers 8 32k;
        proxy_busy_buffers_size 64k;
        proxy_temp_file_write_size 64k;
        proxy_max_temp_file_size 128m;

        # Таймауты защиты от зависаний бэкенда
        proxy_connect_timeout 2s;
        proxy_send_timeout 10s;
        proxy_read_timeout 15s;

        # Политика отказоустойчивости и защиты от шторма повторов (Retry Storm)
        proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 6s;

        location / {
            proxy_pass http://backend_api;

            # Обеспечение работы upstream keepalive
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            # Передача оригинальных заголовков клиента
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Сокрытие внутренних заголовков инфраструктуры
            proxy_hide_header X-Powered-By;
            proxy_hide_header Server;
        }

        # Эндпоинт для проверки здоровья самого балансировщика
        location = /healthz {
            access_log off;
            add_header Content-Type text/plain;
            return 200 "healthy\n";
        }
    }
}
```

### Сценарий 2: Двухуровневая High Availability On-Prem архитектура (L4 IPVS/Keepalived + L7 Nginx Cluster)

Для исключения единой точки отказа (SPOF) перед группой Nginx балансировщиков разворачивается отказоустойчивый кластер L4 на базе Keepalived (VRRP) и IPVS:

```
          Виртуальный IP адрес (VIP: 198.51.100.10)
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   [L4 Node 1: Keepalived/IPVS]     [L4 Node 2: Backup/Standby]
            │                                 │
            └────────────────┬────────────────┘
                             │ Трафик с PROXY Protocol v2
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   [L7 Nginx Proxy 1: 10.0.0.2]      [L7 Nginx Proxy 2: 10.0.0.3]
            │                                 │
            └────────────────┬────────────────┘
                             │ Балансировка HTTP/Keepalive
                             ▼
            [Upstream Кластер Приложений: 10.0.0.11-13]
```

Конфигурация приемного сокета L7 Nginx с поддержкой PROXY Protocol:

```nginx
server {
    # Прием трафика от L4-балансировщика с заголовком PROXY Protocol
    listen 80 proxy_protocol;
    listen 443 ssl proxy_protocol;
    server_name service.example.local;

    # Доверенный диапазон адресов нод Keepalived/IPVS
    set_real_ip_from 10.0.0.0/24;
    real_ip_header proxy_protocol;

    # Сертификаты TLS
    ssl_certificate /etc/ssl/certs/service.crt;
    ssl_certificate_key /etc/ssl/private/service.key;

    location / {
        proxy_pass http://backend_api;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # В переменной $remote_addr теперь содержится реальный адрес внешнего клиента
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
    }
}
```

### Сценарий 3: Балансировка современных протоколов реального времени (gRPC и WebSocket)

```nginx
# Определение заголовков Upgrade для WebSocket
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

upstream grpc_servers {
    zone grpc_zone 256k;
    server 10.0.0.21:50051;
    server 10.0.0.22:50051;
    keepalive 32;
}

upstream ws_servers {
    zone ws_zone 256k;
    server 10.0.0.31:8081;
    server 10.0.0.32:8081;
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name stream.example.local;

    ssl_certificate /etc/ssl/certs/stream.crt;
    ssl_certificate_key /etc/ssl/private/stream.key;

    # Балансировка gRPC-сервиса на уровне L7
    location /orders.OrderService/ {
        grpc_pass grpc://grpc_servers;
        grpc_connect_timeout 2s;
        grpc_read_timeout 60s;
        grpc_send_timeout 60s;
        grpc_buffer_size 16k;
    }

    # Балансировка долгоживущих соединений WebSocket
    location /ws/ {
        proxy_pass http://ws_servers;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;

        # Отключение буферизации для стриминга в реальном времени
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

---

## Операции и команды

### Валидация и безаварийное применение конфигурации

```bash
# 1. Проверка синтаксиса и целостности всех подключаемых файлов конфигурации
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Вывод полной скомпилированной конфигурации для проверки блоков upstream
nginx -T | grep -A 15 "upstream"
# → upstream backend_api {
# →     zone backend_api_zone 512k;
# →     least_conn;
# →     server 10.0.0.11:8080 weight=3 max_fails=3 fail_timeout=15s;
# →     server 10.0.0.12:8080 weight=2 max_fails=3 fail_timeout=15s;
# →     keepalive 64;
# → }

# 3. Безаварийное применение конфигурации (Zero-Downtime Reload)
nginx -s reload
# → 2026/10/17 15:00:00 [notice] 1234#1234: signal process started

# 4. Проверка статуса процессов master и worker через systemd
systemctl status nginx --no-pager
# → ● nginx.service - A high performance web server and a reverse proxy server
# →    Loaded: loaded (/lib/systemd/system/nginx.service; enabled; vendor preset: enabled)
# →    Active: active (running) since Sat 2026-10-17 14:00:00 MSK; 1h ago
```

### Инспекция сетевых сокетов и пула Keepalive в Linux

```bash
# 1. Просмотр установленных соединений Nginx к конкретному узлу бэкенда
ss -tn state established '( daddr = 10.0.0.11 and dport = :8080 )'
# → Recv-Q Send-Q Local Address:Port  Peer Address:Port
# → 0      0      10.0.0.2:48392      10.0.0.11:8080
# → 0      0      10.0.0.2:48394      10.0.0.11:8080

# 2. Подсчет общего количества активных соединений к пулу бэкендов
ss -tn state established '( dport = :8080 )' | wc -l
# → 48

# 3. Проверка сокетов в состоянии TIME_WAIT (признак отсутствия или нехватки keepalive)
ss -tan state time-wait '( dport = :8080 )' | wc -l
# → 12

# 4. Проверка очередей слушающего сокета Nginx (Send-Q = лимит сокета, Recv-Q = текущая очередь)
ss -lnt '( sport = :443 )'
# → State  Recv-Q Send-Q Local Address:Port Peer Address:Port
# → LISTEN 0      4096   0.0.0.0:443        0.0.0.0:*
```

### Анализ распределения трафика и задержек в реальном времени

```bash
# 1. Проверка распределения запросов по узлам upstream (на основе переменной uaddr)
awk -F'uaddr="' '{print $2}' /var/log/nginx/access.log | awk -F'"' '{print $1}' | sort | uniq -c | sort -rn
# → 5420 10.0.0.11:8080
# → 3610 10.0.0.12:8080
# → 1805 10.0.0.13:8080

# 2. Вычисление 95-го перцентиля задержки ответа бэкендов ($upstream_response_time)
awk -F'urt="' '{print $2}' /var/log/nginx/access.log | awk -F'"' '$1 ~ /^[0-9.]+$/ {print $1}' | \
sort -n | awk '{all[NR] = $0} END {print "p95 =", all[int(NR*0.95)], "sec (" NR " requests)"}'
# → p95 = 0.042 sec (10835 requests)

# 3. Мониторинг кодов ответов upstream в потоковом режиме
tail -f /var/log/nginx/access.log | grep -o 'ustatus="[^"]*"'
# → ustatus="200"
# → ustatus="200"
# → ustatus="502"
```

### Прямая валидация доступности и задержек бэкендов через `curl`

```bash
# Тестирование времени отклика бэкенда напрямую (декомпозиция DNS, TCP, TTFB, Total)
curl -w "\nDNS: %{time_namelookup}s | TCP: %{time_connect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s\n" \
     -o /dev/null -s http://10.0.0.11:8080/healthz
# → DNS: 0.000045s | TCP: 0.000852s | TTFB: 0.004120s | Total: 0.004185s
```

---

## Диагностика и устранение неполадок

### Сводная матрица инцидентов L7-балансировки

| Симптом | Корневая причина | Диагностический маркер | Решение |
| :--- | :--- | :--- | :--- |
| **502 Bad Gateway** (все запросы) | Все бэкенды пула недоступны, упали или заблокированы локальным фаерволом (iptables/nftables) | `error.log`: `connect() failed (111: Connection refused) while connecting to upstream` | Проверить статус службы приложения: `systemctl status app`; проверить доступность порта `curl -I http://10.0.0.11:8080`; проверить правила фаервола. |
| **502 Bad Gateway** (периодически) | Превышение лимита соединений бэкенда (`listen backlog`), сброс сокета приложению (RST) | `error.log`: `recv() failed (104: Connection reset by peer) while reading response header from upstream` | Увеличить пул воркеров приложения; настроить `proxy_next_upstream error timeout http_502;`; увеличить `somaxconn` в ОС бэкенда. |
| **504 Gateway Timeout** | Бэкенд не успевает сформировать ответ за интервал `proxy_read_timeout` (долгие SQL-запросы, зависание потоков) | `error.log`: `upstream timed out (110: Connection timed out) while reading response header from upstream` | Оптимизировать медленные запросы приложения; временно увеличить `proxy_read_timeout 30s;`; проверить загрузку CPU/RAM на серверах бэкенда. |
| **503 Service Unavailable** | В Angie/Plus достигнут лимит `max_conns` при заполненной очереди `queue` | `error.log`: `no free servers in upstream` или `queue full` | Добавить серверы в upstream; увеличить емкость очереди `queue` или увеличить `max_conns`. |
| **"upstream sent too big header"** | Объем заголовков ответа бэкенда (крупные `Set-Cookie`, JWT-токены) превысил `proxy_buffer_size` | `error.log`: `upstream sent too big header while reading response header from upstream` | Увеличить размер буфера заголовков: `proxy_buffer_size 16k;` (по умолчанию 4k/8k). |
| **"an upstream response is buffered to a temporary file"** | Размер тела ответа бэкенда превысил оперативную память `proxy_buffers` при медленном чтении клиентом | `warn` в `error.log`: `an upstream response is buffered to a temporary file` | Увеличить `proxy_buffers 8 32k;` и `proxy_busy_buffers_size 64k;`. Если диск SSD/NVMe и это штатный сценарий — настроить `proxy_max_temp_file_size`. |
| **Дисбаланс нагрузки при `ip_hash`** | Тысячи клиентов обращаются через единый корпоративный прокси / NAT-шлюз с одного публичного IP | Анализ access-лога: 90%+ трафика поступает на единственный сервер пула | Заменить `ip_hash` на балансировку по cookie (`sticky cookie` в Angie/Plus) или консистентный хеш заголовка (`hash $http_x_user_id consistent;`). |
| **Retry Storm / Каскадное падение кластера** | `proxy_next_upstream` не ограничен параметрами `tries` и `timeout`, перегружая живые узлы повторными запросами | Лавинообразный рост `upstream_response_time`, массовые 504 ошибки на всех серверах пула | Жестко ограничить попытки: `proxy_next_upstream_tries 3;` и `proxy_next_upstream_timeout 6s;`. Исключить неидемпотентные методы. |
| **Исчерпание портов (Port Exhaustion)** | Отсутствие keepalive к бэкендам при высоком RPS генерирует десятки тысяч сокетов в `TIME_WAIT` | `error.log`: `cannot assign requested address (99: Cannot assign requested address) while connecting to upstream` | Включить `keepalive 64;` в `upstream`, задать `proxy_http_version 1.1; proxy_set_header Connection "";`. Включить `sysctl net.ipv4.tcp_tw_reuse = 1`. |

### Пошаговый алгоритм расследования инцидентов (Triage Workflow)

```
[Алерт: Всплеск 502/504 на балансировщике]
                   │
                   ▼
1. Локализация: Проверка журнала ошибок Nginx
   grep -E "502|504|Connection refused|Connection reset|timed out" /var/log/nginx/error.log | tail -n 20
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
[Connection refused]   [timed out while reading]
         │                   │
         ▼                   ▼
2. Проверка порта бэкенда    3. Проверка профиля latency бэкенда
   nc -zvw2 10.0.0.11 8080      curl -w "TTFB: %{time_starttransfer}s\n" http://10.0.0.11:8080/api
         │                   │
         ▼                   ▼
[Служба упала / Firewall]    [Узкое место в коде приложения / БД]
   systemctl status app         Анализ slow-логов бэкенда и очередей
```

---

## Лучшие практики

### Архитектура и надежность (SRE)

1. **Обязательное объявление разделяемой памяти (`zone`):** В любой upstream-группе должна присутствовать директива `zone <имя> <размер>`. Без нее балансировщик не способен синхронизировать счетчики пассивных проверок (`max_fails`) между воркерами, что нарушает изоляцию сбойных узлов.
2. **Ограничение шторма повторов (Retry Storm Budget):** При настройке `proxy_next_upstream` обязательно задавайте директивы `proxy_next_upstream_tries 3;` и `proxy_next_upstream_timeout <T>;`. Значение таймаута должно быть строго меньше, чем клиентский таймаут, иначе при падении одного узла повторные запросы вызовут перегрузку и каскадный отказ оставшихся бэкендов.
3. **Безопасные повторные запросы (Идемпотентность):** По умолчанию Nginx не повторяет запросы с методами `POST`, `LOCK`, `PATCH`, если часть тела уже была передана бэкенду. Не включайте директиву `non_idempotent` в `proxy_next_upstream`, если бэкенд не гарантирует идемпотентность операций на уровне транзакций базы данных.
4. **Использование аварийного резерва (`backup`):** Назначайте минимальный резервный узел (`server ... backup;`), способный отдавать статическую заглушку о технических работах или деградированную версию ответа при полном отказе основного кластера.

### Производительность и сайзинг соединений (Performance)

1. **Формула расчета директивы `keepalive` в блоке `upstream`:**
   Количество свободных сокетов в кэше воркера должно покрывать пиковый RPS, приходящийся на этот воркер, с учетом среднего времени ответа бэкенда:
   $$\text{keepalive per worker} = \frac{\text{Target RPS}}{\text{worker\_processes}} \times \text{Average TTFB (seconds)} \times 1.5$$
   *Пример:* Нагрузка 10 000 RPS, 8 воркеров Nginx, TTFB бэкенда 20 мс (0.02 с):
   $$\text{keepalive} = \frac{10000}{8} \times 0.02 \times 1.5 = 1250 \times 0.03 = 37.5 \approx 64$$
2. **Оптимизация буферов под профиль нагрузки:**
   - Если API отдает короткие JSON-ответы (до 8 КБ), установите `proxy_buffers 4 8k;` и `proxy_buffer_size 8k;`. Это минимизирует footprint оперативной памяти при десятках тысяч соединений.
   - Задавайте `proxy_busy_buffers_size` равным $2 \times \text{размер одного буфера}$.

### Системное администрирование и тюнинг ядра Linux (SysAdmin / Bare-Metal)

Для предотвращения сетевых блокировок под нагрузкой настройте параметры ядра Linux в `/etc/sysctl.d/99-nginx-lb.conf`:

```ini
# Увеличение длины очереди слушающих сокетов ядра (listen backlog)
net.core.somaxconn = 65535

# Увеличение максимальной очереди входящих SYN-пакетов
net.ipv4.tcp_max_syn_backlog = 65535

# Расширение пула эфемерных портов для исходящих соединений к бэкендам
net.ipv4.ip_local_port_range = 10240 65535

# Разрешение безопасного повторного использования сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1

# Сокращение времени удержания сокета в состоянии FIN-WAIT-2
net.ipv4.tcp_fin_timeout = 15

# Максимальное число открытых файлов на уровне системы
fs.file-max = 2097152
```

Применение параметров:
```bash
sysctl -p /etc/sysctl.d/99-nginx-lb.conf
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_max_syn_backlog = 65535
# → net.ipv4.ip_local_port_range = 10240 65535
# → net.ipv4.tcp_tw_reuse = 1
# → net.ipv4.tcp_fin_timeout = 15
# → fs.file-max = 2097152
```

Настройка лимитов процессов в `/etc/security/limits.d/99-nginx.conf`:
```ini
nginx       soft    nofile      65535
nginx       hard    nofile      65535
```

### Безопасность (Security)

1. **Валидация доверенных прокси (`set_real_ip_from`):** Никогда не доверяйте заголовкам `X-Forwarded-For` или `X-Real-IP` от произвольных сетевых узлов. Указывайте только точные IP-адреса ваших пограничных L4/L7-балансировщиков.
2. **Изоляция служебных заголовков:** Скрывайте внутренние заголовки приложения с помощью директив `proxy_hide_header X-Powered-By;` и `proxy_hide_header Server;`.
3. **Безопасность сессионных cookie:** При использовании Sticky Sessions (Angie/Plus) выставляйте флаги `httponly` и `secure` для предотвращения перехвата сессий через XSS.

### Наблюдаемость и мониторинг (Observability)

1. **Декомпозиция времени ответа (Timing Breakdown):** Включайте в лог-формат четыре базовые временные метрики Nginx:
   - `$request_time`: общее время обработки запроса клиентом (от первого байта клиента до последнего переданного байта).
   - `$upstream_connect_time`: время установления TCP/TLS-соединения с бэкендом (рост указывает на перегрузку сокетов бэкенда).
   - `$upstream_header_time`: время от отправки запроса до получения первого байта заголовков бэкенда (TTFB приложения).
   - `$upstream_response_time`: время полного считывания ответа от сервера upstream.
2. **Алертинг SRE:** Настройте Prometheus/Grafana алерты на:
   - Рост доли ответов `502 Bad Gateway` и `504 Gateway Timeout` более чем на 0.5% от общего RPS.
   - Дисбаланс распределения нагрузки между узлами пула более чем на 20% при использовании Round Robin или Least Conn.
   - Превышение порога p95 задержки `$upstream_response_time` выше установленного SLO (например, > 200 мс).

---

## Дополнительная информация

### Связанные документы

- [Алгоритмы балансировки](./algorithms.md) — математика и особенности Round Robin, Least Connections, Hash, IP Hash, Random, Least Time, Feedback.
- [Практическая конфигурация балансировки](./practical_configuration.md) — директивы `proxy_pass`, `proxy_set_header`, настройка буферов и базовых параметров upstream.
- [Health Checks и мониторинг](./health_checks_and_monitoring.md) — архитектура пассивных и активных проверок доступности, модули телеметрии VTS и Status API.
- [Sticky Sessions (Прилипание сессий)](./sticky_sessions.md) — механизмы Cookie, Learn и Route для сохранения состояния клиентов.
- [Динамическое разрешение DNS](./dynamic_dns_resolution.md) — параметры `resolver` и директива `resolve` для динамических окружений.
- [Сравнение балансировщиков и дополнительные сведения](./additional_info_and_comparisons.md) — архитектурное сопоставление Nginx, HAProxy, Traefik и Apache.
- [L4-проксирование Nginx (Stream)](../nginx_l4_proxying.md) — балансировка TCP/UDP на транспортном уровне.
- [Оптимизация производительности Nginx](../../Performance/nginx_performance_tuning.md) — глубокий тюнинг воркеров, ядра Linux и сокетов.
- [PROXY Protocol](../../../../Networking/Protocols/proxy_protocol.md) — спецификация и применение протокола PROXY v1/v2.
- [Кластеризация и балансировка для HA](../../../../Concepts/High_Availability/ha_clustering_and_load_balancing.md) — принципы высокой доступности, VRRP и IPVS.
