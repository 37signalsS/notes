# Конфигурация виртуальных хостов TLS в Nginx

## Определения

### Виртуальный хост (`server`)

Блок `server` в Nginx описывает конфигурацию отдельного сайта. Параметры TLS, заданные на этом уровне, применяются только к конкретному домену и переопределяют глобальные настройки TLS (если таковые заданы в `http`-блоке). Подробнее о глобальных параметрах: [Глобальные параметры TLS](./nginx_tls_global_parameters.md).

## Основные понятия

### Базовая конфигурация HTTPS

Для работы HTTPS необходимо указать порт 443 с параметром `ssl`, а также пути к сертификату и приватному ключу.

```nginx
server {
    # listen 443 ssl — указывает Nginx слушать стандартный HTTPS-порт.
    # Параметр `ssl` активирует обработку TLS-трафика на этом порту.
    # `http2` включает поддержку HTTP/2 (см. раздел ниже).
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name your_domain.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    # HSTS — заголовок, предписывающий браузеру использовать только HTTPS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    location / {
        # ... остальная конфигурация сайта
    }
}
```

**Ключевые директивы:**

- `listen 443 ssl http2` — прослушивание порта 443 с TLS и HTTP/2.
- `ssl_certificate` — путь к файлу цепочки сертификатов (`fullchain.pem`: серверный + промежуточные сертификаты).
- `ssl_certificate_key` — путь к приватному ключу сервера. Должен быть защищён от несанкционированного доступа.

## Практические сценарии

### Перенаправление с HTTP на HTTPS

Для обеспечения безопасности и SEO все HTTP-запросы должны перенаправляться на HTTPS с кодом `301 Moved Permanently`.

```nginx
server {
    listen 80;
    server_name your_domain.com www.your_domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your_domain.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    # ... остальная конфигурация HTTPS
}
```

> **Примечание:** При отладке используйте `302` (временный редирект), так как `301` агрессивно кэшируется браузерами.

### Включение HTTP/2

Достаточно добавить параметр `http2` к директиве `listen`:

```nginx
server {
    listen 443 ssl http2;
    # ...
}
```

### Включение HTTP/3 (QUIC)

HTTP/3 требует UDP-порт и анонсирование поддержки через заголовок `Alt-Svc`:

```nginx
server {
    listen 443 ssl http2;
    listen 443 quic reuseport;

    http3 on;
    add_header Alt-Svc 'h3=":443"; ma=86400';

    # ...
}
```

Подробная документация по HTTP/2 и HTTP/3: [Конфигурация HTTP/2 и HTTP/3 в Nginx](../../Performance/nginx_http_versions.md).

#### DNS-запись типа HTTPS

Для информирования клиентов о поддержке HTTP/2 и HTTP/3 можно использовать DNS-запись:

```dns
your_domain.com. IN HTTPS 1 . alpn="h2,h3"
```

**Важно:** Запись типа `HTTPS` несовместима с `CNAME`. Требуется `A` или `AAAA` запись. Подробнее: [DNS-записи HTTPS/SVCB](../../../../Networking/Protocols/DNS/dns_records.md).

### Использование EC и RSA сертификатов одновременно

Nginx позволяет настроить оба типа сертификатов для максимальной совместимости с клиентами:

```nginx
server {
    # ...
    # EC-сертификат (ECDSA, предпочтительный)
    ssl_certificate /path/to/ec_cert.pem;
    ssl_certificate_key /path/to/ec_key.pem;

    # RSA-сертификат (для совместимости со старыми клиентами)
    ssl_certificate /path/to/rsa_cert.pem;
    ssl_certificate_key /path/to/rsa_key.pem;
    # ...
}
```

Nginx автоматически выберет подходящий сертификат в зависимости от возможностей клиента.

## Дополнительная информация

### См. также

- [Глобальные параметры TLS](./nginx_tls_global_parameters.md) — протоколы, шифры, кэш сессий, OCSP
- [Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md) — теория и концепции
- [Конфигурация HTTP/2 и HTTP/3](../../Performance/nginx_http_versions.md) — подробности о протоколах
