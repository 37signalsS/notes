# Практическая конфигурация балансировки нагрузки Nginx

**Актуально для:** Nginx 1.26+ (OSS/Plus) / 1.28+ (Mainline), Angie 1.6+ / 1.12.x

## Определения

**Upstream-группа (Upstream Pool)** — логический именованный пул бэкенд-серверов, объявленный директивой `upstream` в контексте `http`. Определяет адреса целевых серверов, их веса, лимиты одновременных подключений и правила выбывания узлов при сбоях.

**Проксирование (Reverse Proxying)** — архитектурный процесс приема клиентского сетевого запроса балансировщиком Nginx, его инспекции, модификации заголовков и последующей передачи целевому узлу из пула через семейство директив `proxy_*`.

**Пул соединений Upstream (Upstream Keepalive Pool)** — механизм кэширования и повторного использования открытых TCP/TLS-сокетов между воркерами Nginx и бэкенд-серверами. Устраняет накладные расходы на постоянное трехстороннее рукопожатие TCP (3-way handshake) и TLS-сессии.

**Буферизация ответа (Response Buffering)** — режим работы Nginx, при котором ответ бэкенда считывается сервером на максимальной скорости в оперативную память (или во временные файлы на диске) и лишь затем отдается клиенту, минимизируя время удержания потока бэкенда.

**Отказоустойчивое переключение (Failover / `proxy_next_upstream`)** — механизм автоматической прозрачной повторной отправки запроса на следующий работоспособный сервер пула при возникновении ошибки соединения, таймаута или сбойного HTTP-статуса на первичном узле.

**Восстановление реального IP (Real IP Restoration)** — процедура извлечения фактического сетевого адреса клиента из служебных HTTP-заголовков (`X-Forwarded-For`, `X-Real-IP`) или бинарного заголовка PROXY Protocol при нахождении Nginx за промежуточными L4/L7-балансировщиками.

**Исчерпание эфемерных портов (Ephemeral Port Exhaustion)** — состояние сетевого стека ядра Linux, при котором нехватка свободных локальных TCP-портов (`net.ipv4.ip_local_port_range`) из-за скопления сокетов в состоянии `TIME_WAIT` приводит к невозможности открыть соединение с бэкендом (ошибка `Cannot assign requested address`).

**mTLS (Mutual TLS)** — протокол двусторонней криптографической аутентификации по стандарту TLS, при котором не только балансировщик проверяет сертификат бэкенда, но и бэкенд валидирует клиентский сертификат Nginx.

---

## Основные концепции и архитектура

### Роль и структура Upstream

Директива `upstream` изолирует топологию серверной инфраструктуры от конфигурации правил маршрутизации запросов в блоках `server` и `location`.

```text
[ Внешние клиенты ]
        │ HTTP/1.1, HTTP/2, HTTP/3
        ▼
┌────────────────────────────────────────────────────────┐
│ Nginx Reverse Proxy & Load Balancer                    │
│                                                        │
│  location /api/ {                                      │
│      proxy_pass http://backend_cluster;               │
│  }                                                     │
│                                                        │
│  upstream backend_cluster {                            │
│      zone cluster_zone 256k;                           │
│      server 10.0.1.11:8080 weight=3 max_conns=200;    │
│      server 10.0.1.12:8080 weight=1 max_conns=200;    │
│      server 10.0.1.13:8080 backup;                    │
│      keepalive 64;                                     │
│  }                                                     │
└───────┬────────────────────────┬───────────────────────┘
        │                        │ (Keepalive TCP pool)
        ▼                        ▼
┌──────────────────┐     ┌──────────────────┐
│ Backend Node 01  │     │ Backend Node 02  │
│ 10.0.1.11:8080   │     │ 10.0.1.12:8080   │
└──────────────────┘     └──────────────────┘
```

Преимущества выделения upstream-пула:
1. **Абстракция инфраструктуры:** добавление, плановый вывод на обслуживание или изменение IP-адресов бэкендов производятся централизованно в блоке `upstream`.
2. **Межпроцессная синхронизация (`zone`):** выделение общей памяти позволяет всем worker-процессам оперировать едиными счетчиками сбоев, динамическими весами и лимитами соединений (`max_conns`).
3. **Оптимизация сетевых задержек:** сохранение постоянных пулов открытых соединений (`keepalive`) снижает задержку TTFB (Time to First Byte) на величину RTT рукопожатия TCP и TLS.

### Механизм передачи запроса

При выполнении директивы `proxy_pass` Nginx инициирует отдельный сеанс взаимодействия с бэкендом в роли HTTP-клиента. Жизненный цикл проксируемого запроса включает следующие этапы:

