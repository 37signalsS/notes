# Upstream Keepalive и Connection Pooling для веб-производительности

**Актуально для:** Nginx 1.26+, Angie 1.8+ / 1.12.x, HAProxy 2.8+ / 3.0+, Apache 2.4.60+, Linux Kernel 6.x

## Определения

- **Keepalive Connection Pool (Пул постоянных upstream-соединений)** — механизм кэширования и повторного использования открытых сетевых сокетов (обычно HTTP/1.1 или FastCGI/uWSGI) между обратным прокси-сервером (Nginx, Angie, HAProxy, Apache) и вышестоящими бэкендами. Устраняет необходимость выполнения процедур 3-way handshake TCP и согласования TLS для каждого поступающего клиентского запроса.
- **Keepalive Timeout (Таймаут простоя соединения)** — максимальный интервал неактивности, в течение которого сокет в состоянии `idle` удерживается в пуле в ожидании нового запроса перед принудительным закрытием со стороны прокси или бэкенда.
- **Max Requests Per Connection (`keepalive_requests`)** — предельное количество последовательных HTTP-транзакций, которое разрешено обслужить через одно постоянное TCP-соединение до его контролируемого закрытия и замены новым. Служит защитой от утечек памяти в долгоживущих процессах бэкенда и обеспечивает балансировку нагрузки между серверами.
- **Max Lifetime Per Connection (`keepalive_time`)** — максимальное абсолютное время жизни соединения в пуле независимо от объема обслуженных запросов. Предотвращает перекосы в распределении нагрузки при динамических изменениях DNS или конфигурации upstream.
- **TIME_WAIT State & 2MSL** — состояние TCP-сокета на стороне инициатора закрытия соединения (active closer), при котором порт остается заблокированным на удвоенное максимальное время жизни сегмента (2MSL, в Linux стандартно 60 секунд) для гарантированной доставки запоздавших пакетов и защиты от перепутывания данных старого и нового воплощения соединения.
- **Ephemeral Port Exhaustion (Исчерпание эфемерных портов)** — отказ в установке новых исходящих TCP-соединений (`connect() failed: 99 Cannot assign requested address`), вызванный тем, что все доступные порты из диапазона `ip_local_port_range` для конкретного 4-tuple (`src_ip:src_port -> dst_ip:dst_port`) находятся в состояниях `ESTABLISHED` или `TIME_WAIT`.
- **Keepalive Race Condition (Гонка таймаутов простоя / Silent Close)** — ситуация асинхронного закрытия соединения, при которой бэкенд закрывает сокет по собственному `idle_timeout` точно в тот момент, когда прокси извлекает это же соединение из пула и отправляет в него новый HTTP-запрос. Приводит к возврату пакета TCP RST от бэкенда и возникновению ошибки `502 Bad Gateway` на прокси.
- **Reuse Ratio (Коэффициент переиспользования соединений)** — ключевая SRE-метрика эффективности пула, вычисляемая как отношение повторно использованных соединений к общему числу обработанных запросов:
  $$\text{Reuse Ratio} = 1 - \frac{\text{Новые TCP Handshakes}}{\text{Всего запросов к бэкенду}}$$
  В высоконагруженных прокси-системах целевой показатель составляет $>95\%$.
- **Origin Latency (Задержка источника / TTFB бэкенда)** — суммарное время от момента передачи запроса с обратного прокси на бэкенд до получения первого байта ответа. Пул соединений уменьшает Origin Latency ровно на величину $1\text{--}3 \times \text{RTT}$.
- **Multiplexing vs Pooling (Мультиплексирование против пулинга)** — фундаментальное различие протоколов: HTTP/1.1 передает запросы по TCP строго последовательно (Head-of-Line Blocking на уровне HTTP), требуя пула из десятков параллельных сокетов. HTTP/2 и gRPC мультиплексируют сотни независимых потоков внутри одного TCP-соединения, кардинально снижая потребность в большом количестве сокетов.

---

## Основные концепции

### Задержки сетевых рукопожатий и математика производительности

При отсутствии постоянных соединений каждый запрос клиента, требующий обращения к бэкенду, порождает каскад сетевых накладных расходов:

```
Прокси                                              Бэкенд
  │                                                   │
  │ ──── SYN (1 RTT TCP Handshake) ─────────────────► │
  │ ◄─── SYN-ACK ──────────────────────────────────── │
  │ ──── ACK + ClientHello (TLS 1.3 Handshake) ─────► │
  │ ◄─── ServerHello + Finished (1 RTT TLS) ───────── │
  │ ──── HTTP Request ──────────────────────────────► │
  │ ◄─── HTTP Response First Byte (TTFB) ──────────── │
```

Без upstream keepalive минимальная задержка до получения первого байта составляет:
- **Чистый HTTP:** $1 \times \text{RTT} + T_{\text{app}}$ (где $T_{\text{app}}$ — время обработки в приложении);
- **HTTPS (TLS 1.3):** $2 \times \text{RTT} + T_{\text{app}} + T_{\text{crypto}}$ (криптографические вычисления ключей ECDHE);
- **HTTPS (TLS 1.2):** $3 \times \text{RTT} + T_{\text{app}} + T_{\text{crypto}}$.

При задержке в дата-центре $\text{RTT} = 0.5\text{--}1.0\text{ мс}$ накладные расходы составляют единицы миллисекунд. Однако при распределенной архитектуре, гео-распределенных ЦОД или межсерверных каналах с $\text{RTT} = 20\text{--}50\text{ мс}$ накладные расходы на каждый запрос достигают **60–150 мс**, что катастрофически снижает производительность.

