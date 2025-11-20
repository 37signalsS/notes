# Балансировка и проксирование L4-трафика (TCP/UDP) в Angie

В этом документе рассматриваются возможности Angie (NGINX) по балансировке нагрузки и проксированию на уровне L4 (TCP/UDP), а также связанные с этим функции, такие как SSL-терминация, SSL Pre-read и Proxy Protocol. Для информации о балансировке нагрузки на уровне L7 (HTTP/S) см. [Балансировка нагрузки HTTP(S) в Angie](./angie_http_load_balancing.md).

## L4 против L7 проксирования

Традиционно NGINX используется для работы с HTTP-трафиком (L7), где конфигурация находится в контексте `http` и позволяет работать с запросами на уровне приложения. Однако модуль `stream` позволяет работать на уровне транспорта (TCP/UDP), что открывает возможности для проксирования любых протоколов, не ограничиваясь HTTP/HTTPS.

Такой подход требует значительно меньше ресурсов, так как балансировщику не нужно разбирать протокол уровня приложения, что позволяет пропускать через себя больше трафика.

### Отличия модуля `stream` от `http`:

*   **Уровень работы:** L4 (TCP/UDP) вместо L7 (HTTP/S).
*   **Протоколы:** Поддержка любых TCP/UDP протоколов (базы данных, DNS, NTP, SSH и т.д.).
*   **Обработка трафика:** Работа с сессиями подключения, а не с отдельными запросами.
*   **Ограничения:** Меньше возможностей для глубокой инспекции трафика по сравнению с L7, но достаточная гибкость для маршрутизации на основе данных сессии.

## Логирование в модуле Stream

По умолчанию логирование в модуле `stream` отключено. Для его включения необходимо явно определить формат с помощью `log_format` и указать путь к файлу в `access_log`. Логирование оперирует сессиями, а не запросами.

**Пример переменных для логирования:**

*   `$bytes_received`: Количество байт, полученных от клиента.
*   `$bytes_sent`: Количество байт, отправленных клиенту.
*   `$session_time`: Общая продолжительность сессии.
*   `$remote_addr`: IP-адрес клиента.
*   `$upstream_addr`: IP-адрес вышестоящего сервера.
*   `$protocol`: Используемый протокол (`TCP` или `UDP`).
*   `$status`: Статус завершения сессии (например, `200` для успешной).

## Ограничения подключений

В модуле `stream` доступна директива `limit_conn` для ограничения количества одновременных подключений от одного IP-адреса. Директива `limit_req` (для ограничения запросов) недоступна, так как на уровне L4 нет понятия "запрос".

## Структура конфигурации

Конфигурация L4-проксирования размещается в блоке `stream`, который является родственным для `http`. Часто для удобства управления используются отдельные файлы конфигурации для каждого сервиса в директории `stream.d`.

```nginx
# /etc/angie/angie.conf
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time "$upstream_addr"';

    access_log /var/log/angie/stream-access.log basic;

    # Включение конфигураций из stream.d
    include /etc/angie/stream.d/*.conf;
}
```

## Пример: Проксирование MySQL (TCP)

Этот пример демонстрирует балансировку нагрузки для MySQL-серверов (например, Master/Slave) с использованием TCP-проксирования.

```nginx
# /etc/angie/stream.d/mysql.conf
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
    access_log /var/log/angie/mysql-master-access.log basic;
    error_log /var/log/angie/mysql-master-error.log warn;
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
*   **`upstream`:** Определяет группы серверов.
*   **`zone`:** Создает зону разделяемой памяти для хранения статуса upstream-серверов и мониторинга.
*   **Балансировка:** Поддерживаются все методы, доступные в `http`, кроме `ip_hash`.
*   **Управление доступом:** Директивы `allow` и `deny` позволяют контролировать доступ по IP-адресам.

## Пример: SSL-терминация

Angie может выступать в роли SSL-терминатора, принимая зашифрованные соединения, расшифровывая их и затем проксируя трафик дальше в открытом виде.

```nginx
# /etc/angie/stream.d/ssl_termination.conf
upstream web_backend {
    server 127.0.0.1:9001;
}

