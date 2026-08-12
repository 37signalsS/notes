# Конфигурация виртуальных хостов TLS в Nginx

## Определения

**Виртуальный хост TLS (`server`)** — блок конфигурации Nginx, описывающий настройки безопасности и логику обработки запросов для конкретного доменного имени. Параметры, заданные внутри `server`, имеют приоритет над глобальными настройками из блока `http`, что позволяет гибко настраивать разные уровни защиты для разных сайтов на одном сервере.

## Основные концепции

### Базовая конфигурация HTTPS (2026)

Современный стандарт 2026 года требует одновременной поддержки TCP (HTTP/1.1, HTTP/2) и UDP (HTTP/3) протоколов, а также использования защищенных методов обработки рукопожатия и скрытия SNI через ECH.

```nginx
server {
    # --- Сетевые интерфейсы (Dual Stack + HTTP/3) ---
    # TCP порт 443 для TLS (HTTP/1.1 и HTTP/2)
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on; # Нативная активация в Nginx 1.30+

    # UDP порт 443 для QUIC (HTTP/3)
    # reuseport включается один раз на IP:PORT в основном конфиге
    listen 443 quic;
    listen [::]:443 quic;
    http3 on;

    server_name example.com www.example.com;

    # --- Приватность (ECH) ---
    # Шифрование SNI (требует OpenSSL 4.0+)
    ssl_ech_file /etc/nginx/ech/example_com.config;

    # --- Сертификаты (ECDSA + RSA) ---
    # ECDSA — приоритетный (высокая производительность, ключи P-256/P-384)
    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # RSA — резервный (для совместимости со старыми клиентами)
    ssl_certificate     /etc/letsencrypt/live/example.com-rsa/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com-rsa/privkey.pem;

    # --- Усиление безопасности (Hardening) ---
    # HSTS (2 года + поддомены + preload)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    
    # Информирование браузера о поддержке HTTP/3 (QUIC)
    add_header Alt-Svc 'h3=":443"; ma=86400';

    # Постквантовая защита (Hybrid PQC) на уровне хоста
    ssl_ecdh_curve X25519MLKEM768:X25519;

    location / {
        proxy_pass http://backend_upstream;
    }
}
```

## Практические сценарии

### 1. Безопасный редирект HTTP → HTTPS

Все запросы на порт 80 должны перенаправляться на защищенную версию сайта с использованием кода 301. Важно сохранять доступность для проверок ACME.

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # Исключение для HTTP-01 вызова Let's Encrypt
    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
```

### 2. Защита от сканирования SNI (`ssl_reject_handshake`)

Критически важная настройка для `default_server`. Позволяет обрывать соединение на стадии TLS-рукопожатия, если клиент запрашивает неизвестный домен или обращается напрямую по IP. Это предотвращает утечку вашего сертификата (и доменного имени в нем) случайным сканерам.

```nginx
# В файле /etc/nginx/conf.d/default.conf
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    # Обрыв рукопожатия без передачи сертификата (Nginx 1.19.4+)
    ssl_reject_handshake on;
}
```

### 3. Оптимизация производительности (0-RTT и OCSP)

Для минимизации задержек (TTFB) рекомендуется настраивать возобновление сессий и степлинг на уровне виртуального хоста.

```nginx
server {
    # ... базовые настройки ...

    # TLS 1.3 0-RTT (Early Data)
    ssl_early_data on;
    
    # OCSP Stapling (индивидуальный резолвер для хоста)
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    location / {
        # Передаем бэкенду статус Early Data для предотвращения Replay атак
        proxy_set_header Early-Data $ssl_early_data;
        proxy_pass http://app;
    }
}
```

### 4. Настройка QUIC и HTTP/3

В 2026 году QUIC является основным протоколом для мобильного трафика. Обратите внимание на настройки повторных попыток для защиты от UDP-флуда.

- **`http3 on;`**: Включает поддержку протокола.
- **`quic_retry on;`**: Защищает от атак с подменой IP (UDP amplification) через проверку токена.
- **`add_header Alt-Svc`**: Обязательный заголовок для переключения клиентов с TCP на UDP.

Подробнее о системном тюнинге: **[Конфигурация HTTP/2 и HTTP/3 в Nginx](../../Performance/nginx_http_versions.md)**.

## Дополнительная информация

### См. также

*   **[Глобальные параметры TLS](./nginx_tls_global_parameters.md)** — общие настройки шифров, кэша сессий и PQC.
*   **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — архитектура, kTLS и определения.
*   **[Диагностика TLS/SSL](./nginx_tls_troubleshooting_and_compatibility.md)** — отладка ошибок рукопожатия и совместимость.
*   **[Let's Encrypt и Certbot](../../../Concepts/https_with_certbot.md)** — автоматизация выпуска и обновления сертификатов.
