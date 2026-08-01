# Руководство по безопасности веб-сервера Nginx и Angie

**Надёжность:** 10 (SSoT + OWASP Hardening + Рекомендации Mozilla 2026)
**Свежесть:** Июль 2026 (Актуально для Nginx 1.26+, 1.27.x+, Angie 1.12+)

## Определения

*   **DoS (Denial of Service) / DDoS** — атаки, направленные на нарушение доступности сервиса через исчерпание ресурсов сервера (CPU, RAM, пропускная способность сети).
*   **Базовая аутентификация (`auth_basic`)** — метод проверки учетных данных в HTTP, передаваемых в заголовке `Authorization` в Base64.
*   **HTTP-заголовки безопасности (Security Headers)** — специальные инструкции для браузера, предотвращающие атаки на стороне клиента (XSS, Clickjacking, MIME-sniffing).
*   **Content Security Policy (CSP)** — механизм контроля доверенных источников контента. Стандарт 2026 года использует `strict-dynamic` для защиты от обхода через доверенные CDN.
*   **HSTS (HTTP Strict Transport Security)** — заголовок, заставляющий браузер использовать исключительно HTTPS, предотвращая атаки SSL Stripping.
*   **Изоляция ресурсов (COOP/COEP/CORP)** — (Стандарт 2026) заголовки, предотвращающие утечки данных через побочные каналы ( Spectre) в браузерной среде.

## Основные концепции

Защита Nginx/Angie — это многослойный процесс, охватывающий сетевой уровень, конфигурацию сервера и логику обработки браузером.

### Защита от DoS/DDoS-атак

Защита на уровне одного сервера эффективна против примитивного флуда и попыток подбора паролей. Для масштабных распределенных атак необходимо использовать внешние сервисы (WAF, Scrubbing centers).

Для локальной защиты используются модули ограничения частоты запросов (`limit_req`) и соединений (`limit_conn`).

**Особенности Angie (Cluster Sync):**
В отличие от Nginx OSS, **Angie** поддерживает параметр `sync` в директивах `limit_req_zone` и `limit_conn_zone`. Это позволяет синхронизировать состояние лимитов между несколькими узлами балансировщика в реальном времени, обеспечивая честное ограничение трафика во всем кластере.

> **[Полное руководство по DoS-защите в Angie/Nginx](../../Angie/High_Load/dos_protection.md)**

### Контроль доступа

Механизмы контроля позволяют четко разграничить доступ к административным и инфраструктурным ресурсам.

> **[Детальный разбор контроля доступа в Angie/Nginx](../../Angie/angie_access_control.md)**

**Ключевые векторы:**
*   **Ограничение по IP**: Доступ к `/admin` только из доверенных сетей или VPN.
*   **Аутентификация через подзапрос (`auth_request`)**: Передача проверки прав внешнему сервису (OIDC, LDAP).
*   **Минимизация методов**: Отключение `PUT`, `DELETE`, `TRACE`, если они не требуются API.
*   **Защита инфраструктуры**: Блокировка доступа к `.git`, `.env`, `.ssh` и другим чувствительным данным.

### Усиление безопасности через заголовки

Заголовки безопасности — это первая линия обороны пользователей. Параметр `always` в директиве `add_header` критически важен: он гарантирует отправку заголовка даже в ответах с ошибками (404, 500), где злоумышленник может искать зацепки.

### Безопасная эксплуатация и системный Hardening

*   **Сокрытие версии**: Использование `server_tokens off;` для минимизации информации о стеке.
*   **Мониторинг**: Настройка детального логирования (`access_log`, `error_log`) с уровнями `warn` и `info` для TLS-диагностики.
*   **Права доступа**: Строгое разделение прав между процессом Nginx (пользователь `www-data`/`nginx`) и владельцем конфигурационных файлов (`root`).

---

## Практические сценарии

### 1. Защита от DoS на уровне протокола

Ограничение количества заголовков и размеров буферов для борьбы с Header Flooding и Slowloris.