1. **Разрешение адреса и выбор узла:** алгоритм балансировки выбирает целевой узел из пула `upstream` с учетом состояния здоровья узлов и текущих соединений.
2. **Установление или извлечение соединения:** Nginx проверяет наличие свободного idle-соединения в локальном пуле `keepalive` воркера. При его отсутствии открывается новый TCP-сокет к IP-адресу бэкенда.
3. **Модификация и отправка заголовков:** формируются директивы `proxy_set_header`, перезаписывается `Host`, проставляются IP-адреса цепочки проксирования (`X-Forwarded-For`, `X-Real-IP`, `X-Forwarded-Proto`).
4. **Передача тела запроса:** при `proxy_request_buffering on` Nginx сначала полностью считывает тело запроса клиента в буфер памяти/диска и только затем передает бэкенду. При значении `off` тело стримится напрямую по мере поступления.
5. **Чтение ответа бэкенда:** заголовки ответа считываются в буфер `proxy_buffer_size`. Если размер заголовков превышает буфер, Nginx возвращает клиенту ошибку `502 Bad Gateway`.
6. **Буферизация тела ответа:** тело ответа вычитывается на максимальной сетевой скорости в цепочку буферов `proxy_buffers`. При переполнении памяти излишек сохраняется во временный файл (`proxy_temp_path`).
7. **Обработка сбоев (Failover):** при фиксации сбоя, подпадающего под условия `proxy_next_upstream`, Nginx немедленно обращается к следующему серверу пула (если передача ответа клиенту еще не началась).

### Таймауты проксирования и сетевые гарантии

Каждая директива таймаута контролирует конкретный этап межсерверного сетевого диалога. Ошибочный выбор значений приводит либо к зависанию рабочих процессов, либо к ложным обрывам запросов пользователей:

| Директива | Назначение | По умолчанию | Рекомендация для SRE |
| :--- | :--- | :--- | :--- |
| `proxy_connect_timeout` | Предельное время ожидания завершения TCP 3-way handshake с бэкендом. | `60s` | `1s - 3s` (в локальной сети задержка более 1s свидетельствует о сетевой деградации или переполнении backlog бэкенда). |
| `proxy_send_timeout` | Таймаут между двумя последовательными операциями записи данных в сокет бэкенда (не на весь запрос). | `60s` | `10s - 30s` (уменьшать для API, увеличивать для загрузки тяжелых файлов). |
| `proxy_read_timeout` | Таймаут между двумя последовательными операциями чтения данных из сокета бэкенда после отправки запроса. | `60s` | `15s - 60s` (определяет предел времени генерации ответа бэкендом; увеличивать точечно в `location` для долгих отчетов). |
| `proxy_next_upstream_timeout` | Суммарный лимит времени на все попытки повторной отправки запроса к бэкендам. | `0` (без ограничений) | `5s - 10s` (значение должно быть строго меньше клиентского таймаута ожидания). |
| `proxy_next_upstream_tries` | Максимальное число серверов, опрашиваемых для выполнения одного клиентского запроса (включая первый). | `0` (все серверы пула) | `2 - 3` (предотвращает каскадное падение пула при шторме повторов). |

### Проблема идемпотентности и риск каскадного шторма (Retry Storm)

По умолчанию `proxy_next_upstream` срабатывает только для идемпотентных HTTP-методов (`GET`, `HEAD`, `OPTIONS`, `PUT`, `DELETE`, `TRACE`), если бэкенд не успел передать клиенту ни одного байта ответа.

Если включить флаг `non_idempotent`, Nginx будет повторять также запросы `POST`, `LOCK`, `PATCH`. 

> [!WARNING]
> Включение `non_idempotent` без реализации сквозных ключей идемпотентности (Idempotency Keys) на уровне бизнес-логики приложения строго не рекомендуется. В случае сбоя сети на этапе ожидания ответа повторный `POST`-запрос может привести к дублированию финансовых транзакций или дублированию записей в базах данных.

---

## Практические сценарии и конфигурации

### Предварительные требования: настройка сетевого стека ядра Linux

Высоконагруженный балансировщик Nginx обрабатывает два сокета на каждый запрос: клиентский и апстримный. Для предотвращения нехватки дескрипторов и исчерпания сетевых портов в `/etc/sysctl.d/99-nginx-proxy.conf` на хосте прокси задаются параметры:

```ini
# Расширение диапазона локальных эфемерных портов для исходящих соединений к бэкендам
net.ipv4.ip_local_port_range = 10240 65535

# Разрешение переиспользования сокетов в состоянии TIME_WAIT для исходящих TCP-соединений
net.ipv4.tcp_tw_reuse = 1

# Увеличение максимального размера системной очереди соединений ядра
net.core.somaxconn = 65535

# Максимальное число открытых файлов в системе
fs.file-max = 2097152
```

Применение изменений:
```bash
sysctl --system
# → net.ipv4.ip_local_port_range = 10240 65535
# → net.ipv4.tcp_tw_reuse = 1
# → net.core.somaxconn = 65535
# → fs.file-max = 2097152
```