Кроме RTT, новое TCP-соединение всегда начинает передачу с минимального окна перегрузки (**Initial Congestion Window, initcwnd** = 10 MSS) и проходит фазу медленного старта (**Slow Start**). Пул соединений удерживает сокет в разогретом состоянии с уже расширенным окном перегрузки (**cwnd**), обеспечивая передачу объемных тел ответов на полной пропускной способности интерфейса.

---

### Архитектура пулов: Nginx, Angie, HAProxy и Apache

Различные серверы реализуют управление соединениями на базе различных архитектурных моделей:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           АРХИТЕКТУРНЫЕ МОДЕЛИ ПУЛОВ                        │
├──────────────────────────────────────┬──────────────────────────────────────┤
│  Nginx OSS (Изоляция по воркерам)    │  Angie (Разделяемая память zone)     │
│                                      │                                      │
│  Worker 1: [Conn1, Conn2, .. ConnN]  │  Worker 1 ──┐                        │
│  Worker 2: [Conn1, Conn2, .. ConnN]  │  Worker 2 ──┼──► Shared Memory Zone  │
│  (Пулы строго изолированы;           │  Worker 3 ──┤    (Единый учет пиров, │
│   нет переиспользования между ядрами)│  Worker 4 ──┘    статистика, API)    │
├──────────────────────────────────────┼──────────────────────────────────────┤
│  HAProxy (Потокобезопасный пул)      │  Apache httpd (mod_proxy / Event)    │
│                                      │                                      │
│  Thread 1 ──┐                        │  Process/Thread Pool                 │
│  Thread 2 ──┼──► Global/Per-Thread   │  ├── smax: мягкий порог idle-сокетов │
│  Thread 3 ──┤    Safe Connection     │  ├── max: жесткий предел пула        │
│  Thread 4 ──┘    Pool (http-reuse)   │  └── ttl: таймаут жизни сокета       │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

#### 1. Модель Nginx OSS: Изоляция рабочих процессов
В классическом Nginx директива `keepalive N` определяет максимальное число свободных (`idle`) постоянных соединений **на один рабочий процесс (`worker_process`)**:
- Если сервер имеет 16 воркеров и в блоке `upstream` задано `keepalive 32`, то суммарно прокси может удерживать до $16 \times 32 = 512$ открытых idle-соединений.
- Соединение, открытое воркером №1, не может быть использовано воркером №2. При неравномерном распределении трафика (например, при отсутствии `reuseport`) часть воркеров будет открывать новые TCP-соединения, пока другие держат неиспользуемые сокеты.
- Директива `keepalive` не ограничивает общее число одновременно активных соединений. При всплеске нагрузки воркер откроет столько сокетов, сколько требуется, но по завершении запроса сохранит в кэше не более $N$ штук, а остальные немедленно закроет (переведя их в `TIME_WAIT`).

#### 2. Модель Angie: Синхронизация и разделяемая память
Российский веб-сервер Angie расширяет архитектуру Nginx:
- Директива `zone <name> <size>` внутри `upstream` организует хранение состояния пула, счетчиков и пиров в общей памяти (`shared memory`).
- Встроенный модуль мониторинга и консолидированная статистика через HTTP REST API (`/api/status/http/upstreams/`) позволяют в реальном времени отслеживать точное число свободных и активных keepalive-соединений по каждому бэкенду.
- Поддерживается прямое проксирование HTTP/2 и gRPC к бэкендам с динамическим управлением мультиплексированными соединениями.

#### 3. Модель HAProxy: Интеллектуальный пул и стратегии `http-reuse`
HAProxy использует многопоточную модель (`threads`) с общим пулом соединений к каждому бэкенд-серверу (`server`). Поведение повторного использования регулируется параметром `http-reuse`:
- `http-reuse never` — постоянные соединения отключены; каждое клиентское соединение инициирует новое подключение к бэкенду.
- `http-reuse safe` — режим по умолчанию в современных версиях. Соединение повторно используется только для первого запроса клиентской сессии или для заведомо идемпотентных запросов, гарантируя отсутствие сбоев при гонках таймаутов.
- `http-reuse aggressive` — соединение берется из пула немедленно для любого запроса. Если бэкенд параллельно закрыл сокет, HAProxy прозрачно повторяет запрос на свежем соединении (если тело запроса не было передано в сеть).
- `http-reuse always` — максимально агрессивное переиспользование сокетов между всеми клиентами без каких-либо задержек.

#### 4. Модель Apache httpd: `mod_proxy`
В сервере Apache (с MPM `event` или `worker`) пул регулируется параметрами директивы `ProxyPass`:
- `enablereuse=On` — включает постоянные соединения пула;
- `smax` — мягкий лимит свободных соединений. Соединения сверх `smax` закрываются по истечении таймаута `ttl`;
- `max` — абсолютный предел одновременных TCP-соединений к конкретному узлу;
- `ttl` — время жизни неактивного сокета в пуле;
- `acquire` — предельное время ожидания освобождения сокета из пула при достижении `max`.

---

### Сравнительный анализ директив и возможностей серверов