```nginx
http {
    # Лимит количества заголовков (Nginx 1.29+ / Angie 1.4+)
    max_headers 100;

    # Тайм-ауты для борьбы с медленными соединениями
    client_body_timeout 10s;
    client_header_timeout 10s;
    keepalive_timeout 65s;
    send_timeout 10s;

    # Буферы: защищают RAM от переполнения большими запросами
    client_body_buffer_size 16k;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;

    # Лимиты с корректным статус-кодом (429 Too Many Requests)
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_status 429;
}
```

### 2. Кластерная синхронизация лимитов (Только Angie)

Синхронизация состояния через общую память (требует модуля `ngx_stream_zone_sync_module` в `stream` блоке).

```nginx
http {
    # Параметр sync активирует обмен данными между узлами кластера
    limit_req_zone $binary_remote_addr zone=cluster_limit:20m rate=100r/s sync;
}
```

### 3. Блокировка конфиденциальных данных

Защита файлов систем контроля версий и окружения.

```nginx
# Блокировка доступа ко всем скрытым файлам (начинающимся с точки)
location ~ /\.(?!well-known) {
    deny all;
    return 404; # Скрываем факт существования файла
}

# Блокировка специфических файлов
location ~ /(config\.php|wp-config\.php|\.env|composer\.json) {
    deny all;
}
```

### 4. Запрет на выполнение скриптов в каталогах загрузки

Критично для предотвращения атак типа Web Shell.

```nginx
location /static/uploads/ {
    # Запрет на выполнение PHP
    location ~ \.php$ {
        deny all;
    }
    # Запрет на выполнение других скриптовых языков
    location ~ \.(pl|py|sh|cgi|exe)$ {
        return 403;
    }
}
```

### 5. Современные HTTP-заголовки безопасности (2026)

Комплексный набор для защиты от большинства клиентских атак.

```nginx
server {
    listen 443 ssl;
    # ... TLS настройки (TLS 1.3, ECDSA) ...

    # 1. HSTS (2 года + поддомены + preload)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # 2. Clickjacking & MIME-Sniffing
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    # 3. Referrer & Permissions Policy (2026 Standard)
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), usb=(), payment=()" always;

    # 4. Изоляция кросс-доменных ресурсов (Защита от Spectre)
    add_header Cross-Origin-Opener-Policy "same-origin" always;
    add_header Cross-Origin-Resource-Policy "same-origin" always;

    # 5. Content-Security-Policy (CSP) с strict-dynamic
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'nonce-$cspNonce' 'strict-dynamic'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; upgrade-insecure-requests;" always;
}
```

### 6. Сокрытие версии и заголовков бэкенда

```nginx
http {
    # Скрытие версии Nginx
    server_tokens off;
    
    # Лимит размера тела запроса (защита от загрузки гигантских файлов)
    client_max_body_size 10M;
}

# В контексте проксирования
location / {
    # Скрытие информации о стеке бэкенда
    proxy_hide_header X-Powered-By;
    proxy_hide_header Server;
    proxy_pass http://backend;
}
```

### 7. Системные права доступа (Hardening)

```bash
# Исполняемые файлы и конфиги — только для root
sudo chown -R root:root /etc/nginx
sudo chmod -R 755 /etc/nginx
sudo chmod 640 /etc/nginx/nginx.conf

# Директории сайта — владелец myuser, группа www-data
sudo chown -R myuser:www-data /var/www/mysite
sudo find /var/www/mysite -type d -exec chmod 755 {} \;
sudo find /var/www/mysite -type f -exec chmod 644 {} \;
```

## Дополнительная информация

### См. также

*   **[Оптимальная настройка TLS/SSL в Nginx](./TLS_SSL/nginx_tls_ssl_overview.md)** — полное руководство по шифрованию.
*   **[Диагностика Nginx](../Operations/nginx_troubleshooting.md)** — методы анализа логов на наличие атак.
*   **[Обзор DoS/DDoS-атак](../../../Networking/Concepts/dos_ddos_overview.md)** — теоретическая база.
*   **[Security Headers Checklist (OWASP)](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Strict_Transport_Security_Cheat_Sheet.html)** — внешняя база знаний.
*   **[Mozilla Observatory](https://observatory.mozilla.org/)** — инструмент для проверки заголовков сайта.
