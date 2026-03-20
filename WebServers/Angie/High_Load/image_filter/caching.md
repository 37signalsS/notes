# Модуль image_filter в Angie: кэширование

## Определения

**Proxy Cache** — временное хранение сгенерированных изображений с автоматическим управлением (LRU).

**Proxy Store** — постоянное хранение сгенерированных изображений с ручным управлением.

## Основные концепции

### Кэширование результатов

## Практические сценарии

### Сценарий 5: Кэширование результатов

**Proxy Cache (временное хранение):**

```nginx
http {
    proxy_cache_path /var/cache/angie/image_cache
        levels=1:2
        keys_zone=image_cache:10m
        max_size=1g
        inactive=24h
        use_temp_path=off;
}

server {
    location @resize {
        proxy_pass http://127.0.0.1:8081$request_uri;

        proxy_cache image_cache;
        proxy_cache_key $host$uri;
        proxy_cache_valid 200 14d;
        proxy_cache_min_uses 2;  # Кэшировать после 2 запросов
        proxy_cache_use_stale updating error timeout http_500;
        proxy_cache_background_update on;
        proxy_cache_lock on;
    }
}
```

**Proxy Store (постоянное хранение):**

```nginx
location @resize {
    proxy_pass http://127.0.0.1:8081$request_uri;
    proxy_store /var/www/images$uri;
    proxy_store_access user:rw group:rw all:r;
}
```

**Сравнение подходов:**

| Параметр | Proxy Cache | Proxy Store |
|----------|-------------|-------------|
| Хранение | Временное (inactive) | Постоянное |
| Управление | Автоматическое (LRU) | Ручное |
| Дисковое пространство | Ограничено max_size | Не ограничено |
| Гибкость | Высокая | Низкая |
| Подходит для | Частого обновления | Статичного контента |

---

**См. также:**
- [Обзор модуля](./overview.md)
- [Установка и базовая настройка](./installation.md)
- [Конфигурация сайта (Image Front)](./site_configuration.md)