| Возможность / Параметр | Nginx OSS | Angie | HAProxy | Apache httpd (`mod_proxy`) |
| :--- | :--- | :--- | :--- | :--- |
| **Единица изоляции пула** | Процесс (`worker`) | Процесс (`worker`) + Shared Zone | Поток / Процесс (Global) | Поток / Процесс MPM |
| **Лимит idle-соединений** | `keepalive N` (на воркер) | `keepalive N` (на воркер) | `pool-max-conn N` (на сервер) | `smax` / `max` (на воркер) |
| **Предел запросов на сокет**| `keepalive_requests` | `keepalive_requests` | Нет (управляется бэкендом) | `max` в комбинации с MPM |
| **Предел времени жизни** | `keepalive_time` | `keepalive_time` | `pool-purge-delay` | `ttl` |
| **Таймаут простоя (idle)** | `keepalive_timeout` | `keepalive_timeout` | `timeout http-keep-alive` | `ttl` / `connectiontimeout` |
| **FastCGI / uWSGI пулинг** | Да (`fastcgi_keep_conn`) | Да (`fastcgi_keep_conn`) | Через FastCGI app-mode | Да (`ProxyPass fcgi://`) |
| **Мониторинг пула в runtime**| Косвенно через `stub_status`| Полноценный REST API JSON | Runtime Socket (`show pools`)| `mod_status` |

---

### Механика гонки таймаутов простоя (Keepalive Race Condition)

Самый распространенный скрытый сбой в архитектуре с постоянными соединениями — возникновение спорадических ошибок `502 Bad Gateway` (или `Connection reset by peer`) при низкой или волнообразной нагрузке.

```
Прокси (Nginx/Angie/HAProxy)                         Бэкенд (Node.js/Go/Gunicorn/PHP-FPM)
    │                                                        │
    │ ─── Соединение находится в состоянии IDLE в пуле ───   │
    │                                                        │
    │                                           [Таймаут бэкенда истек!]
    │ [Поступает клиентский запрос]             Бэкенд отправляет TCP FIN
    │ Прокси извлекает сокет из пула                         │
    │ Прокси отправляет HTTP-запрос (TCP PSH/ACK)            │
    │        \                                      /        │
    │         \                                    /         │
    │          ─── Пакеты пересекаются в сети ────           │
    │         /                                    \         │
    │        ▼                                      ▼        │
    │ Получает TCP FIN                        Получает HTTP-запрос на уже
    │ (сокет переходит в CLOSE_WAIT)          закрывающемся сокете!
    │                                         Бэкенд отвечает пакетом TCP RST
    │ ◄──────────────── TCP RST ──────────────────────────── │
    ▼
[Сбой!] Прокси фиксирует сброс соединения
(502 Bad Gateway, если отключен повтор запроса)
```

#### Фундаментальное правило таймаутов
Чтобы гарантировать отсутствие гонок закрытия, **таймаут простоя на стороне бэкенда должен быть строго больше таймаута простоя на стороне прокси**:

$$T_{\text{idle}}(\text{Backend}) \ge T_{\text{idle}}(\text{Proxy}) + \Delta t$$

где $\Delta t$ — запас на сетевую задержку и джиттер планировщика операционной системы (рекомендуется не менее 5–15 секунд).

*Пример корректной настройки:*
- **Прокси (Nginx/Angie):** `keepalive_timeout 60s;`
- **Бэкенд (Go `http.Server` / Node.js / Puma):** `IdleTimeout = 75s;`
- **Бэкенд (Gunicorn):** `--keep-alive 75`

> [!IMPORTANT]
> Если сервер Nginx получает ошибку `Connection reset by peer` на сокете из keepalive-пула, он может повторить запрос к следующему серверу **только в том случае**, если директива `proxy_next_upstream` включает параметры `error` и `timeout`, а сам HTTP-метод признан идемпотентным (GET, HEAD), либо включен параметр `non_idempotent` (требует осторожности, чтобы не продублировать финансовые транзакции или мутирующие POST-запросы).

---

### Специфика пулов FastCGI, uWSGI и SCGI

Проксирование к серверам приложений по специализированным протоколам имеет архитектурные отличия от HTTP/1.1:

1. **FastCGI (PHP-FPM):**
   - По протоколу FastCGI после передачи каждого ответа процесс отправляет запись `FCGI_END_REQUEST`.
   - Если в Nginx не включена директива `fastcgi_keep_conn on;`, сервер Nginx выставляет флаг закрытия и разрывает TCP-соединение или UNIX-сокет сразу после первого же ответа.
   - Для поддержания пула к PHP-FPM обязательна связка:
     ```nginx
     upstream php_backend {
         server 127.0.0.1:9000;
         keepalive 32;
     }
     # в блоке location:
     fastcgi_pass php_backend;
     fastcgi_keep_conn on;
     ```
2. **uWSGI и SCGI:**
   - Родной протокол `uwsgi` изначально проектировался для обработки запроса в рамках одного соединения на процесс. При классическом развертывании Nginx открывает и закрывает сокет на каждый запрос.
   - Для включения постоянных соединений на стороне uWSGI-сервера требуется сборка с поддержкой keepalive и указание параметров `--http-keepalive` или запуск в режиме HTTP-проксирования, либо использование постоянных соединений через `uwsgi_socket_keepalive on;` на уровне сокетов ОС.

---

### Влияние на Core Web Vitals и метрики производительности

Использование постоянных соединений напрямую влияет на показатели производительности веб-приложений:

```
Метрика Core Web Vitals        Влияние Keepalive          Механизм влияния
─────────────────────────────────────────────────────────────────────────────────────────────
TTFB (Time to First Byte)     Критическое (Прямое)       Устраняет 1-3 RTT на handshake.
                                                         Снижение задержки на 20-150 мс.
LCP (Largest Contentful Paint) Высокое (Прямое)          Быстрая отдача HTML и динамических
                                                         ресурсов сдвигает отрисовку LCP.
INP (Interaction to Next Paint) Высокое (Прямое)         API-запросы, вызванные действием
                                                         пользователя, не ждут открытия сокета.
CLS (Cumulative Layout Shift)  Косвенное                 Быстрая отдача блокирующих данных
                                                         предотвращает запаздывающие сдвиги DOM.
```

