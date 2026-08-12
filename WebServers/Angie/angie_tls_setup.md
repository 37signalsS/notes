# Настройка TLS в Angie

## Определения

**Настройка TLS в Angie** — процесс конфигурации протоколов TLS (Transport Layer Security) и QUIC для обеспечения безопасности передачи данных (конфиденциальность, целостность и аутентификация). 

Angie, являясь современным форком Nginx, не только поддерживает стандартные механизмы шифрования, но и предоставляет встроенные инструменты для упрощения эксплуатации: нативный HTTP/3, автоматизацию сертификатов (модуль ACME) и динамическое управление параметрами SSL без перезагрузки сервера.

## Базовые концепции

### Совместимость и SSoT
Angie сохраняет полную обратную совместимость с директивами Nginx. Общие рекомендации по выбору шифров (ciphers), настройке HSTS и OCSP Stapling являются общими для обоих серверов:
> **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**

### Ключевые преимущества Angie в TLS

*   **Встроенный ACME:** Автоматическое получение и продление сертификатов (Let's Encrypt и др.) средствами самого сервера (модуль `acme`).
*   **Динамическая загрузка:** Поддержка переменных в директивах `ssl_certificate` и `ssl_certificate_key` (Angie 1.3.0+), что позволяет загружать сертификаты «на лету» на основе имени хоста.
*   **Кэширование сертификатов:** Директива `ssl_certificate_cache` (Angie 1.4.0+) ускоряет работу при использовании переменных в путях к сертификатам.
*   **Нативный HTTP/3 (QUIC):** Реализация встроена в ядро и не требует сборки внешних модулей или использования экспериментальных веток.
*   **Автоматизация тикетов сессий:** Ротация ключей `ssl_session_tickets` происходит автоматически между всеми рабочими процессами без необходимости внешних скриптов.
*   **Переменные в SSL-директивах:** Директивы `ssl_crl` и `ssl_ocsp` поддерживают переменные, позволяя менять списки отзыва и параметры проверки без `reload`.

## Практические сценарии

### Сценарий 1: Настройка HTTP/3 (QUIC)

Для работы HTTP/3 необходимо открыть порт по протоколу UDP и анонсировать поддержку через заголовок `Alt-Svc`.

```nginx
server {
    # Порт 443 для TCP (HTTP/1.1, HTTP/2) и UDP (HTTP/3)
    listen 443 ssl;
    listen 443 quic reuseport;

    server_name example.com;

    ssl_certificate     /etc/angie/ssl/cert.crt;
    ssl_certificate_key /etc/angie/ssl/cert.key;

    # Анонс поддержки HTTP/3 для клиентов
    add_header Alt-Svc 'h3=":443"; ma=86400';

    # Оптимизация: использование GSO (Generic Segmentation Offload) для QUIC
    quic_gso on;
}
```
→ Подробнее: **[Конфигурация HTTP/2 и HTTP/3 в Nginx/Angie](../Nginx/Performance/nginx_http_versions.md)**

### Сценарий 2: Динамические сертификаты и кэширование

Используется в инфраструктурах с тысячами доменов, чтобы не описывать каждый `server` блок отдельно.

```nginx
http {
    # Настройка кэша для динамических сертификатов (Angie 1.4.0+)
    # Хранит до 1000 сертификатов в памяти, очистка через 10 минут простоя
    ssl_certificate_cache max=1000 inactive=10m;

    server {
        listen 443 ssl;
        server_name *.example.com;

        # Загрузка сертификата по имени хоста (Angie 1.3.0+)
        ssl_certificate     /etc/angie/ssl/$ssl_server_name.crt;
        ssl_certificate_key /etc/angie/ssl/$ssl_server_name.key;
    }
}
```

### Сценарий 3: Автоматизация через ACME (Quick Start)

Встроенный клиент для Let's Encrypt. Исключает необходимость в Certbot.

```nginx
http {
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    acme_client letsencrypt {
        directory "https://acme-v02.api.letsencrypt.org/directory";
    }

    server {
        listen 443 ssl;
        server_name app.example.com;

        # Использование ACME-сертификатов
        acme letsencrypt;
        ssl_certificate     $acme_cert_letsencrypt;
        ssl_certificate_key $acme_cert_key_letsencrypt;
    }
}
```
→ Подробнее: **[Модуль ACME в Angie: полная конфигурация](./angie_acme_module.md)**

### Сценарий 4: Двухстековые сертификаты (RSA + ECDSA)

Обеспечивает совместимость со старыми клиентами (RSA) и высокую скорость для новых (ECDSA).

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    # RSA
    ssl_certificate     /etc/angie/ssl/example.com.rsa.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.rsa.key;

    # ECDSA (приоритет в современных браузерах)
    ssl_certificate     /etc/angie/ssl/example.com.ecdsa.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.ecdsa.key;

    ssl_protocols TLSv1.2 TLSv1.3;
}
```

### Сценарий 5: Оптимизация через Kernel TLS (kTLS)

Снижает нагрузку на CPU за счет переноса операций шифрования в ядро ОС. Требует OpenSSL 3.0+ и поддержки в ядре (`modprobe tls`).

```nginx
http {
    # Включение kTLS через конфигурацию OpenSSL
    ssl_conf_command Options +KTLS;

    server {
        listen 443 ssl;
        sendfile on; # kTLS работает в связке с sendfile
        
        ssl_certificate     /etc/angie/ssl/cert.crt;
        ssl_certificate_key /etc/angie/ssl/cert.key;
    }
}
```

## Дополнительная информация

### Мониторинг TLS
Angie предоставляет расширенные переменные для мониторинга состояния соединений, которые можно использовать в `log_format`:
*   `$ssl_protocol` — используемый протокол (например, TLSv1.3).
*   `$ssl_cipher` — используемый шифр.
*   `$ssl_curve` — выбранная эллиптическая кривая.
*   `$ssl_session_reused` — статус повторного использования сессии (`r` — reused, `.` — new).
*   `$ssl_server_name` — имя сервера, запрошенное через SNI.

### Рекомендации по безопасности
Для проверки качества настройки TLS рекомендуется использовать внешние сканеры (SSL Labs) или утилиту `testssl.sh`. На 2026 год стандартом является отказ от TLS 1.0/1.1 и использование только TLS 1.2 и 1.3.

## См. также

*   **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)** — SSoT по общим настройкам.
*   **[Взаимная аутентификация (mTLS) в Angie](./angie_client_cert_auth.md)**
*   **[Конфигурация HTTP/2 и HTTP/3 в Nginx](../Nginx/Performance/nginx_http_versions.md)**
*   **[Модуль ACME в Angie](./angie_acme_module.md)**
