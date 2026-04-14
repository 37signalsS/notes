# Модуль image_filter в Angie: конфигурация сайта (Image Front)

## Определения

**Image Front** — основной проксирующий сервер, принимает запросы клиентов на порту 80/443, проверяет кэш и проксирует запросы на Image Filter при отсутствии файла в кэше.

## Базовые концепции

### Принцип работы

Image Front выполняет следующие задачи:

1. **Приём запросов:** обрабатывает HTTPS-запросы с SSL-терминацией
2. **Проверка кэша:** ищет сгенерированные изображения в `proxy_cache`
3. **Рерайт URL:** преобразует запросы для поддержки WebP/AVIF через переменные
4. **Проксирование:** перенаправляет запросы на внутренний Image Filter (порт 8081) при cache miss
5. **Кэширование:** сохраняет результаты обработки для повторной отдачи
6. **Отдача статики:** возвращает кэшированные изображения с заголовками `Cache-Control` и `Vary`

### Ключевые директивы

- `proxy_cache` — зона кэширования для сгенерированных изображений
- `proxy_cache_valid` — срок валидности кэша (рекомендуется 14 дней для изображений)
- `proxy_cache_use_stale` — отдача устаревшего кэша при ошибках бэкенда
- `proxy_cache_background_update` — фоновое обновление кэша без блокировки клиента
- `proxy_cache_lock` — предотвращение одновременных одинаковых запросов к бэкенду (thundering herd)

## Практические сценарии

### Базовая конфигурация Image Front

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

### Пояснения к конфигурации

**Рерайт для WebP/AVIF:**

Директива `rewrite` добавляет префикс `/vp` и суффикс формата к URL. Переменная `$webp_suffix` устанавливается на основе заголовка `Accept` клиента (настраивается через `map` в основном конфиге Angie).

**Обработка 404 через именованный location:**

Если файл отсутствует в `root`, запрос передаётся на Image Filter для генерации. Директива `internal` защищает location от прямых запросов клиентов.

**Параметры кэширования:**

- `proxy_cache_min_uses 2` — кэшировать только после 2 запросов (защита от кэширования единичных запросов)
- `proxy_cache_use_stale` — при ошибках бэкенда отдавать устаревший кэш вместо ошибки
- `proxy_cache_background_update` — обновлять кэш в фоне, клиент получает старую версию немедленно
- `proxy_cache_lock on` — блокировка параллельных одинаковых запросов (только первый идёт на бэкенд)

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
