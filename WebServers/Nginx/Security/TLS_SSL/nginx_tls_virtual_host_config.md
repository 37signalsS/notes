# Конфигурация виртуальных хостов TLS в Nginx

**Надёжность:** 10 (SSoT + Официальная документация Nginx 1.26/1.27 + Спецификации RFC 9114)
**Свежесть:** Июль 2026 (Актуально для Nginx 1.26+, 1.27.3+)

## Определения

**Виртуальный хост TLS (`server`)** — блок конфигурации Nginx, описывающий настройки безопасности и логику обработки запросов для конкретного доменного имени. Параметры, заданные внутри `server`, имеют приоритет над глобальными настройками из блока `http`.

## Основные концепции

### Базовая конфигурация HTTPS (2026)

Современный стандарт требует одновременной поддержки TCP (HTTP/1.1, HTTP/2) и UDP (HTTP/3) протоколов, а также использования защищенных методов обработки рукопожатия.

```nginx
server {
    # --- Сетевые интерфейсы (Dual Stack + HTTP/3) ---
    # TCP порт 443 для TLS
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on; # Отдельная директива в Nginx 1.25.1+

    # UDP порт 443 для QUIC (HTTP/3)
    # reuseport включается один раз на IP:PORT в nginx.conf
    listen 443 quic;
    listen [::]:443 quic;
    http3 on;

    server_name example.com www.example.com;

    # --- Сертификаты (ECDSA + RSA) ---
    # ECDSA — приоритетный (быстрый, малые ключи)
    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # RSA — резервный (для старых клиентов)
    ssl_certificate     /etc/letsencrypt/live/example.com-rsa/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com-rsa/privkey.pem;

    # --- Усиление безопасности (Hardening) ---
    # HSTS (2 года + поддомены + preload)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    
    # Сообщаем браузеру о поддержке HTTP/3
    add_header Alt-Svc 'h3=":443"; ma=86400';

    location / {
        proxy_pass http://backend_upstream;
    }
}
```

## Практические сценарии

### 1. Безопасный редирект HTTP → HTTPS

Все запросы на порт 80 должны безусловно перенаправляться на защищенную версию сайта с использованием кода 301.

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # Исключение для проверок Let's Encrypt (если не используется DNS-01)
    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
```

### 2. Защита от сканирования (`ssl_reject_handshake`)

Лучшая практика 2026 года для «дефолтного» сервера. Позволяет обрывать соединение на стадии TLS-рукопожатия, если клиент запрашивает неизвестный домен или обращается напрямую по IP-адресу. Это предотвращает утечку доменных имен через сертификаты-заглушки.

```nginx
# В файле /etc/nginx/conf.d/default.conf
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    # Обрыв соединения без передачи сертификата (Nginx 1.19.4+)
    ssl_reject_handshake on;
}
```

### 3. Настройка HTTP/2 и HTTP/3 (QUIC)

В современных версиях Nginx параметры `http2` и `http3` вынесены из директивы `listen` в отдельные команды для повышения гибкости.

- **HTTP/2**: Снижает задержки за счет мультиплексирования.
- **HTTP/3**: Работает на базе UDP (QUIC), полностью устраняет блокировку очереди (HoL blocking) на уровне транспорта.
- **Требование**: Порт 443/UDP должен быть открыт в Firewall вашей инфраструктуры.

Подробнее: **[Конфигурация HTTP/2 и HTTP/3 в Nginx](../../Performance/nginx_http_versions.md)**.

### 4. Оптимизация 0-RTT (Early Data)

Позволяет отправлять данные в первом же пакете при повторном соединении (TLS 1.3).

```nginx
server {
    # ... базовые настройки ...
    ssl_early_data on;
    
    location / {
        # Передаем бэкенду статус Early Data для защиты от Replay атак
        proxy_set_header Early-Data $ssl_early_data;
        proxy_pass http://app;
    }
}
```

## Дополнительная информация

### См. также

*   **[Глобальные параметры TLS](./nginx_tls_global_parameters.md)** — общие настройки шифров, кэша сессий и OCSP.
*   **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — архитектура, ECH и kTLS.
*   **[Диагностика TLS/SSL](./nginx_tls_troubleshooting_and_compatibility.md)** — отладка ошибок рукопожатия и SNI.
*   **[Let's Encrypt и Certbot](../../../Concepts/https_with_certbot.md)** — автоматизация выпуска сертификатов.