Кроме снижения времени отклика, устранение постоянных рукопожатий разгружает центральный процессор серверов:
- Экономия до **15–25% CPU** на кластере за счет устранения асимметричных криптографических вычислений алгоритмов ECDH/RSA при повторных TLS-хендшейках.
- Устранение пиковых блокировок системных вызовов ядра Linux (`sys_enter_connect`, `sys_enter_accept4`, выделение структур сокетов `struct sock`).

---

## Практические сценарии

### Сценарий 1: Промышленная конфигурация Nginx и Angie для высоконагруженного API и PHP-FPM

Комплексный пример настройки высокопроизводительного обратного прокси с пулами соединений к HTTP/1.1 микросервисам и пулу воркеров PHP-FPM с использованием общей памяти `zone`.

```nginx
# /etc/nginx/conf.d/highload_upstreams.conf

# 1. Пул постоянных соединений к микросервисам HTTP/1.1
upstream backend_api {
    # Зона разделяемой памяти (критично для Angie и Nginx Plus)
    zone backend_api_zone 256k;

    server 10.0.10.11:8080 max_fails=3 fail_timeout=10s weight=1;
    server 10.0.10.12:8080 max_fails=3 fail_timeout=10s weight=1;
    server 10.0.10.13:8080 backup;

    # Максимальное число свободных (idle) постоянных соединений на каждый worker
    keepalive 64;

    # Ротация соединений: предотвращает утечки памяти на бэкенде и балансирует нагрузку
    keepalive_requests 10000;

    # Максимальное время жизни одного сокета в пуле (1 час)
    keepalive_time 1h;

    # Таймаут простоя: сокет закрывается прокси, если не поступил запрос за 60 секунд.
    # Бэкенды должны иметь IdleTimeout >= 75 секунд!
    keepalive_timeout 60s;
}

# 2. Пул постоянных соединений к пулу PHP-FPM FastCGI
upstream php_fpm_pool {
    zone php_fpm_zone 128k;

    # Подключение через локальный TCP или абстрактный UNIX-сокет
    server 127.0.0.1:9000 max_fails=2 fail_timeout=5s;
    server 127.0.0.1:9001 max_fails=2 fail_timeout=5s;

    keepalive 32;
    keepalive_requests 2000;
    keepalive_timeout 30s;
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name api.enterprise.internal;

    # TLS-сертификаты и настройки сессий
    ssl_certificate /etc/ssl/certs/api_prod.crt;
    ssl_certificate_key /etc/ssl/private/api_prod.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:50m;
    ssl_session_timeout 1d;

    # Тюнинг клиентских буферов
    client_body_buffer_size 128k;
    client_max_body_size 10m;

    # Роутинг к HTTP API микросервисам
    location /v1/ {
        proxy_pass http://backend_api;

        # ОБЯЗАТЕЛЬНО для активации keepalive в upstream Nginx/Angie:
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Передача метаданных клиента
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Защита от зависаний и обработка сбоев
        proxy_connect_timeout 2s;
        proxy_send_timeout 10s;
        proxy_read_timeout 15s;

        # Идемпотентный автоматический повтор при получении RST из-за гонки таймаутов
        proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 5s;

        # Оптимизация буферизации ответов
        proxy_buffering on;
        proxy_buffer_size 8k;
        proxy_buffers 16 16k;
        proxy_busy_buffers_size 32k;
    }

    # Роутинг к PHP-FPM FastCGI
    location ~ \.php$ {
        fastcgi_pass php_fpm_pool;

        # ОБЯЗАТЕЛЬНО для работы keepalive с протоколом FastCGI
        fastcgi_keep_conn on;

        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;

        fastcgi_connect_timeout 2s;
        fastcgi_send_timeout 30s;
        fastcgi_read_timeout 30s;
    }
}
```

---

### Сценарий 2: HAProxy 2.8+ / 3.0+ Advanced Connection Pooling

Настройка высокопроизводительного пула соединений в HAProxy с распределением нагрузки, защитой от гонок таймаутов и динамическим мониторингом через Runtime Socket.

```haproxy
# /etc/haproxy/haproxy.cfg

global
    log /dev/log local0 info
    maxconn 100000
    user haproxy
    group haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners
    stats timeout 30s
    nbthread 8
    cpu-map auto:1/1-8 0-7

defaults
    log     global
    mode    http
    option  httplog
    option  dontlognull
    retries 3
    option  redispatch

    # Клиентские таймауты
    timeout connect 3s
    timeout client  30s
    timeout server  30s

    # Таймаут ожидания нового запроса в рамках постоянного соединения
    timeout http-keep-alive 60s

frontend fe_main
    bind 0.0.0.0:80
    bind 0.0.0.0:443 ssl crt /etc/haproxy/certs/site.pem alpn h2,http/1.1
    default_backend be_dynamic_cluster

backend be_dynamic_cluster
    mode http
    balance roundrobin

    # Активация keepalive и выбор политики переиспользования:
    # 'safe' гарантирует отсутствие разрывов при гонках закрытия сокетов
    option http-keep-alive
    http-reuse safe

    # Проверка доступности бэкендов на уровне L7
    option httpchk GET /healthz
    http-check expect status 200

    # Настройка серверов пула:
    # - maxconn 500: жесткий лимит одновременных активных запросов на сервер
    # - pool-max-conn 64: максимум idle-соединений, сохраняемых в пуле
    # - pool-low-conn 16: минимальный порог разогретых соединений
    # - pool-purge-delay 5s: очистка сокетов, не используемых дольше 5 секунд
    server app-01 10.0.20.101:8080 check inter 2s fall 3 rise 2 maxconn 500 pool-max-conn 64 pool-low-conn 16
    server app-02 10.0.20.102:8080 check inter 2s fall 3 rise 2 maxconn 500 pool-max-conn 64 pool-low-conn 16
    server app-03 10.0.20.103:8080 check inter 2s fall 3 rise 2 maxconn 500 pool-max-conn 64 pool-low-conn 16
```

