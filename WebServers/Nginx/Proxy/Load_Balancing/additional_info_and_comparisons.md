# Балансировка нагрузки в Nginx: сравнение и дополнительные сведения

**Актуально для:** Nginx 1.26+ / 1.28+ (Mainline), Angie 1.6+ / 1.12.x, HAProxy 3.0+ / 3.4+, Traefik 3.x, Apache 2.4.x

## Определения

**Обратный прокси (Reverse Proxy)** — сетевой шлюз, принимающий входящие соединения от внешних клиентов и перенаправляющий их на один или несколько внутренних узлов (бэкендов). Изолирует внутреннюю топологию сети, осуществляет терминацию TLS, кэширование и распределение запросов.

**Балансировка нагрузки (Load Balancing)** — метод распределения входящих запросов между пулом вычислительных узлов для оптимизации утилизации ресурсов, снижения задержек (latency) и предотвращения отказа сервиса при сбоях отдельных серверов. Базовые принципы описаны в документе [Кластеризация и балансировка для HA](../../../../Concepts/High_Availability/ha_clustering_and_load_balancing.md).

**Upstream** — логическая именованная группа бэкенд-серверов в конфигурации Nginx, определяющая адреса узлов, их вес, лимиты соединений и параметры отказоустойчивости. Механика работы алгоритмов представлена в [Алгоритмах балансировки](./algorithms.md).

**L4 / L7 балансировка** — классификация по модели OSI:
- **L4 (Transport Layer):** маршрутизация на уровне потоков TCP/UDP (IP-адреса, порты, SNI) без дешифрования полезной нагрузки. Реализуется модулем `ngx_stream_proxy_module`. Подробнее: [L4-проксирование](../nginx_l4_proxying.md).
- **L7 (Application Layer):** маршрутизация на уровне протокола приложения с полным разбором HTTP-запросов (URI, заголовки, cookies, тело запроса, gRPC-фреймы). Реализуется модулем `ngx_http_proxy_module`.

**Зона разделяемой памяти (Shared Memory Zone, `zone`)** — область оперативной памяти, доступная всем рабочим процессам (`worker processes`) Nginx одновременно. Хранит конфигурацию upstream, состояние бэкендов, счетчики активных соединений и таблицы sticky-сессий.

**Keepalive-пул (Upstream Keepalive)** — механизм повторного использования установленных TCP/TLS-соединений между Nginx и бэкендами. Директива `keepalive <N>` кэширует открытые сокеты на уровне каждого рабочего процесса, устраняя накладные расходы на трехстороннее рукопожатие (TCP 3-way handshake) и TLS-согласование для каждого запроса.

**Событийно-ориентированная архитектура (Event-Driven)** — модель асинхронного неблокирующего ввода-вывода (системный вызов `epoll` в Linux), при которой фиксированное число рабочих процессов мультиплексирует десятки тысяч одновременных соединений в одном потоке без накладных расходов на переключение контекста ядра ОС.

**Пассивная и активная проверка (Health Checks)**:
- **Пассивные проверки (Passive / Circuit Breaker):** оценка состояния сервера по результатам обработки реального клиентского трафика (`max_fails`, `fail_timeout`).
- **Активные проверки (Active / Synthetic Probing):** периодическая отправка балансировщиком синтетических тестовых запросов к бэкендам независимо от наличия пользовательского трафика (в Angie и Nginx Plus нативно, в Nginx OSS через сторонние модули). Подробнее: [Health Checks и мониторинг](./health_checks_and_monitoring.md).

**Липкие сессии (Sticky Sessions / Session Affinity)** — алгоритмы маршрутизации, гарантирующие отправку повторных запросов конкретного клиента на один и тот же бэкенд (на основе IP-адреса, cookie или хэша заголовка). Подробнее: [Sticky Sessions](./sticky_sessions.md).

**Прокси-протокол (PROXY Protocol v1/v2)** — протокол передачи исходных метаданных клиента (IP-адрес, порт источника и назначения, статус TLS) через цепочку промежуточных L4-прокси без изменения полезной нагрузки TCP. Спецификация и настройка: [PROXY Protocol](../../../../Networking/Protocols/proxy_protocol.md).

**Плавный перезапуск (Graceful Reload / Hitless Reload)** — процедура применения новой конфигурации сервиса без разрыва установленных клиентских соединений, без сброса очередей сокетов ядра и без отказа в обслуживании новых запросов.

**Синтетическое нагрузочное тестирование (Load Benchmarking)** — методология оценки предельной пропускной способности (RPS), времени отклика и распределения перцентилей задержек (p50, p95, p99) прокси-сервера под управляемой конкурентной нагрузкой.

---

## Основные концепции и архитектура

### Архитектурное сравнение балансировщиков нагрузки

