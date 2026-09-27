# Image Optimization Pipeline для веб-производительности

## Определения

**AVIF (AV1 Image File Format)** — формат изображений на базе кодека AV1. В 2026 году является приоритетным форматом для веб-изображений: обеспечивает плотность сжатия на 20-30% выше, чем WebP, при том же качестве.

**WebP** — формат изображений от Google. Является fallback для AVIF. Поддерживается всеми актуальными браузерами, кроме старых версий Safari (<14).

**Responsive Images** — подход доставки изображений, при котором браузер получает изображение, оптимизированное под размер viewport, разрешение экрана и условия сети.

**Adaptive Images** — техника доставки изображений через `Accept` заголовок: прокси анализирует `Accept: image/avif,image/webp` и отдаёт наиболее эффективный формат из предварительно сгенерированных версий.

**Content Negotiation** — процесс согласования формата изображения между клиентом и сервером через заголовки `Accept` и `Vary`.

**LCP Image (Largest Contentful Paint Image)** — изображение, определяющее LCP. Оптимизация LCP-изображения имеет наивысший приоритет в performance budget.

## Основные концепции

### Форматы изображений: сравнение 2026

| Формат | Сжатие | Поддержка браузерами | Использование |
| :--- | :--- | :--- | :--- |
| **AVIF** | Лучшее (AV1) | Chrome 85+, Firefox 93+, Safari 16+ | Приоритетный формат для LCP-изображений |
| **WebP** | Хорошее (VP8/VP9) | Все актуальные браузеры | Fallback для AVIF |
| **JPEG XL** | Отличное | Поддержка отменена в Chrome | Не использовать в 2026 |
| **JPEG** | Среднее | Универсальная | Fallback для очень старых браузеров |
| **PNG** | Без потерь | Универсальная | Только для прозрачности и скриншотов |

### Влияние на Core Web Vitals

LCP-изображение — самый критичный ресурс на странице:

| Оптимизация | Влияние на LCP | Влияние на CLS | Влияние на bandwidth |
| :--- | :--- | :--- | :--- |
| **AVIF вместо JPEG** | -20-30% размера | Нет прямого влияния | -50-70% |
| **WebP вместо JPEG** | -15-25% размера | Нет прямого влияния | -40-60% |
| **Responsive (srcset)** | -30-50% на мобильных | Нет прямого влияния | -40-60% |
| **Lazy Loading (non-LCP)** | Нет влияния на LCP | -0.02-0.05 CLS | -20-30% |

### Архитектура pipeline

```
Upload (原始 изображение)
    ↓
[CI/CD] Генерация вариантов
    ├── photo.jpg (оригинал)
    ├── photo.avif (AVIF, quality 50-60)
    ├── photo.webp (WebP, quality 70-80)
    ├── photo-480w.jpg (480px width)
    ├── photo-800w.jpg (800px width)
    └── photo-1200w.jpg (1200px width)
    ↓
[CDN/PROXY] Adaptive delivery
    ├── Accept: image/avif → photo.avif
    ├── Accept: image/webp → photo.webp
    └── Accept: image/jpeg → photo.jpg
    ↓
[CLIENT] Браузер получает оптимальный формат
```

## Практические сценарии

### Сценарий 1: Генерация AVIF/WebP в CI/CD

```bash
#!/bin/bash
# build-images.sh — CI/CD этап

SRC_DIR="dist/images"
QUALITY_AVIF=55
QUALITY_WEBP=75
SIZES=(480 800 1200)

# Генерация AVIF и WebP
for img in "$SRC_DIR"/*.{jpg,jpeg,png}; do
  base=$(basename "$img" .${img##*.})

  # AVIF (приоритетный)
  if command -v avifenc &> /dev/null; then
    avifenc --min 50 --max 60 --speed 6 "$img" "$SRC_DIR/${base}.avif"
  fi

  # WebP (fallback)
  if command -v cwebp &> /dev/null; then
    cwebp -q $QUALITY_WEBP -m 6 "$img" -o "$SRC_DIR/${base}.webp"
  fi

  # Responsive sizes
  for size in "${SIZES[@]}"; do
    convert "$img" -resize "${size}x" "$SRC_DIR/${base}-${size}w.jpg"
    # Опционально: AVIF/WebP для каждого размера
    if command -v avifenc &> /dev/null; then
      avifenc --min 50 --max 60 --speed 6 "$SRC_DIR/${base}-${size}w.jpg" "$SRC_DIR/${base}-${size}w.avif"
    fi
  done
done

# Проверка результатов
ls -lh "$SRC_DIR"/*.avif "$SRC_DIR"/*.webp
```

### Сценарий 2: Adaptive delivery через Nginx/Angie

```nginx
# Определение поддержки форматов клиентом
map $http_accept $image_suffix {
    default "";
    "~*avif" ".avif";
    "~*webp" ".webp";
}

server {
    location ~* \.(jpg|jpeg|png)$ {
        root /var/www/images;

        # Пробуем AVIF, затем WebP, затем оригинал
        try_files $uri$image_suffix $uri =404;

        # Кэширование
        expires 365d;
        add_header Cache-Control "public, immutable" always;
        add_header Vary "Accept" always;
    }
}
```

