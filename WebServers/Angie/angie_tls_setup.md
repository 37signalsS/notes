# Настройка TLS в Angie

## Определения

**Настройка TLS в Angie** — процесс конфигурации протокола TLS (Transport Layer Security) для обеспечения конфиденциальности, целостности и подлинности данных между сервером и клиентом. 

Angie, являясь форком Nginx, поддерживает все классические механизмы шифрования, но предлагает расширенные возможности «из коробки», такие как встроенный HTTP/3, автоматизация сертификатов (ACME) и упрощенное управление двухстековыми конфигурациями.

## Базовые концепции

### Связь с экосистемой Nginx

Angie полностью совместим с TLS-директивами Nginx. Общие принципы настройки OCSP Stapling, HSTS и базовых параметров безопасности описаны в SSoT-документе:
> **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**

### Ключевые отличия и преимущества Angie

*   **Нативный HTTP/3:** Поддержка QUIC встроена в ядро (не требует отдельной сборки модуля).
*   **Встроенный ACME:** Управление сертификатами (Let's Encrypt и др.) без использования внешних утилит типа Certbot.
*   **Автоматизация тикетов:** Автоматическая генерация и ротация ключей `ssl_session_tickets` между всеми рабочими процессами.
*   **Двухстековые сертификаты:** Упрощенная настройка одновременного использования RSA и ECDSA.

## Практические сценарии
### Сценарий 1: Настройка HTTP/3 (QUIC)

Angie обеспечивает нативную поддержку HTTP/3 "из коробки" (не требует сборки сторонних модулей). Для активации необходимо открыть UDP-порт 443 и анонсировать поддержку через заголовок `Alt-Svc`.

Подробные примеры конфигурации, включая оптимизацию eBPF и 0-RTT, приведены в основном руководстве:

→ **[Конфигурация HTTP/2 и HTTP/3 в Nginx/Angie](../Nginx/Performance/nginx_http_versions.md)**

---
### Сценарий 2: Двухстековые сертификаты (RSA + ECDSA)

Для обеспечения максимальной скорости (ECDSA) при сохранении совместимости со старыми клиентами (RSA) используйте обе директивы одновременно. Angie выберет оптимальный вариант автоматически.

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    # RSA сертификат (для старых систем)
    ssl_certificate     /etc/angie/ssl/example.com.rsa.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.rsa.key;

    # ECDSA сертификат (для современных систем - приоритет)
    ssl_certificate     /etc/angie/ssl/example.com.ecdsa.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.ecdsa.key;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
}
```

### Сценарий 3: Возобновление сессий (Session Caching)

Для снижения нагрузки на CPU при повторных рукопожатиях настройте разделяемый кэш.

```nginx
http {
    # 10 МБ кэша вмещают ~40 000 сессий
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    # Тикеты включены по умолчанию, ключи ротируются автоматически
    ssl_session_tickets on;
}
```

## Дополнительная информация

### Автоматизация через ACME

Вместо внешней настройки Certbot, используйте встроенный функционал:
*   [Автоматические TLS-сертификаты в Angie: модуль ACME](./angie_acme_module.md)

### Оптимизация производительности

Для высоконагруженных систем рекомендуется использовать Kernel TLS (kTLS) для ускорения `sendfile` через HTTPS.
*   [Оптимизация производительности Nginx — Kernel TLS](../Nginx/Performance/nginx_performance_tuning.md#kernel-tls-ktls)

## См. также

*   [Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)
*   [Взаимная аутентификация (mTLS) в Angie](./angie_client_cert_auth.md)
*   [Конфигурация HTTP/2 и HTTP/3 в Nginx](../Nginx/Performance/nginx_http_versions.md)