В `/etc/nginx/nginx.conf` на глобальном уровне выставляется лимит дескрипторов процесса:
```nginx
worker_processes auto;
worker_rlimit_nofile 131072;

events {
    worker_connections 32768;
    use epoll;
    multi_accept on;
}
```

### Сценарий 1: Объявление и параметризация upstream-группы

Объявление пула серверов выполняется в контексте `http`.

```nginx
http {
    upstream backend_api {
        # Зона разделяемой памяти для синхронизации состояния между всеми worker-процессами
        zone backend_api_zone 256k;

        # Основные узлы с весами и лимитами соединений
        server 10.0.1.11:8080 weight=3 max_conns=250 max_fails=3 fail_timeout=15s;
        server 10.0.1.12:8080 weight=1 max_conns=250 max_fails=3 fail_timeout=15s;

        # Резервный узел: трафик идет на него только при недоступности всех основных
        server 10.0.1.13:8080 backup max_conns=250;

        # Временно выведенный из эксплуатации узел
        server 10.0.1.14:8080 down;
    }
}
```

Параметры директивы `server`:
- `weight=N` — относительный вес сервера (по умолчанию `1`). Сервер с `weight=3` получает втрое больше запросов, чем сервер с `weight=1`.
- `max_conns=N` — жесткий лимит одновременных активных соединений с данным сервером. Предотвращает исчерпание пула потоков/процессов бэкенда. При попытке превысить лимит Nginx в OSS возвращает ошибку `502 Bad Gateway` (в Angie/Plus запрос может вставать в директиву `queue`).
- `max_fails=N` — число неудачных попыток связи с сервером за интервал `fail_timeout`, после которых узел помечается как неработоспособный (по умолчанию `1`).
- `fail_timeout=T` — интервал времени, в течение которого подсчитываются ошибки, а также длительность изоляции узла от трафика при фиксации сбоя (по умолчанию `10s`).
- `backup` — маркирует сервер как резервный.
- `down` — перманентно отключает сервер без удаления из конфигурации (сохраняет хеш-суммы при использовании `ip_hash`).

### Сценарий 2: Настройка проксирования, передача заголовков и WebSocket

Для передачи бэкенду полных метаданных запроса формируется стандартный набор заголовков. Дополнительно настраивается проброс WebSocket-соединений:

```nginx
# Отображение заголовка Upgrade для корректного переключения Connection
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name api.example.internal;

    # Максимальный размер тела клиентского запроса
    client_max_body_size 50M;

    location / {
        proxy_pass http://backend_api;

        # Передача оригинального имени хоста
        proxy_set_header Host $host;

        # Передача реального IP клиента
        proxy_set_header X-Real-IP $remote_addr;

        # Формирование цепочки всех промежуточных прокси
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Передача схемы протокола (http или https)
        proxy_set_header X-Forwarded-Proto $scheme;

        # Передача порта входящего соединения
        proxy_set_header X-Forwarded-Port $server_port;

        # Поддержка WebSocket и HTTP/1.1 Upgrade
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        # Отключение модификации заголовков Location и Refresh в ответах бэкенда
        proxy_redirect off;
    }
}
```

### Сценарий 3: Восстановление реального IP клиента (`real_ip` и PROXY Protocol)

Когда перед Nginx работает внешний L4-балансировщик нагрузки (HAProxy, IPVS) или промежуточный шлюз, переменная `$remote_addr` указывает на IP-адрес этого балансировщика, а не клиента.

Для восстановления реального IP используется модуль `ngx_http_realip_module`:

```nginx
# Доверенные адреса внутренних L4/L7-балансировщиков
set_real_ip_from 10.0.0.0/8;
set_real_ip_from 172.16.0.0/12;
set_real_ip_from 192.168.1.10/32;

# Выбор источника данных об исходном IP:
# Вариант А: заголовок HTTP
real_ip_header X-Forwarded-For;

# Вариант Б: при использовании PROXY Protocol на слушающем порту:
# listen 80   proxy_protocol;
# listen 443  ssl proxy_protocol;
# real_ip_header proxy_protocol;

# Рекурсивный поиск: исключает подмену IP внешним клиентом
real_ip_recursive on;
```

> [!IMPORTANT]
> Если директива `real_ip_recursive on` не активирована, злоумышленник может внедрить произвольный IP-адрес в свой собственный заголовок `X-Forwarded-For`, обойдя локальные черные списки, лимиты `limit_req` и гео-блокировки. С опцией `recursive on` Nginx отбрасывает все доверенные прокси с конца списка и фиксирует первый недоверенный IP как `$remote_addr`.

### Сценарий 4: Высокопроизводительный Keep-alive пул к бэкендам

По умолчанию модуль `ngx_http_proxy_module` работает с бэкендами по протоколу HTTP/1.0 и закрывает TCP-соединение после каждого запроса (заголовок `Connection: close`).

Для организации пула постоянных соединений настраивается блок `upstream` и целевой `location`:

