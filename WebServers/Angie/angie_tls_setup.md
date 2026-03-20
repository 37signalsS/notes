# Настройка TLS в Angie

## Определения

**Настройка TLS в Angie** — это процесс конфигурации шифрования для защиты данных, передаваемых между сервером и клиентом.

## Основные концепции

Поскольку Angie является форком Nginx, подходы к настройке TLS в них практически идентичны.

**Основным и наиболее полным руководством по настройке TLS следует считать заметку:**
> **[Оптимальная настройка TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**

В данном документе рассматриваются только ключевые отличия и особенности, характерные для Angie.

## Практические сценарии

### Сценарий: Настройка HTTP/3 (QUIC)

Конфигурация для включения HTTP/3 в Angie является более прямолинейной по сравнению с Nginx.

```nginx
server {
    # Включаем HTTP/2 для TCP и QUIC (HTTP/3) для UDP
    listen 443 ssl http2;
    listen 443 quic reuseport;

    # ... сертификаты ...
    ssl_certificate /path/to/your_cert.pem;
    ssl_certificate_key /path/to/your_key.pem;

    # Явное включение HTTP/3
    http3 on;

    # Заголовок для обнаружения поддержки HTTP/3 клиентами
    add_header Alt-Svc 'h3=":443"; ma=86400';
}
```

- `listen 443 quic reuseport`: Указывает Angie слушать UDP-порт 443 для протокола QUIC.
- `http3 on`: Включает поддержку HTTP/3.

### Сценарий: Оптимизация отдачи статики (Kernel TLS)

**Kernel TLS (kTLS)** позволяет перенести шифрование TLS в ядро ОС, что даёт возможность использовать `sendfile` для отдачи файлов по HTTPS с приростом производительности ~30%.

**Важно:** kTLS несовместим с HTTP/2 — используйте HTTP/1.1 для отдачи больших файлов.

> **Полная документация:** [Оптимизация производительности Nginx](../Nginx/Performance/nginx_performance_tuning.md#kernel-tls-ktls) — SSoT по Kernel TLS

**Краткая конфигурация:**

```nginx
server {
    listen 443 ssl;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # Включение kTLS
    ssl_conf_command Ciphersuites TLS_AES_128_GCM_SHA256;
    
    # Только HTTP/1.1 (HTTP/2 с kTLS даёт деградацию)
    http2 off;
}
```

**Требования:**

- Ядро Linux 5.x+
- OpenSSL 3.0+
- Модуль ядра `tls` (`lsmod | grep tls`)

## Дополнительная информация

### DNS-запись типа HTTPS

Для информирования клиентов о поддержке HTTP/3 можно использовать DNS-запись типа `HTTPS`, которая позволяет браузеру сразу установить соединение по самому современному протоколу.

**Пример:**

```dns
your_domain.com. IN HTTPS 1 . alpn="h2,h3"
```

**Важно:** Запись типа `HTTPS` несовместима с `CNAME`. Требуется `A` или `AAAA` запись.

**Подробная документация:** [DNS-записи HTTPS/SVCB](../../Networking/Protocols/DNS/dns_records.md#записи-для-сервисов)

**Для всех остальных аспектов настройки TLS** (Keep-Alive, кэширование сессий, использование EC/RSA сертификатов, проверка конфигурации) следует обращаться к основному [руководству по настройке Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md).
