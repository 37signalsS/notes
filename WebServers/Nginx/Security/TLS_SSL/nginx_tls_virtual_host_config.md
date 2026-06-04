# Конфигурация виртуальных хостов TLS в Nginx

## Определения

### Виртуальный хост (`server`)

Блок `server` в Nginx описывает конфигурацию отдельного сайта. Параметры TLS, заданные на этом уровне, применяются только к конкретному домену и переопределяют глобальные настройки TLS (если таковые заданы в `http`-блоке). Подробнее о глобальных параметрах: [Глобальные параметры TLS](./nginx_tls_global_parameters.md).

## Основные понятия

### Базовая конфигурация HTTPS

Для работы HTTPS необходимо указать порт 443 с параметром `ssl`, а также пути к сертификату и приватному ключу.

```nginx
server {
    # listen 443 ssl — активирует обработку TLS-трафика на стандартном порту
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name your_domain.com;

    # Пути к сертификату и ключу
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    # HSTS — заголовок, предписывающий браузеру использовать только HTTPS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    location / {
        # Конфигурация приложения
    }
}
```

**Ключевые директивы:**

- `listen 443 ssl` — прослушивание порта 443 с активацией TLS.
- `ssl_certificate` — путь к файлу цепочки сертификатов (`fullchain.pem`: серверный + промежуточные сертификаты).
- `ssl_certificate_key` — путь к приватному ключу сервера.

## Практические сценарии

### Перенаправление с HTTP на HTTPS

Для обеспечения безопасности все HTTP-запросы должны перенаправляться на HTTPS с кодом `301 Moved Permanently`.

```nginx
server {
    listen 80;
    server_name your_domain.com www.your_domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your_domain.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    # ... остальная конфигурация HTTPS
}
```

### Поддержка HTTP/2 и HTTP/3

Nginx поддерживает современные версии протокола HTTP, которые значительно повышают производительность за счет мультиплексирования и использования QUIC.

- **HTTP/2:** Активируется параметром `http2` в директиве `listen`.
- **HTTP/3 (QUIC):** Требует прослушивания UDP-порта и анонсирования поддержки через заголовок `Alt-Svc`.

Подробные инструкции по настройке и требования к версиям ПО находятся в основном разделе: [Конфигурация HTTP/2 и HTTP/3 в Nginx](../../Performance/nginx_http_versions.md).

### Использование EC и RSA сертификатов одновременно

Nginx позволяет настроить оба типа сертификатов для максимальной совместимости. Клиенты, поддерживающие современные алгоритмы, получат EC-сертификат (Elliptic Curve), остальные — классический RSA.

```nginx
server {
    listen 443 ssl;
    server_name your_domain.com;

    # EC-сертификат (ECDSA, предпочтительный)
    ssl_certificate /path/to/ec_cert.pem;
    ssl_certificate_key /path/to/ec_key.pem;

    # RSA-сертификат (для старых клиентов)
    ssl_certificate /path/to/rsa_cert.pem;
    ssl_certificate_key /path/to/rsa_key.pem;

    # Nginx автоматически выберет сертификат на основе возможностей клиента
}
```

## Дополнительная информация

### См. также

- [Глобальные параметры TLS](./nginx_tls_global_parameters.md) — протоколы, шифры, кэш сессий, OCSP
- [Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md) — теория и концепции
- [Диагностика TLS/SSL](./nginx_tls_troubleshooting_and_compatibility.md) — решение проблем с сертификатами