```nginx
upstream backend_keepalive_pool {
    zone backend_keepalive_zone 256k;
    server 10.0.1.11:8080 max_conns=300;
    server 10.0.1.12:8080 max_conns=300;

    # Максимальное число незанятых (idle) keepalive-соединений к бэкендам на ОДИН worker-процесс
    keepalive 64;

    # Максимальное количество запросов, обслуживаемых через одно постоянное соединение
    keepalive_requests 10000;

    # Таймаут закрытия незанятого соединения при отсутствии запросов
    keepalive_timeout 60s;

    # Предельное общее время жизни одного соединения в пуле (Nginx 1.19.10+)
    keepalive_time 1h;
}

server {
    listen 80;
    server_name service.example.internal;

    location / {
        proxy_pass http://backend_keepalive_pool;

        # ОБЯЗАТЕЛЬНО: переключение протокола взаимодействия с upstream на HTTP/1.1
        proxy_http_version 1.1;

        # ОБЯЗАТЕЛЬНО: очистка заголовка Connection для отмены передачи "close"
        proxy_set_header Connection "";

        proxy_set_header Host $host;
    }
}
```

**Формула расчета директивы `keepalive` для SRE:**
Параметр `keepalive <N>` выделяется для каждого рабочего процесса отдельно. Если на сервере работает 8 воркеров, а в upstream задано `keepalive 64;`, суммарно в резерве может поддерживаться до $8 \times 64 = 512$ открытых TCP-сокетов. Значение $N$ должно приблизительно равняться:
$$N = \frac{\text{Пиковый RPS} \times \text{Среднее время ответа бэкенда (сек)}}{\text{Количество worker\_processes}}$$

### Сценарий 5: Отказоустойчивость и защита от каскадных сбоев (Failover)

Автоматический переход на следующий сервер пула регулируется директивами `proxy_next_upstream`:

```nginx
location /api/ {
    proxy_pass http://backend_api;

    # Условия перехода на следующий узел
    proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;

    # Лимит числа попыток (включая первую)
    proxy_next_upstream_tries 3;

    # Суммарный лимит времени на все попытки обращения
    proxy_next_upstream_timeout 8s;

    # Таймауты межсерверного диалога
    proxy_connect_timeout 2s;
    proxy_read_timeout 15s;
    proxy_send_timeout 10s;

    proxy_set_header Host $host;
}
```

Пояснение условий `proxy_next_upstream`:
- `error` — сетевая ошибка при установке соединения, передаче запроса или чтении заголовка ответа (TCP RST, `Connection refused`).
- `timeout` — истечение таймаута соединения или чтения данных.
- `invalid_header` — бэкенд вернул пустой или поврежденный ответ, не соответствующий спецификации HTTP.
- `http_502`, `http_503`, `http_504` — перехват кодов ошибок шлюза и недоступности сервиса.
- `http_429` (Nginx 1.25.3+) — возможность переключения узла при получении статуса `Too Many Requests`.

### Сценарий 6: Управление буферизацией ответов и стримингом

Параметры буферизации изолируют бэкенды от медленных каналов внешних клиентов:

