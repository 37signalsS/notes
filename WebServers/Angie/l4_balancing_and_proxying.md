# Балансировка и проксирование L4-трафика (TCP/UDP) в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Модуль `stream` в Angie** — подсистема веб-сервера, обеспечивающая высокопроизводительное проксирование и балансировку сетевого трафика на транспортном уровне (L4 модели OSI). Модуль оперирует сырыми TCP-сессиями и UDP-датаграммами без глубокого разбора протоколов прикладного уровня, что позволяет обслуживать произвольные сервисы: реляционные и NoSQL СУБД (PostgreSQL, MySQL, Redis), брокеры сообщений (RabbitMQ, Kafka), службы каталогов и авторизации (LDAP), DNS-серверы, почтовые агенты (SMTP/IMAP), SSH-бастионы и IoT-шлюзы (MQTT).

**L4 (Transport Layer) проксирование** — режим передачи данных, при котором балансировщик принимает решение о маршрутизации пакетов на основе IP-адресов источника и назначения, TCP/UDP-портов, а также ограниченного набора метаданных рукопожатия (TLS SNI/ALPN через механизм Pre-read). Полезная нагрузка сессии передается напрямую между сокетами клиента и бэкенда.

**L7 (Application Layer) проксирование** — режим передачи данных (реализованный в модуле `http`), при котором сервер полностью десериализует протокол прикладного уровня (HTTP/1.1, HTTP/2, HTTP/3, gRPC), анализирует заголовки, куки, URI и тело запроса.

### Сравнение L4 и L7 проксирования

| Характеристика | L4 (Модуль `stream`) | L7 (Модуль `http`) |
| :--- | :--- | :--- |
| **Уровень модели OSI** | Уровень 4 (Транспортный: TCP, UDP) | Уровень 7 (Прикладной: HTTP, HTTPS, gRPC, WebSocket) |
| **Единица обработки** | Непрерывный двунаправленный байтовый поток (TCP) или датаграмма (UDP) | Дискретный запрос (Request) и ответ (Response) |
| **Инспекция содержимого** | Отсутствует (за исключением заголовка TLS ClientHello или заголовка пакета MQTT CONNECT при Pre-read) | Полный синтаксический анализ структуры заголовков, параметров, Cookie и тела сообщения |
| **Накладные расходы CPU/RAM** | Минимальные (zero-copy в ядре, потоковая передача через кольцевые буферы) | Высокие (выделение структур под парсинг HTTP, декомпрессия gzip/brotli, перешифрование) |
| **Поддерживаемые функции** | Балансировка TCP/UDP, SNI-маршрутизация, PROXY Protocol, ограничение соединений (`limit_conn`), ограничение полосы | Кэширование ответов, WAF, модификация URI/заголовков, сжатие, разграничение прав (`auth_request`, OIDC) |
| **Модификация данных** | Исключена (за исключением вставки/удаления заголовка PROXY Protocol) | Полная трансформация запроса и ответа на лету |
| **Задержка (Latency)** | Субмиллисекундная (прямая трансляция буферов сокетов) | Зависит от времени разбора и сборки HTTP-фреймов |

### Ключевые термины подсистемы Stream

*   **Upstream-группа (L4)** — именованный пул сетевых адресов бэкендов (`IP:port` или UNIX-доменные сокеты), объединенных общим алгоритмом распределения нагрузки и правилами отслеживания доступности.
*   **Зона разделяемой памяти (`zone`)** — сегмент оперативной памяти, выделяемый через `mmap` и доступный всем рабочим процессам (`worker processes`) Angie. Необходима для синхронизации счетчиков соединений, весов, динамического состава бэкендов и алгоритма `least_conn`.
*   **Зона мониторинга (`status_zone`)** — механизм агрегации эксплуатационной телеметрии в реальном времени. В блоке `server` собирает метрики пропускной способности и сессий слушающего порта, в блоке `upstream` — детальную статистику по каждому бэкенду. В отличие от Nginx OSS, в Angie функционал `status_zone` встроен в базовую бесплатную версию (Open Source).
*   **Сессионная привязка (Session Persistence)** — алгоритм направления пакетов или сессий определенного клиента на один и тот же бэкенд на основе консистентного хэширования параметров соединения (IP-адрес, порт, идентификатор MQTT-клиента).
*   **SSL/TLS Pre-read (`ssl_preread`)** — инспекция первых байтов входящего TCP-соединения (пакет TLS `ClientHello`) без выполнения криптографического рукопожатия и владения закрытым ключом. Позволяет извлекать доменное имя SNI (`$ssl_preread_server_name`), версию протокола (`$ssl_preread_protocol`) и согласованный протокол ALPN (`$ssl_preread_alpn_protocols`).
*   **MQTT Pre-read (`mqtt_preread`)** — встроенный анализатор сетевых пакетов протокола MQTT (версии 3.1.1 и 5.0), считывающий заголовок пакета `CONNECT` для извлечения параметров `$mqtt_preread_clientid` и `$mqtt_preread_username` (доступен с версии Angie 1.4.0).
*   **PROXY Protocol (v1 / v2)** — сетевой стандарт (разработанный HAProxy), позволяющий передавать метаданные исходного клиентского соединения (реальный IP-адрес клиента, порт, IP-адрес прокси, параметры TLS) внутри заголовка в начале TCP-потока.
*   **Плавный старт (`slow_start`)** — режим постепенного ввода восстановившегося после сбоя или вновь добавленного сервера в рабочий пул: вес бэкенда плавно увеличивается от нуля до номинального за заданный интервал времени. В Angie директива доступна в OSS-версии для пулов с настроенной `zone`.
*   **Проверки доступности (Health Checks)**:
    *   *Пассивные проверки (OSS/PRO):* мониторинг ошибок в ходе обработки штатного трафика (`max_fails`, `fail_timeout`).
    *   *Активные проверки (Angie PRO):* генерация периодических проверочных TCP-соединений или UDP-зондов независимым фоновым процессом (`upstream_probe`).
*   **Динамическое обнаружение сервисов (Service Discovery)** — обновление списка адресов в `upstream` без перезагрузки процесса Angie через Docker API (`docker_endpoint`), DNS-резолвер (`resolve`, SRV-записи) или программный REST API (Angie PRO).
*   **Пользовательские метрики (`ngx_stream_metric_module`)** — модуль сбора числовых агрегатов и гистограмм в контексте `stream` (появился в Angie 1.7.0).

---

## Основные концепции и архитектура

### Архитектура модуля stream и жизненный цикл L4-сессии

Модуль `stream` компилируется в ядро Angie (или подключается динамически) и функционирует на базе общей событийно-ориентированной архитектуры (Event-Driven Architecture) с пулом рабочих процессов (`worker processes`), использующих мультиплексирование системных вызовов ядра Linux (`epoll`).

```
[ Клиент: TCP/UDP ]
        │
        ▼ (1. TCP SYN / UDP Datagram)
┌────────────────────────────────────────────────────────────────────────┐
│ Angie Master Process                                                   │
│   └── Worker Process (epoll loop, non-blocking I/O)                    │
│        ├── 2. Listen Socket (reuseport, backlog, TCP_DEFER_ACCEPT)      │
│        ├── 3. Pre-read Phase (ssl_preread / mqtt_preread)              │
│        ├── 4. Access Phase (limit_conn, allow/deny)                     │
│        ├── 5. Upstream Selection (Shared Zone, RR / least_conn / hash)  │
│        │        │                                                      │
│        │        ├─► [ Shared Memory: zone & status_zone ]              │
│        │        │                                                      │
│        ├── 6. Connect to Upstream (TCP Handshake, proxy_connect_timeout)│
│        ├── 7. Session Data Relaying (Bi-directional Stream, zero-copy) │
│        └── 8. Session Termination & Metrics Flush                      │
└────────────────────────────────────────────────────────────────────────┘
        │
        ▼ (PROXY Protocol v1/v2 Header + Payload)
[ Upstream Server: PostgreSQL / Redis / RabbitMQ / DNS ]
```