---

### Сценарий 3: Настройка сетевого стека Linux ядра (Sysctl & Limits) для 100k+ RPS

При интенсивном повторном использовании соединений или кратковременных всплесках трафика операционная система должна быть подготовлена к утилизации сокетов без переполнения очередей и исчерпания портов.

```ini
# /etc/sysctl.d/99-network-performance.conf

# 1. Расширение диапазона исходящих (эфемерных) портов.
# По умолчанию: 32768-60999 (28k портов). Расширяем до 55k портов.
net.ipv4.ip_local_port_range = 10240 65535

# 2. Безопасное повторное использование сокетов в состоянии TIME_WAIT для исходящих коннектов.
# Работает ТОЛЬКО при включенных метках времени (tcp_timestamps = 1) согласно RFC 1323.
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_timestamps = 1

# 3. Сокращение интервала удержания сокета в FIN_WAIT_2 / TIME_WAIT (в секундах)
net.ipv4.tcp_fin_timeout = 15

# 4. Предел одновременно удерживаемых сокетов в состоянии TIME_WAIT в системе.
# Предотвращает DoS памяти ядра при лавинообразном закрытии соединений.
net.ipv4.tcp_max_tw_buckets = 262144

# 5. Очереди входящих и полуоткрытых соединений (backlog)
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.core.netdev_max_backlog = 65535

# 6. Тюнинг буферов приема и отправки TCP (память автоподстройки wmem/rmem)
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# 7. Защита от переполнения таблицы conntrack (если включен iptables/nftables)
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
```

Применение конфигурации ядра:
```bash
sysctl --system
# → * Applying /etc/sysctl.d/99-network-performance.conf ...
# → net.ipv4.ip_local_port_range = 10240 65535
# → net.ipv4.tcp_tw_reuse = 1
# → net.ipv4.tcp_timestamps = 1
# → net.ipv4.tcp_fin_timeout = 15
# → net.ipv4.tcp_max_tw_buckets = 262144
# → net.core.somaxconn = 65535
```

Настройка лимитов системных дескрипторов для сервиса в `systemd`:
```ini
# /etc/systemd/system/nginx.service.d/override.conf
[Service]
LimitNOFILE=1048576
LimitNPROC=512000
```

```bash
systemctl daemon-reload
systemctl restart nginx
cat /proc/$(pgrep -f "nginx: master" | head -n1)/limits | grep "Max open files"
# → Max open files            1048576              1048576              files
```

---

### Сценарий 4: gRPC и HTTP/2 Мультиплексирование vs HTTP/1.1 Пулинг

При переходе на протоколы HTTP/2 или gRPC архитектура взаимодействия с upstream серверами кардинально меняется:

```
HTTP/1.1 Upstream (Пул параллельных TCP-сокетов)
Прокси ═══════════════[ TCP Conn 1 ]═══════════════► Бэкенд (Request A -> Response A)
Прокси ═══════════════[ TCP Conn 2 ]═══════════════► Бэкенд (Request B -> Response B)
Прокси ═══════════════[ TCP Conn 3 ]═══════════════► Бэкенд (Request C -> Response C)

HTTP/2 & gRPC Upstream (Мультиплексирование потоков в одном TCP-сокете)
                      ┌─ Stream 1: Request A / Response A ─┐
Прокси ═══════════════╡  Stream 3: Request B / Response B  ╞═══════════════► Бэкенд
                      └─ Stream 5: Request C / Response C ─┘
```

Конфигурация Angie / Nginx для gRPC и HTTP/2 upstream:
```nginx
upstream grpc_cluster {
    zone grpc_cluster_zone 128k;
    server 10.0.30.21:50051;
    server 10.0.30.22:50051;

    # Для HTTP/2 и gRPC достаточно небольшого количества сокетов (1-4 на процесс),
    # так как каждый сокет обслуживает сотни параллельных потоков (streams)
    keepalive 8;
    keepalive_time 2h;
    keepalive_timeout 300s;
}

server {
    listen 50051 ssl;
    http2 on;

    location /payments.PaymentService/ {
        grpc_pass grpc://grpc_cluster;

        # Таймауты для gRPC streaming-вызовов
        grpc_connect_timeout 2s;
        grpc_send_timeout 60s;
        grpc_read_timeout 60s;

        # Keepalive на уровне сокета для предотвращения разрыва NAT-шлюзами
        grpc_socket_keepalive on;
    }
}
```

---

### Сценарий 5: Zero-Downtime деплой бэкендов и дренаж постоянных соединений

При перезапуске или обновлении приложений бэкенда клиенты могут столкнуться с `502 Bad Gateway`, если бэкенд грубо разрывает активные или idle-соединения без предупреждения прокси.

**Последовательность шагов безопасного вывода бэкенда из пула:**

```
1. Фаза Pre-drain: Прокси перестает слать новые сессии (перевод узла в DRAIN).
2. Фаза Idle Close: Прокси закрывает простаивающие сокеты по `keepalive_timeout`.
3. Фаза Graceful Stop: Бэкенд дожидается завершения активных запросов.
4. Перезапуск процесса / замена контейнера.
```