```nginx
# 1. Оптимизированный профиль буферизации для стандартного Web/API
location /api/ {
    proxy_pass http://backend_api;

    proxy_buffering on;

    # Буфер для чтения заголовков ответа
    proxy_buffer_size 16k;

    # Количество и размер буферов для тела ответа
    proxy_buffers 8 32k;

    # Лимит данных, одновременно удерживаемых в состоянии отправки клиенту
    proxy_busy_buffers_size 64k;

    # Предельный объем дискового временного файла при переполнении буферов памяти
    proxy_max_temp_file_size 256m;
    proxy_temp_file_write_size 64k;
    proxy_temp_path /var/cache/nginx/proxy_temp 1 2;
}

# 2. Профиль для стриминга (SSE - Server-Sent Events, gRPC, длительные загрузки)
location /stream/ {
    proxy_pass http://backend_api;

    # Немедленная передача чанков клиенту без накопления
    proxy_buffering off;

    # Отключение буферизации тела клиентского запроса для больших аплоадов
    proxy_request_buffering off;

    # Отключение кэширования ответов
    proxy_cache_bypass 1;
    proxy_no_cache 1;

    # Длительный таймаут чтения для открытых каналов событий
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

Правила подбора буферов:
- `proxy_buffer_size` должен вмещать максимальный размер заголовков бэкенда (включая крупные cookies сессий и токены JWT).
- `proxy_busy_buffers_size` обязан быть меньше суммарного размера `proxy_buffers` минус один буфер, но не менее `proxy_buffer_size`.

### Сценарий 7: Защищенное взаимодействие с бэкендами (HTTPS и mTLS)

Когда трафик между балансировщиком и узлами upstream передается через недоверенную корпоративную сеть, Nginx выполняет проверку подлинности бэкендов и шифрование по TLS:

```nginx
upstream secure_backend {
    zone secure_backend_zone 128k;
    server 10.0.2.11:8443;
    server 10.0.2.12:8443;
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name portal.example.internal;

    # Сертификаты для внешних клиентов
    ssl_certificate /etc/nginx/ssl/external_domain.crt;
    ssl_certificate_key /etc/nginx/ssl/external_domain.key;

    location / {
        proxy_pass https://secure_backend;

        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;

        # Включение верификации сертификата бэкенда
        proxy_ssl_verify on;
        proxy_ssl_verify_depth 2;

        # Доверенный корневой сертификат внутренней инфраструктуры PKI
        proxy_ssl_trusted_certificate /etc/nginx/ssl/internal_ca.crt;

        # Передача имени сервера через SNI (Server Name Indication)
        proxy_ssl_server_name on;
        proxy_ssl_name backend.internal;

        # Протоколы и шифры к бэкенду
        proxy_ssl_protocols TLSv1.2 TLSv1.3;
        proxy_ssl_ciphers HIGH:!aNULL:!MD5;

        # Клиентский сертификат Nginx для взаимной аутентификации (mTLS)
        proxy_ssl_certificate /etc/nginx/ssl/nginx_client.crt;
        proxy_ssl_certificate_key /etc/nginx/ssl/nginx_client.key;

        # Кэширование TLS-сессий с бэкендами
        proxy_ssl_session_reuse on;
    }
}
```

### Сценарий 8: Перехват ошибок бэкенда и резервный контур (Fallback)

Директива `proxy_intercept_errors` позволяет перехватывать ответы бэкенда со статусами $\ge 300$ и отдавать клиенту кастомные статические документы или переключать запрос на резервный location:

```nginx
server {
    listen 80;
    server_name service.example.internal;

    # Активация перехвата кодов ошибок шлюза
    proxy_intercept_errors on;

    # Перенаправление ошибок на внутренний именованный location
    error_page 502 503 504 = @service_fallback;

    location / {
        proxy_pass http://backend_api;
        proxy_set_header Host $host;
        proxy_connect_timeout 2s;
        proxy_read_timeout 5s;
    }

    # Резервный контур аварийного обслуживания
    location @service_fallback {
        # Запрет прямого доступа извне
        internal;

        # Отдача статического JSON для API-клиентов
        default_type application/json;
        return 503 '{"status": "error", "code": 503, "message": "Service temporarily degraded. Please retry later."}';
    }
}
```

### Сценарий 9: Эталонная производственная конфигурация хоста

Сводный пример готового виртуального хоста `/etc/nginx/conf.d/production_app.conf` с логированием латентности upstream:

```nginx
# Лог-формат с метриками задержки бэкендов для сбора в мониторинг
log_format upstream_telemetry '$remote_addr - $remote_user [$time_local] '
                              '"$request" $status $body_bytes_sent '
                              '"$http_referer" "$http_user_agent" '
                              'upstream_addr="$upstream_addr" '
                              'upstream_status="$upstream_status" '
                              'upstream_response_time="$upstream_response_time" '
                              'upstream_connect_time="$upstream_connect_time" '
                              'upstream_header_time="$upstream_header_time" '
                              'request_time="$request_time"';

upstream app_production_pool {
    zone app_production_zone 512k;

    server 10.0.1.21:8080 weight=2 max_conns=300 max_fails=3 fail_timeout=10s;
    server 10.0.1.22:8080 weight=2 max_conns=300 max_fails=3 fail_timeout=10s;
    server 10.0.1.23:8080 weight=1 max_conns=150 max_fails=3 fail_timeout=10s;
    server 10.0.1.24:8080 backup max_conns=300;

    keepalive 128;
    keepalive_requests 20000;
    keepalive_timeout 60s;
}

server {
    listen 80;
    server_name app.company.internal;

    access_log /var/log/nginx/app_access.log upstream_telemetry buffer=32k flush=5s;
    error_log  /var/log/nginx/app_error.log warn;

    client_max_body_size 20M;

    # Восстановление реального IP от доверенных шлюзов
    set_real_ip_from 10.0.0.0/8;
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;

    # Перехват критических кодов ошибок
    proxy_intercept_errors on;
    error_page 502 503 504 /custom_error.html;

    location = /custom_error.html {
        root /usr/share/nginx/html;
        internal;
    }

    location / {
        proxy_pass http://app_production_pool;

        # Keepalive параметры
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Метаданные клиента
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Таймауты
        proxy_connect_timeout 2s;
        proxy_send_timeout 15s;
        proxy_read_timeout 30s;

        # Отказоустойчивость
        proxy_next_upstream error timeout invalid_header http_502 http_503;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 6s;

        # Буферизация
        proxy_buffering on;
        proxy_buffer_size 16k;
        proxy_buffers 8 32k;
        proxy_busy_buffers_size 64k;
        proxy_max_temp_file_size 128m;

        # Безопасность: скрытие заголовков окружения бэкенда
        proxy_hide_header X-Powered-By;
        proxy_hide_header Server;
    }
}
```

---

## Операции и команды

### Валидация и применение конфигурации

```bash
# Синтаксическая проверка конфигурационных файлов без перезапуска демона
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка и вывод полного результирующего дерева конфигурации (включая все include)
nginx -T | grep -A 15 "upstream"
# → upstream app_production_pool {
# →     zone app_production_zone 512k;
# →     server 10.0.1.21:8080 ...