#### Этапы жизненного цикла TCP-сессии:

1.  **Прием соединения (Accept):** Рабочий процесс извлекает дескриптор нового соединения из очереди ожидания сокета `listen`. При использовании опции `reuseport` ядро Linux автоматически распределяет входящие SYN-пакеты между слушающими сокетами разных воркеров по хэшу 4-tuple.
2.  **Фаза предварительного анализа (Pre-read):** Если включен `ssl_preread` или `mqtt_preread`, Angie приостанавливает установку соединения с бэкендом и читает первые входящие байты от клиента в промежуточный буфер. Модуль парсит метаданные (SNI, ALPN или ClientID) и инициализирует соответствующие переменные.
3.  **Фаза контроля доступа (Access):** Проверяются ограничения директив `allow` / `deny`, а также лимиты параллельных соединений `limit_conn`. При превышении лимита соединение немедленно сбрасывается (TCP RST) или закрывается (TCP FIN).
4.  **Выбор бэкенда (Upstream Selection):** Из shared memory зоны считывается состояние серверов. Применяется выбранный алгоритм балансировки с учетом текущих весов, коэффициента `slow_start` и счетчиков активных коннектов.
5.  **Установка соединения с бэкендом (Connect):** Воркер инициирует неблокирующий системный вызов `connect()` к адресу выбранного целевого сервера. Если бэкенд не отвечает в течение `proxy_connect_timeout`, сервер помечается неисправным, и Angie переключается на следующий узел в соответствии с правилами `proxy_next_upstream`.
6.  **Трансляция данных (Proxying):** После установления соединения Angie приступает к двунаправленной ретрансляции данных. Если активирована директива `proxy_protocol on;`, перед первыми байтами клиентских данных в сокет бэкенда записывается бинарный или текстовый заголовок PROXY Protocol. Передача данных ведется через кольцевые буферы памяти (`proxy_buffer_size`) без сохранения на диск.
7.  **Завершение и фиксация метрик (Close):** При закрытии сокета любой из сторон или по истечении таймаута неактивности (`proxy_timeout`), соединение финализируется. Время сессии, количество переданных/принятых байтов и статус выполнения атомарно инкрементируются в `status_zone` и сбрасываются в `access_log`.

#### Особенности обработки UDP-трафика:
В силу отсутствия состояния соединения в протоколе UDP, Angie эмулирует виртуальную сессию. Сессия инициируется приемом первой датаграммы на порт `listen ... udp`. Ответные датаграммы от бэкенда перенаправляются обратно клиенту. Жизненный цикл сессии завершается либо по получению заданного директивой `proxy_responses` числа пакетов (например, ровно один ответ для DNS A-запроса), либо по истечении таймаута `proxy_timeout`.

---

### Сравнение возможностей Angie и Nginx OSS на уровне L4

| Функционал / Характеристика | Nginx Open Source | Angie Open Source | Angie PRO |
| :--- | :--- | :--- | :--- |
| **Сбор метрик в памяти (`status_zone`)** | Нет (только в коммерческом Nginx Plus) | **Да** (нативно в OSS на уровне `server` и `upstream`) | **Да** (расширенные метрики + персистентность) |
| **Плавный старт серверов (`slow_start`)** | Нет (только в Nginx Plus) | **Да** (доступно в базовом пакете) | **Да** |
| **Разбор протокола MQTT (`mqtt_preread`)** | Нет | **Да** (начиная с Angie 1.4.0) | **Да** |
| **Автообнаружение через Docker API** | Нет | **Да** (начиная с Angie 1.10.0) | **Да** |
| **Динамическое разрешение DNS (`resolve` / SRV)** | Нет (только в Nginx Plus) | **Да** (поддерживаются A/AAAA и SRV) | **Да** |
| **Активные проверки доступности** | Требуются сторонние патчи/модули | Требуются сторонние модули | **Да** (нативная директива `upstream_probe`) |
| **Конфигурационный REST API в runtime** | Нет | Нет | **Да** (методы `GET`, `PUT`, `PATCH`, `DELETE`) |
| **Кластерная синхронизация зон (`sync`)** | Нет | Нет | **Да** (модуль кластерной репликации) |
| **Файл персистентного состояния (`state`)** | Нет | **Да** (для DNS/Docker SD) | **Да** (для API и SD) |

---

### Структура конфигурации и топология каталогов

В отличие от блоков виртуальных хостов `http`, контекст `stream` конфигурируется на корневом уровне файла `/etc/angie/angie.conf` параллельно с блоками `events` и `http`.

Рекомендуемая топология файлов для On-Premises серверов:

```
/etc/angie/
├── angie.conf                 # Основной файл конфигурации
├── stream.d/                  # Каталог для конфигураций L4-сервисов
│   ├── 01_postgres.conf       # Проксирование баз данных
│   ├── 02_redis.conf          # Проксирование кэш-серверов
│   ├── 03_dns.conf            # Проксирование UDP/TCP DNS
│   ├── 04_rabbitmq.conf       # Проксирование AMQP брокеров
│   └── 05_sni_router.conf     # Маршрутизация по SNI
└── certs/                     # Сертификаты для TLS-терминации на L4
    ├── stream_redis.crt
    └── stream_redis.key
```

Базовый каркас `/etc/angie/angie.conf`:

```nginx
user angie;
worker_processes auto;
worker_rlimit_nofile 1048576;
error_log /var/log/angie/error.log warn;
pid /run/angie.pid;

events {
    worker_connections 65535;
    use epoll;
    multi_accept on;
}

# Блок L7-трафика (используется для отдачи статики, API и сбора метрик)
http {
    include /etc/angie/mime.types;
    default_type application/octet-stream;
    
    server {
        listen 127.0.0.1:8888;
        server_name localhost;

        # Эндпоинт мониторинга Status API
        location /status/ {
            status;
        }

        # Эндпоинт метрик Prometheus
        location /p_status {
            prometheus all;
        }
    }
}

# Корневой блок L4-трафика
stream {
    # Формат логирования L4-сессий
    log_format stream_detailed '$remote_addr [$time_local] '
                               '$protocol $status $bytes_sent $bytes_received '
                               '$session_time "$upstream_addr" '
                               '"$upstream_bytes_sent" "$upstream_bytes_received" '
                               '"$upstream_connect_time"';

    access_log /var/log/angie/stream-access.log stream_detailed;

    # Подключение изолированных конфигураций
    include /etc/angie/stream.d/*.conf;
}
```

---

### Алгоритмы балансировки L4-трафика

Выбор сервера из пула `upstream` определяется одной из поддерживаемых директив:

1.  **Round Robin (по умолчанию):** запросы распределяются циклически с учетом весов `weight`. Применяется для однородных статических сервисов.
2.  **Least Connections (`least_conn;`):** соединение направляется на сервер с наименьшим текущим количеством активных соединений. Идеально подходит для протоколов с длительными транзакциями (PostgreSQL, MySQL, SSH).
3.  **Hash (`hash $key [consistent];`):** выбор сервера по хэш-сумме произвольной строки или переменной. Опция `consistent` задействует алгоритм консистентного хэширования Кетэма (Ketama), благодаря чему при выходе сервера из строя или добавлении нового перенаправляется лишь минимальная часть ключей ($\frac{1}{N}$).
4.  **Least Time (Angie PRO: `least_time connect | first_byte | last_byte;`):** соединение перенаправляется на бэкенд с минимальным средним временем отклика и наименьшим числом активных сессий.
5.  **Random (`random [two [least_conn]];`):** случайный выбор бэкенда либо выбор между двумя случайными серверами по критерию наименьшего числа соединений.

---

### Сессионная привязка (Session Persistence)

На транспортном уровне привязка клиента обеспечивается хэшированием сетевых параметров:

*   **По IP-адресу клиента:** `hash $remote_addr consistent;` — гарантирует, что запросы одного клиентского хоста направляются на закрепленный бэкенд (актуально для реплицированных кластеров баз данных при чтении).
*   **По связке IP:Port:** `hash $remote_addr:$remote_port;` — привязка конкретного сокета клиента (позволяет балансировать трафик разных процессов с одного хоста).
*   **По идентификатору MQTT ClientID:** `hash $mqtt_preread_clientid consistent;` — критично для брокеров сообщений MQTT, где каждый IoT-клиент обязан удерживать сессию на одном и том же узле кластера.

---

### Терминация TLS и сквозная маршрутизация (SSL Passthrough)

Angie на уровне L4 поддерживает два фундаментальных сценария работы с шифрованным трафиком:

1.  **Полная терминация TLS на балансировщике:**
    Angie выступает конечной точкой шифрования: принимает TLS-соединение от клиента, проверяет сертификаты и передает незашифрованный TCP-трафик к бэкендам в защищенном контуре.
    *Директивы:* `listen <port> ssl;`, `ssl_certificate`, `ssl_certificate_key`, `ssl_protocols`, `ssl_ciphers`.
2.  **Сквозное проксирование без расшифровки (SSL Passthrough):**
    Шифрованный поток передается на целевой сервер в неизменном виде. Сертификаты и закрытые ключи располагаются исключительно на конечных сервисах. Выбор целевого пула выполняется анализом расширения SNI через модуль предварительного чтения.
    *Директивы:* `ssl_preread on;`, переменная `$ssl_preread_server_name`.

---

### Интеграция с PROXY Protocol

Поскольку L4-проксирование подменяет исходный IP-адрес клиента адресом интерфейса балансировщика, целевые сервисы видят входящие соединения как исходящие от Angie. Для прозрачной передачи метаданных используется PROXY Protocol:

*   **Режим отправки (Angie -> Backend):** директива `proxy_protocol on;` в блоке `server`. Angie формирует служебный заголовок и передает его первыми байтами бэкенду.
*   **Режим приема (Внешний LB -> Angie):** директива `listen <port> proxy_protocol;`. В этом случае Angie ожидает заголовок от внешнего балансировщика (HAProxy, сетевой аппаратный коммутатор), восстанавливает реальный адрес в переменную `$remote_addr`, а для защиты от спуфинга использует фильтр доверенных адресов `set_real_ip_from <CIDR>;`.

---

## Практические сценарии и конфигурация

### Сценарий 1: Отказоустойчивая балансировка пула PostgreSQL с Proxy Protocol, Slow Start и Status Zone

Сценарий организации пула серверов СУБД PostgreSQL (реплики для чтения под управлением Patroni/PgBouncer). Балансировщик защищает холодные ноды с помощью `slow_start`, транслирует реальный IP клиента в базу через PROXY Protocol и экспортирует метрики состояния пула.

**Предварительные требования:**
*   Установленный Angie на ОС Linux (Debian/Ubuntu или RHEL/AlmaLinux/Rocky).
*   Доступные ноды PostgreSQL: `192.168.10.21:5432`, `192.168.10.22:5432` и резервный узел `192.168.10.23:5432`.
*   На стороне PostgreSQL/PgBouncer включена поддержка PROXY Protocol (`proxy_protocol_networks = '192.168.10.10/32'`).

**Файл конфигурации `/etc/angie/stream.d/postgres_lb.conf`:**

```nginx
stream {
    # Группа серверов СУБД с разделяемой памятью
    upstream pg_read_pool {
        zone pg_read_zone 128k;
        status_zone pg_read_upstreams;

        # Алгоритм: наименьшее количество активных соединений
        least_conn;

        # Основные реплики: ограничение 250 коннектов, плавный пуск 45 секунд
        server 192.168.10.21:5432 max_conns=250 max_fails=3 fail_timeout=10s slow_start=45s;
        server 192.168.10.22:5432 max_conns=250 max_fails=3 fail_timeout=10s slow_start=45s;

        # Резервный узел (активируется только при падении основных нод)
        server 192.168.10.23:5432 backup;
    }

    server {
        # Слушаем стандартный порт PostgreSQL на внешнем интерфейсе балансировщика
        listen 192.168.10.10:5432;
        status_zone pg_frontend_listener;

        # Проксирование в upstream
        proxy_pass pg_read_pool;

        # Передача реального IP клиента бэкенду
        proxy_protocol on;

        # Таймауты TCP
        proxy_connect_timeout 2s;      # Максимальное время установки TCP к СУБД
        proxy_timeout 1h;              # Таймаут неактивности существующей сессии

        # Ограничение параллельных транзакций с одного IP (защита от исчерпания пула)
        limit_conn_zone $binary_remote_addr zone=pg_client_limit:10m;
        limit_conn pg_client_limit 50;
    }
}
```

**Пошаговая валидация и проверка:**

```bash
# 1. Проверка синтаксиса конфигурации
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Применение конфигурации без разрыва существующих соединений
angie -s reload
# → Graceful reload выполнен успешно

# 3. Проверка сокета слушателя в операционной системе
ss -tlnp | grep ':5432'
# → LISTEN 0 4096 192.168.10.10:5432 0.0.0.0:* users:(("angie",pid=14205,fd=8),("angie",pid=14206,fd=8))

# 4. Проверка прохождения запроса через утилиту psql
psql -h 192.168.10.10 -p 5432 -U app_user -d production_db -c "SELECT inet_server_addr(), inet_client_addr();"
# →  inet_server_addr | inet_client_addr 
# → ------------------+------------------
# →  192.168.10.21     | 192.168.1.150

# 5. Снятие метрик состояния апстрима через встроенный API
curl -s http://127.0.0.1:8888/status/stream/upstreams/pg_read_pool/ | jq '.peers[] | {server, state, active, requests, fails}'
# → {
# →   "server": "192.168.10.21:5432",
# →   "state": "up",
# →   "active": 12,
# →   "requests": 1450,
# →   "fails": 0
# → }
```

---

### Сценарий 2: Мультиплексирование HTTPS, SSH и MQTT на одном внешнем порту 443

Сценарий эффективного использования сетевой инфраструктуры в условиях жестких ограничений фаервола: внешний порт 443 принимает HTTPS, SSH-соединения и протокол IoT (MQTT) без дешифрования данных.

**Предварительные требования:**
*   Angie с включенными модулями `stream_ssl_preread` и `stream_mqtt_preread` (включены в Angie по умолчанию).
*   Локальные службы: локальный SSH (`127.0.0.1:22`), внутренний HTTPS-кластер (`192.168.20.10:8443`) и брокер MQTT Mosquitto/EMQX (`192.168.20.20:1883`).

**Файл конфигурации `/etc/angie/stream.d/port_multiplexer.conf`:**

