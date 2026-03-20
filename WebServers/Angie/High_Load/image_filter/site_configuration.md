# Модуль image_filter в Angie: конфигурация сайта (Image Front)

## Определения

**Image Front** — основной сайт, раздает изображения, кэширует результаты. Работает на порту 80/443.

## Основные концепции

### Конфигурация сайта (Image Front)

## Практические сценарии

### Сценарий 2: Конфигурация сайта (Image Front)

```nginx
server {
    listen 443 ssl http2;
    server_name images.example.com;

    root /var/www/images;

    # Рерайт для поддержки WebP/AVIF
    location ~* ^/img/ {
        rewrite ^(/img/.*)$ /vp$webp_suffix$1 last;
    }

    # Отдача статических изображений
    location ~* \.(jpe?g|png|gif)$ {
        add_header Cache-Control "public, max-age=31536000";
        add_header Expires "Thu, 31 Dec 2037 23:55:55 GMT";
        add_header Vary "Accept";

        try_files $uri =404;

        # Обработка отсутствующих файлов через image_filter
        error_page 404 = @resize;
    }

    # Именованный location для обработки
    location @resize {
        internal;
        proxy_pass http://127.0.0.1:8081$request_uri;
        proxy_set_header Host $host;

        # Кэширование
        proxy_cache image_cache;
        proxy_cache_valid 200 14d;
        proxy_cache_min_uses 2;
        proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;
        proxy_cache_lock on;
    }
}
```

---

**См. также:**
- [Обзор модуля](./overview.md)
- [Установка и базовая настройка](./installation.md)
- [Конфигурация фильтра (внутренний сервер)](./filter_configuration.md)
- [Кэширование](./caching.md)