Выбор балансировщика в DevOps/SRE-практике зависит от требований к задержкам, модели управления конфигурацией, потребности в отдаче статического контента и сетевой топологии:

| Характеристика | Nginx (OSS) | Angie | HAProxy | Traefik | Apache HTTP Server (`mod_proxy_balancer`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Базовая модель I/O** | Single-threaded Event Loop (Master-Worker, `epoll`) | Single-threaded Event Loop (Master-Worker, `epoll`) | Multi-threaded Event Loop (`nbthread`, `epoll`) | Go Coroutines (Network Poller) | Multi-Process (`prefork`) или Multi-Thread (`event`/`worker`) |
| **Потребление RAM (10k сокетов)** | ~2–4 МБ | ~2–4 МБ | ~2–3 МБ | ~30–60 МБ | >100–500 МБ |
| **Специализация** | Универсальный L7/L4 прокси, HTTP-кэш, веб-сервер статики | Drop-in замена Nginx с расширенным L7/L4 функционалом | Высокоточный специализированный L4/L7 балансировщик | Динамический edge-маршрутизатор микросервисов | Традиционный веб-сервер со шлюзом `mod_proxy` |
| **Активные Health Checks** | Только сторонний модуль (`nginx_upstream_check_module`) | Нативно (`check`) | Нативно (`check inter ...`) | Нативно (`healthcheck`) | Нативно (`lbmethod`, `hcmethod`) |
| **Zero-Downtime Reload** | Запуск новых воркеров, дренаж старых | Запуск новых воркеров, дренаж старых | Передача сокетов (Socket Transfer `-x`) | Hot-reload без перезапуска процесса | Перезапуск потоков (`graceful`) |
| **Динамическое изменение бэкендов** | Требует `reload` (или платный Nginx Plus) | Нативно через REST API и консоль | Нативно через Runtime API (Unix socket) | Нативно через провайдеры (Docker, Nomad, File) | Через `balancer-manager` (web UI) |
| **Нативная телеметрия** | `stub_status` (базовые счетчики) | REST API, Prometheus-эндпоинт | Встроенная веб-статистика, Prometheus `/metrics` | Нативный Prometheus `/metrics`, OpenTelemetry | `mod_status` (HTML/plain text) |
| **Отдача статики (Zero-Copy)** | `sendfile`, `splice` (эталонная производительность) | `sendfile`, `splice` | Ограниченно / отсутствует (не является веб-сервером) | Стандартный HTTP file server (Go) | `sendfile` (высокие накладные расходы потоков) |

#### Выводы для архитектора и SRE:
1. **Nginx / Angie** оптимальны в качестве пограничных шлюзов (Edge Reverse Proxy), где в рамках одного сервиса требуется терминировать TLS, отдавать тяжелую статику с диска через системный кэш, осуществлять микрокэширование динамики и балансировать запросы на локальные пулы приложений.
2. **HAProxy** превосходит аналоги в сценариях чистой высоконагруженной L4/L7-балансировки с критическими требованиями к задержкам (микросекундный диапазон), сложным многоуровневым правилам ACL и динамическому переключению весов серверов через Runtime API без перезагрузки процесса.
3. **Traefik** доминирует в средах с непрерывным Service Discovery (динамические стенды, микросервисы в Docker/Nomad), где конфигурация маршрутизации генерируется автоматически на базе меток контейнеров.
4. **Apache HTTP Server** уступает современным решениям по плотности соединений и расходу памяти на соединение, сохраняя целесообразность исключительно в инфраструктурах с жесткой зависимостью от распределенных файлов `.htaccess` и legacy-модулей.

---

### Жизненный цикл обработки запроса в Upstream Nginx

```
[Клиент]
   │
   │ 1. TCP Handshake / TLS Negotiation (epoll)
   ▼
[Nginx Worker]
   │ 2. Сопоставление server_name и location
   │ 3. Вызов ngx_http_proxy_module
   ▼
[Upstream Core] ◄─── Чтение состояния из Shared Memory Zone (`zone`)
   │ 4. Выбор бэкенда по алгоритму (RR, least_conn, hash)
   │ 5. Извлечение сокета из Keepalive-пула или новый TCP connect
   ▼
[Бэкенд-сервер]
   │ 6. Передача HTTP-запроса (буферизация тела клиента)
   │ 7. Ожидание первого байта (proxy_read_timeout)
   │
   ├─► [Сбой / Таймаут] ──► Повтор на backup/следующий (proxy_next_upstream)
   │
   ▼
[Nginx Worker]
   │ 8. Прием заголовков ответа (proxy_buffer_size)
   │ 9. Потоковая отдача клиенту или запись в буферы (proxy_buffering)
   │ 10. Возврат соединения бэкенда в Keepalive-пул
   ▼
[Клиент]
```

#### Детальный разбор фаз:

1. **Прием клиентского соединения:** Рабочий процесс регистрирует событие готовности сокета в селекторе `epoll`. После завершения TCP-рукопожатия и TLS-терминации формируется структура HTTP-запроса `ngx_http_request_t`.
2. **Маршрутизация к upstream:** Директива `proxy_pass http://upstream_name;` переводит запрос в подсистему `ngx_http_upstream`.
3. **Синхронизация через разделяемую память:** Если в блоке `upstream` объявлена директива `zone`, воркер захватывает spinlock в shared memory, считывает глобальные счетчики ошибок и активных соединений для каждого узла.
4. **Селекция бэкенда:** Алгоритм балансировки выбирает целевой сервер. Если узел находится в статусе `down` или временно отключен пассивным счетчиком `max_fails`, он исключается из итерации.
5. **Инициализация соединения с бэкендом:** 
   - Модуль `ngx_http_upstream_keepalive` проверяет локальный кэш сокетов воркера. При наличии свободного сокета с соответствующим адресом он переиспользуется без сетевых задержек.
   - Если пул пуст, инициируется неблокирующий системный вызов `connect()`. Таймер отслеживается параметром `proxy_connect_timeout`.
6. **Передача данных и буферизация:** 
   - По умолчанию (`proxy_buffering on;`) Nginx считывает ответ бэкенда с максимальной скоростью в буферы оперативной памяти (`proxy_buffers`). Это немедленно освобождает рабочий поток приложения на бэкенде.
   - При превышении объема выделенной RAM излишки сбрасываются во временные файлы на диске (`proxy_temp_path`).
   - Если буферизация отключена (`proxy_buffering off;`), данные передаются клиенту синхронно по мере поступления, что критично для Server-Sent Events (SSE) и потоковых API.
7. **Обработка сбоев (Circuit Breaker):** Если бэкенд возвращает статус, указанный в `proxy_next_upstream` (например, `error timeout http_502 http_503`), Nginx увеличивает счетчик сбоев узла в `zone` и прозрачно для клиента повторяет запрос к следующему серверу из группы.
8. **Освобождение соединения:** После передачи тела ответа сокет бэкенда не закрывается `FIN`-пакетом, а переводится в состояние ожидания и помещается в кольцевой буфер keepalive-пула текущего воркера.

---

### Роль зоны разделяемой памяти (`zone`)

Архитектура Nginx предполагает полную независимость рабочих процессов (`shared-nothing`). Каждый воркер оперирует собственной изолированной таблицей файловых дескрипторов и локальной памятью:

```
БЕЗ ДИРЕКТИВЫ ZONE:
┌─────────────────┐      ┌─────────────────┐
│ Worker Proc 1   │      │ Worker Proc 2   │
│ - Upstream peer │      │ - Upstream peer │
│   fails: 1/3    │      │   fails: 2/3    │
└─────────────────┘      └─────────────────┘
  Состояние НЕ синхронизировано. Для исключения ноды с max_fails=3
  требуется 3 сбоя НА КАЖДЫЙ воркер (при 16 ядрах = 48 ошибок для клиента!)

С ДИРЕКТИВОЙ ZONE:
┌─────────────────┐      ┌─────────────────┐
│ Worker Proc 1   │      │ Worker Proc 2   │
└────────┬────────┘      └────────┬────────┘
         │   Shared Memory Block  │
         └──────────►┌────────────┴────────┐
                     │ Upstream Zone (RAM) │
                     │ - Server 1: 3 fails │ ──► СТАТУС: DOWN ДЛЯ ВСЕХ
                     │ - Least_conn: N     │
                     └─────────────────────┘
```

#### Почему директива `zone` критически важна:
1. **Счетчики отказов (Passive Health Checks):** Без `zone` узел будет отключен только тогда, когда **каждый** отдельный воркер накопит `max_fails` ошибок. На многоядерных серверах (32–64 ядра) неисправный бэкенд продолжит получать трафик и отдавать ошибки клиентам длительное время.
2. **Алгоритм `least_conn`:** Без `zone` каждый рабочий процесс отслеживает соединения изолированно. В результате выбор наименее загруженного узла превращается в локальный псевдо-Round Robin.
3. **Механизм `least_time` и динамический DNS:** Модули сбора латентности и динамического разрешения адресов (`resolve`) в Angie и Nginx Plus технически требуют наличия `zone` для регистрации runtime-состояния.

---

### Механика Zero-Downtime Reload и дренажа соединений

Применение новой конфигурации через сигнал `SIGHUP` (`nginx -s reload` или `systemctl reload nginx`) выполняется по схеме Master-Worker:

1. **Считывание и валидация конфигурации:** Master-процесс парсит конфигурационные файлы, проверяет синтаксис директив и открывает новые сетевые сокеты (если изменился список прослушиваемых портов).
2. **Запуск нового поколения воркеров:** Master запускает новый пул воркеров (`Generation N+1`), которые наследуют открытые сокеты и немедленно начинают вызывать `epoll_wait()` для приема входящего трафика.
3. **Перевод старых воркеров в режим Graceful Shutdown:** Master отправляет воркерам поколения `Generation N` сигнал `SIGQUIT`.
4. **Дренаж соединений (Connection Draining):** 
   - Старые воркеры закрывают слушающие сокеты (больше не принимают новые запросы).
   - Активные HTTP-транзакции дорабатываются до конца.
   - Клиентские соединения в состоянии Keepalive закрываются немедленно после завершения текущего запроса (выставляется заголовок `Connection: close`).
5. **Ограничения Nginx при долгих соединениях:**
   - Если через Nginx проксируются постоянные потоки (WebSockets, gRPC-стримы, SSE или длительные загрузки файлов), старые воркеры будут оставаться в памяти в статусе `is shutting down` бесконечно долго (или до срабатывания таймаута ядра).
   - В Angie и Nginx Plus данная проблема решается директивой `worker_shutdown_timeout <время>;`, по истечении которой старые процессы принудительно завершаются по `SIGKILL`.
   - **Сравнение с HAProxy:** HAProxy поддерживает механизм передачи файловых дескрипторов сокетов между старым и новым процессом через UNIX-сокет (Socket Transfer `-x`), что исключает зависание процессов при перезагрузке конфигурации.

---

## Практические сценарии

### 1. Высоконагруженный Edge-балансировщик с TLS и L7-маршрутизацией

Сценарий типового фронтенд-шлюза: терминирование TLS, отдача статических файлов напрямую через Zero-Copy, сжатие, маршрутизация API на динамический пул приложений с активным keepalive-пулом.

```nginx
# /etc/nginx/nginx.conf
user nginx;
worker_processes auto;
worker_cpu_affinity auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 16384;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Оптимизация дискового и сетевого стека ядра
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    # Зона разделяемой памяти для upstream
    upstream api_backend_pool {
        zone api_pool_zone 512k;
        
        # least_conn эффективен при неодинаковом времени обработки API-запросов
        least_conn;

        server 10.10.1.11:8080 weight=3 max_fails=3 fail_timeout=15s;
        server 10.10.1.12:8080 weight=3 max_fails=3 fail_timeout=15s;
        server 10.10.1.13:8080 weight=2 max_fails=3 fail_timeout=15s;
        
        # Резервный узел: включается только при отказе всех основных
        server 10.10.1.20:8080 backup;

        # Пул открытых постоянных соединений к бэкендам (на каждый воркер!)
        keepalive 64;
        keepalive_requests 1000;
        keepalive_timeout 60s;
    }

    server {
        listen 80;
        listen [::]:80;
        server_name api.example.corp;
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl reuseport;
        listen [::]:443 ssl reuseport;
        server_name api.example.corp;

        ssl_certificate /etc/ssl/certs/api.example.corp.crt;
        ssl_certificate_key /etc/ssl/private/api.example.corp.key;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
        ssl_session_cache shared:SSL:20m;
        ssl_session_timeout 1d;
        ssl_session_tickets off;

        # Локальная статика отдается без проксирования
        location /static/ {
            alias /var/www/static/;
            expires 30d;
            add_header Cache-Control "public, no-transform";
            access_log off;
        }

        # Динамический API
        location /api/ {
            proxy_pass http://api_backend_pool;
            
            # Обязательно для работы upstream keepalive (HTTP/1.1 без Connection: close)
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            # Передача реальных сетевых атрибутов клиента
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Управление таймаутами
            proxy_connect_timeout 3s;
            proxy_send_timeout 10s;
            proxy_read_timeout 10s;

            # Отказоустойчивый повтор при сетевых сбоях бэкенда
            proxy_next_upstream error timeout invalid_header http_502 http_503;
            proxy_next_upstream_tries 3;
            proxy_next_upstream_timeout 5s;

            # Настройка буферов в RAM
            proxy_buffering on;
            proxy_buffer_size 8k;
            proxy_buffers 16 16k;
            proxy_busy_buffers_size 32k;
        }
    }
}
```

---

### 2. Отказоустойчивый HA-кластер на Bare-Metal / VM (Keepalived + VRRP)

Одиночный экземпляр Nginx является единой точкой отказа (SPOF). В on-premises инфраструктуре стандартом высокой доступности является развертывание пары серверов Nginx под управлением **Keepalived** с общим виртуальным IP-адресом (VIP):

```
                     Входящий клиентский трафик
                                 │
                                 ▼
                     Virtual IP (192.168.10.100)
                                 │
                 ┌───────────────┴───────────────┐
                 │                               │
        [Master Node: lb01]             [Backup Node: lb02]
         IP: 192.168.10.11               IP: 192.168.10.12
         Keepalived (VRRP Master)        Keepalived (VRRP Backup)
         Nginx (Active)                  Nginx (Hot Standby)
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
                     Внутренняя сеть бэкендов
```

#### Конфигурация Keepalived на узле lb01 (`/etc/keepalived/keepalived.conf`):

```ini
global_defs {
    router_id lb01
    enable_script_security
    script_user root
}

# Скрипт проверки работоспособности локального Nginx
vrrp_script check_nginx {
    script "/usr/bin/killall -0 nginx"
    interval 2
    weight 2
    fall 2
    rise 2
}

vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass VrrpAuthSecret2026
    }

    virtual_ipaddress {
        192.168.10.100/24 dev eth0 label eth0:vip
    }

    track_script {
        check_nginx
    }
}
```

#### Настройка узла lb02 (Backup):
На втором узле параметр `state` выставляется в `BACKUP`, а `priority` в `100`. При падении процесса Nginx на `lb01` скрипт завершается с ненулевым кодом, приоритет мастера падает со 101 до 99, и узел `lb02` с приоритетом 100 мгновенно перехватывает VIP-адрес посредством отправки Gratuitous ARP (GARP).

#### Обязательная настройка ядра Linux для привязки к нелокальному IP:
Чтобы Nginx мог запуститься и слушать VIP-адрес на резервном узле еще до фактического получения адреса на интерфейсе, активируется параметр `ip_nonlocal_bind`:

```bash
# Разрешение привязки сервисов к нелокальным адресам (sysctl)
echo "net.ipv4.ip_nonlocal_bind = 1" >> /etc/sysctl.d/99-ha-vip.conf
sysctl -p /etc/sysctl.d/99-ha-vip.conf
# → net.ipv4.ip_nonlocal_bind = 1
```

Подробное руководство по отказоустойчивым кластерам: [Keepalived: обзор и настройка](../../../../Networking/ServicesAndTools/keepalived_overview.md).

---

### 3. Гибридная двухуровневая архитектура: HAProxy (L4) + Nginx (L7)

В сверхнагруженных bare-metal инфраструктурах часто используется гибридный стек:
- **HAProxy на L4 (Front):** Принимает входящие сетевые пакеты, выполняет первичную защиту от SYN-flood и распределяет сырой TCP-трафик между группой серверов Nginx через **PROXY Protocol v2**.
- **Nginx на L7 (Application Edge):** Терминирует TLS, валидирует сложные правила безопасности, производит маршрутизацию по URL, кэширует ответы и взаимодействует с бэкендами.

#### Конфигурация Nginx для приема PROXY Protocol от HAProxy:

```nginx
server {
    # Флаг proxy_protocol активирует чтение бинарного префикса v1/v2
    listen 443 ssl proxy_protocol;
    server_name portal.example.corp;

    ssl_certificate /etc/ssl/certs/portal.crt;
    ssl_certificate_key /etc/ssl/private/portal.key;

    # Доверенная подсеть вышестоящих балансировщиков HAProxy
    set_real_ip_from 192.168.10.0/24;
    
    # Восстановление реального IP клиента из структуры PROXY-протокола
    real_ip_header proxy_protocol;

    location / {
        proxy_pass http://backend_pool;
        # В $remote_addr теперь содержится реальный адрес внешнего клиента
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
    }
}
```

---

### 4. Снятие нод с нагрузки без простоя (Graceful Drain & Rolling Deployment)

При проведении плановых технических работ или развертывании новой версии приложения узел необходимо вывести из балансировки без генерации ошибок 502/504 для активных пользователей.

#### Вариант А: Использование параметра `down` в Nginx OSS
В конфигурационном файле узел помечается директивой `down`, после чего выполняется перезагрузка:

```nginx
upstream app_cluster {
    zone app_zone 256k;
    server 10.10.1.11:8080;
    # Узел выведен на обслуживание
    server 10.10.1.12:8080 down;
    server 10.10.1.13:8080;
}
```
Применение: `nginx -s reload`. Новые запросы не будут направляться на сервер `10.10.1.12`, но текущие соединения будут обработаны корректно.

#### Вариант Б: Динамическое управление через REST API (Angie)
В Angie изменение статуса и веса узла выполняется мгновенно на лету без `reload`:

```bash
# Перевод сервера в режим drain (только завершение существующих сессий)
curl -X PATCH -d '{"drain": true}' \
     http://127.0.0.1:8080/api/v1/http/upstreams/app_cluster/servers/1

# Полный вывод из балансировки
curl -X PATCH -d '{"down": true}' \
     http://127.0.0.1:8080/api/v1/http/upstreams/app_cluster/servers/1

# Возврат узла в строй с плавным нарастанием нагрузки (slow_start)
curl -X PATCH -d '{"down": false, "drain": false, "weight": 5}' \
     http://127.0.0.1:8080/api/v1/http/upstreams/app_cluster/servers/1
```

---

## Операции и команды

### Валидация и безопасная перезагрузка

```bash
# 1. Проверка синтаксиса и целостности всех инклюдов
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Вывод полной скомпилированной конфигурации на экран (удобно для аудита)
nginx -T | grep -A 10 "upstream"

# 3. Безопасное применение изменений конфигурации (Graceful Reload)
nginx -s reload
# → signal reload started

# 4. Проверка состояния рабочих процессов (контроль завершения старого поколения)
ps -eo pid,ppid,user,stat,command | grep [n]ginx
# → 12400     1 root     Ss   nginx: master process /usr/sbin/nginx
# → 14501 12400 nginx    S    nginx: worker process
# → 14502 12400 nginx    S    nginx: worker process
```

---

### Анализ работы upstream через структурированные логи

Для SRE-диагностики распределения нагрузки и задержек настройте расширенный формат логов в блоке `http`:

```nginx
log_format upstream_sre '$remote_addr - [$time_local] "$request" '
                        '$status $body_bytes_sent '
                        'upstream: $upstream_addr '
                        'status: $upstream_status '
                        'rt: $request_time '
                        'uct: "$upstream_connect_time" '
                        'urt: "$upstream_response_time"';
```

#### Команды анализа логов:

```bash
# Анализ распределения входящих запросов по IP-адресам бэкендов
awk -F'upstream: ' '{print $2}' /var/log/nginx/access.log | awk '{print $1}' | sort | uniq -c | sort -rn
# → 45210 10.10.1.11:8080
# → 44980 10.10.1.12:8080
# → 15200 10.10.1.13:8080

# Выявление бэкендов с временем ответа более 1.5 секунд
awk -F'urt: ' '$2 > 1.5 {print $0}' /var/log/nginx/access.log | tail -n 15

# Подсчет кодов ошибок upstream (502, 503, 504)
grep -o 'status: 50[234]' /var/log/nginx/access.log | sort | uniq -c
# →    12 status: 502
# →     3 status: 504
```

---

### Сбор метрик и телеметрия для Prometheus

Для наблюдения за пулами upstream в инфраструктуре Prometheus используются следующие подходы:

```bash
# 1. Проверка стандартного модуля stub_status (Nginx OSS)
curl -s http://127.0.0.1:8080/nginx_status
# → Active connections: 142 
# → server accepts handled requests
# →  105420 105420 289304 
# → Reading: 2 Writing: 18 Waiting: 122

# 2. Опрос экспортера nginx-prometheus-exporter
curl -s http://127.0.0.1:9113/metrics | grep nginx_connections
# → # HELP nginx_connections_active Active client connections
# → # TYPE nginx_connections_active gauge
# → nginx_connections_active 142

# 3. Опрос нативного Prometheus-эндпоинта Angie (включается через prometheus on)
curl -s http://127.0.0.1:8080/metrics | grep angie_http_upstreams
# → angie_http_upstreams_peers_requests_total{upstream="api_backend_pool",peer="10.10.1.11:8080"} 45210
# → angie_http_upstreams_peers_state{upstream="api_backend_pool",peer="10.10.1.11:8080"} 1
```

---

### Нагрузочное тестирование upstream с `wrk` и `hey`

Для проверки корректности алгоритмов распределения нагрузки и замера перцентилей задержек прокси-сервера:

```bash
# Запуск 10-секундного теста в 4 потока и 200 конкурентных соединений
wrk -t4 -c200 -d10s --latency http://api.example.corp/api/v1/ping
# → Running 10s test @ http://api.example.corp/api/v1/ping
# →   4 threads and 200 connections
# →   Thread Stats   Avg      Stdev     Max   +/- Stdev
# →     Latency     3.42ms    1.12ms  42.50ms   88.20%
# →     Req/Sec    14.65k     1.20k   18.10k    72.25%
# →   Latency Distribution
# →      50%    3.10ms
# →      75%    3.80ms
# →      90%    4.65ms
# →      99%    8.90ms
# →   584020 requests in 10.02s, 124.50MB read
# → Requests/sec:  58285.43
# → Transfer/sec:     12.42MB

# Анализ распределения ответов бэкенда через hey
hey -n 10000 -c 50 http://api.example.corp/api/v1/users
# → Status code distribution:
# →   [200] 10000 responses
```

---

## Диагностика и устранение неполадок

### Матрица типовых сбоев upstream

| Симптом | Первопричина | Диагностика и исправление |
| :--- | :--- | :--- |
| `502 Bad Gateway` (Connection refused) | Процесс на целевом сервере остановлен, слушает другой порт или заблокирован локальным фаерволом (iptables/nftables) | Проверить состояние бэкенда: `curl -I http://10.10.1.11:8080`; проверить порт: `ss -tlnp \| grep 8080`. Проверить журнал: `grep "connect() failed (111: Connection refused)" /var/log/nginx/error.log`. |
| `504 Gateway Timeout` | Время выполнения запроса приложением превысило `proxy_read_timeout` (по умолчанию 60с) | Найти медленные запросы в логах приложения. Временно увеличить лимит: `proxy_read_timeout 120s;`. Оптимизировать запросы к БД на стороне бэкенда. |
| `502 Bad Gateway` (Cannot assign requested address) | **Исчерпание эфемерных портов** на балансировщике при отключенном upstream keepalive | Проверить диапазон портов: `cat /proc/sys/net/ipv4/ip_local_port_range`. Включить `keepalive` в блоке `upstream` и активировать переиспользование сокетов: `net.ipv4.tcp_tw_reuse = 1`. |
| `upstream sent too big header` | Размер HTTP-заголовков ответа бэкенда (например, крупные Set-Cookie или токены авторизации) превысил размер одного буфера Nginx | Увеличить размер заголовка в секции `http` или `location`: `proxy_buffer_size 16k; proxy_buffers 4 32k; proxy_busy_buffers_size 64k;`. |
| `an upstream response is buffered to a temporary file` | Объем передаваемого ответа превысил суммарный размер буферов в памяти `proxy_buffers`, Nginx выполняет медленную запись на диск | Увеличить количество буферов: `proxy_buffers 16 32k;` или отключить буферизацию для специфических путей выгрузки: `proxy_buffering off;`. |
| Резкий дисбаланс нагрузки при `ip_hash` | Множество корпоративных клиентов обращаются через общий промежуточный прокси-сервер или корпоративный NAT с одного IP | Заменить `ip_hash` на балансировку по cookie пользователя: `hash $cookie_SESSIONID consistent;` или использовать `least_conn`. |
| Сбой `no resolver defined to resolve ...` | Имя бэкенда задано через переменную (`proxy_pass http://$backend_host`), но в конфигурации не объявлен DNS-сервер | Задать системный DNS-сервер: `resolver 127.0.0.53 10.0.0.2 valid=30s;`. Подробнее: [Динамическое разрешение DNS](./dynamic_dns_resolution.md). |

---

### Диагностические команды системного администратора

```bash
# 1. Проверка активных сетевых соединений от Nginx к бэкенд-пулу
ss -ant '( dport = :8080 )' | awk '{print $1}' | sort | uniq -c
# →   48 ESTAB
# →  120 TIME-WAIT

# 2. Подсчет открытых файловых дескрипторов процессами Nginx
cat /proc/$(pgrep -o -f "nginx: worker")/limits | grep "Max open files"
# → Max open files            65535                65535                files

# 3. Проверка фактического числа используемых дескрипторов воркером
ls -1 /proc/$(pgrep -o -f "nginx: worker")/fd | wc -l
# → 184

# 4. Проверка сброса временных буферов на диск
ls -lh /var/lib/nginx/proxy/ 2>/dev/null || ls -lh /var/cache/nginx/proxy_temp/
# → total 0 (если чисто — буферов в RAM достаточно)

# 5. Поиск последних критических ошибок в журнале сбоев
grep -E "\[error\]|\[crit\]" /var/log/nginx/error.log | tail -n 20
```

---

## Лучшие практики

### Производительность и оптимизация ядра Linux

Для предотвращения деградации производительности высоконагруженного балансировщика нагрузки внесите параметры в `/etc/sysctl.d/99-load-balancer.conf`:

```ini
# Максимальная глубина очереди входящих соединений (backlog)
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# Расширение диапазона эфемерных портов для соединений с бэкендами
net.ipv4.ip_local_port_range = 10240 65535

# Разрешение переиспользования сокетов в состоянии TIME_WAIT для исходящих подключений
net.ipv4.tcp_tw_reuse = 1

# Увеличение лимита отслеживания соединений conntrack (при активном firewall)
net.netfilter.nf_conntrack_max = 1048576
```
Применить: `sysctl -p /etc/sysctl.d/99-load-balancer.conf`.

#### Рекомендации по настройке Nginx:
1. **Всегда используйте `zone`:** Любой блок `upstream` в продакшене обязан содержать директиву `zone`, иначе счетчики ошибок и алгоритмы распределения не будут координироваться между ядрами CPU.
2. **Всегда включайте `keepalive` в `upstream`:** Установка постоянных соединений снижает сетевую задержку на 30–50% и снимает нагрузку с бэкендов. Обязательно добавляйте `proxy_http_version 1.1;` и `proxy_set_header Connection "";`.
3. **Расчет размера keepalive:** Эмпирическое правило для параметра `keepalive <N>`: от 20% до 50% от максимального числа одновременных запросов, приходящихся на один рабочий процесс.
4. **Консистентное хеширование для кэшей:** Если бэкенд выполняет локальное кэширование, используйте `hash $request_uri consistent;`. Это минимизирует сброс кэшей при добавлении или удалении серверов из пула.

---

### Эксплуатация и SRE (Golden Signals)

1. **Мониторинг четырех «золотых сигналов» (Four Golden Signals):**
   - **Latency (Задержка):** Отслеживайте `$upstream_response_time` отдельно от полного времени запроса `$request_time`. Разница между ними указывает на сетевые задержки или медленный прием данных клиентом.
   - **Traffic (Трафик):** Мониторинг RPS суммарно и по каждому бэкенду. Дисбаланс более 15–20% при использовании Round Robin свидетельствует о залипании соединений или неоднородности инфраструктуры.
   - **Errors (Ошибки):** Коэффициент ошибок 5xx со стороны upstream. Алерты должны срабатывать при превышении порога в 0.5% от общего объема трафика.
   - **Saturation (Насыщение):** Утилизация пула соединений `keepalive`, количество дескрипторов сокетов и загрузка очередей воркеров.
2. **Идемпотентность и безопасность `proxy_next_upstream`:**
   - По умолчанию Nginx повторяет запросы только при сбоях уровня сети (`error timeout`).
   - Будьте осторожны при добавлении `non_idempotent` методов (POST, PATCH, PUT): повторный запрос при получении `http_502` или таймауте может привести к повторному списанию средств или дублированию записей в базе данных бэкенда!
3. **Разделение доменов отказа:** Размещайте резервные бэкенды (`backup`) на независимых физических гипервизорах или в изолированных стойках серверной комнаты.

---

### Безопасность

1. **Изоляция управляющих интерфейсов:** Доступ к эндпоинтам `stub_status`, метрикам Prometheus или REST API (Angie/Nginx Plus) должен быть строго ограничен внутренними IP-адресами мониторинга:
   ```nginx
   location /nginx_status {
       stub_status;
       allow 127.0.0.1;
       allow 10.10.0.0/16;
       deny all;
   }
   ```
2. **Скрытие служебной информации:** Подавляйте заголовки бэкендов, раскрывающие стек технологий:
   ```nginx
   proxy_hide_header X-Powered-By;
   proxy_hide_header Server;
   server_tokens off;
   ```
3. **Защита от атак медленного чтения (Slowloris / Slow Read):** Ограничивайте время чтения тела запроса и отправки ответов директивами `client_body_timeout 10s;` и `send_timeout 10s;`.

---

## Дополнительная информация

### См. также

- [Обзор балансировки L7 в Nginx](./overview_concepts.md) — фундаментальные принципы, процессная модель, L4 vs L7.
- [Алгоритмы балансировки](./algorithms.md) — детальный разбор Round Robin, Least Connections, IP Hash, Generic Hash, Least Time.
- [Практическая конфигурация балансировки](./practical_configuration.md) — директивы `proxy_pass`, `keepalive`, буферизация, проксирование WebSocket.
- [Health Checks и мониторинг](./health_checks_and_monitoring.md) — пассивные и активные проверки, метрики Prometheus, интеграция с Grafana.
- [Sticky Sessions в Nginx](./sticky_sessions.md) — методы привязки сессий (cookie, route, learn).
- [Динамическое разрешение DNS в Nginx](./dynamic_dns_resolution.md) — параметры директивы `resolver` для динамических окружений.
- [Балансировка и проксирование L4-трафика](../nginx_l4_proxying.md) — модуль `stream`, проксирование баз данных и TCP/UDP-сервисов.
- [Обзор Nginx](../../Core/nginx_overview.md) — архитектура, модули, конфигурационные блоки и жизненный цикл.
- [Обзор Angie](../../../Angie/angie_overview.md) — нативные активные проверки, REST API, Prometheus и расширенная балансировка.
- [Обзор HAProxy](../../../haproxy_overview.md) — архитектура, Runtime API, Stick Tables, высокоточная L4/L7-балансировка.
- [Keepalived: обзор и настройка](../../../../Networking/ServicesAndTools/keepalived_overview.md) — протокол VRRP, плавающий VIP и построение отказоустойчивых кластеров.
- [Кластеризация и балансировка для HA](../../../../Concepts/High_Availability/ha_clustering_and_load_balancing.md) — архитектура высокой доступности, модели Active-Active, Active-Passive и DSR.
