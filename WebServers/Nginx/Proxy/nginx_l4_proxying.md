# Балансировка и проксирование L4-трафика (TCP/UDP) в Nginx

## Определения

**Модуль stream в Nginx** — расширение функциональности Nginx, предоставляющее возможности для балансировки нагрузки и проксирования трафика на транспортном уровне (L4). Позволяет работать с протоколами, не основанными на HTTP: базами данных (MySQL, PostgreSQL), DNS, NTP, SSH и другими.

**L4 vs L7 проксирование**:

- **L4 (Transport layer)**: Модуль stream работает на уровне транспорта (TCP/UDP), проксируя соединения без разбора содержимого (до версии 1.25.5).
- **L7 (Application layer)**: Nginx работает с HTTP-трафиком в контексте http, обрабатывая запросы на уровне приложения.

*Примечание:* Начиная с версии 1.25.5, модуль stream поддерживает директиву `server_name`, что позволяет выполнять маршрутизацию на основе SNI (Server Name Indication) для TLS-трафика, сближая возможности L4 и L7.

## Основные концепции

### Сравнение L4 и L7 проксирования

Ключевые отличия L4-проксирования от L7:

- **Уровень работы**: L4 (TCP/UDP) вместо L7 (HTTP/S).
- **Протоколы**: любые TCP/UDP-протоколы (базы данных, DNS, NTP, SSH).
- **Обработка**: сессии подключения вместо отдельных запросов.
- **Ресурсы**: меньше накладных расходов на CPU/RAM, так как не требуется разбор протокола приложения (headers, cookies).
- **Видимость**: на уровне L4 Nginx не видит URL, заголовки и Cookies (если не используется SNI).

### Конфигурация и основные директивы