**Валидация:**
```bash
# Запрос AVIF
curl -sI -H "Accept: image/avif" https://example.com/images/photo.jpg
# → content-type: image/avif
# → cache-control: public, immutable
# → vary: Accept

# Запрос WebP
curl -sI -H "Accept: image/webp" https://example.com/images/photo.jpg
# → content-type: image/webp
```

### Сценарий 3: LCP Image optimization

```html
<!-- LCP-изображение: предзагрузка + fetchpriority -->
<link rel="preload" as="image" href="/images/hero.avif" type="image/avif" imagesrcset="/images/hero.avif 1x, /images/hero@2x.avif 2x" imagesizes="(max-width: 1200px) 1200px, 800px">

<img src="/images/hero.avif"
     srcset="/images/hero.avif 1x, /images/hero@2x.avif 2x"
     sizes="(max-width: 1200px) 1200px, 800px"
     fetchpriority="high"
     loading="eager"
     alt="Hero image">

<!-- Fallback для браузеров без AVIF -->
<picture>
  <source type="image/avif" srcset="/images/hero.avif">
  <source type="image/webp" srcset="/images/hero.webp">
  <img src="/images/hero.jpg" alt="Hero image" loading="eager">
</picture>
```

### Сценарий 4: Performance budget для изображений

```yaml
# .performance-budget.yaml
metrics:
  LCP: 2.5
  INP: 200
  CLS: 0.1
  images:
    LCP-image: 100KB  # LCP-изображение
    other-images: 50KB # Остальные изображения
    total-images: 500KB # Общий вес изображений на странице
```

```bash
# Проверка бюджета в CI
lhci collect --url=https://staging.example.com/ --numberOfRuns=3
lhci assert --assertions=largest-contentful-paint:maxNumericValue=2500
```

## Операции и команды

### Генерация изображений

```bash
# AVIF
avifenc --min 50 --max 60 --speed 6 input.jpg output.avif

# WebP
cwebp -q 75 -m 6 input.jpg -o output.webp

# Resize
convert input.jpg -resize 800x output-800w.jpg

# Batch processing
for img in *.jpg; do
  avifenc "$img" "${img%.jpg}.avif"
  cwebp "$img" -o "${img%.jpg}.webp"
done
```

### Проверка формата

```bash
# Проверка Content-Type
curl -sI https://example.com/images/photo.jpg | grep -i content-type
# → content-type: image/avif

# Проверка Vary
curl -sI https://example.com/images/photo.jpg | grep -i vary
# → vary: Accept
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Неправильный формат** | Клиент получает JPEG despite поддерживая AVIF | `curl -I -H "Accept: image/avif"` | Проверить `map $http_accept` и `try_files` |
| **Отсутствует Vary: Accept** | Кэш отдаёт JPEG клиенту с AVIF | `curl -sI | grep vary` | Добавить `add_header Vary "Accept" always` |
| **LCP-изображение не оптимизировано** | LCP > 2.5 с, Resource Load Delay > 500 мс | Chrome DevTools → Network → LCP | Добавить `fetchpriority="high"`, `preload`, AVIF |
| **Большой вес LCP-изображения** | LCP Resource Load Duration > 500 мс | DevTools → Size колонка | Сконвертировать в AVIF, уменьшить качество |
| **CLS из-за изображений** | Сдвиги макета > 0.1 | Chrome DevTools → Layout Shift Regions | Добавить `aspect-ratio`, явные `width`/`height` |
| **Lazy Loading для LCP** | LCP > 2.5 с | DevTools → Loading attribute | Заменить `loading="lazy"` на `loading="eager"` для LCP |

## Рекомендации

### Базовые правила

1. **Используйте AVIF как приоритетный формат:** Лучшее сжатие, поддержка всеми актуальными браузерами.
2. **Предусмотрите WebP fallback:** Для браузеров без AVIF.
3. **Не lazy-load LCP-изображение:** `loading="eager"` + `fetchpriority="high"`.
4. **Резервируйте место для изображений:** `aspect-ratio` + `width`/`height` для предотвращения CLS.
5. **Используйте responsive images:** `srcset` + `sizes` для доставки оптимального размера под viewport.
6. **Добавьте Vary: Accept:** Для корректной работы кэширования с адаптивными изображениями.
7. **Performance budget:** Ограничьте вес LCP-изображения (100KB), общий вес изображений (500KB).

### Для DevOps/SRE/SysAdmin

- **CI/CD pipeline:** Автоматическая генерация AVIF/WebP на этапе сборки.
- **Cache busting:** Используйте fingerprinting (хеш в имени файла) для инвалидации кэша при обновлении изображений.
- **Monitoring:** Отслеживайте `Content-Type` и `Vary` в ответах. Алерт при отсутствии `Vary: Accept`.

## Дополнительная информация

### См. также

- [Оптимизация веб-приложений: Обзор](./overview.md) — архитектура уровней оптимизации.
- [Лучшие практики оптимизации](./best_practices.md) — performance budget, lazy loading.
- [Кэширование и Web Vitals](./caching.md) — кэширование изображений.
- [Сжатие контента (Gzip, Brotli, ZSTD)](./server_compression.md) — сжатие текстовых ресурсов.

### RFC и спецификации

- **RFC 9297** — AVIF: Image File Format.
- **RFC 9561** — WebP: Image File Format.
