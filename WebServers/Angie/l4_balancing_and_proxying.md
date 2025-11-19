# Балансировка и проксирование L4-трафика (TCP/UDP) в Angie

В этом документе рассматриваются возможности Angie (NGINX) по балансировке нагрузки и проксированию на уровне L4 (TCP/UDP), а также связанные с этим функции, такие как SSL-терминация, SSL Pre-read и Proxy Protocol. Для информации о балансировке нагрузки на уровне L7 (HTTP/S) см. [Балансировка нагрузки HTTP(S) в Angie](./angie_http_load_balancing.md).

## L4 против L7 проксирования

Традиционно NGINX используется для работы с HTTP-трафиком (L7), где конфигурация находится в контексте `http` и позволяет работать с запросами. Однако модуль `stream` позволяет работать на уровне TCP/UDP, что открывает возможности для проксирования различных протоколов, не ограничиваясь HTTP/HTTPS.

### Отличия модуля `stream` от `http`:

*   **Уровень работы:** L4 (TCP/UDP) вместо L7 (HTTP/HTTPS).
*   **Протоколы:** Поддержка любых TCP/UDP протоколов (базы данных, DNS, NTP и т.д.).
*   **Обработка трафика:** Работа с сессиями подключения, а не с запросами.
*   **Ограничения:** Меньше возможностей для глубокой обработки трафика по сравнению с L7, но достаточная гибкость для маршрутизации и переадресации на основе данных сессии.

## Логирование в модуле Stream

По умолчанию логирование в модуле `stream` отключено. Для его включения необходимо явно указать директиву `log_format` и `access_log`. Логирование отличается от HTTP-модуля, так как оперирует сессиями, а не запросами.

**Пример переменных для логирования:**

*   `$bytes_received`: Количество полученных байт.
*   `$bytes_sent`: Количество отправленных байт.
*   `$session_time`: Время сессии.
*   `$remote_addr`: Адрес клиента.
*   `$upstream_addr`: Адрес вышестоящего сервера.

## Ограничения подключений

В модуле `stream` доступна директива `limit_conn` для ограничения количества одновременных подключений. Директива `limit_req` (для ограничения запросов) недоступна из-за сессионной природы L4-трафика.

## Структура конфигурации

Конфигурация L4-проксирования размещается в блоке `stream`. Часто для удобства управления используются отдельные файлы конфигурации для каждого сервиса в директории `stream.d`.

```nginx
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time "$upstream_addr"';

    access_log /var/log/nginx/stream-access.log basic;

    # Включение конфигураций из stream.d
    include /etc/nginx/stream.d/*.conf;
}
```

## Пример: Проксирование MySQL (TCP)

Этот пример демонстрирует балансировку нагрузки для MySQL-серверов (Master/Slave) с использованием TCP-проксирования.

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
    limit_conn per_ip 10; # Ограничение подключений
    access_log /var/log/nginx/mysql-master-access.log basic;
    error_log /var/log/nginx/mysql-master-error.log warn;
    # allow 192.168.1.0/24;
    # deny all;
    status_zone mysql_master_status; # Для мониторинга
}

server {
    listen 6307; # Порт для Slave
    proxy_pass mysql_slave;
    limit_conn per_ip 10;
    access_log /var/log/nginx/mysql-slave-access.log basic;
    error_log /var/log/nginx/mysql-slave-error.log warn;
    status_zone mysql_slave_status;
}
```

**Особенности:**

*   **`upstream`:** Определяет группы серверов.
*   **`zone`:** Создает зону разделяемой памяти для хранения статуса upstream-серверов и мониторинга.
*   **`listen`:** Указывает TCP-порт для прослушивания.
*   **`proxy_pass`:** Перенаправляет трафик на определенный `upstream`.
*   **Балансировка:** Поддерживаются все методы балансировки, кроме `ip_hash`.
*   **Управление доступом:** Директивы `allow` и `deny` позволяют контролировать доступ по IP-адресам.

## Пример: SSL-терминация

Angie может выступать в роли SSL-терминатора, принимая зашифрованные соединения, расшифровывая их и затем проксируя трафик дальше.

```nginx
# /etc/nginx/stream.d/ssl_termination.conf
server {
    listen 9443 ssl; # Прослушивание порта с SSL
    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;
    proxy_pass 127.0.0.1:9001; # Проксирование на незашифрованный бэкенд
}

