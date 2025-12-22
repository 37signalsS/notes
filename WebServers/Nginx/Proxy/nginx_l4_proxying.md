# Балансировка и проксирование L4-трафика (TCP/UDP) в Nginx

## 1. Определения и базовые концепции

Nginx, помимо работы с HTTP (L7), предоставляет мощные возможности для балансировки нагрузки и проксирования трафика на **уровне L4 (TCP/UDP)** через модуль `stream`. Это позволяет работать с различными протоколами, которые не основаны на HTTP, такими как базы данных (MySQL, PostgreSQL), DNS, NTP и др.

### Отличия от L7 (HTTP) проксирования

В отличие от HTTP-контекста, где Nginx оперирует понятиями "запрос" и "ответ", в `stream` модуле работа ведется с "сессиями подключения". Это означает, что:
*   **Нет понятия запроса:** Обработка происходит на уровне потока данных, а не отдельных HTTP-запросов.
*   **Более низкий уровень OSI:** Nginx работает ближе к сетевому уровню, что дает гибкость, но накладывает некоторые ограничения на возможности обработки трафика.
*   **Внедрение в трафик:** Несмотря на работу на низком уровне, Nginx может анализировать начало сессии (например, для SSL/TLS) и на основе этих данных принимать решения о маршрутизации.

---
## 2. Конфигурация и основные директивы

Для использования L4-функциональности необходимо, чтобы в `nginx.conf` присутствовал блок `stream`.

```nginx
# /etc/nginx/nginx.conf
stream {
    # Здесь будут располагаться конфигурации L4-сервисов
    # Например, включение других файлов конфигурации
    include /etc/nginx/stream.d/*.conf;

    # ... общие параметры stream ...
}
```

### Логирование в `stream`

По умолчанию логирование в модуле `stream` отключено. Его можно настроить с помощью директивы `access_log`. Логирование будет отличаться от HTTP, так как фиксируются параметры сессии, а не запросов.

```nginx
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time "$upstream_addr"';

    access_log /var/log/nginx/stream-access.log basic;
}
```

Пример переменных для логирования:
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

### 3.1. Проксирование MySQL (TCP) для репликации
Nginx может распределять нагрузку между master и slave-серверами базы данных.

```nginx
stream {
    upstream mysql_master {
        zone mysql_master_zone 64k;
        server 127.0.0.1:3307; # Мастер
    }

    upstream mysql_slaves {
        zone mysql_slaves_zone 64k;
        server 127.0.0.1:3308; # Слейв 1
        server 127.0.0.1:3309; # Слейв 2
        # ... другие слейвы
    }

    server {
        listen 6306; # Порт для записи (на мастер)
        proxy_pass mysql_master;
        status_zone mysql_master_status; # Для мониторинга
    }

    server {
        listen 6307; # Порт для чтения (на слейвы)
        proxy_pass mysql_slaves;
        status_zone mysql_slaves_status; # Для мониторинга
        # Возможны различные алгоритмы балансировки: round robin (по умолчанию), least_conn и т.д.
    }
}
```

### 2. SSL/TLS терминация на L4

Nginx может терминировать SSL/TLS соединения на L4, а затем проксировать трафик на бэкенды по незашифрованному протоколу или передавать управление в HTTP-модуль.

```nginx
stream {
    upstream dns_servers {
        server 192.168.1.1:53;
        server 192.168.1.2:53;
    }

    server {
        listen 53 udp; # Слушаем UDP на порту 53
        listen 53 tcp; # Опционально, если DNS также работает по TCP
        proxy_responses 1; # Для UDP: ожидаем 1 ответ от бэкенда
        proxy_pass dns_servers;
    }
}
```

*   `proxy_responses 1`: Эта директива критически важна для UDP. В отличие от TCP, у UDP нет формальной сессии, и Nginx не может знать, когда обмен данными завершен. `proxy_responses` указывает, сколько ответов (пакетов) следует ожидать от бэкенда, прежде чем закрыть сессию. Это предотвращает "зависание" соединений. Для DNS, где на один запрос обычно приходит один ответ, значение `1` является стандартным.
*   **Важное замечание:** Модуль `stream` не выполняет конвертацию протоколов. Если Nginx получает UDP-трафик, он будет проксирован дальше как UDP.