**Реализация через HAProxy Runtime CLI:**
```bash
# 1. Переводим сервер бэкенда в режим дренажа (новые соединения не берутся)
echo "set server be_dynamic_cluster/app-01 state drain" | socat stdio /run/haproxy/admin.sock
# → [Server be_dynamic_cluster/app-01 is now in DRAIN state]

# 2. Ожидаем завершения текущих активных транзакций
while [ $(echo "show servers conn be_dynamic_cluster" | socat stdio /run/haproxy/admin.sock | awk '$2=="app-01" {print $4}') -gt 0 ]; do
    echo "Waiting for active connections to drain..."
    sleep 1
done

# 3. Полностью выключаем сервер для проведения работ
echo "set server be_dynamic_cluster/app-01 state maint" | socat stdio /run/haproxy/admin.sock

# 4. Обновляем сервис на сервере 10.0.20.101 и возвращаем в строй
echo "set server be_dynamic_cluster/app-01 state ready" | socat stdio /run/haproxy/admin.sock
```

---

## Операции и команды

### 1. Глубокий анализ состояния сокетов через утилиту `ss`

```bash
# Просмотр соединений с таймерами keepalive и детальной TCP-информацией к порту бэкенда
ss -tni -o '( dport = :8080 )'
# → ESTAB  0  0  10.0.10.1:45322  10.0.10.11:8080  timer:(keepalive,58sec,0)
# →      cubic wscale:7,7 rto:200 rtt:0.32/0.05 ato:40 mss:1460 rcvspace:14600 ssthresh:10 cwnd:10

# Подсчет количества установленных и idle-соединений с группировкой по процессам Nginx
ss -tnp state established '( dport = :8080 )' | awk '{print $NF}' | cut -d',' -f1 | sort | uniq -c
# →  32 users:(("nginx",pid=12401
# →  32 users:(("nginx",pid=12402
# →  32 users:(("nginx",pid=12403
# →  32 users:(("nginx",pid=12404

# Мониторинг соединений в состоянии TIME_WAIT
ss -s
# → Total: 1240
# → TCP:   5800 (estab 210, closed 5420, orphaned 0, timewait 4810)
```

### 2. Захват пакетов и выявление гонок закрытия (`tcpdump`)

Выявление отправки пакетов `RST` со стороны бэкенда при попытке использования разорванного keepalive-соединения:

```bash
# Отслеживание пакетов TCP RST и TCP FIN между прокси и бэкендом
tcpdump -nn -tt -i eth0 "tcp port 8080 and (tcp[tcpflags] & (tcp-rst|tcp-fin) != 0)"
# → 16:40:12.102345 IP 10.0.10.11.8080 > 10.0.10.1.45322: Flags [F.], seq 105234, ack 501, win 502
# → 16:40:12.102390 IP 10.0.10.1.45322 > 10.0.10.11.8080: Flags [P.], seq 501:850, ack 105234
# → 16:40:12.102580 IP 10.0.10.11.8080 > 10.0.10.1.45322: Flags [R], seq 105235, win 0
# Примечание: Флаг [F.] — бэкенд шлет FIN; прокси одновременно шлет данные [P.]; бэкенд сбрасывает соединение флагом [R] (RST)!
```

### 3. Снятие метрик пула через Angie Status REST API

```bash
# Получение детальной телеметрии upstream-пула в формате JSON
curl -s http://127.0.0.1:8888/api/status/http/upstreams/backend_api/ | jq '{
    zone: .zone,
    keepalive_pool_size: .keepalive,
    peers: [.peers[] | {
        server: .server,
        state: .state,
        active_conns: .selected.current,
        total_requests: .requests,
        cached_idle_conns: .keepalive,
        fails_count: .fails
    }]
}'
# → {
# →   "zone": "backend_api_zone",
# →   "keepalive_pool_size": 64,
# →   "peers": [
# →     {
# →       "server": "10.0.10.11:8080",
# →       "state": "up",
# →       "active_conns": 5,
# →       "total_requests": 142050,
# →       "cached_idle_conns": 31,
# →       "fails_count": 0
# →     },
# →     {
# →       "server": "10.0.10.12:8080",
# →       "state": "up",
# →       "active_conns": 4,
# →       "total_requests": 139880,
# →       "cached_idle_conns": 33,
# →       "fails_count": 0
# →     }
# →   ]
# → }
```

### 4. Инспекция пула соединений в HAProxy через Runtime Socket

```bash
# Просмотр статистики распределения пулов соединений
echo "show pools" | socat stdio /run/haproxy/admin.sock | head -n 15
# → Dumping pools usage :
# →   - Pool connection (448 bytes) : 256 allocated (114688 bytes), 64 used, 4 max
# →   - Pool conn_stream (256 bytes) : 128 allocated (32768 bytes), 12 used

# Просмотр количества активных и простаивающих соединений к серверам
echo "show servers conn be_dynamic_cluster" | socat stdio /run/haproxy/admin.sock
# → # bk_name/srv_name cur_conn srv_idle_conn cur_idle_thr max_idle_conn
# → be_dynamic_cluster/app-01 12 32 8 64
# → be_dynamic_cluster/app-02 10 30 8 64
# → be_dynamic_cluster/app-03 0 0 0 64
```

### 5. Бенчмаркинг эффективности переиспользования соединений (`curl` и `wrk`)