server {
    listen 9444 ssl;
    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;
    pass http_backend_name; # Передача управления в HTTP-модуль
}
```

**Особенности:**

*   **`listen ... ssl`:** Указывает, что порт прослушивается с использованием SSL.
*   **`ssl_certificate`, `ssl_certificate_key`:** Пути к сертификату и приватному ключу.
*   **`proxy_pass`:** Проксирование на другой адрес/порт.
*   **`pass`:** Специальная директива, которая передает управление обработкой соединения в HTTP-модуль NGINX. Это удобно, если после SSL-терминации трафик должен быть обработан как обычный HTTP-запрос в рамках того же NGINX.

## Пример: SSL Pre-read (определение протокола)

Функция SSL Pre-read позволяет Angie "заглянуть" в начало SSL-соединения (handshake) для определения протокола (например, TLS) без полной его терминации. Это позволяет маршрутизировать трафик на основе обнаруженного протокола.

```nginx
# /etc/nginx/stream.d/ssl_preread.conf
map $ssl_preread_protocol $upstream_by_protocol {
    "TLSv1.2" 192.168.1.100:8443; # Пример: TLSv1.2 на удаленный сервер
    "TLSv1.3" 192.168.1.100:8443; # Пример: TLSv1.3 на удаленный сервер
    default   127.0.0.1:22;       # Пример: Если не TLS, то на SSH
}

server {
    listen 8443; # Прослушивание порта без SSL-флага
    ssl_preread on; # Включение SSL Pre-read
    proxy_pass $upstream_by_protocol; # Проксирование на основе переменной
    status_zone ssl_preread_status;
}
```

**Особенности:**

*   **`map $ssl_preread_protocol ...`:** Создает переменную `$upstream_by_protocol`, значение которой зависит от обнаруженного протокола.
*   **`ssl_preread on;`:** Включает предварительное чтение SSL. Angie не обрабатывает сам TLS, а только читает handshake для определения протокола.
*   **`proxy_pass $upstream_by_protocol;`:** Динамическое проксирование на основе определенного протокола.

## Пример: Proxy Protocol

Proxy Protocol позволяет передавать исходный IP-адрес клиента через прокси-сервер к бэкенду, что критически важно для корректного логирования и работы приложений.

```nginx
# /etc/nginx/stream.d/proxy_protocol_frontend.conf
server {
    listen 982; # Входящий порт
    proxy_pass 127.0.0.1:820 proxy_protocol; # Проксирование с включением Proxy Protocol
}

# /etc/nginx/stream.d/proxy_protocol_backend.conf
server {
    listen 820 proxy_protocol; # Прослушивание порта с Proxy Protocol
    set_real_ip_from 127.0.0.1/8; # Доверенные IP-адреса прокси
    real_ip_header proxy_protocol; # Использование заголовка Proxy Protocol
    access_log /var/log/nginx/proxy-protocol-access.log basic;
}
```

**Особенности:**

*   **`proxy_pass ... proxy_protocol`:** На стороне фронтенда указывает Angie передавать информацию Proxy Protocol бэкенду.
*   **`listen ... proxy_protocol`:** На стороне бэкенда указывает Angie ожидать информацию Proxy Protocol.
*   **`set_real_ip_from`:** Определяет доверенные источники, от которых можно принимать информацию об исходном IP-адресе.
*   **`real_ip_header proxy_protocol`:** Указывает Angie использовать данные из Proxy Protocol для определения реального IP-адреса клиента.

## Пример: Проксирование UDP DNS

Angie может проксировать UDP-трафик, например, для DNS-серверов.

```nginx
# /etc/nginx/stream.d/udp_dns.conf
upstream dns_servers {
    server 192.168.1.1:53;
    server 192.168.1.2:53;
}

server {
    listen 53 udp; # Прослушивание UDP-порта
    listen 53;     # Прослушивание TCP-порта (DNS также использует TCP)
    proxy_responses 1; # Ожидать 1 ответ от бэкенда (для UDP)
    proxy_pass dns_servers;
}
```

**Особенности:**

*   **`listen ... udp`:** Указывает, что порт прослушивается для UDP-трафика.
*   **`proxy_responses 1`:** Важно для UDP, так как формальной сессии нет. Эта директива указывает Angie ожидать определенное количество ответов от бэкенда, чтобы не держать соединение открытым бесконечно. Для DNS обычно достаточно одного ответа.
*   **Без конвертации:** Angie не конвертирует протоколы. Если на вход приходит UDP, то и на выход будет UDP.

## См. также

*   [Настройка Angie в роли обратного HTTP-прокси](./angie_reverse_proxy.md)
*   [Настройка TLS в Angie: безопасность и скорость](./angie_tls_setup.md)
*   [Установка Angie из пакетов](./angie_installation.md)
*   [Почему стоит переходить на Angie](./angie_why_migrate.md)