# Грациозное перечитывание конфигурации на лету (Zero-Downtime Reload)
nginx -s reload
# → signal reload started

# Проверка статуса службы в systemd
systemctl status nginx --no-pager
# → Active: active (running) since ...
```

### Диагностика сетевых сокетов и пула Keepalive

```bash
# Просмотр числа активных и keepalive-соединений к конкретному IP бэкенда
ss -tn state established '( daddr = 10.0.1.21 and dport = :8080 )' | wc -l
# → 42

# Просмотр соединений в состоянии TIME_WAIT к порту бэкендов
ss -tn state time-wait '( dport = :8080 )' | wc -l
# → 12

# Общая сводка состояния сетевых сокетов хоста
ss -s
# → Total: 1845
# → TCP:   1210 (estab 840, closed 210, orphaned 12, timewait 180)
```

### Анализ журналов и задержек бэкендов

```bash
# Топ-10 бэкендов по распределению трафика (требуется лог с $upstream_addr)
awk '{for(i=1;i<=NF;i++) if($i ~ /upstream_addr=/) print $i}' /var/log/nginx/app_access.log | sort | uniq -c | sort -rn
# → 14230 upstream_addr="10.0.1.21:8080"
# → 14195 upstream_addr="10.0.1.22:8080"
# → 7120 upstream_addr="10.0.1.23:8080"

# Выявление запросов с временем ответа бэкенда более 2 секунд
awk '$0 ~ /upstream_response_time=/ {match($0, /upstream_response_time="([0-9.]+)"/, a); if (a[1] > 2.0) print $0}' /var/log/nginx/app_access.log | tail -n 10
# → 192.168.1.50 ... upstream_addr="10.0.1.21:8080" upstream_status="200" upstream_response_time="2.412" ...

# Подсчет кодов ответов бэкендов (502, 503, 504) за последний час
grep -E "upstream_status=\"(502|503|504)\"" /var/log/nginx/app_access.log | wc -l
# → 3

# Мониторинг системных ошибок проксирования в реальном времени
tail -fn0 /var/log/nginx/app_error.log | grep -E "upstream|connect\(\)|timeout"
```

### Тестирование балансировщика через curl

```bash
# Проверка HTTP-статуса и заголовков ответа
curl -I -s http://app.company.internal/health
# → HTTP/1.1 200 OK
# → Server: nginx
# → Date: ...
# → Content-Type: application/json

