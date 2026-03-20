# Кэширование в веб-серверах

## Клиентское кэширование (Browser Caching)

Управляется заголовками `Cache-Control` (например, `max-age`, `immutable`), `Expires`, `ETag`.

## Серверное кэширование (Nginx Proxy Cache)

Кэширование ответов от бэкенд-серверов. Значительно снижает нагрузку на бэкенд. Подробно этот механизм рассмотрен в заметке о [кэшировании в Nginx](../Nginx/Performance/Caching/proxy_caching.md).

* Настраивается с помощью `proxy_cache_path`, `proxy_cache`, `proxy_cache_valid`.
* `proxy_use_stale` и `proxy_background_update` позволяют отдавать устаревший контент при проблемах с бэкендом и плавно обновлять кэш.
* **Ограничение:** Стандартный Nginx не имеет встроенных средств для точечной инвалидации кэша.

## Пример конфигурации Nginx Proxy Cache

```nginx
# Определение зоны кэширования в http-блоке
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=my_cache:10m inactive=60m max_size=1g;

# Использование кэша в location
location / {
    proxy_pass http://my_backend;
    proxy_cache my_cache;
    proxy_cache_valid 200 302 1h;
    proxy_cache_valid 404 1m;
    proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
    proxy_cache_background_update on;
    proxy_cache_lock on;
    add_header X-Proxy-Cache $upstream_cache_status;
}
```

---

**Связанные темы:**

* [Компрессия контента](./server_compression.md) — Gzip, Brotli, ZSTD
* [Оптимизация TLS](./tls_optimization.md) — ускорение безопасного соединения
* [Кэширование в Nginx](../Nginx/Performance/Caching/proxy_caching.md)
