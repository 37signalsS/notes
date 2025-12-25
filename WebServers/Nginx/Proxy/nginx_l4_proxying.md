# Балансировка и проксирование L4-трафика ([TCP](../../../Networking/Protocols/tcp.md)/[UDP](../../../Networking/Protocols/udp.md)) в Nginx

## 1. Определения и базовые концепции

Nginx, помимо работы с [HTTP (L7)](nginx_load_balancing.md), предоставляет мощные возможности для балансировки нагрузки и проксирования трафика на **уровне L4 (TCP/UDP)** через модуль `stream`. Это позволяет работать с различными протоколами, которые не основаны на HTTP, такими как базы данных ([MySQL](../../../Databases/mysql.md), [PostgreSQL](../../../Databases/PostgreSQL/overview.md)), [DNS](../../../Networking/Protocols/dns.md), NTP и др.

### L4 против L7 проксирования

Традиционно NGINX используется для работы с HTTP-трафиком (L7), где конфигурация находится в контексте `http` и позволяет работать с запросами на уровне приложения. Однако модуль `stream` позволяет работать на уровне транспорта ([TCP](../../../Networking/Protocols/tcp.md)/[UDP](../../../Networking/Protocols/udp.md))), что открывает возможности для проксирования любых протоколов, не ограничиваясь HTTP/HTTPS.

Такой подход требует значительно меньше ресурсов, так как балансировщику не нужно разбирать протокол уровня приложения, что позволяет пропускать через себя больше трафика.

### Отличия модуля `stream` от `http`:

*   **Уровень работы:** L4 (TCP/UDP) вместо L7 (HTTP/S).
*   **Протоколы:** Поддержка любых [TCP](../../../Networking/Protocols/tcp.md)/[UDP](../../../Networking/Protocols/udp.md) протоколов (базы данных, [DNS](../../../Networking/Protocols/dns.md), NTP, [SSH](../../../Linux/Security/ssh/ssh_overview.md) и т.д.).
*   **Обработка трафика:** Работа с сессиями подключения, а не с отдельными запросами.
*   **Ограничения:** Меньше возможностей для глубокой инспекции трафика по сравнению с L7, но достаточная гибкость для маршрутизации на основе данных сессии.

---
## 2. Конфигурация и основные директивы