```nginx
stream {
    # Сопоставление по версии TLS: если пришел TLS-пакет, направляем на HTTPS
    map $ssl_preread_protocol $is_tls {
        "TLSv1.2" https_upstream;
        "TLSv1.3" https_upstream;
        default   check_mqtt_phase;
    }

    # Если это не TLS, проверяем наличие MQTT ClientID
    map $mqtt_preread_clientid $multiplexed_backend {
        ""        ssh_upstream;        # Пустой ClientID и не TLS -> считаем SSH
        default   mqtt_upstream;       # Распознан протокол MQTT
    }

    # Финальный выбор бэкенда
    map $is_tls $final_backend {
        https_upstream https_upstream;
        default        $multiplexed_backend;
    }

    upstream https_upstream {
        zone https_zone 64k;
        server 192.168.20.10:8443;
    }

    upstream mqtt_upstream {
        zone mqtt_zone 64k;
        # Привязка MQTT-клиентов по их ClientID
        hash $mqtt_preread_clientid consistent;
        server 192.168.20.20:1883;
    }

    upstream ssh_upstream {
        zone ssh_zone 64k;
        server 127.0.0.1:22;
    }

    server {
        listen 192.168.1.100:443;
        status_zone multiplexer_port_443;

        # Включение предварительного парсинга заголовков
        ssl_preread on;
        mqtt_preread on;

        proxy_pass $final_backend;

        proxy_connect_timeout 3s;
        proxy_timeout 30m;
    }
}
```

**Пошаговая валидация и проверка:**

```bash
# 1. Проверка синтаксиса и перезагрузка
angie -t && angie -s reload
# → syntax is ok / reload successful

# 2. Проверка маршрутизации HTTPS трафика через OpenSSL
openssl s_client -connect 192.168.1.100:443 -tls1_3 -brief
# → CONNECTION ESTABLISHED
# → Protocol version: TLSv1.3
# → В логах /var/log/angie/stream-access.log upstream_addr указывает на 192.168.20.10:8443

# 3. Проверка подключения SSH через тот же порт 443
ssh -p 443 user@192.168.1.100 -o StrictHostKeyChecking=no "echo SSH_SUCCESS"
# → SSH_SUCCESS
# → В логах upstream_addr указывает на 127.0.0.1:22

# 4. Проверка подключения MQTT через консольный клиент mosquitto_pub
mosquitto_pub -h 192.168.1.100 -p 443 -i "sensor_node_01" -t "telemetry/status" -m "ONLINE"
# → Публикация выполнена успешно
# → В логах upstream_addr указывает на 192.168.20.20:1883
```

---

### Сценарий 3: Высокопроизводительный локальный DNS-прокси (UDP и TCP)

Организация отказоустойчивого кэширующего шлюза для DNS-запросов внутренней инфраструктуры на базе BIND/PowerDNS. Шлюз обрабатывает запросы по UDP и TCP с контролем числа ответов и защитой от Amplification-атак.

**Предварительные требования:**
*   DNS-резолверы внутренней сети: `192.168.1.2:53` и `192.168.1.3:53`.
*   Необходимость одновременного обслуживания UDP и TCP трафика на стандартном 53-м порту.

**Файл конфигурации `/etc/angie/stream.d/dns_proxy.conf`:**

```nginx
stream {
    upstream internal_dns_servers {
        zone dns_zone 64k;
        status_zone dns_upstreams;

        server 192.168.1.2:53 weight=2 max_fails=2 fail_timeout=3s;
        server 192.168.1.3:53 weight=1 max_fails=2 fail_timeout=3s;
    }

    # Ограничение частоты сессий с одного IP (защита от DoS/DDoS)
    limit_conn_zone $binary_remote_addr zone=dns_limit:10m;

    # UDP обработчик
    server {
        listen 192.168.1.5:53 udp;
        status_zone dns_udp_listener;

        proxy_pass internal_dns_servers;

        # Для стандартного DNS-запроса ожидается ровно 1 ответный пакет
        proxy_responses 1;

        # Таймаут ожидания ответа от DNS-сервера
        proxy_timeout 2s;

        limit_conn dns_limit 100;
    }

    # TCP обработчик (для DNS-зон и ответов размер которых превышает 512 байт / EDNS0)
    server {
        listen 192.168.1.5:53;
        status_zone dns_tcp_listener;

        proxy_pass internal_dns_servers;

        proxy_connect_timeout 1s;
        proxy_timeout 10s;

        limit_conn dns_limit 50;
    }
}
```

**Пошаговая валидация и проверка:**

```bash
# 1. Валидация и перезагрузка службы
angie -t && angie -s reload
# → syntax is ok / reload successful

# 2. Проверка UDP DNS запроса через утилиту dig
dig @192.168.1.5 -p 53 corp.internal A +short
# → 192.168.10.50

# 3. Проверка TCP DNS запроса (флаг +tcp)
dig @192.168.1.5 -p 53 corp.internal A +tcp +short
# → 192.168.10.50

# 4. Проверка счетчиков запросов и потерь в Status API
curl -s http://127.0.0.1:8888/status/stream/upstreams/internal_dns_servers/ | jq '.peers[] | {server, requests, responses}'
# → {
# →   "server": "192.168.1.2:53",
# →   "requests": 10520,
# →   "responses": 10520
# → }
```

---

### Сценарий 4: Защищенный прокси для Redis / KeyDB с SSL/TLS-терминацией

Сценарий защиты устаревших приложений, не поддерживающих TLS: Angie принимает защищенное TLS-соединение от удаленного клиента, расшифровывает трафик и перенаправляет в локальный нешифрованный кластер Redis Sentinel / Master.

**Предварительные требования:**
*   Локальный узел Redis: `127.0.0.1:6379`.
*   TLS-сертификат и закрытый ключ хоста: `/etc/angie/certs/redis_proxy.crt` и `/etc/angie/certs/redis_proxy.key`.
*   Клиентская сеть: `192.168.50.0/24`.

**Файл конфигурации `/etc/angie/stream.d/redis_tls.conf`:**

```nginx
stream {
    upstream redis_backend {
        zone redis_zone 64k;
        status_zone redis_upstreams;

        server 127.0.0.1:6379 max_conns=1000;
    }

    server {
        # Слушаем защищенный порт с активацией SSL
        listen 192.168.50.10:6380 ssl;
        status_zone redis_tls_frontend;

        # TLS параметры
        ssl_certificate     /etc/angie/certs/redis_proxy.crt;
        ssl_certificate_key /etc/angie/certs/redis_proxy.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;
        ssl_session_cache   shared:RedisSSL:10m;
        ssl_session_timeout 4h;

        proxy_pass redis_backend;

        # Настройки таймаутов
        proxy_connect_timeout 2s;
        proxy_timeout 300s;

        # Ограничение доступа по IP (только доверенная подсеть сервисов)
        allow 192.168.50.0/24;
        deny all;
    }
}
```

**Пошаговая валидация и проверка:**

```bash
# 1. Валидация и перезагрузка
angie -t && angie -s reload
# → syntax is ok / reload successful

# 2. Проверка статуса порта через ss
ss -tlnp | grep ':6380'
# → LISTEN 0 4096 192.168.50.10:6380 users:(("angie",pid=14205,fd=12))

# 3. Проверка выполнения PING через утилиту redis-cli с флагом --tls
redis-cli -h 192.168.50.10 -p 6380 --tls --cacert /etc/angie/certs/redis_proxy.crt PING
# → PONG

# 4. Проверка блокировки доступа с недоверенного адреса (симуляция deny all)
# Запрос с постороннего IP вернет немедленный сброс соединения
# → Error: Connection reset by peer
```

