# Модуль image_filter в Angie: конфигурация сайта

## Определения

**Image Front** — основной проксирующий сервер (фронтенд), который принимает запросы клиентов, управляет логикой выбора формата изображения (WebP/AVIF), проверяет наличие файлов в кэше и перенаправляет запросы на внутренний сервер фильтрации.

## Базовые концепции

Для реализации адаптивной доставки изображений в Angie используется заголовок `Accept`, на основе которого определяются переменные для выбора оптимального формата. Эти директивы `map` должны располагаться в контексте `http` (обычно в файле `angie.conf`).

### Подготовка переменных (map)

```nginx
# Определение суффиксов для статической адаптивной доставки (try_files)
map $http_accept $webp_suffix {
    "~*webp"  ".webp";
    default   "";
}
map $http_accept $avif_suffix {
    "~*avif"  ".avif";
    default   "";
}

# Определение префиксов для динамической обработки (rewrite)
map $http_accept $webp_prefix {
    "~*webp"  "-vp";
    default   "";
}
map $http_accept $avif_prefix {
    "~*avif"  "-avif";
    default   "";
}
```

## Практические сценарии

### Сценарий: Статическая адаптивная доставка

Используется, если оптимизированные версии изображений уже существуют на диске (например, созданы заранее или сохранены через `proxy_store`).

```nginx
location ~* ^/opt/ {
    add_header Vary "Accept";
    # Последовательный поиск: AVIF -> WebP -> Оригинал
    try_files $uri$avif_suffix $uri$webp_suffix $uri =404;
    add_header Cache-Control "public, max-age=31536000";
}
```

### Сценарий: Динамическая обработка с кэшированием

Основной сценарий работы `image_filter`, при котором отсутствующие версии генерируются «на лету» и сохраняются в кэше.

```nginx
server {
    listen 443 ssl http2;
    server_name images.example.com;
    root /var/www/images;

    # Маршрутизация на основе поддержки форматов браузером
    location ~* ^/img/ {
        # Рерайт добавляет префикс /vp или -avif для выбора нужной ветки обработки
        rewrite ^(/img/.*)$ /vp$webp_prefix$1 last;
    }

    # Локация для отдачи файлов из корня или кэша
    location ~* \.(jpe?g|png|gif)$ {
        add_header Vary "Accept";
        add_header Cache-Control "public, max-age=31536000";

        try_files $uri =404;

        # Если файл не найден — переходим к генерации
        error_page 404 = @resize;
    }

    location @resize {
        internal;
        proxy_pass http://127.0.0.1:8081$request_uri;
        proxy_set_header Host $host;

        # Настройки кэширования (см. раздел по кэшированию)
        proxy_cache image_cache;
        proxy_cache_valid 200 14d;
        proxy_cache_lock on;
        add_header X-Cache-Status $upstream_cache_status;
    }
}
```

## Дополнительная информация

### Архитектурные особенности

- **Разделение ролей:** Image Front не должен выполнять операции фильтрации напрямую. Его задача — эффективная раздача и кэширование. Непосредственная обработка выполняется на [Image Filter](./filter_configuration.md).
- **Кэширование:** Подробное описание директив `proxy_cache`, `proxy_cache_lock` и других параметров приведено в [разделе кэширования](./caching.md).
- **Безопасность:** Рекомендуется ограничивать доступ к внутреннему серверу фильтрации (порт 8081), разрешая запросы только с IP фронтенда.

---

**См. также:**

- [Обзор модуля image_filter](./overview.md)
- [Конфигурация Image Filter](./filter_configuration.md)
- [Кэширование изображений](./caching.md)