Для использования L4-функциональности необходимо, чтобы в главном конфигурационном файле [`nginx.conf`](../Core/nginx_setup.md#структура-конфигурации) присутствовал блок `stream`.

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

### Логирование в `stream`

По умолчанию логирование в модуле `stream` отключено. Его можно настроить с помощью директивы `access_log`. Логирование будет отличаться от HTTP, так как фиксируются параметры сессии, а не запросов.

**Пример переменных для логирования:**

*   `$remote_addr`: IP-адрес клиента.
*   `$time_local`: Локальное время.
*   `$protocol`: Используемый протокол (TCP/UDP).
*   `$status`: Статус сессии.
*   `$bytes_sent`: Количество отправленных байт.
*   `$bytes_received`: Количество полученных байт.
*   `$session_time`: Продолжительность сессии.
*   `$upstream_addr`: Адрес вышестоящего сервера.

### Ограничение подключений

В `stream` можно ограничивать количество одновременных подключений (`limit_conn`), но не частоту запросов (`limit_req`), так как понятия запроса нет.

```nginx
stream {
    limit_conn_zone $binary_remote_addr zone=per_ip:10m;

    server {
        listen 12345;
        limit_conn per_ip 10; # Ограничение до 10 подключений с одного IP
        proxy_pass backend_service;
    }
}
```

---

## 3. Практические сценарии

### 3.1. Проксирование [MySQL](../../../Databases/mysql.md) ([TCP](../../../Networking/Protocols/tcp.md))

Nginx может распределять нагрузку между master и slave-серверами базы данных.

```nginx
# /etc/nginx/stream.d/mysql.conf
upstream mysql_master {
    zone mysql_master_zone 64k;
    server 127.0.0.1:3307; # Пример: Master-сервер
}

upstream mysql_slave {
    zone mysql_slave_zone 64k;
    server 127.0.0.1:3308; # Пример: Slave-сервер 1
    # server 127.0.0.1:3309; # Пример: Slave-сервер 2
}

server {
    listen 6306; # Порт для Master
    proxy_pass mysql_master;
    limit_conn_zone $binary_remote_addr zone=per_ip_conn:10m;
    limit_conn per_ip_conn 10; # Ограничение подключений
    access_log /var/log/nginx/mysql-master-access.log basic;
    error_log /var/log/nginx/mysql-master-error.log warn;
    # allow 192.168.1.0/24;
    # deny all;
    status_zone mysql_master_status; # Для мониторинга
}

server {
    listen 6307; # Порт для Slave
    proxy_pass mysql_slave;
    status_zone mysql_slave_status;
}
```

**Особенности:**
*   **`upstream`:** Определяет именованную группу ([`upstream`](nginx_load_balancing.md)) серверов, как и при [балансировке L7-трафика](nginx_load_balancing.md).
*   **`zone`:** Создает зону разделяемой памяти для хранения статуса upstream-серверов и мониторинга.
*   **Балансировка:** Поддерживаются все методы, доступные в `http`, кроме `ip_hash`.
*   **Управление доступом:** Директивы `allow` и `deny` позволяют контролировать доступ по IP-адресам.

### 3.2. [SSL/TLS терминация](../Security/nginx_tls_ssl_configuration.md) на L4

Nginx может выступать в роли SSL-терминатора, принимая зашифрованные соединения, расшифровывая их и затем проксируя трафик дальше в открытом виде.

```nginx
# /etc/nginx/stream.d/ssl_termination.conf
upstream web_backend {
    server 127.0.0.1:9001;
}

server {
    listen 9443 ssl; # Прослушивание порта с SSL
    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;
    proxy_pass web_backend; # Проксирование на незашифрованный бэкенд
}
```

### Передача в HTTP-модуль

Особенно мощной является возможность передать расшифрованный трафик напрямую в `http` контекст самого Nginx для дальнейшей обработки.

```nginx
# /etc/nginx/nginx.conf
# В http-контексте создается сервер, слушающий на внутреннем сокете
http {
    # ...
    server {
        listen 127.0.0.1:8000; # Слушает только локально
        # ... здесь обычная обработка HTTP-запроса
    }
}

# /etc/nginx/stream.d/ssl_pass.conf
# В stream-контексте
server {
    listen 9444 ssl;
    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;
    
    # Передача расшифрованного соединения в http-модуль
    proxy_pass 127.0.0.1:8000;
}
```
Эта связка позволяет использовать `stream` для эффективной терминации TLS, а `http` — для всей мощи L7-обработки.

### 3.3. SSL Pre-read (маршрутизация TLS vs SSH)

Функция SSL Pre-read позволяет Nginx "заглянуть" в начало входящего TCP-соединения, чтобы определить, используется ли TLS, без полной терминации сессии. Это позволяет маршрутизировать разный трафик, приходящий на один порт.

Классический пример — мультиплексирование HTTPS и [SSH](../../../Linux/Security/ssh/ssh_overview.md) на одном порту (443).

```nginx
# /etc/nginx/stream.d/ssl_preread.conf
map $ssl_preread_server_name $backend_by_sni {
    hostnames;
    default         ssh_backend; # По умолчанию отправляем на SSH
    www.example.com http_backend;  # Если SNI совпал, на HTTP
}

upstream http_backend {
    server 127.0.0.1:8080;
}
upstream ssh_backend {
    server 127.0.0.1:22;
}

server {
    listen 443;
    
    # Включаем "подглядывание" в соединение
    ssl_preread on;
    
    # Проксируем на основе переменной, определенной в map
    proxy_pass $backend_by_sni;
    
    status_zone ssl_preread_status;
}
```

**Особенности:**

*   **[`map`](../Core/nginx_rewrite_rules_and_try_files.md#директива-map):** Создает переменную `$backend_by_sni` на основе значения другой переменной. В данном случае, значение (имя апстрима) зависит от имени сервера, переданного в TLS SNI (`$ssl_preread_server_name`). Если клиент не передает SNI (как в случае с SSH), используется значение `default`.
*   **`listen 443;`**: Обратите внимание, что флаг `ssl` не используется, так как Nginx не терминирует соединение.
*   **`ssl_preread on;`:** Включает "подглядывание" в Client Hello.
*   **`proxy_pass $backend_by_sni;`:** Динамическое проксирование на основе результата `map`.

### 3.4. Использование [Proxy Protocol](../../../Networking/Concepts/proxy.md)

Proxy Protocol позволяет передавать исходный IP-адрес клиента через прокси-сервер к бэкенду, что критически важно для корректного логирования и работы приложений.

```nginx
# Фронтенд-балансировщик
server {
    listen 982;
    # Добавляем заголовок Proxy Protocol перед отправкой на бэкенд
    proxy_pass 127.0.0.1:820 proxy_protocol;
}

# Бэкенд-сервер (может быть другим Nginx)
server {
    # Указываем, что на этом порту ожидается заголовок Proxy Protocol
    listen 820 proxy_protocol;
    
    # Указываем доверенные IP-адреса прокси
    set_real_ip_from 127.0.0.1/8;
    
    # Указываем, что реальный IP нужно брать из заголовка Proxy Protocol
    real_ip_header proxy_protocol;
    
    access_log /var/log/nginx/proxy-protocol-access.log basic;
    
    # ... дальнейшая обработка
}
```

### 3.5. Проксирование UDP [DNS](../../../Networking/Protocols/dns.md)

Nginx может проксировать UDP-трафик, например, для DNS-серверов.

```nginx
# /etc/nginx/stream.d/udp_dns.conf
upstream dns_servers {
    zone dns_upstreams 64k;
    server 8.8.8.8:53;
    server 1.1.1.1:53;
}

server {
    listen 53 udp; # Прослушивание UDP-порта
    listen 53;     # Прослушивание TCP-порта (DNS также использует TCP)
    
    # Для UDP, где нет формального закрытия сессии, эта директива указывает Nginx,
    # что нужно ждать только один ответ от бэкенда, после чего сессия считается завершенной.
    proxy_responses 1;
    
    proxy_pass dns_servers;
}
```

**Особенности:**
*   **`listen ... udp`:** Указывает, что порт прослушивается для UDP-трафика.
*   **`proxy_responses 1`:** Критически важно для UDP-протоколов без состояния, чтобы Nginx не держал сессию открытой бесконечно.
*   **Без конвертации:** Модуль `stream` не конвертирует протоколы. Если Nginx получает UDP-трафик, он будет проксирован дальше как UDP.

---

## 4. [Мониторинг](../../../Concepts/Observability_and_Monitoring/observability_overview.md) L4-трафика

Для сбора метрик L4-трафика можно использовать `status_zone` в блоке `server` модуля `stream`.

```nginx
stream {
    server {
        listen 12345;
        proxy_pass backend_service;
        status_zone my_l4_service; # Имя зоны для сбора метрик
    }
}