---

### Сценарий 5: Маршрутизация корпоративного TCP-трафика на основе SNI без дешифрования

Маршрутизация зашифрованного трафика к изолированным внутренним серверам (GitLab, Nextcloud, S3 MinIO) на основе запрашиваемого доменного имени (SNI) без расшифровки на балансировщике. Балансировщик не имеет доступа к закрытым ключам бэкендов.

**Предварительные требования:**
*   Внешний IP балансировщика: `198.51.100.1:443`.
*   Целевые серверы с собственными сертификатами:
    *   GitLab: `192.168.30.15:443`
    *   S3 MinIO: `192.168.30.25:443`
    *   Служебный дефолтный узел: `192.168.30.99:443`

**Файл конфигурации `/etc/angie/stream.d/sni_router.conf`:**

```nginx
stream {
    # Сопоставление домена из SNI с upstream-группой
    map $ssl_preread_server_name $sni_target_backend {
        "git.corp.internal"    gitlab_cluster;
        "s3.corp.internal"     minio_cluster;
        default                default_reject_pool;
    }

    upstream gitlab_cluster {
        zone gitlab_zone 64k;
        server 192.168.30.15:443 max_fails=2 fail_timeout=5s;
    }

    upstream minio_cluster {
        zone minio_zone 64k;
        server 192.168.30.25:443 max_fails=2 fail_timeout=5s;
    }

    upstream default_reject_pool {
        zone reject_zone 64k;
        server 127.0.0.1:9; # Недоступный порт (Blackhole)
    }

    server {
        listen 198.51.100.1:443;
        status_zone sni_router_listener;

        # Активация разбора SNI без расшифровки
        ssl_preread on;

        proxy_pass $sni_target_backend;

        proxy_connect_timeout 2s;
        proxy_timeout 15m;
    }
}
```

**Пошаговая валидация и проверка:**

```bash
# 1. Валидация и перезагрузка
angie -t && angie -s reload
# → syntax is ok / reload successful

# 2. Проверка маршрутизации для имени git.corp.internal
openssl s_client -connect 198.51.100.1:443 -servername git.corp.internal -brief
# → CONNECTION ESTABLISHED
# → Сертификат CN: git.corp.internal
# → В логах stream-access.log: upstream_addr равен 192.168.30.15:443

# 3. Проверка маршрутизации для имени s3.corp.internal
openssl s_client -connect 198.51.100.1:443 -servername s3.corp.internal -brief
# → CONNECTION ESTABLISHED
# → Сертификат CN: s3.corp.internal
# → В логах stream-access.log: upstream_addr равен 192.168.30.25:443
```

---

### Сценарий 6: Балансировка кластера брокеров RabbitMQ (AMQP) с защитой от исчерпания памяти

Балансировка постоянных AMQP-сессий между нодами кластера RabbitMQ с жестким ограничением максимального числа соединений (`max_conns`) на узел, предотвращающим перегрузку памяти брокера и падение по OOM.

**Предварительные требования:**
*   Три ноды кластера RabbitMQ: `10.10.5.11:5672`, `10.10.5.12:5672`, `10.10.5.13:5672`.
*   Лимит подключений на узел: не более 500 коннектов.

**Файл конфигурации `/etc/angie/stream.d/rabbitmq_amqp.conf`:**

```nginx
stream {
    # Зона отслеживания количества параллельных соединений с клиентских IP
    limit_conn_zone $binary_remote_addr zone=amqp_clients:10m;

    upstream rabbitmq_cluster {
        zone rmq_zone 128k;
        status_zone rmq_upstreams;

        # Балансировка по наименьшему числу коннектов
        least_conn;

        server 10.10.5.11:5672 max_conns=500 max_fails=3 fail_timeout=10s;
        server 10.10.5.12:5672 max_conns=500 max_fails=3 fail_timeout=10s;
        server 10.10.5.13:5672 max_conns=500 max_fails=3 fail_timeout=10s;
    }

    server {
        listen 10.10.5.100:5672;
        status_zone rmq_frontend;

        proxy_pass rabbitmq_cluster;

        # Лимит не более 100 одновременных AMQP каналов/сессий с одного IP
        limit_conn amqp_clients 100;

        # AMQP-специфичные таймауты
        proxy_connect_timeout 3s;
        proxy_timeout 7200s; # Долгоживущие подключения консьюмеров

        # Ограничение полосы для предотвращения насыщения канала крупными сообщениями
        proxy_download_rate 20m;
        proxy_upload_rate 20m;
    }
}
```

**Пошаговая валидация и проверка:**

```bash
# 1. Валидация и перезагрузка
angie -t && angie -s reload
# → syntax is ok / reload successful

# 2. Проверка распределения активных коннектов через Status API
curl -s http://127.0.0.1:8888/status/stream/upstreams/rabbitmq_cluster/ | jq '.peers[] | {server, active, max_conns}'
# → {
# →   "server": "10.10.5.11:5672",
# →   "active": 45,
# →   "max_conns": 500
# → }
# → {
# →   "server": "10.10.5.12:5672",
# →   "active": 43,
# →   "max_conns": 500
# → }
```

---

### Сценарий 7: Динамическое обнаружение L4-бэкендов через сокет Docker Engine и DNS SRV

Автоматическое добавление и удаление TCP-серверов в upstream при масштабировании контейнеров в локальном Docker Engine на On-Premises сервере, а также динамическое разрешение через DNS SRV-записи.

**Предварительные требования:**
*   Локальный Docker Engine доступен через UNIX-сокет `/var/run/docker.sock`.
*   Пользователь `angie` добавлен в системную группу `docker` (`usermod -aG docker angie`).
*   Локальный DNS-сервер поддерживает SRV-записи (например, Consul или BIND).

**Файл конфигурации `/etc/angie/stream.d/dynamic_discovery.conf`:**

```nginx
stream {
    # Подключение к локальному демону Docker Engine
    docker_endpoint unix:/var/run/docker.sock;

    # DNS-резолвер для разрешения SRV-записей
    resolver 192.168.1.2 192.168.1.3 valid=10s ipv6=off;
    resolver_timeout 2s;

    # Динамический upstream на основе меток Docker
    upstream dynamic_docker_tcp {
        zone docker_stream_zone 128k;
        status_zone docker_stream_upstreams;
        # Upstream наполняется автоматически событиями Docker Engine API
    }

    # Динамический upstream на основе DNS SRV-записей
    upstream dynamic_srv_pool {
        zone srv_stream_zone 128k;
        status_zone srv_stream_upstreams;

        # Разрешение IP и портов через SRV-запись
        server db.service.corp.internal service=_pg._tcp resolve;
    }

    server {
        listen 192.168.1.100:9000;
        status_zone docker_front;
        proxy_pass dynamic_docker_tcp;
        proxy_timeout 60s;
    }

    server {
        listen 192.168.1.100:9001;
        status_zone srv_front;
        proxy_pass dynamic_srv_pool;
        proxy_timeout 60s;
    }
}
```

**Фрагмент `docker-compose.yml` целевого микросервиса:**

```yaml
services:
  worker-node:
    image: internal-registry.corp.internal/worker-tcp:v1.2.0
    deploy:
      replicas: 2
    networks:
      - internal_lan
    labels:
      - "angie.stream.upstreams.dynamic_docker_tcp.port=9000"
      - "angie.stream.upstreams.dynamic_docker_tcp.weight=2"
      - "angie.stream.upstreams.dynamic_docker_tcp.max_conns=100"

networks:
  internal_lan:
    external: true
```