Для использования L4-функциональности в [`nginx.conf`](../Core/nginx_setup.md#структура-конфигурации) должен присутствовать блок `stream`.

```nginx
# /etc/nginx/nginx.conf
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time "$upstream_addr"';

    access_log /var/log/nginx/stream-access.log basic;

    # Включение конфигураций из stream.d
    include /etc/nginx/stream.d/*.conf;
}
```

### Логирование в модуле stream

По умолчанию логирование в модуле `stream` отключено. Настраивается через директиву `access_log`. В данном режиме фиксируются параметры сессии, а не отдельных запросов.

**Ключевые переменные:**

- `$remote_addr` / `$remote_port` — IP-адрес и порт клиента.
- `$time_local` — локальное время.
- `$protocol` — используемый протокол (TCP/UDP).
- `$status` — статус сессии (например, 200 — успешно, 403 — доступ запрещен, 500 — внутренняя ошибка).
- `$bytes_sent` / `$bytes_received` — количество отправленных/полученных байтов.
- `$session_time` — продолжительность сессии в секундах с точностью до миллисекунд.
- `$upstream_addr` — адрес выбранного upstream-сервера.
- `$upstream_connect_time` — время установления соединения с бэкендом.
- `$upstream_first_byte_time` — время до получения первого байта данных от бэкенда.
- `$ssl_preread_server_name` — имя сервера из SNI (требует `ssl_preread on`).
- `$ssl_preread_protocol` — самая высокая версия протокола SSL/TLS, поддерживаемая клиентом.
- `$ssl_preread_alpn_protocols` — список протоколов ALPN, присланных клиентом.

### Безопасность и контроль доступа

В модуле `stream` доступны стандартные механизмы ограничения доступа по IP-адресам, аналогичные модулю `http`.

```nginx
server {
    listen 12345;
    
    # Разрешить доступ только из локальной сети
    allow 192.168.1.0/24;
    allow 10.0.0.0/8;
    deny all;
    
    proxy_pass backend_service;
}
```

### Оптимизация производительности

Для высоконагруженных L4-сервисов (например, прокси для баз данных) критически важна минимальная задержка и эффективное использование ресурсов.

**Директивы оптимизации:**

- `tcp_nodelay on;` — (по умолчанию `on`) отключает алгоритм Нагла. Критично для интерактивных протоколов и БД.
- `proxy_buffer_size <size>;` — задает размер буфера для чтения данных. Значение по умолчанию (обычно 16k) часто достаточно, но для тяжелых сессий может быть увеличено.
- `proxy_download_rate` / `proxy_upload_rate` — ограничение скорости передачи данных на уровне сессии.
- `proxy_bind <address> [transparent];` — привязка исходящих соединений к конкретному IP-адресу. Параметр `transparent` позволяет бэкенду видеть IP клиента (требует настройки маршрутизации на уровне ОС).
- `proxy_requests <number>;` — (UDP) задает количество клиентских запросов, после которых сессия будет закрыта.
- `listen ... deferred;` — (Linux) включает `TCP_DEFER_ACCEPT`, ядро передает сокет Nginx только после поступления данных.
- `worker_processes auto;` — масштабирование на все ядра CPU.

### Ограничение подключений

В контексте `stream` можно ограничивать количество одновременных подключений (`limit_conn`), но нельзя ограничить частоту запросов (`limit_req`), так как на этом уровне понятие HTTP-запроса отсутствует.

```nginx
stream {
    limit_conn_zone $binary_remote_addr zone=per_ip:10m;

    server {
        listen 12345;
        limit_conn per_ip 10; # До 10 подключений с одного IP
        proxy_pass backend_service;
    }
}
```

## Практические сценарии

### Проксирование MySQL (TCP) с балансировкой Master/Slave и проверками состояния

Сценарий распределения нагрузки между master-сервером БД (для записи) и slave-серверами (для чтения).

**Пример конфигурации (/etc/nginx/stream.d/mysql.conf):**

```nginx
# Группа для мастера (запись)
upstream mysql_master {
    server 192.168.77.14:3306 max_fails=3 fail_timeout=30s;
}

# Группа для слейвов (чтение)
upstream mysql_slave {
    zone mysql_slave_zone 64k; # Разделяемая память для хранения состояния (доступно в OSS)
    server 192.168.77.12:3306 max_fails=3 fail_timeout=30s;
    server 192.168.77.13:3306 max_fails=3 fail_timeout=30s;
}

# Сервер для записи (Master)
server {
    listen 6306;
    proxy_pass mysql_master;
    proxy_connect_timeout 1s;
    proxy_timeout 1h;

    # Ограничение подключений для защиты мастера
    limit_conn_zone $binary_remote_addr zone=per_ip_master:10m;
    limit_conn per_ip_master 5;
}

# Сервер для чтения (Slaves)
server {
    listen 6307;
    proxy_pass mysql_slave;
    proxy_connect_timeout 5s;
    proxy_timeout 1h;
}
```

**Разбор конфигурации:**

1. **Таймауты**:
   - `proxy_connect_timeout` — время ожидания установления TCP-соединения с бэкендом (по умолчанию `60s`).
   - `proxy_timeout` — время между двумя операциями чтения или записи (по умолчанию `10m`). Если данных нет дольше этого времени, соединение закрывается. Для БД и SSH важно ставить большие значения (часы), чтобы избежать обрыва длинных сессий.
2. **Health Checks**:
   - **Пассивные проверки (OSS)**: Nginx отслеживает ошибки соединения. Если сервер не отвечает `max_fails` раз в течение `fail_timeout`, он помечается как недоступный.
   - **Активные проверки (Nginx Plus / Angie)**: Nginx сам отправляет периодические запросы («пробы») к бэкендам через директиву `health_check`.
3. **Ограничения**:
   - `limit_conn` предотвращает исчерпание пула соединений БД одним клиентом.

### Маршрутизация на основе SNI и ALPN (Nginx 1.25.5+)

С версии 1.25.5 Nginx поддерживает виртуальные серверы в модуле `stream` через SNI. Также можно использовать переменные `ssl_preread` для сложной маршрутизации через `map`.

```nginx
stream {
    ssl_preread on;

    # Маршрутизация по протоколу (ALPN)
    map $ssl_preread_alpn_protocols $backend_pool {
        "h2"      http2_backend;
        "http/1.1" http1_backend;
        default    generic_backend;
    }

    server {
        listen 443;
        server_name db.example.com; # Прямая поддержка SNI
        proxy_pass db_backend;
    }

    server {
        listen 443;
        proxy_pass $backend_pool;
    }
}
```

Это позволяет использовать один IP и порт 443 для проксирования разных TCP-сервисов, разделяя их по доменному имени или версии протокола.

### Передача соединения между модулями (pass)

Модуль `ngx_stream_pass_module` позволяет передать принятое соединение в другой модуль (http, mail) напрямую. Это эффективнее, чем `proxy_pass` на локальный адрес.

```nginx
stream {
    server {
        listen 443 ssl;
        ssl_certificate /etc/nginx/certs/server.crt;
        ssl_certificate_key /etc/nginx/certs/server.key;

        # Передача расшифрованного трафика в HTTP-модуль
        pass 127.0.0.1:8000;
    }
}

http {
    server {
        listen 127.0.0.1:8000;
        location / {
            return 200 "Hello from HTTP via Stream pass!";
        }
    }
}
```

### SSL/TLS терминация на L4

Nginx принимает зашифрованные соединения, расшифровывает их и проксирует трафик в открытом виде на бэкенд.

```nginx
# /etc/nginx/stream.d/ssl_termination.conf
upstream web_backend {
    server 127.0.0.1:9001;
}

server {
    listen 9443 ssl;
    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;
    proxy_pass web_backend; # Проксирование на незашифрованный бэкенд
}
```

Подробнее: [SSL/TLS в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md).

### Передача в HTTP-модуль

Расшифрованный трафик передается в контекст http для L7-обработки.

```nginx
# /etc/nginx/nginx.conf — http-контекст
http {
    server {
        listen 127.0.0.1:8000; # Только локально
        # ... обработка HTTP-запроса
    }
}

# /etc/nginx/stream.d/ssl_pass.conf — stream-контекст
server {
    listen 9444 ssl;
    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;

    # Передача расшифрованного соединения в http-модуль
    proxy_pass 127.0.0.1:8000;
}
```

Модуль stream эффективен для терминации TLS, в то время как http — для глубокой L7-обработки.

### SSL Pre-read (маршрутизация TLS vs SSH)

Функция SSL Pre-read позволяет Nginx анализировать начало TCP-соединения (Client Hello) и определять тип трафика или имя сервера (SNI) без терминации SSL.

**Пример: мультиплексирование HTTPS и SSH на порту 443**

```nginx
# /etc/nginx/stream.d/ssl_preread.conf
map $ssl_preread_server_name $backend_by_sni {
    hostnames;
    default         ssh_backend;
    www.example.com http_backend;
}

upstream http_backend { server 127.0.0.1:8080; }
upstream ssh_backend { server 127.0.0.1:22; }

server {
    listen 443;
    ssl_preread on; # Включаем анализ Client Hello
    proxy_pass $backend_by_sni;
}
```

*Примечание:* В современных версиях Nginx для SNI-маршрутизации TLS-трафика предпочтительнее использовать директиву `server_name` внутри блоков `server`, однако `map` по-прежнему необходим для мультиплексирования разных протоколов (например, SSH vs TLS).

### Использование Proxy Protocol

Proxy Protocol передает исходный IP клиента через прокси к бэкенду. Подробнее о протоколе: [Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md).

```nginx
# Фронтенд-балансировщик
server {
    listen 982;
    proxy_pass 127.0.0.1:820 proxy_protocol; # Добавляем заголовок Proxy Protocol
}

# Бэкенд-сервер (другой Nginx)
server {
    listen 820 proxy_protocol; # Ожидание заголовка Proxy Protocol

    set_real_ip_from 127.0.0.0/8; # Доверенные IP прокси
    real_ip_header proxy_protocol; # Извлечение реального IP

    access_log /var/log/nginx/proxy-protocol-access.log basic;
}
```

### Проксирование UDP (DNS)

Nginx может проксировать UDP-трафик, например для DNS-серверов.

```nginx
# /etc/nginx/stream.d/udp_dns.conf
upstream dns_servers {
    zone dns_upstreams 64k;
    server 8.8.8.8:53;
    server 1.1.1.1:53;
}

server {
    listen 53 udp; # UDP-порт
    listen 53;     # TCP-порт (DNS использует оба)

    proxy_responses 1; # Ожидание одного ответа от бэкенда
    proxy_timeout 3s;  # Для UDP важно ставить небольшие таймауты

    proxy_pass dns_servers;
}
```

**Особенности:**

- **listen ... udp** — указывает на прослушивание UDP-трафика.
- **proxy_responses <number>** — задает количество ожидаемых ответов от бэкенда перед закрытием UDP-сессии (по умолчанию 0 — количество ответов не ограничено до истечения таймаута).
- **proxy_requests <number>** — задает количество запросов от клиента, после которых сессия закрывается.
- **proxy_timeout** — для UDP определяет время ожидания ответа; если бэкенд не ответил вовремя, сессия закрывается.

## Дополнительная информация

### Мониторинг L4-трафика

Для сбора метрик в модуле `stream` используется директива `status_zone`.

- **Nginx OSS**: Не поддерживает `status_zone` и встроенный API для метрик. Требуется использование сторонних модулей (например, `nginx-module-vts`) или анализ логов.
- **Nginx Plus / Angie**: Поддерживают `status_zone` для сбора детальной статистики (соединения, байты, ошибки) по каждому виртуальному серверу и upstream-группе. Данные доступны через REST API.

```nginx
server {
    listen 12345;
    proxy_pass backend_service;
    status_zone my_l4_service; # Только Plus / Angie
}
```

### Связанные документы

- [Основы Nginx](../Core/nginx_overview.md)
- [Конфигурация Nginx](../Core/nginx_setup.md)
- [Балансировка и проксирование L4 в Angie](../../Angie/l4_balancing_and_proxying.md)
- [Прокси-сервер — концепции](../../../Networking/Concepts/proxy.md)