```bash
# Измерение задержки первого запроса (с установкой TCP и TLS) против повторного (keepalive)
curl -s -k -w "TCP: %{time_connect}s | TLS: %{time_appconnect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s\n" \
     -o /dev/null https://api.enterprise.internal/v1/ping \
     --next \
     -s -k -w "TCP: %{time_connect}s | TLS: %{time_appconnect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s\n" \
     -o /dev/null https://api.enterprise.internal/v1/ping
# → Запрос 1: TCP: 0.024s | TLS: 0.052s | TTFB: 0.068s | Total: 0.070s
# → Запрос 2: TCP: 0.000s | TLS: 0.000s | TTFB: 0.012s | Total: 0.013s
# (Экономия 55 мс на устранении повторного TCP/TLS рукопожатия!)

# Нагрузочное тестирование с сохранением постоянных соединений (wrk)
wrk -t8 -c200 -d30s -H "Connection: keep-alive" https://api.enterprise.internal/v1/ping
# → Requests/sec:  48520.40
# → Latency 50%:    2.10ms
# → Latency 99%:    6.45ms
```

---

## Диагностика и устранение неисправностей

| Проблема | Симптомы | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- | :--- |
| **Спорадические 502 Bad Gateway / RST** | В логах прокси: `recv() failed (104: Connection reset by peer) while reading response header from upstream` | **Keepalive Race Condition:** Таймаут простоя бэкенда меньше или равен таймауту прокси. Бэкенд закрывает сокет во время отправки запроса. | Замерить таймауты: `tcpdump -nn -i any "tcp[tcpflags] & tcp-rst != 0"`; сверить таймауты в конфигах. | Установить: $T_{\text{backend\_idle}} \ge T_{\text{proxy\_idle}} + 15\text{s}$. Включить `proxy_next_upstream error timeout;`. |
| **Исчерпание эфемерных портов** | `connect() failed (99: Cannot assign requested address) while connecting to upstream` | Огромное число короткоживущих сокетов в `TIME_WAIT` исчерпало диапазон портов; постоянные соединения отключены. | `ss -s` (показывает тысячи timewait); `sysctl net.ipv4.ip_local_port_range` | Включить `net.ipv4.tcp_tw_reuse = 1`; расширить диапазон портов `10240 65535`; активировать `keepalive` в upstream. |
| **Keepalive не работает (постоянный Handshake)** | `time_connect` в curl не равен 0; рост CPU на бэкенде; метрика `keepalive` в Status API всегда 0 | В блоке `location` отсутствует `proxy_http_version 1.1;` либо заголовок `Connection` не очищен (`proxy_set_header Connection "";`). | `tcpdump -A -i lo "tcp port 8080"` (виден заголовок `Connection: close`). | Добавить `proxy_http_version 1.1;` и `proxy_set_header Connection "";`. Для FastCGI: `fastcgi_keep_conn on;`. |
| **Перегрузка памяти бэкенда (Pool Exhaustion)** | Падение процессов приложения (OOM), исчерпание пулов потоков/воркеров на стороне сервиса | Слишком большой `keepalive` на прокси умножается на количество воркеров: $N_{\text{workers}} \times N_{\text{keepalive}}$. | `ss -tnp '( dport = :8080 )' \| wc -l`; `top` на ноде бэкенда. | Уменьшить `keepalive` в Nginx до обоснованного расчетного значения; в HAProxy ограничить `pool-max-conn`. |
| **Утечка сессий или задержка деплоя** | Клиенты попадают на старую версию приложения после rolling update; бэкенд не может завершить graceful shutdown | Значения `keepalive_requests` и `keepalive_time` слишком велики или не заданы; сокеты удерживаются часами. | Проверить возраст сокетов через `ss -ti -o`. | Задать жесткий `keepalive_time 30m;` и `keepalive_requests 5000;`. Перед деплоем применять процедуру дренажа. |
| **Сбой сессий TLS upstream** | Медленный TTFB к HTTPS upstream; повторные полные TLS-хендшейки при переоткрытии сокетов | Отключен кэш сессий между прокси и бэкендом при защищенном upstream-проксировании. | Проверить параметр `proxy_ssl_session_reuse`. | Добавить в конфигурацию `proxy_ssl_session_reuse on;`. |

---

## Рекомендации

### Математическая формула расчета размера пула

Задание директивы `keepalive` наугад — главная причина скрытых сбоев:
- **Заниженное значение:** постоянный сброс и переоткрытие сокетов, нулевая эффективность пула при пиковых нагрузках.
- **Завышенное значение:** напрасный расход файловых дескрипторов и памяти (`TCP socket buffer`) на прокси и бэкенде.

Формула расчета оптимального числа idle-соединений на один воркер Nginx/Angie:

$$N_{\text{idle\_per\_worker}} = \left\lceil \frac{\text{RPS}_{\text{peak}} \times T_{\text{latency}}}{N_{\text{workers}}} \times M \right\rceil$$

Где:
- $\text{RPS}_{\text{peak}}$ — пиковая нагрузка на данный upstream (запросов в секунду);
- $T_{\text{latency}}$ — средняя задержка обработки запроса бэкендом (в секундах, например $0.05\text{ с}$ для 50 мс);
- $N_{\text{workers}}$ — количество рабочих процессов прокси (обычно равно числу CPU ядер);
- $M$ — коэффициент запаса на неравномерность распределения трафика между воркерами (рекомендуется $1.3\text{--}1.5$).