**Пошаговая валидация и проверка:**

```bash
# 1. Запуск контейнеров
docker compose up -d --scale worker-node=3
# → [+] Running 3/3
# → ✔ Container worker-node-1 Started
# → ✔ Container worker-node-2 Started
# → ✔ Container worker-node-3 Started

# 2. Проверка логов Angie на предмет обнаружения новых контейнеров
sudo tail -n 10 /var/log/angie/error.log | grep docker
# → [info] 14205#14205: [docker] connected to Docker daemon via unix:/var/run/docker.sock
# → [info] 14205#14205: [docker] peer 172.20.0.12:9000 added to stream upstream "dynamic_docker_tcp"
# → [info] 14205#14205: [docker] peer 172.20.0.13:9000 added to stream upstream "dynamic_docker_tcp"
# → [info] 14205#14205: [docker] peer 172.20.0.14:9000 added to stream upstream "dynamic_docker_tcp"

# 3. Инспекция пиров через Status API
curl -s http://127.0.0.1:8888/status/stream/upstreams/dynamic_docker_tcp/ | jq '.peers | keys'
# → [
# →   "172.20.0.12:9000",
# →   "172.20.0.13:9000",
# →   "172.20.0.14:9000"
# → ]
```

---

### Сценарий 8: Активный мониторинг бэкендов в Angie PRO и управление через REST API

Использование директивы `upstream_probe` в коммерческой версии Angie PRO для превентивной отправки проверочных зондов на порт базы данных, а также управление состоянием серверов (`drain` и `down`) через HTTP API без reload.

**Предварительные требования:**
*   Установлен Angie PRO 1.12.x с действующей лицензией.
*   Настроен конфигурационный API в блоке `http`.

**Фрагмент конфигурации `/etc/angie/angie.conf` и `/etc/angie/stream.d/pro_stream.conf`:**

```nginx
# В блоке http объявляем конфигурационный API
http {
    server {
        listen 127.0.0.1:8888;

        # Управление конфигурацией через REST API (только локальный доступ)
        location /config/ {
            api /config/;
            api_write on;
        }

        location /status/ {
            status;
        }
    }
}

# В блоке stream настраиваем активные проверки
stream {
    upstream pg_pro_cluster {
        zone pg_pro_zone 128k;
        status_zone pg_pro_upstreams;

        # Файл сохранения состояния бэкендов при перезапуске процесса
        state /var/lib/angie/state/stream_pg.state;

        server 10.20.1.11:5432;
        server 10.20.1.12:5432;
    }

    server {
        listen 10.20.1.100:5432;
        status_zone pg_pro_frontend;
        proxy_pass pg_pro_cluster;

        # Таймаут ожидания зонда
        upstream_probe_timeout 1500ms;

        # Активная проверка доступности порта TCP
        upstream_probe pg_tcp_check
            port=5432
            interval=3s
            fails=2
            passes=2
            mode=always;
    }
}
```

**Пошаговое управление серверами через API:**

```bash
# 1. Проверка текущего статуса активных проверок
curl -s http://127.0.0.1:8888/status/stream/upstreams/pg_pro_cluster/peers | jq '.[] | {server, state, fails: .health.fails}'
# → {
# →   "server": "10.20.1.11:5432",
# →   "state": "up",
# →   "fails": 0
# → }
# → {
# →   "server": "10.20.1.12:5432",
# →   "state": "up",
# →   "fails": 0
# → }

# 2. Плавный вывод сервера 10.20.1.11 на техническое обслуживание (режим Drain)
# Существующие соединения продолжат обслуживаться, новые направляться не будут
curl -X PATCH -d '{"drain": true}' \
  http://127.0.0.1:8888/config/stream/upstreams/pg_pro_cluster/peers/10.20.1.11:5432/
# → HTTP/1.1 200 OK

# 3. Полный вывод узла из балансировки (Down)
curl -X PATCH -d '{"down": true}' \
  http://127.0.0.1:8888/config/stream/upstreams/pg_pro_cluster/peers/10.20.1.11:5432/
# → HTTP/1.1 200 OK

# 4. Динамическое добавление нового узла в runtime без reload
curl -X POST -d '{"server": "10.20.1.13:5432", "weight": 2, "max_conns": 300}' \
  http://127.0.0.1:8888/config/stream/upstreams/pg_pro_cluster/peers/
# → HTTP/1.1 201 Created
```

---

## Операции и команды

### Валидация и управление службой

```bash
# Тестирование синтаксиса полной конфигурации (включая все блоки stream.d/*.conf)
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Безопасная перезагрузка конфигурации без разрыва установленных TCP/UDP сессий
angie -s reload
# → Выполняется fork новых воркеров, старые воркеры дорабатывают существующие сессии

# Принудительная быстрая остановка сервиса
angie -s stop

# Проверка статуса сервиса через systemd
systemctl status angie
# → Active: active (running) since ...

# Потоковый просмотр журналов ошибок уровня stream
journalctl -u angie -f --grep='stream'
```

---

### Сетевая диагностика сокетов и сессий

```bash
# Просмотр всех слушающих TCP сокетов Angie с указанием PID и размера очереди backlog
ss -tlnp | grep angie
# → LISTEN 0 4096 192.168.10.10:5432 0.0.0.0:* users:(("angie",pid=14205,fd=8))

# Просмотр активных клиентских сессий к порту 5432 с группировкой по IP
ss -tnp dst :5432 | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn
# → 45 192.168.1.150
# → 12 192.168.1.151

# Проверка состояния слушающих UDP сокетов
ss -ulnp | grep angie
# → UNCONN 0 0 192.168.1.5:53 0.0.0.0:* users:(("angie",pid=14205,fd=10))

# Диагностика TCP-параметров ядра (retransmits, RTT, cwnd) для сессий Angie
ss -ti 'sport = :5432' | head -n 20
# → rtt:0.25/0.05 retrans:0/1 cwnd:10 ssthresh:7

# Захват первых пакетов для отладки SNI-маршрутизации через tcpdump
tcpdump -i any -nn -s 0 -A 'tcp dst port 443 and (tcp[((tcp[12:1] & 0xf0) >> 2):1] = 0x16)' -c 5
# → Анализ поля server_name в заголовке ClientHello

# Проверка передачи заголовка PROXY Protocol к бэкенду
tcpdump -i any -nn -A 'tcp port 5432 and (tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x50524f58)' -c 1
# → Вывод: PROXY TCP4 192.168.1.150 192.168.10.10 52341 5432\r\n
```

---

### Оперативный сбор метрик через Status API

```bash
# Получение общего списка всех L4-пулов и их текущего состояния
curl -s http://127.0.0.1:8888/status/stream/upstreams/ | jq 'keys'
# → [
# →   "pg_read_pool",
# →   "rabbitmq_cluster",
# →   "redis_backend"
# → ]

# Детальные показатели конкретного пула (активные коннекты, ошибки, трафик)
curl -s http://127.0.0.1:8888/status/stream/upstreams/pg_read_pool/ | jq '.peers[] | {
  server: .server,
  state: .state,
  active: .active,
  max_conns: .max_conns,
  sent_bytes: .data.sent,
  received_bytes: .data.received,
  fails: .fails
}'

# Просмотр статистики слушающего порта (server_zone)
curl -s http://127.0.0.1:8888/status/stream/server_zones/pg_frontend_listener/ | jq '{
  processing: .processing,
  connections: .connections,
  sessions: .sessions,
  data: .data
}'

# Мониторинг зон лимитирования соединений (limit_conn)
curl -s http://127.0.0.1:8888/status/stream/limit_conns/ | jq '.'
```