# Детальный замер времени подключения, TTFB и общей длительности запроса
curl -w "DNS: %{time_namelookup}s | Connect: %{time_connect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s | Code: %{http_code}\n" -o /dev/null -s http://app.company.internal/api/ping
# → DNS: 0.0012s | Connect: 0.0025s | TTFB: 0.0142s | Total: 0.0145s | Code: 200
```

---

## Диагностика и устранение неполадок

### Типичные ошибки и сбои

| Симптом | Системное сообщение в `error.log` | Причина сбоя | Инженерное решение (Runbook) |
| :--- | :--- | :--- | :--- |
| **`502 Bad Gateway`** (Отказ соединения) | `connect() failed (111: Connection refused) while connecting to upstream` | Процесс бэкенда остановлен, упал, завис или слушает другой локальный порт. | Проверить состояние службы бэкенда: `systemctl status backend`; убедиться, что порт слушается: `ss -tulpn \| grep 8080`; проверить настройки локального фаервола. |
| **`502 Bad Gateway`** (Нет доступных узлов) | `no live upstreams while connecting to upstream` | Все узлы пула помечены неработоспособными из-за превышения `max_fails` за интервал `fail_timeout`. | Проверить доступность бэкендов; временно увеличить `fail_timeout` и снизить `max_fails`; принудительно вернуть узел в строй через перезагрузку или API. |
| **`502 Bad Gateway`** (Сброс соединения бэкендом) | `upstream prematurely closed connection while reading response header` | Бэкенд аварийно завершил процесс (OOM Killer, Segfault) или закрыл TCP-сокет без отправки корректного HTTP-ответа. | Проверить логи бэкенда и `dmesg -T \| grep -i oom`; проверить системные лимиты памяти процесса бэкенда. |
| **`502 Bad Gateway`** (Превышение размера заголовка) | `upstream sent too big header while reading response header from upstream` | Суммарный объем HTTP-заголовков бэкенда (крупные `Set-Cookie`, заголовки авторизации JWT) превысил буфер `proxy_buffer_size`. | Увеличить размер буфера: `proxy_buffer_size 16k;` или `32k;` и скорректировать `proxy_busy_buffers_size 32k;` в целевом блоке `location`. |
| **`504 Gateway Timeout`** | `upstream timed out (110: Connection timed out) while reading response header` | Приложение бэкенда не успело сгенерировать ответ за интервал, определенный директивой `proxy_read_timeout`. | Локализовать медленный запрос в access.log; оптимизировать SQL-запросы или логику бэкенда; увеличить `proxy_read_timeout` для тяжелых эндпоинтов. |
| **`503 Service Unavailable`** | `server has reached max_conns limit` | Текущее количество активных запросов к бэкенду превысило параметр `max_conns`. | Добавить вычислительные узлы в пул; оптимизировать время обработки запроса приложением; увеличить порог `max_conns`. |
| **`502 Bad Gateway`** (Исчерпание портов) | `bind() to 0.0.0.0:0 failed (99: Cannot assign requested address)` | Исчерпан диапазон локальных TCP-портов (`TIME_WAIT` saturation) из-за отключенного keepalive к бэкендам. | Включить `keepalive` в блоке `upstream`; перевести проксирование на `proxy_http_version 1.1;`; настроить ядро: `sysctl -w net.ipv4.tcp_tw_reuse=1`. |
| **Дисковое переполнение буферов** | `an upstream response is buffered to a temporary file /var/cache/nginx/proxy_temp/...` | Объем тела ответа бэкенда превышает суммарный объем буферов в оперативной памяти (`proxy_buffers`). | Увеличить память под буферы: `proxy_buffers 16 32k;` или отключить буферизацию для стриминга (`proxy_buffering off;`). |
| **`worker_connections are not enough`** | `2048 worker_connections are not enough while connecting to upstream` | Исчерпан пул доступных сетевых дескрипторов воркера (каждый проксируемый запрос занимает минимум 2 соединения). | Увеличить `worker_connections` в секции `events` и синхронно поднять `worker_rlimit_nofile` в глобальном контексте. |

### Диагностические команды локализации проблем

```bash
# 1. Поиск критических ошибок в журналах Nginx
grep -E "111: Connection refused|no live upstreams|prematurely closed|too big header|timed out" /var/log/nginx/error.log | tail -n 25

# 2. Выявление фактов сброса ответов во временные дисковые файлы
grep "buffered to a temporary file" /var/log/nginx/error.log | tail -n 10

# 3. Проверка прямого ответа проблемного бэкенда с хоста прокси в обход балансировщика
curl -iv -o /dev/null http://10.0.1.21:8080/health
# → * Connected to 10.0.1.21 (10.0.1.21) port 8080
# → < HTTP/1.1 200 OK

# 4. Проверка числа сокетов в состоянии TIME_WAIT на сетевом интерфейсе
ss -tan 'state time-wait' | wc -l