server {
    listen 9443 ssl; # Прослушивание порта с SSL
    ssl_certificate /etc/angie/certs/server.crt;
    ssl_certificate_key /etc/angie/certs/server.key;
    proxy_pass web_backend; # Проксирование на незашифрованный бэкенд
}
```

### Передача в HTTP-модуль

Особенно мощной является возможность передать расшифрованный трафик напрямую в `http` контекст самого Angie для дальнейшей обработки.

```nginx
# /etc/angie/angie.conf
# В http-контексте создается сервер, слушающий на внутреннем сокете
http {
    # ...
    server {
        listen 127.0.0.1:8000; # Слушает только локально
        # ... здесь обычная обработка HTTP-запроса
    }
}

# /etc/angie/stream.d/ssl_pass.conf
# В stream-контексте
server {
    listen 9444 ssl;
    ssl_certificate /etc/angie/certs/server.crt;
    ssl_certificate_key /etc/angie/certs/server.key;
    
    # Передача расшифрованного соединения в http-модуль
    proxy_pass 127.0.0.1:8000;
}
```
Эта связка позволяет использовать `stream` для эффективной терминации TLS, а `http` — для всей мощи L7-обработки.

## Пример: SSL Pre-read (маршрутизация TLS vs SSH)

Функция SSL Pre-read позволяет Angie "заглянуть" в начало входящего TCP-соединения, чтобы определить, используется ли TLS, без полной терминации сессии. Это позволяет маршрутизировать разный трафик, приходящий на один порт.

Классический пример — мультиплексирование HTTPS и SSH на одном порту (443).

```nginx
# /etc/angie/stream.d/ssl_preread.conf
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
*   **`map`:** Создает переменную `$backend_by_sni`, значение которой (имя апстрима) зависит от имени сервера, переданного в TLS SNI (`$ssl_preread_server_name`). Если клиент не передает SNI (как в случае с SSH), используется значение `default`.
*   **`listen 443;`**: Обратите внимание, что флаг `ssl` не используется, так как Angie не терминирует соединение.
*   **`ssl_preread on;`:** Включает "подглядывание" в Client Hello.
*   **`proxy_pass $backend_by_sni;`:** Динамическое проксирование на основе результата `map`.

## Пример: Proxy Protocol

Proxy Protocol позволяет передавать исходный IP-адрес клиента через прокси-сервер к бэкенду, что критически важно для корректного логирования и работы приложений.

```nginx
# Фронтенд-балансировщик
server {
    listen 982;
    # Добавляем заголовок Proxy Protocol перед отправкой на бэкенд
    proxy_pass 127.0.0.1:820 proxy_protocol;
}

# Бэкенд-сервер (может быть другим Angie)
server {
    # Указываем, что на этом порту ожидается заголовок Proxy Protocol
    listen 820 proxy_protocol;
    
    # Указываем доверенные IP-адреса прокси
    set_real_ip_from 127.0.0.1/8;
    
    # Указываем, что реальный IP нужно брать из заголовка Proxy Protocol
    real_ip_header proxy_protocol;
    
    access_log /var/log/angie/proxy-protocol-access.log basic;
    
    # ... дальнейшая обработка
}
```

## Пример: Проксирование UDP DNS

Angie может проксировать UDP-трафик, например, для DNS-серверов.

```nginx
# /etc/angie/stream.d/udp_dns.conf
upstream dns_servers {
    zone dns_upstreams 64k;
    server 8.8.8.8:53;
    server 1.1.1.1:53;
}

server {
    listen 53 udp; # Прослушивание UDP-порта
    listen 53;     # Прослушивание TCP-порта (DNS также использует TCP)
    
    # Для UDP, где нет формального закрытия сессии, эта директива указывает Angie,
    # что нужно ждать только один ответ от бэкенда, после чего сессия считается завершенной.
    proxy_responses 1;
    
    proxy_pass dns_servers;
}
```

**Особенности:**
*   **`listen ... udp`:** Указывает, что порт прослушивается для UDP-трафика.
*   **`proxy_responses 1`:** Критически важно для UDP-протоколов без состояния, чтобы Angie не держал сессию открытой бесконечно.
*   **Без конвертации:** Angie не конвертирует протоколы. Если на вход приходит UDP, то и на бэкенд будет отправлен UDP.

## См. также

*   [Настройка Angie в роли обратного HTTP-прокси](./angie_reverse_proxy.md)
*   [Настройка TLS в Angie: безопасность и скорость](./angie_tls_setup.md)
*   [Установка Angie из пакетов](./angie_installation.md)
*   [Почему стоит переходить на Angie](./angie_why_migrate.md)