---

### Мониторинг через экспорт в Prometheus

При наличии строки `prometheus all;` в блоке `http`, Angie нативно отдает L4-метрики по адресу `http://127.0.0.1:8888/p_status`:

```bash
# Сбор метрик L4-потоков для Prometheus
curl -s http://127.0.0.1:8888/p_status | grep -E '^angie_stream_'
# → # HELP angie_stream_server_zone_connections_total Total connections accepted
# → # TYPE angie_stream_server_zone_connections_total counter
# → angie_stream_server_zone_connections_total{server_zone="pg_frontend_listener"} 15420
# → # HELP angie_stream_upstream_peers_active Active connections to upstream peer
# → # TYPE angie_stream_upstream_peers_active gauge
# → angie_stream_upstream_peers_active{upstream="pg_read_pool",peer="192.168.10.21:5432"} 14
# → angie_stream_upstream_peers_active{upstream="pg_read_pool",peer="192.168.10.22:5432"} 11
```

---

## Устранение неисправностей

### 1. Клиент получает "Connection refused" или немедленный сброс (TCP RST)

*   **Симптом:** Клиентские приложения при попытке установить соединение падают с ошибкой `connection refused` или `ECONNRESET`.
*   **Возможные причины:**
    1. Процесс Angie не слушает указанный сокет (ошибка в директиве `listen`, конфликт портов).
    2. Межсетевой экран хоста (`iptables`, `nftables`, `ufw`) сбрасывает входящие SYN-пакеты.
    3. Срабатывание механизма `limit_conn` (превышен лимит одновременных подключений).
    4. Ограничения политик безопасности SELinux/AppArmor на прослушивание нестандартных портов.
*   **Диагностика:**
    ```bash
    # 1. Проверяем, привязан ли сокет к нужному адресу
    ss -tlnp | grep ':5432'
    # Если вывод пуст — порт не слушается. Проверьте правильность IP в listen

    # 2. Проверяем правила файрвола на хосте
    iptables -L -n -v | grep 5432
    # или
    nft list ruleset | grep 5432

    # 3. Проверяем блокировки SELinux
    grep "angie" /var/log/audit/audit.log | grep "denied"
    # Решение: semanage port -a -t http_port_t -p tcp 5432
    ```
*   **Решение:** Убедитесь, что `listen` указывает на корректный локальный IP (или `0.0.0.0`), откройте порт в брандмауэре (`nft add rule inet filter input tcp dport 5432 accept`), увеличьте параметр `limit_conn` при необходимости.

---

### 2. Ошибка "no live upstreams while connecting to upstream"

*   **Симптом:** В логе `/var/log/angie/stream-error.log` фиксируется сообщение:
    `[error] 14205#14205: no live upstreams while connecting to upstream, client: 192.168.1.150, server: 0.0.0.0:5432`.
*   **Возможные причины:**
    1. Все бэкенды в группе `upstream` перешли в состояние `down` из-за превышения порога `max_fails`.
    2. Все серверы достигли лимита соединений `max_conns`, а очередь отсутствует.
    3. Не выделена разделяемая память `zone` (счетчики отказов не синхронизируются, воркер считает серверы упавшими).
*   **Диагностика:**
    ```bash
    # Проверка статуса серверов через Status API
    curl -s http://127.0.0.1:8888/status/stream/upstreams/pg_read_pool/ | jq '.peers[] | {server, state, fails, unavailable}'
    # → { "server": "192.168.10.21:5432", "state": "unavailable", "fails": 3 }
    # → { "server": "192.168.10.22:5432", "state": "unavailable", "fails": 3 }
    ```
*   **Решение:**
    1. Обязательно добавьте директиву `zone <name> 128k;` в блок `upstream`.
    2. Скорректируйте пороги пассивных проверок: увеличьте `fail_timeout=30s` и `max_fails=5`.
    3. Добавьте резервный узел с параметром `backup`.
    4. Проверьте сетевую связность до бэкендов: `nc -zv 192.168.10.21 5432`.

---

### 3. Ошибки и разрывы соединений при использовании PROXY Protocol

*   **Симптом:** База данных или бэкенд разрывает соединение с ошибкой синтаксиса протокола (например, PostgreSQL пишет в лог: `FATAL: invalid frontend message type 80` или `broken header`).
*   **Возможные причины:**
    1. Рассинхронизация настроек: Angie отправляет PROXY Protocol (`proxy_protocol on;`), а бэкенд ожидает сырой TCP-поток (или наоборот).
    2. При приеме трафика от внешнего балансировщика не настроена директива `set_real_ip_from`, из-за чего заголовок расценивается как данные клиента.
*   **Диагностика:**
    ```bash
    # Проверка первых байт трафика, отправляемого в сторону бэкенда
    tcpdump -i eth0 -nn -A -s 128 'dst port 5432 and tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x50524F58'
    # Должен быть виден текстовый заголовок: PROXY TCP4 ...
    ```
*   **Решение:**
    *   Если бэкенд не обучен работать с PROXY Protocol — отключите директиву: `proxy_protocol off;`.
    *   Если на стороне бэкенда используется PgBouncer/PostgreSQL — включите в `postgresql.conf`: `proxy_protocol_networks = '192.168.10.10/32'`.

---

### 4. Дисбаланс распределения соединений при использовании хэширования

*   **Симптом:** При настройке `hash $remote_addr;` один сервер пула утилизирован на 90%, а остальные простаивают.
*   **Возможные причины:**
    1. Клиенты приходят через корпоративный NAT или шлюз, имея один и тот же публичный `$remote_addr`.
    2. Не указана директива `consistent`, из-за чего смена состава пула приводит к лавинообразному перекосу хэш-таблицы.
*   **Диагностика:**
    ```bash
    # Анализ уникальности IP-адресов в логе сессий
    awk '{print $1}' /var/log/angie/stream-access.log | sort | uniq -c | sort -rn | head -n 5
    # Если 95% запросов идут с одного IP — балансировка по $remote_addr неэффективна
    ```
*   **Решение:**
    *   Перейдите на алгоритм `least_conn;`.
    *   Используйте консистентный хэш от комбинации IP и порта: `hash $remote_addr:$remote_port consistent;`.
    *   Принимайте реальный IP через PROXY Protocol от вышестоящего балансировщика: `listen <port> proxy_protocol; set_real_ip_from <CIDR>;`.

---

### 5. Потеря или зависание UDP-датаграмм (DNS, Syslog)

*   **Симптом:** Клиенты жалуются на таймауты DNS (`connection timed out; no servers could be reached`), при этом бэкенд отвечает на запросы.
*   **Возможные причины:**
    1. Не задана или некорректно задана директива `proxy_responses`. Для протоколов типа «запрос-ответ» Angie ожидает неограниченное число пакетов до истечения `proxy_timeout`.
    2. Недостаточный размер кольцевого буфера UDP.
*   **Диагностика:**
    ```bash
    # Мониторинг счетчиков ошибок UDP в Status API
    curl -s http://127.0.0.1:8888/status/stream/upstreams/internal_dns_servers/ | jq '.peers[] | {requests, responses, fails}'
    ```
*   **Решение:**
    *   Для DNS строго указывайте `proxy_responses 1;` и короткий таймаут `proxy_timeout 2s;`.
    *   Для потокового UDP (Syslog/NetFlow) выставляйте `proxy_responses 0;`.

---

### 6. Высокий уровень сокетов в состоянии TIME_WAIT и исчерпание портов

