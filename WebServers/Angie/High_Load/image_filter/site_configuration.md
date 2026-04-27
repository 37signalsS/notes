# Модуль image_filter в Angie: конфигурация сайта (Image Front)

## Определения

**Image Front** — основной проксирующий сервер, принимает запросы клиентов на порту 80/443, проверяет кэш и проксирует запросы на Image Filter при отсутствии файла в кэше.

## Базовые концепции

### Подготовка данных (map)

Для реализации адаптивной доставки (как статической, так и динамической) в основном конфиге `angie.conf` (блок `http`) определяются переменные на основе заголовка `Accept`:

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

### Сценарий 1: Статическая адаптивная доставка

Используется, если изображения уже заранее оптимизированы и лежат на диске рядом с оригиналами (например, `photo.jpg` и `photo.jpg.avif`).

```nginx
location ~* ^/opt/ {
    add_header Vary "Accept";
    # Перебор форматов: AVIF -> WebP -> Оригинал
    try_files $uri$avif_suffix $uri$webp_suffix $uri =404;
    add_header Cache-Control "public, max-age=31536000";
}
```

### Сценарий 2: Динамическая обработка через Image Front

Если файла нет на диске, запрос уходит на внутренний фильтр.

```nginx
server {
    listen 443 ssl http2;
    server_name images.example.com;
    root /var/www/images;

    # Динамический рерайт на основе поддержки браузера
    location ~* ^/img/ {
        # Если браузер поддерживает WebP, запрос уходит на /vp/img/...
        # Переменная $webp_prefix добавит префикс для маршрутизации
        rewrite ^(/img/.*)$ /vp$webp_prefix$1 last;
    }

    # Локация для отдачи и кэширования результатов
    location ~* \.(jpe?g|png|gif)$ {
        add_header Vary "Accept";
        add_header Cache-Control "public, max-age=31536000";

        try_files $uri =404;

        # Если файла нет в кэше/на диске — идем генерировать
        error_page 404 = @resize;
    }

    location @resize {
        internal;
        proxy_pass http://127.0.0.1:8081$request_uri;
        proxy_set_header Host $host;

        proxy_cache image_cache;
        proxy_cache_valid 200 14d;
        proxy_cache_min_uses 1; # Для теста можно 1, для продакшена 2
        proxy_cache_lock on;
        add_header X-Cache-Status $upstream_cache_status;
    }
}
```

### Пояснения к конфигурации

**Рерайт для WebP/AVIF:**

Директива `rewrite` добавляет префикс `/vp` и суффикс формата к URL. Переменная `$webp_suffix` устанавливается на основе заголовка `Accept` клиента (настраивается через `map` в основном конфиге Angie).

**Обработка 404 через именованный location:**

Если файл отсутствует в `root`, запрос передаётся на Image Filter для генерации. Директива `internal` защищает location от прямых запросов клиентов.

### Ключевые директивы кэширования

- `proxy_cache` — зона кэширования для сгенерированных изображений.
- `proxy_cache_valid` — срок валидности кэша (рекомендуется **14 дней** для изображений).
- `proxy_cache_use_stale` — отдача устаревшего кэша при ошибках бэкенда (`error`, `timeout`, `http_500` и др.). Повышает отказоустойчивость.
- `proxy_cache_background_update` — фоновое обновление кэша без блокировки клиента (клиент получает старую версию, пока Nginx асинхронно обновляет кэш).
- `proxy_cache_lock` — предотвращение одновременных одинаковых запросов к бэкенду (thundering herd/«стадо бизонов»). Только первый запрос уходит на генерацию, остальные ждут результата.
- `proxy_cache_min_uses` — кэшировать только после указанного числа запросов (защита от «мусорного» кэширования).

## Дополнительная информация

### Связь с другими компонентами

Image Front работает в паре с [Image Filter](./filter_configuration.md) — внутренним сервером на порту 8081, который выполняет непосредственную обработку изображений (resize, конвертация). Архитектура подробно описана в [обзоре модуля](./overview.md).

### Стратегия кэширования

Кэш хранится на диске в зоне `image_cache` (настраивается в основном конфиге Angie). Рекомендации по настройке кэширования см. в [разделе кэширования](./caching.md).

---

**См. также:**

- [Обзор модуля](./overview.md)
- [Конфигурация фильтра](./filter_configuration.md)
- [Кэширование](./caching.md)
