# Настройка TLS в Angie

## Определения

**Настройка TLS в Angie** — процесс конфигурации шифрования TLS/SSL для защиты данных, передаваемых между сервером Angie и клиентом. Angie является форком Nginx, поэтому подходы к настройке TLS в них практически идентичны.

## Основные концепции

Angie наследует TLS-архитектуру Nginx: те же директивы (`ssl_certificate`, `ssl_protocols`, `ssl_ciphers`, `ssl_session_cache`), те же механизмы (OCSP Stapling, HSTS, mTLS, Kernel TLS).

**Основным руководством по настройке TLS следует считать:**
> **[Оптимальная настройка TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**

В данном документе рассматриваются только особенности, характерные для Angie.

### Отличия Angie в области TLS

| Возможность | Nginx | Angie |
|:------------|:------|:------|
| HTTP/3 (QUIC) | Требует сборку с `--with-http_v3_module` | Встроенная поддержка, директива `http3 on` |
| ACME-модуль | Внешний (Certbot, acme.sh) | Встроенный модуль `acme` |
| Лицензирование | Open Source / Plus | Бесплатно + коммерческая лицензия |
| TLS-директивы | Полная совместимость | Полная совместимость |

**Подробная документация:**

- ACME-модуль: [Автоматические TLS-сертификаты в Angie](./angie_acme_module.md)
- mTLS: [Аутентификация клиентов в Angie](./angie_client_cert_auth.md)
- Базовая настройка TLS: [Оптимальная настройка TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)

## Практические сценарии

### Сценарий: Настройка HTTP/3 (QUIC)

Конфигурация HTTP/3 в Angie требует UDP-порта и анонсирования через заголовок `Alt-Svc`:

```nginx
server {
    # TCP-порт для HTTP/2 и TLS
    listen 443 ssl http2;
    # UDP-порт для QUIC (HTTP/3)
    listen 443 quic reuseport;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # Включение HTTP/3
    http3 on;

    # Анонсирование поддержки HTTP/3
    add_header Alt-Svc 'h3=":443"; ma=86400';
}
```

**Ключевые директивы:**

- `listen 443 quic reuseport` — прослушивание UDP-порта 443 для QUIC
- `http3 on` — активация поддержки HTTP/3
- `Alt-Svc` — заголовок, сообщающий клиенту о доступности HTTP/3

**Подробная документация по HTTP/3:** [Конфигурация HTTP/2 и HTTP/3 в Nginx](../Nginx/Performance/nginx_http_versions.md)

### Сценарий: Оптимизация отдачи статики (Kernel TLS)

**Kernel TLS (kTLS)** — механизм переноса операций шифрования TLS из пользовательского пространства (OpenSSL) в ядро ОС. Позволяет использовать системный вызов `sendfile` для отдачи статических файлов по HTTPS.

**Основные положения:**

- **Прирост производительности:** ~30% для HTTP/1.1 при отдаче больших файлов
- **Несовместимость с HTTP/2:** использование kTLS с HTTP/2 приводит к деградации производительности в 2-4 раза
- **Требования:** ядро Linux 5.x+, OpenSSL 3.0+, модуль ядра `tls` (`lsmod | grep tls`)

**Краткая конфигурация:**

```nginx
server {
    listen 443 ssl;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # Включение kTLS через TLS 1.3 cipher suites
    ssl_conf_command Ciphersuites TLS_AES_128_GCM_SHA256;

    # Только HTTP/1.1 (HTTP/2 с kTLS даёт деградацию)
    http2 off;
}
```

**Подробная документация:** [Оптимизация производительности Nginx — Kernel TLS](../Nginx/Performance/nginx_performance_tuning.md#kernel-tls-ktls)

## Дополнительная информация

### DNS-запись типа HTTPS

Для информирования клиентов о поддержке HTTP/2 и HTTP/3 можно использовать DNS-запись типа `HTTPS`:

```dns
your_domain.com. IN HTTPS 1 . alpn="h2,h3"
```

**Важно:** Запись типа `HTTPS` несовместима с `CNAME`. Требуется `A` или `AAAA` запись.

**Подробная документация:** [DNS-записи HTTPS/SVCB](../../Networking/Protocols/DNS/dns_records.md)

### См. также

- [Оптимальная настройка TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md) — полное руководство по TLS/SSL
- [Автоматические TLS-сертификаты в Angie](./angie_acme_module.md) — встроенный ACME-модуль
- [Аутентификация клиентов в Angie (mTLS)](./angie_client_cert_auth.md) — взаимная TLS-аутентификация
