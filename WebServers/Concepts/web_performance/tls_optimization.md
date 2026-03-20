# Оптимизация TLS

Оптимизация TLS сокращает время установки безопасного соединения, которое может занимать до 4 RTT.

## Основные рекомендации

### Версии TLS

Используйте **TLS 1.2** и **TLS 1.3**. TLS 1.3 значительно сокращает количество RTT для установки соединения (до 1 RTT или 0-RTT).

### Сертификаты

Используйте **ECDSA-сертификаты** вместо RSA для меньшей нагрузки. Рекомендуется использовать пары сертификатов RSA и ECDSA.

### Кэширование сессий

Включите **Session Cache** или **Session Tickets**.

### HSTS (HTTP Strict Transport Security)

Заголовок, заставляющий браузеры всегда использовать HTTPS. **Внимание:** HSTS — очень жесткий кэш, включайте его только после полной уверенности в корректности настройки HTTPS.

### Инструменты

* **Mozilla TLS Configurator**
* **SSL Labs Server Test**

## Пример конфигурации Nginx/Angie для TLS

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
ssl_prefer_server_ciphers on;
ssl_dhparam /etc/nginx/dhparam.pem; # openssl dhparam -out /etc/nginx/dhparam.pem 2048

ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;

add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
```

---

**Связанные темы:**

* [Компрессия контента](./server_compression.md) — Gzip, Brotli, ZSTD
* [HTTP/2 и HTTP/3](./http2_http3.md) — современные протоколы
* [Конфигурация HTTP/2 и HTTP/3 в Nginx](../Nginx/Performance/nginx_http_versions.md)
