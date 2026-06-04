# Балансировка и проксирование L4-трафика (TCP/UDP) в Nginx

## Определения

**Модуль stream в Nginx** — расширение функциональности Nginx, предоставляющее возможности для балансировки нагрузки и проксирования трафика на транспортном уровне (L4). Позволяет работать с протоколами, не основанными на HTTP: базами данных (MySQL, PostgreSQL), DNS, NTP, SSH и другими.

**L4 vs L7 проксирование**:

- **L4 (Transport layer)**: Модуль stream работает на уровне транспорта (TCP/UDP), проксируя соединения без разбора содержимого.
- **L7 (Application layer)**: Nginx работает с HTTP-трафиком в контексте http, обрабатывая запросы на уровне приложения.

## Основные концепции

### Сравнение L4 и L7 проксирования

Ключевые отличия L4-проксирования от L7:

- Уровень работы: L4 (TCP/UDP) вместо L7 (HTTP/S).
- Протоколы: любые TCP/UDP-протоколы (базы данных, DNS, NTP, SSH).
- Обработка: сессии подключения вместо отдельных запросов.
- Ресурсы: меньше накладных расходов, так как не требуется разбор протокола приложения.

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

**Переменные для логирования:**

- `$remote_addr` — IP-адрес клиента.
- `$time_local` — локальное время.
- `$protocol` — используемый протокол (TCP/UDP).
- `$status` — статус сессии.
- `$bytes_sent` — количество отправленных байтов.
- `$bytes_received` — количество полученных байтов.
- `$session_time` — продолжительность сессии.
- `$upstream_addr` — адрес upstream-сервера.

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

### Проксирование MySQL (TCP) с балансировкой master/slave

Сценарий распределения нагрузки между master-сервером БД (для записи) и slave-серверами (для чтения).

**Пример конфигурации (/etc/nginx/stream.d/mysql.conf):**

```nginx
# Группа для мастера (запись)
upstream mysql_master {
    zone mysql_master_zone 64k;
    server 192.168.77.14:3307 proxy_protocol;
}

# Группа для слейвов (чтение)
upstream mysql_slave {
    zone mysql_slave_zone 64k;
    server 192.168.77.12:3308 proxy_protocol;
    server 192.168.77.13:3309 proxy_protocol;
}

# Виртуальный сервер для мастера
server {
    listen 6306;
    proxy_pass mysql_master;

    # Ограничение подключений для защиты мастера
    limit_conn_zone $binary_remote_addr zone=per_ip_conn:10m;
    limit_conn per_ip_conn 10;

    access_log /var/log/nginx/mysql-master-access.log basic;
    error_log /var/log/nginx/mysql-master-error.log warn;
    status_zone mysql_master_status;
}

# Виртуальный сервер для слейвов
server {
    listen 6307;
    proxy_pass mysql_slave;
    status_zone mysql_slave_status;
}
```

**Разбор конфигурации:**

1. **Блоки upstream**:
   - `zone <name> 64k;` — выделяет общую память для хранения состояния группы (статистика соединений, динамическое управление).
   - `server ... proxy_protocol;` — включает [Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md), который добавляет к TCP-соединению заголовок с реальным IP-адресом клиента.

2. **Блоки server**:
   - `listen 6306;` — виртуальный TCP-сервер на порту 6306.
   - `proxy_pass mysql_master;` — направление трафика в upstream-группу mysql_master.
   - `limit_conn_*` — ограничение одновременных соединений с одного IP.
   - `status_zone <name>;` — зона статистики для мониторинга через API Nginx.

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

Функция SSL Pre-read позволяет Nginx анализировать начало TCP-соединения и определять тип трафика без полной терминации сессии.

**Пример: мультиплексирование HTTPS и SSH на порту 443**

```nginx
# /etc/nginx/stream.d/ssl_preread.conf
map $ssl_preread_server_name $backend_by_sni {
    hostnames;
    default         ssh_backend;
    www.example.com http_backend;
}

upstream http_backend {
    server 127.0.0.1:8080;
}
upstream ssh_backend {
    server 127.0.0.1:22;
}

server {
    listen 443;

    ssl_preread on; # Включаем анализ Client Hello
    proxy_pass $backend_by_sni;

    status_zone ssl_preread_status;
}
```

**Особенности:**

- **map** — определяет `$backend_by_sni` на основе SNI (`$ssl_preread_server_name`). Если SNI отсутствует (например, SSH), используется значение `default`.
- **listen 443** — без флага `ssl`, так как Nginx не терминирует соединение самостоятельно.
- **ssl_preread on** — включает анализ Client Hello.
- **proxy_pass $backend_by_sni** — динамическое проксирование на основе переменной.

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

    proxy_pass dns_servers;
}
```

**Особенности:**

- **listen ... udp** — указывает на прослушивание UDP-трафика.
- **proxy_responses 1** — предотвращает бесконечное удержание сессии для UDP.

## Дополнительная информация

### Мониторинг L4-трафика

Для сбора метрик используется `status_zone` в блоке `server` модуля `stream`.

```nginx
stream {
    server {
        listen 12345;
        proxy_pass backend_service;
        status_zone my_l4_service; # Зона для сбора метрик
    }
}
```

Метрики (активные соединения, трафик и т.д.) доступны через API Nginx (модуль `ngx_http_stub_status_module` или NGINX Plus API).

### Связанные документы

- [Основы Nginx](../Core/nginx_overview.md)
- [Конфигурация Nginx](../Core/nginx_setup.md)
- [Прокси-сервер — концепции](../../../Networking/Concepts/proxy.md)
