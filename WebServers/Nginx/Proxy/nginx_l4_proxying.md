# Балансировка и проксирование L4-трафика (TCP/UDP) в Nginx

## Определения

* **Модуль `stream` Nginx**: Расширение функциональности Nginx, предоставляющее возможности для балансировки нагрузки и проксирования трафика на **уровне L4 (Transport layer)**. Позволяет работать с протоколами, не основанными на HTTP: базами данных (MySQL, PostgreSQL), DNS, NTP, SSH и др.

* **L4 vs L7 проксирование**:
  * **L7 (Application layer):** Nginx работает с HTTP-трафиком в контексте `http`, обрабатывая запросы на уровне приложения.
  * **L4 (Transport layer):** Модуль `stream` работает на уровне транспорта (TCP/UDP), проксируя соединения без разбора содержимого.
  * **Ключевые отличия:**
    * Уровень работы: L4 (TCP/UDP) вместо L7 (HTTP/S)
    * Протоколы: Любые TCP/UDP-протоколы (базы данных, DNS, NTP, SSH)
    * Обработка: Сессии подключения вместо отдельных запросов
    * Ресурсы: Меньше накладных расходов, так как не требуется разбор протокола приложения

## Основные концепции

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

### Логирование в `stream`

По умолчанию логирование в модуле `stream` отключено. Настраивается через `access_log`. Фиксируются параметры сессии, а не запросов.

**Переменные для логирования:**

* `$remote_addr`: IP-адрес клиента
* `$time_local`: Локальное время
* `$protocol`: Протокол (TCP/UDP)
* `$status`: Статус сессии
* `$bytes_sent`: Отправленные байты
* `$bytes_received`: Полученные байты
* `$session_time`: Продолжительность сессии
* `$upstream_addr`: Адрес upstream-сервера

### Ограничение подключений

В `stream` можно ограничивать количество одновременных подключений (`limit_conn`), но не частоту запросов (`limit_req`), так как понятия запроса нет.

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

Сценарий распределения нагрузки между master-сервером БД (на запись) и slave-серверами (на чтение).

**Пример конфигурации (`/etc/nginx/stream.d/mysql.conf`):**

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

1. **Блоки `upstream`**:
    * `zone <name> 64k;`: Выделяет общую память для хранения состояния группы (статистика соединений, динамическое управление).
    * `server ... proxy_protocol;`: Включает **[Proxy Protocol](../../../Networking/Concepts/proxy.md)** — добавляет к TCP-соединению заголовок с **реальным IP-адресом клиента**. Без этого БД видит только IP Nginx.

2. **Блоки `server`**:
    * `listen 6306;`: Виртуальный TCP-сервер на порту `6306`.
    * `proxy_pass mysql_master;`: Направление трафика в upstream `mysql_master`.
    * `limit_conn_*`: Ограничение одновременных соединений с одного IP для защиты мастера.
    * `status_zone <name>;`: Зона статистики для мониторинга через API Nginx.

### SSL/TLS терминация на L4

Nginx принимает зашифрованные соединения, расшифровывает и проксирует трафик в открытом виде.

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

Расшифрованный трафик передаётся в `http` контекст для L7-обработки.

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

`stream` эффективен для терминации TLS, `http` — для L7-обработки.

### SSL Pre-read (маршрутизация TLS vs SSH)

Функция SSL Pre-read позволяет Nginx "заглянуть" в начало TCP-соединения и определить тип трафика без полной терминации сессии.

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

* **[`map`](../Core/nginx_rewrite_rules_and_try_files.md#директива-map):** Определяет `$backend_by_sni` на основе SNI (`$ssl_preread_server_name`). Без SNI (как в SSH) — используется `default`.
* **`listen 443;`**: Без флага `ssl` — Nginx не терминирует соединение.
* **`ssl_preread on;`:** Включает анализ Client Hello.
* **`proxy_pass $backend_by_sni;`:** Динамическое проксирование на основе `map`.

### Использование Proxy Protocol

Proxy Protocol передаёт исходный IP клиента через прокси к бэкенду.

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

Nginx проксирует UDP-трафик, например для DNS-серверов.

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

* **`listen ... udp`:** Указывает прослушивание UDP-трафика.
* **`proxy_responses 1`:** Критично для UDP без состояния — предотвращает бесконечное удержание сессии.
* **Без конвертации протоколов:** UDP проксируется как UDP, TCP — как TCP.

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

### See also

* [Основы Nginx](../Core/nginx_overview.md)
* [Конфигурация Nginx](../Core/nginx_setup.md)
* [Концепции проксирования](../../../Networking/Concepts/proxy.md)