---

## 4. Продвинутые детали

### 4.1. SSL/TLS терминация на L4

Nginx может терминировать SSL/TLS соединения на L4, а затем проксировать трафик на бэкенды по незашифрованному протоколу.

```nginx
stream {
    server {
        listen 9443 ssl; # Nginx терминирует SSL
        ssl_certificate     /etc/nginx/certs/server.crt;
        ssl_certificate_key /etc/nginx/certs/server.key;
        proxy_pass backend_http; # Проксирование на HTTP бэкенд
    }

    # Передача управления в HTTP-модуль
    server {
        listen 9444 ssl;
        ssl_certificate     /etc/nginx/certs/server.crt;
        ssl_certificate_key /etc/nginx/certs/server.key;
        pass http; # Передача запроса в HTTP-контекст Nginx
    }
}
```

Директива `pass http` — это удобный механизм, который позволяет после терминации SSL в модуле `stream` передать управление запросом в контекст модуля `http` этого же сервера Nginx. Это избавляет от необходимости проксировать трафик на другой порт (`proxy_pass`) и удобно, если за одним L4-терминатором находится обычный веб-сайт, обслуживаемый тем же Nginx.

### 3.  SSL Preread для мультиплексирования протоколов

Модуль `ssl_preread` позволяет Nginx читать начальные данные SSL/TLS handshake для определения версии протокола или SNI (Server Name Indication) без полной терминации SSL. Это дает возможность маршрутизировать трафик на разные бэкенды в зависимости от обнаруженного протокола.

```nginx
stream {
    map $ssl_preread_protocol $upstream_backend {
        "TLSv1.2"   backend_https;
        "TLSv1.3"   backend_https;
        default     backend_ssh; # Если не TLS, считаем, что это SSH
    }

    upstream backend_https { server 192.168.1.100:443; }
    upstream backend_ssh { server 192.168.1.101:22; }

    server {
        listen 443;
        ssl_preread on; # Включаем предварительное чтение SSL
        proxy_pass $upstream_backend;
    }
}
```
Такая конфигурация позволяет реализовать "мультиплексирование" протоколов на одном порту. Например, можно принимать на одном и том же порту и HTTPS-трафик для веб-сайта, и SSH-подключения, перенаправляя их на разные внутренние серверы. Nginx в данном случае не терминирует SSL/TLS, а лишь "заглядывает" в начало сессии для принятия решения о маршрутизации.

### 4.3. Использование Proxy Protocol

Proxy Protocol позволяет передавать исходный IP-адрес клиента через несколько прокси-серверов до конечного бэкенда, что критично для корректного логирования.

**На фронтенде (отправка):**
```nginx
stream {
    server {
        listen 982;
        proxy_protocol on; # Включаем Proxy Protocol для исходящего соединения
        proxy_pass backend_with_proxy_protocol;
    }
}
```
**На бэкенде (прием):**
```nginx
stream {
    server {
        listen 820 proxy_protocol; # Указываем, что ожидаем Proxy Protocol
        set_real_ip_from 127.0.0.1/8; # Доверяем IP из этого диапазона
        real_ip_header proxy_protocol; # Указываем, что реальный IP берется из Proxy Protocol
        access_log /var/log/nginx/proxy_protocol_access.log;
        proxy_pass actual_application_backend;
    }

    upstream actual_application_backend {
        server 127.0.0.1:8080; # Ваш реальный бэкенд
    }
}
```

### 4.4. Мониторинг L4-трафика
Для сбора метрик L4-трафика можно использовать `status_zone` в блоке `server` модуля `stream`.

```nginx
stream {
    server {
        listen 12345;
        proxy_pass backend_service;
        status_zone my_l4_service; # Имя зоны для сбора метрик
    }
}
```