*   **Симптом:** Ошибки в логе `[crit] 14205#14205: connect() to 192.168.10.21:5432 failed (99: Cannot assign requested address)`.
*   **Возможные причины:** При высокой частоте короткоживущих L4-сессий балансировщик исчерпывает эфемерные порты для соединения с бэкендами. Сокеты удерживаются ядром в состоянии `TIME_WAIT` (по умолчанию 60 секунд).
*   **Диагностика:**
    ```bash
    # Подсчет количества сокетов в TIME_WAIT
    ss -tan | grep TIME-WAIT | wc -l
    # Если значение приближается к 30000–60000 — налицо истощение портов
    ```
*   **Решение:** Настройте параметры сетевого стека ядра Linux в `/etc/sysctl.d/99-angie-stream.conf`:
    ```ini
    net.ipv4.tcp_tw_reuse = 1
    net.ipv4.ip_local_port_range = 1024 65535
    net.ipv4.tcp_fin_timeout = 15
    ```

---

## Лучшие практики

### Оптимизация параметров ядра Linux (sysctl) под L4

Для обеспечения стабильной работы балансировщика при нагрузках свыше 50 000 параллельных сессий создайте файл конфигурации `/etc/sysctl.d/99-angie-l4.conf` и примените параметры:

```ini
# Максимальный размер очереди не полностью установленных соединений (SYN-пакеты)
net.ipv4.tcp_max_syn_backlog = 65536

# Максимальный размер очереди сокетов listen (SOMAXCONN)
net.core.somaxconn = 65536

# Диапазон локальных эфемерных портов для соединений с бэкендами
net.ipv4.ip_local_port_range = 1024 65535

# Повторное использование сокетов в состоянии TIME_WAIT для исходящих коннектов
net.ipv4.tcp_tw_reuse = 1

# Время удержания закрываемого сокета в состоянии FIN-WAIT-2
net.ipv4.tcp_fin_timeout = 15

# Максимальное количество сокетов, находящихся в TIME_WAIT одновременно
net.ipv4.tcp_max_tw_buckets = 262144

# Увеличение максимального лимита открытых файловых дескрипторов в системе
fs.file-max = 2097152

# Разрешение привязки к нелокальным IP (полезно при VRRP/Keepalived)
net.ipv4.ip_nonlocal_bind = 1
```

Применение изменений без перезагрузки:
```bash
sudo sysctl --system
# → * Applying /etc/sysctl.d/99-angie-l4.conf ...
```

В файле `/etc/security/limits.d/angie.conf` зафиксируйте лимиты дескрипторов:
```ini
angie soft nofile 1048576
angie hard nofile 1048576
```

---

### Расчет размера разделяемой памяти (Sizing)

Отсутствие или недостаточный размер директивы `zone` приводит к отказу динамических модулей и падению балансировки.

**Формула расчета:**
$$\text{RAM}_{\text{zone}} = 32\text{ КБ (базовые метаданные)} + (\text{Число серверов} \times 1\text{ КБ})$$

*   `64k`: достаточно для статических групп до 30 серверов.
*   `128k`: рекомендуется для кластеров до 100 бэкендов с включенными `status_zone` и `slow_start`.
*   `1m`–`4m`: обязательно при динамическом обнаружении через Docker API на тысячи контейнеров.

Для зон ограничения соединений (`limit_conn_zone`):
*   Каждое отслеживаемое состояние IPv4-адреса занимает 64 байта в памяти (`$binary_remote_addr`).
*   Зона размером `10m` способна одновременно отслеживать около 160 000 уникальных активных клиентских IP.

---

### Безопасность и изоляция

1.  **Ограничение сетевого доступа:**
    Всегда закрывайте доступ к служебным портам баз данных на внешних интерфейсах с помощью директив `allow` и `deny`.
2.  **Защита сокета Docker:**
    Права на `/var/run/docker.sock` должны быть строго ограничены (`chmod 660 /var/run/docker.sock`). Не запускайте воркеры Angie от пользователя `root`.
3.  **Изоляция Status API:**
    Блок мониторинга `/status/` и конфигурационный API `/config/` должны слушать исключительно локальный адрес `127.0.0.1` или закрытый Management VLAN с авторизацией.
4.  **Валидация источников PROXY Protocol:**
    При использовании `listen ... proxy_protocol;` обязательно объявляйте `set_real_ip_from` только для доверенных IP вышестоящих балансировщиков. В противном случае злоумышленник сможет подделать IP в заголовке соединения.

---

### Эксплуатационные стандарты и SRE

1.  **Информативное логирование сессий:**
    Всегда включайте в `log_format` параметры длительности `$session_time`, времени соединения `$upstream_connect_time`, объема переданных данных `$bytes_sent` / `$bytes_received` и статус `$status`. Это позволяет строить квантили сетевых задержек (p95/p99) в Grafana.
2.  **Плавный ввод серверов в строй:**
    Для тяжелых СУБД (PostgreSQL, ClickHouse) используйте параметр `slow_start=30s`–`60s`. Это исключает лавинообразную перегрузку сервера сразу после его возврата в строй при непрогретых кэшах shared buffers.
3.  **Graceful Reload:**
    Никогда не используйте `systemctl restart angie` в рабочее время для изменения конфигураций. Команда `angie -s reload` сохраняет открытыми долгоживущие транзакции баз данных и AMQP-очередей.

---

### Архитектурные ограничения модуля stream

*   **Отсутствие контекста `location`:** Вся логика L4 настраивается строго в рамках директив `server` и `upstream`.
*   **Невозможность инспекции тела запроса:** Модуль не может фильтровать SQL-запросы, заголовки HTTP или тело gRPC.
*   **Имена статус-зон:** Значение `status_zone` обязано быть статической строкой; использование переменных не допускается синтаксисом сервера.

---

## Дополнительная информация

### Ссылки на связанные разделы базы знаний

*   [Обзор архитектуры Angie](./angie_overview.md) — общие принципы архитектуры, структура мастер-процесса и воркеров.
*   [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md) — принципы и механизмы балансировки на прикладном уровне (L7).
*   [Динамические группы проксируемых серверов в Angie](./dynamic_upstreams.md) — детальная настройка Service Discovery для upstream.
*   [Мониторинг Angie: концепции](./angie_monitoring/angie_monitoring_concepts.md) — устройство статус-зон, агрегация метрик и сбор телеметрии.
*   [Мониторинг Angie — возможности Angie PRO](./angie_monitoring/angie_monitoring_pro.md) — директива `upstream_probe` и управление через `api /config/;`.
*   [Балансировка и проксирование L4 в Nginx](../Nginx/Proxy/nginx_l4_proxying.md) — базовая специфика модуля stream классического Nginx.
*   [Proxy Protocol](../../Networking/Protocols/proxy_protocol.md) — детальное описание структуры заголовков v1 и v2, сценарии интеграции.

### Официальные источники

*   Документация Angie: [Модуль ngx_stream_core_module](https://angie.software/ru/configuration/stream/)
*   Документация Angie: [Модуль ngx_stream_upstream_module](https://angie.software/ru/configuration/stream_upstream/)
*   Документация Angie: [Модуль ngx_stream_proxy_module](https://angie.software/ru/configuration/stream_proxy/)
*   Документация Angie: [Модуль ngx_stream_mqtt_preread_module](https://angie.software/ru/configuration/stream_mqtt_preread/)
*   Документация Angie: [Модуль ngx_stream_status_zone_module](https://angie.software/ru/configuration/stream_status_zone/)