*Пример расчета:*
- Пиковый трафик к API: $\text{RPS} = 10\,000$;
- Время ответа приложения: $T = 30\text{ мс} = 0.03\text{ с}$;
- Сервер Nginx: 8 ядер ($N_{\text{workers}} = 8$);
- Запас $M = 1.3$:
$$N_{\text{idle}} = \left\lceil \frac{10\,000 \times 0.03}{8} \times 1.3 \right\rceil = \lceil 37.5 \times 1.3 \rceil = \lceil 48.75 \rceil = 49$$
**Итоговая рекомендация:** выставляем `keepalive 48;` или `keepalive 64;` в блоке `upstream`.

---

### Матрица иерархии таймаутов

Для предотвращения зависаний и гонок соблюдайте строгую иерархию таймаутов на всех уровнях инфраструктуры:

```
Уровень                 Параметр                     Рекомендуемое значение
─────────────────────────────────────────────────────────────────────────────
1. Клиент / Edge        client_header_timeout        10s – 15s
                        client_body_timeout          15s – 30s
2. Proxy Idle           keepalive_timeout (прокси)   60s (надежная граница)
3. Backend Idle         IdleTimeout (приложение)     75s – 90s (строго > прокси!)
4. Сетевой стек Linux   tcp_fin_timeout              15s
                        tcp_keepalive_time           300s – 600s
```

---

### Рекомендации для SRE, DevOps и системных администраторов

#### Архитектура и эксплуатация
1. **Никогда не включайте `tcp_tw_recycle`:** Данный параметр удален в ядре Linux 4.12+, так как он нарушает спецификацию TCP при работе клиентов через NAT, приводя к массовой потере пакетов SYN. Используйте исключительно `net.ipv4.tcp_tw_reuse = 1`.
2. **Всегда задавайте `keepalive_requests` и `keepalive_time`:** Бесконечные соединения приводят к неравномерной утилизации upstream-нод при масштабировании кластера и маскируют утечки памяти в бэкендах. Оптимально: `keepalive_requests 5000-10000; keepalive_time 30m-1h;`.
3. **Используйте UNIX Domain Sockets при локальном размещении:** Если Nginx/Angie и приложение (PHP-FPM, Gunicorn, Puma) находятся на одном хосте, используйте UNIX-сокеты вместо loopback (`127.0.0.1`). Это полностью исключает накладные расходы сетевого стека ядра, проверки портов и состояния `TIME_WAIT`.

#### Мониторинг и алертинг (Prometheus / Grafana)
Настройте отслеживание метрик эффективности пула и правила алертинга:

```yaml
# Prometheus Alerting Rules
groups:
  - name: upstream_connection_pool_alerts
    rules:
      - alert: UpstreamLowReuseRatio
        expr: |
          (
            sum(rate(nginx_upstream_requests_total[5m])) - sum(rate(node_netstat_Tcp_ActiveOpens[5m]))
          ) / sum(rate(nginx_upstream_requests_total[5m])) < 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Низкий коэффициент переиспользования соединений (Reuse Ratio < 85%)"
          description: "Прокси создает избыточное количество новых TCP-соединений к бэкенду. Проверьте заголовки Connection и параметры keepalive."

      - alert: EphemeralPortExhaustionRisk
        expr: node_sockstat_TCP_tw > 40000
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Критическое количество сокетов в состоянии TIME_WAIT"
          description: "Число сокетов TIME_WAIT превысило 40 000. Высокий риск исчерпания эфемерных портов."
```

---

## Дополнительная информация

### См. также

- [Мониторинг HAProxy: метрики, runtime socket и алерты](file:///c:/Users/Elise/notes/WebServers/Concepts/haproxy_monitoring.md) — детальное руководство по управлению соединениями и пулами через Runtime CLI.
- [Circuit Breaker и паттерны деградации веб-производительности](file:///c:/Users/Elise/notes/WebServers/Concepts/web_performance/circuit_breaker_and_degradation.md) — изоляция сбойных бэкендов и взаимодействие с пулами.
- [Протоколы HTTP/2 и HTTP/3 для веб-производительности](file:///c:/Users/Elise/notes/WebServers/Concepts/web_performance/http2_http3.md) — мультиплексирование потоков и отличия от HTTP/1.1 пулинга.
- [Оптимизация производительности веб-сервера Nginx](file:///c:/Users/Elise/notes/WebServers/Nginx/Performance/nginx_performance_tuning.md) — системный тюнинг Nginx и системных вызовов сокетов.
- [Диагностика и устранение неисправностей веб-серверов](file:///c:/Users/Elise/notes/WebServers/Concepts/webserver_troubleshooting.md) — разбор сетевых ошибок 502, 504 и сбросов соединений.
- [Обзор балансировки нагрузки в Angie HTTP](file:///c:/Users/Elise/notes/WebServers/Angie/angie_http_load_balancing.md) — конфигурация апстримов и разделяемой памяти.
- [Архитектурная концепция Connection Pooling в сетях](file:///c:/Users/Elise/notes/Networking/Concepts/connection_pooling.md) — общесетевые аспекты пулов соединений БД и TCP.

### RFC и официальная документация

- **RFC 9112 (HTTP/1.1)** — разд. 9.3: *Persistence and Connection Management*, правила обработки заголовка `Connection`.
- **RFC 9113 (HTTP/2)** — разд. 5: *Streams and Multiplexing*, архитектура мультиплексированных соединений.
- **RFC 9293 (TCP)** — *Transmission Control Protocol Specification*, конечный автомат состояний TCP (`TIME_WAIT`, `FIN_WAIT`, `CLOSE_WAIT`).
- **RFC 1323 / RFC 7323** — *TCP Extensions for High Performance*, метки времени TCP Timestamps для безопасного `tcp_tw_reuse`.
