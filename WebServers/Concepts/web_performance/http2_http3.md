# HTTP/2 и HTTP/3

Подробную информацию о принципах работы и конфигурации этих протоколов в Nginx можно найти в документе: [Конфигурация HTTP/2 и HTTP/3 в Nginx](../Nginx/Performance/nginx_http_versions.md).

## HTTP/2

* **Мультиплексирование:** Устраняет проблему "блокировки начала очереди" (head-of-line blocking) на уровне приложения, позволяя отправлять несколько запросов по одному TCP-соединению.
* **Сжатие заголовков (HPACK).**

## HTTP/3

* **Основан на QUIC (UDP):** Решает проблему Head-of-Line Blocking на транспортном уровне.
* **Встроенный TLS:** Ускоряет установление соединения (0-RTT или 1-RTT).
* **Обнаружение клиентами:** Браузер узнаёт о поддержке HTTP/3 через заголовок `Alt-Svc` (проблема «холодного старта») или DNS-запись типа `HTTPS` (предпочтительный вариант).

## Пример конфигурации Nginx/Angie для HTTP/3

```nginx
# Требует Nginx 1.25.0+ или современную Angie
listen 443 ssl quic reuseport; # Слушаем UDP порт 443 для QUIC
listen 443 ssl http2;         # Слушаем TCP порт 443 для HTTP/2 и HTTP/1.1

http3 on;
add_header Alt-Svc 'h3=":443"; ma=86400';
```

## Рекомендация

Настройте DNS-запись типа `HTTPS` для ускорения первой загрузки:

```dns
example.com HTTPS 1 . alpn="h2,h3"
```

**Подробно:** [DNS-записи HTTPS/SVCB](../Networking/Protocols/DNS/dns_records.md#записи-для-сервисов), [Конфигурация HTTP/2 и HTTP/3 в Nginx](../Nginx/Performance/nginx_http_versions.md)

---

**Связанные темы:**

* [Оптимизация TLS](./tls_optimization.md) — ускорение безопасного соединения
* [Компрессия контента](./server_compression.md) — Gzip, Brotli, ZSTD
* [Кэширование](./caching.md) — клиентское и серверное кэширование