# 5. Проверка текущих значений лимита открытых дескрипторов у процессов воркеров Nginx
for pid in $(pgrep -f "nginx: worker"); do cat /proc/$pid/limits | grep "Max open files"; done
# → Max open files            131072               131072               files
```

---

## Лучшие практики

### Производительность

1. **Обязательно используйте `zone`:** для каждого блока `upstream` объявляйте директиву `zone`. Без разделяемой памяти каждый рабочий процесс ведет независимый учет соединений и ошибок, что приводит к неравномерному распределению нагрузки и запоздалому исключению сбойных узлов.
2. **Включайте `keepalive` в `upstream`:** соединения между Nginx и бэкендами должны быть постоянными. Обязательно передавайте `proxy_http_version 1.1;` и `proxy_set_header Connection "";`. Это сокращает накладные расходы процессора на установку TCP/TLS-соединений до 40% и исключает насыщение сокетов в `TIME_WAIT`.
3. **Размер буферов под профиль нагрузки:** избегайте бездумного завышения `proxy_buffers`. При десятках тысяч соединений чрезмерные буферы приводят к нехватке физической оперативной памяти (OOM). Для легковесных JSON REST API достаточно `proxy_buffer_size 16k; proxy_buffers 4 16k;`.
4. **Отключайте буферизацию для стриминга:** протоколы SSE, Server-Sent Events, WebSockets и длительный экспорт отчетов требуют `proxy_buffering off;`, иначе данные будут задерживаться в памяти Nginx, искажая TTFB.
5. **Согласование таймаутов:** цепочка таймаутов должна уменьшаться от границы к ядру: Клиентский таймаут $\ge$ `proxy_read_timeout` $\ge$ Таймаут приложения к базе данных.

### Безопасность

1. **Строгая валидация источников Real IP:** директива `set_real_ip_from` должна содержать только доверенные IP-адреса внутренней инфраструктуры или внешних L4-балансировщиков. Никогда не указывайте `0.0.0.0/0`, иначе внешний клиент сможет беспрепятственно подделать свой адрес через `X-Forwarded-For`.
2. **Скрытие служебных заголовков бэкенда:** используйте `proxy_hide_header` для маскировки служебных идентификаторов технологий (`X-Powered-By`, `Server`, `X-AspNet-Version`).
3. **Защита межсерверного периметра:** при передаче трафика через недоверенные каналы или дата-центры обязательно включайте шифрование `proxy_ssl_verify on;` с проверкой сертификата по внутреннему доверенному CA.
4. **Контроль размера тела запроса:** параметр `client_max_body_size` должен быть жестко ограничен минимально необходимым значением для предотвращения атак типа отказ в обслуживании (Denial of Service) переполнением дискового пространства хоста.

### Эксплуатация (SRE)

1. **Структурированная телеметрия в журналах:** обязательно добавляйте в `log_format` переменные `$upstream_addr`, `$upstream_status`, `$upstream_response_time`, `$upstream_connect_time`. Это позволяет автоматически строить графики перцентилей (p95, p99) латентности бэкендов в Grafana и оперативно локализовать деградировавший узел.
2. **Ограничение шторма повторов (Retry Storm Budget):** никогда не оставляйте `proxy_next_upstream_tries` со значением по умолчанию `0` (не ограничено). Значение должно быть установлено в `2` или `3`, а `proxy_next_upstream_timeout` — жестко согласован со временем ожидания клиента.
3. **Плавный ввод узлов в ротацию:** в Angie и Nginx Plus используйте параметр `slow_start=30s` для прогрева JIT, кэша приложения и пулов подключений при вводе нового узла. В Nginx OSS при первичном запуске выставляйте серверу пониженный `weight` с последующим повышением после прогрева.
4. **Канареечные развертывания через веса:** изменение параметров `weight` в `upstream` позволяет гибко направлять малый процент реального пользовательского трафика (например, 5–10%) на новую версию сервиса перед полномасштабным релизом.

---

## Дополнительная информация

### См. также

- [Обзор концепций балансировки L7](./overview_concepts.md) — базовые архитектурные принципы, событийно-ориентированная модель и жизненный цикл запросов.
- [Алгоритмы балансировки нагрузки Nginx](./algorithms.md) — математика и конфигурация Round Robin, Least Connections, Hash, IP Hash, Random.
- [Health Checks и мониторинг](./health_checks_and_monitoring.md) — пассивные и активные проверки жизнеспособности серверов, телеметрия VTS и Prometheus.
- [Динамическое разрешение DNS в Upstream](./dynamic_dns_resolution.md) — отслеживание динамических IP-адресов через директивы `resolver` и `resolve`.
- [Sticky Sessions (Прилипание сессий)](./sticky_sessions.md) — обеспечение сессионной связности через `ip_hash`, hash и модуль sticky.
- [Сравнение балансировщиков](./additional_info_and_comparisons.md) — сравнительный анализ производительности и возможностей Nginx, Angie, HAProxy и Traefik.
- [Буферизация и стриминг в Nginx](../nginx_buffering_and_streaming.md) — детальный разбор механики буферизации тела запросов и ответов.
- [L4-проксирование Nginx (Stream)](../nginx_l4_proxying.md) — балансировка сырых TCP и UDP потоков на транспортном уровне.
- [Диагностика и устранение неисправностей Nginx](../../Operations/nginx_troubleshooting.md) — общие регламенты поиска и устранения отказов веб-сервера.
- [Оптимизация производительности Nginx](../../Performance/nginx_performance_tuning.md) — глубокий тюнинг сетевого стека ядра Linux и системных очередей.
- [PROXY Protocol](../../../../Networking/Protocols/proxy_protocol.md) — спецификация передачи метаданных клиента на транспортном уровне L4.
- [Maintenance-режим в Nginx](../../Scenarios/nginx_maintenance_mode.md) — организация штатного регламентного обслуживания без деградации SLA.

### Особенности реализации в Nginx OSS и Angie

- **Зона разделяемой памяти (`zone`):** в Nginx OSS поддерживается базовая директива `zone` для синхронизации состояния upstream-пула между воркерами (начиная с 1.9.0 для Stream и 1.17.2 для HTTP).
- **Лимиты соединений (`max_conns`):** параметр `max_conns` доступен в Nginx OSS начиная с версии 1.11.5. В Nginx OSS при превышении `max_conns` запрос отклоняется с ошибкой `502`, тогда как в Angie и Nginx Plus поддерживается директива `queue` для постановки запросов в очередь ожидания.
- **Динамический DNS (`resolve`):** в Nginx OSS параметр `resolve` для директивы `server` добавлен в ветку Mainline начиная с версии 1.27.3. В Angie функционал Service Discovery и динамического DNS доступен изначально.
- **Активные проверки состояния (Active Health Checks):** нативно присутствуют в Angie (директивы `health_check`) и Nginx Plus; в Nginx Open Source мониторинг состояния бэкендов в стандартной сборке ограничен пассивными проверками (`max_fails`, `fail_timeout`, `proxy_next_upstream`).
