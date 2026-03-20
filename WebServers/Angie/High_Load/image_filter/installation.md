# Модуль image_filter в Angie: установка и базовая настройка

## Определения

**Модуль image_filter** — динамический модуль Angie для обработки изображений на лету: конвертация форматов (WebP, AVIF), изменение размеров (resize), оптимизация качества.

## Основные концепции

### Базовая настройка image_filter

## Практические сценарии

### Сценарий 1: Базовая настройка image_filter

**Установка:**

```bash
# Установка Angie и модуля image_filter
apt install angie angie-module-image-filter
```

**Конфигурация:**

```nginx
# /etc/angie/angie.conf
load_module modules/ngx_http_image_filter_module.so;

http {
    # Определение поддержки форматов браузером
    map $http_accept $webp_suffix {
        default "";
        "~*webp" ".webp";
    }

    map $http_accept $avif_suffix {
        default "";
        "~*avif" ".avif";
    }

    # Кэширование (опционально, см. сценарий 3)
    proxy_cache_path /var/cache/angie/image_cache
        levels=1:2
        keys_zone=image_cache:10m
        max_size=1g
        inactive=24h;
}
```

---

**См. также:**
- [Обзор модуля](./overview.md)
- [Конфигурация сайта (Image Front)](./site_configuration.md)
- [Конфигурация фильтра (внутренний сервер)](./filter_configuration.md)
- [Кэширование](./caching.md)
