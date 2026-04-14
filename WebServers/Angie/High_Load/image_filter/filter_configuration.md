# Конфигурация Image Filter в Angie

## Определения

**Image Filter** — внутренний сервер на порту 8081, обрабатывает изображения: конвертация форматов, resize, оптимизация качества.

## Базовые концепции

### Принцип работы

Внутренний сервер принимает запросы от Image Front (проксирующего сервера), обрабатывает изображения и возвращает результат клиенту. Такая архитектура позволяет отделить логику обработки изображений от основной конфигурации сайта.

### Основные директивы

- `image_filter` — тип обработки (`resize`, `webp`, `avif`)
- `image_filter_jpeg_quality` / `image_filter_webp_quality` / `image_filter_avif_quality` — качество выходного изображения (1–100)
- `image_filter_interlaced` — прогрессивная развертка для JPEG
- `image_filter_sharpen` — повышение резкости (0–100)
- `error_page 415 = @empty` — обработка неподдерживаемых форматов

## Практические сценарии

### JPEG с resize

Конвертация и изменение размера JPEG-изображений с прогрессивной разверткой и повышением резкости:

```nginx
location ~* ^/vp(/img/)(\d+)x(\d+)(.+\.jpe?g)$ {
    image_filter resize $2 $3;
    image_filter_jpeg_quality 80;
    image_filter_interlaced on;
    image_filter_sharpen 1;

    error_page 415 = @empty;
}
```

### PNG/GIF без resize

Конвертация PNG/GIF без изменения размеров, только повышение резкости:

```nginx
location ~* ^/vp(/img/.+\.(png|gif))$ {
    image_filter_sharpen 1;
    error_page 415 = @empty;
}
```

### Конвертация в WebP с resize

Изменение размера и конвертация в формат WebP:

```nginx
location ~* ^/vp(/img/)(\d+)x(\d+)(.+\.(jpe?g|png|gif))$ {
    image_filter webp;
    image_filter resize $2 $3;
    image_filter_webp_quality 80;
    image_filter_sharpen 1;
    error_page 415 = @empty;
}
```

### Конвертация в WebP без resize

Только конвертация в WebP без изменения размеров:

```nginx
location ~* ^/vp(/img/.+\.(jpe?g|png|gif))$ {
    image_filter webp;
    image_filter_webp_quality 80;
    error_page 415 = @empty;
}
```

### Конвертация в AVIF

Конвертация в формат AVIF (требует наличие библиотеки `libavif`):

```nginx
location ~* ^/avif(/img/.+\.(jpe?g|png|gif))$ {
    image_filter avif;
    image_filter_avif_quality 80;
    error_page 415 = @empty;
}
```

### Полная конфигурация внутреннего сервера

```nginx
server {
    listen 127.0.0.1:8081;
    server_name localhost;

    root /var/www/images;

    # Обработка JPEG с resize
    location ~* ^/vp(/img/)(\d+)x(\d+)(.+\.jpe?g)$ {
        image_filter resize $2 $3;
        image_filter_jpeg_quality 80;
        image_filter_interlaced on;
        image_filter_sharpen 1;

        error_page 415 = @empty;
    }

    # Конвертация PNG/GIF без resize
    location ~* ^/vp(/img/.+\.(png|gif))$ {
        image_filter_sharpen 1;
        error_page 415 = @empty;
    }

    # Конвертация в WebP с resize
    location ~* ^/vp(/img/)(\d+)x(\d+)(.+\.(jpe?g|png|gif))$ {
        image_filter webp;
        image_filter resize $2 $3;
        image_filter_webp_quality 80;
        image_filter_sharpen 1;
        error_page 415 = @empty;
    }

    # Конвертация в WebP без resize
    location ~* ^/vp(/img/.+\.(jpe?g|png|gif))$ {
        image_filter webp;
        image_filter_webp_quality 80;
        error_page 415 = @empty;
    }

    # Конвертация в AVIF (требует libavif)
    location ~* ^/avif(/img/.+\.(jpe?g|png|gif))$ {
        image_filter avif;
        image_filter_avif_quality 80;
        error_page 415 = @empty;
    }

    # Пустой GIF для неподдерживаемых форматов
    location @empty {
        default_type image/gif;
        return 200 "\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b";
    }
}
```

---

**См. также:**

- [Обзор модуля](./overview.md)
- [Установка и базовая настройка](./installation.md)
- [Конфигурация сайта](./site_configuration.md)
