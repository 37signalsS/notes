# Image Optimization Pipeline для веб-производительности

**Актуально для:** Nginx 1.25+ / Angie 1.4+ / imgproxy 3.x / libvips 8.15+ (On-Premises)

## Определения

**AVIF (AV1 Image File Format)** — формат растровых изображений на базе открытого видеокодека AV1 (спецификация RFC 9297). Обеспечивает наивысшую плотность сжатия: в среднем на 20–35% эффективнее WebP и на 50–70% эффективнее JPEG при эквивалентном визуальном качестве (метрики SSIMULACRA2, Butteraugli). Поддерживает 10/12-битный цвет, HDR и прозрачность (альфа-канал).

**WebP** — формат сжатия изображений от Google (спецификация RFC 9561), использующий алгоритмы сжатия ключевых кадров VP8 (lossy) и собственный алгоритм LZ77/Хаффмана (lossless). Выступает универсальным стандартом и обязательным fallback-форматом для клиентов, не поддерживающих AVIF.

**JPEG XL (JXL)** — формат растровых изображений (ISO/IEC 18181), поддерживающий сжатие с потерями и без потерь, побайтовое обратимое пережатие существующих JPEG без потерь данных (lossless transcoding), а также прогрессивное декодирование. В 2026 году поддержка в браузерах остаётся фрагментированной (Safari 17+, Chrome за флагом `#enable-jxl-image-format`, экспериментально в Firefox). В production-контурах применяется только при валидации поддержки клиентом.

**AOT (Ahead-of-Time) Image Processing** — статическая пакетная генерация наборов форматов (AVIF, WebP, JPEG) и разрешений на этапе сборки в CI/CD или фоновыми воркерами очередей. Исключает затраты CPU на веб-сервере при обработке пользовательских запросов и позволяет задействовать максимальные уровни сжатия кодеков.

**JIT (Just-in-Time) Image Processing** — динамическая трансформация изображений «на лету» (on-demand) при первом запросе клиента с последующим локальным кэшированием на обратном прокси (reverse proxy). Применяется для UGC (User-Generated Content), динамических каталогов с миллионами SKU и произвольных комбинаций кропа/разрешения.

**Content Negotiation (согласование контента)** — механизм протокола HTTP (RFC 9110), при котором сервер выбирает оптимальное представление ресурса на основе заголовка запроса `Accept` (например, `image/avif,image/webp`) и сообщает промежуточным узлам о зависимости ответа через заголовок `Vary: Accept`.

**Responsive Images** — архитектурный подход адаптивной доставки медиа-контента, при котором браузер запрашивает файл нужного физического разрешения в зависимости от плотности пикселей экрана (DPR), ширины области просмотра (viewport) и сетки макета с использованием HTML-атрибутов `srcset` и `sizes`.

**LCP Image (Largest Contentful Paint Image)** — графический элемент страницы, отрисовка которого фиксирует момент рендеринга наибольшего видимого блока контента в рамках метрик Core Web Vitals. Оптимизация времени загрузки LCP-изображения критична для снижения задержки первого экрана.

**Decompression Bomb (Pixel Flood Attack)** — класс DoS-атак на серверы обработки изображений, при котором передается файл небольшого размера на диске (например, 200 КБ в формате PNG/JPEG), но с экстремальным разрешением (например, 40000×40000 пикселей). При распаковке в несжатый растровый буфер (raw RGBA, 4 байта на пиксель) процесс требует $40000 \times 40000 \times 4 \approx 6.4\text{ GB}$ оперативной памяти, что приводит к исчерпанию ресурсов хоста и срабатыванию OOM Killer.

**HMAC URL Signature** — схема защиты сервисов трансформации изображений, при которой параметры операции (размер, фильтр, формат, исходный URL) подписываются криптографическим хэшем с использованием закрытого ключа и соли на стороне приложения. Предотвращает неконтролируемую генерацию вариантов и DoS-атаки на вычисление графики.

## Основные концепции / Архитектура

### Сравнение форматов изображений

| Формат | Алгоритм / Кодек | Сжатие относительно JPEG | Нагрузка на CPU при кодировании | Поддержка браузерами (2026) | Применение в архитектуре |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AVIF** | AV1 (intra-frame) | -50% ... -70% | Очень высокая (требует тюнинга потоков и скорости) | Chrome 85+, Firefox 93+, Safari 16.4+, Edge 121+ | Приоритетный формат для фото, баннеров и LCP-изображений |
| **WebP** | VP8 / VP8L | -25% ... -40% | Умеренная | Все современные браузеры (Chrome, Safari, Firefox, Edge) | Базовый fallback для клиентов без поддержки AVIF |
| **JPEG XL** | VarDCT / Modular | -55% ... -75% | Высокая | Safari 17+, Chrome (флаг `#enable-jxl-image-format`) | Специализированные контуры при подтверждённой аудитории |
| **JPEG** | DCT (MozJPEG / libjpeg-turbo) | 0% (базовый) | Низкая | Универсальная (100%) | Окончательный fallback для устаревших клиентов и ботов |
| **PNG** | DEFLATE (oxipng / pngquant) | Без потерь / Индексированный | Средняя | Универсальная (100%) | Графика с четкими границами, скриншоты, схемы |
| **SVG** | Векторный XML (SVGO) | N/A (вектор) | Минимальная (парсинг XML) | Универсальная (100%) | Иконки, логотипы, простые иллюстрации |

### Влияние на Core Web Vitals и метрики SRE

Оптимизация изображений напрямую влияет на клиентские метрики производительности и утилизацию серверной инфраструктуры:

| Метрика / Параметр | Механизм влияния | Ожидаемый эффект от оптимизации |
| :--- | :--- | :--- |
| **LCP (Largest Contentful Paint)** | Доставка компактного AVIF/WebP нужного размера с приоритетом `fetchpriority="high"`. | Сокращение Resource Load Delay и Duration на 300–1200 мс. |
| **CLS (Cumulative Layout Shift)** | Явное указание атрибутов `width`/`height` или CSS-свойства `aspect-ratio`. | Снижение сдвигов макета до $0.00$ за счет заблаговременного резервирования места. |
| **Egress Bandwidth (исходящий трафик)** | Замена оригиналов на адаптивные форматы AVIF и WebP под точный viewport. | Снижение общего объема исходящей полосы на 40–65%. |
| **Disk I/O и Page Cache** | Меньший физический размер файлов на хранилище. | Увеличение плотности хранения и эффективности Page Cache ядра Linux. |

### Архитектура гибридного конвейера доставки

В инфраструктурах без облачных сервисов применяется разделение на два контура: **AOT-пайплайн** для статических медиаресурсов проекта и **JIT-пайплайн** для динамического пользовательского контента (UGC).

```
[ AOT: Статические ассеты (UI, лендинги, промо) ]
  Исходники (Git/Storage) ──> [ CI/CD Runner: libvips / cwebp / avifenc ]
                                   │
                                   ├──> photo.jpg (оригинал, оптимизирован MozJPEG)
                                   ├──> photo.jpg.webp (WebP fallback)
                                   └──> photo.jpg.avif (AVIF priority)
                                   │
                                   ▼
[ JIT: Пользовательский контент (UGC, каталоги) ]
  Upload ──> [ Storage / NFS ]
                 │
                 ▼
       [ Nginx / Angie Edge Proxy ] ──(Cache MISS / UDS)──> [ Self-Hosted imgproxy ]
                 │                                                   │
         (proxy_cache NVMe) <────────────────(Generated Response)─────┘
                 │
                 ▼
       [ Client / Browser ] (Content Negotiation: Accept: image/avif,image/webp)
```

1. **AOT-контур:**
   - Выполняется на CI/CD агентах с параллельной обработкой ядер (`GNU parallel`, `xargs`).
   - Исходные изображения пережимаются с максимальным уровнем оптимизации в варианты `.avif`, `.webp`, `.jpg`.
   - Файлы размещаются на диске рядом с оригиналами: `photo.jpg`, `photo.jpg.webp`, `photo.jpg.avif` (или с вырезанием базового расширения).

2. **JIT-контур:**
   - Высокопроизводительный локальный сервис трансформации на базе `imgproxy` (написан на Go с биндингами к `libvips`) либо Angie с модулем `ngx_http_image_filter_module`.
   - Взаимодействие веб-сервера и сервиса трансформации организуется через локальные сокеты UNIX (`unix:/run/imgproxy/imgproxy.sock`) для минимизации оверхеда TCP/IP-стека.
   - Двухуровневое кэширование: Nginx/Angie сохраняет сгенерированный результат на локальный NVMe-накопитель (`proxy_cache`), повторные запросы отдаются без участия микросервиса.

### Безопасность и защита от перегрузок (Resource Governance)

Работа с изображениями сопряжена с рисками исчерпания ресурсов и уязвимостей в библиотеках парсинга графики:

1. **Защита от Pixel Flood:** Ограничение максимального разрешения исходного файла до его декодирования. В `imgproxy` задается лимит `IMGPROXY_MAX_SRC_RESOLUTION` (например, 40–50 мегапикселей). В Nginx/Angie директива `image_filter_buffer` ограничивает максимальный размер загружаемого в память файла.
2. **Изоляция cgroups v2 / systemd:** Процессы конвертации обязаны выполняться с жесткими лимитами памяти (`MemoryMax`, `MemoryHigh`) и процессорного времени (`CPUQuota`). Превышение лимита памяти приводит к перезапуску изолированного воркера сервиса трансформации, предотвращая падение основного веб-сервера.
3. **Защита URL через HMAC:** Открытые эндпоинты трансформации позволяют злоумышленникам генерировать миллионы уникальных запросов с разными размерами (Cache Bypassing DoS). Применение HMAC-SHA256 подписи гарантирует, что сервер обрабатывает только те параметры, которые сгенерированы бэкендом приложения.
4. **Очистка метаданных и санитизация:**
   - Растровые файлы (JPEG/PNG/WebP/AVIF): удаление служебных EXIF, XMP, IPTC и GPS-тегов (`--strip-all`) для защиты приватности пользователей и экономии от 2 до 50 КБ на файл.
   - Векторные файлы (SVG): обязательная санитизация утилитой `svgo` с удалением тегов `<script>`, обработчиков событий `onload`/`onerror`, внешних ссылок и DTD-сущностей во избежание Stored XSS и XXE-инъекций.

## Практические сценарии / Установка и настройка / Конфигурация

### Сценарий 1: CI/CD AOT-пайплайн пакетной оптимизации

Скрипт выполняет параллельную компрессию графики с сохранением хэшей обработанных файлов, исключая повторное сжатие неизмененных ассетов на повторных сборках.

**Необходимые системные пакеты (Debian/Ubuntu):**
```bash
apt-get update && apt-get install -y libavif-bin webp libjpeg-turbo-progs optipng oxipng parallel
# → Setting up libavif-bin ...
# → Setting up webp ...
```

**Скрипт оптимизации (`scripts/optimize-images.sh`):**
```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-dist/assets/images}"
CACHE_FILE="${TARGET_DIR}/.optimization_cache"
touch "$CACHE_FILE"

export QUALITY_AVIF_MIN=25
export QUALITY_AVIF_MAX=35
export SPEED_AVIF=4
export QUALITY_WEBP=78
export QUALITY_JPEG=80

process_image() {
    local img="$1"
    local cache_file="$2"
    local checksum
    checksum=$(sha256sum "$img" | awk '{print $1}')

    # Проверка кэша инкрементальной сборки
    if grep -q "^${img}:${checksum}$" "$cache_file" 2>/dev/null; then
        exit 0
    fi

    local ext="${img##*.}"
    local mime
    mime=$(file --mime-type -b "$img")

    case "$mime" in
        image/jpeg|image/png)
            # 1. Генерация AVIF
            avifenc --min "$QUALITY_AVIF_MIN" --max "$QUALITY_AVIF_MAX" \
                    --speed "$SPEED_AVIF" -j all "$img" "${img}.avif" >/dev/null 2>&1

            # 2. Генерация WebP
            cwebp -q "$QUALITY_WEBP" -m 6 -metadata none "$img" -o "${img}.webp" >/dev/null 2>&1

            # 3. Lossless/Lossy оптимизация оригинала
            if [ "$mime" = "image/jpeg" ]; then
                jpegoptim --max="$QUALITY_JPEG" --strip-all --all-progressive "$img" >/dev/null 2>&1
            elif [ "$mime" = "image/png" ]; then
                oxipng -o 4 --strip safe "$img" >/dev/null 2>&1
            fi
            ;;
        image/svg+xml)
            if command -v svgo &>/dev/null; then
                svgo --multipass "$img" -o "$img" >/dev/null 2>&1
            fi
            ;;
        *)
            exit 0
            ;;
    esac

    echo "${img}:${checksum}" >> "$cache_file"
}

export -f process_image
find "$TARGET_DIR" -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.svg" \) \
    ! -iname "*.avif" ! -iname "*.webp" | \
    parallel -j "$(nproc)" process_image {} "$CACHE_FILE"

echo "Оптимизация изображений завершена."
```

### Сценарий 2: Развертывание self-hosted JIT-трансформера (imgproxy)

Развертывание бинарного демона `imgproxy` под управлением systemd с ограничением ресурсов через cgroups v2 и связью через сокет UNIX.

**1. Конфигурация systemd unit (`/etc/systemd/system/imgproxy.service`):**
```ini
[Unit]
Description=imgproxy standalone image processing server
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
RuntimeDirectory=imgproxy
RuntimeDirectoryMode=0755

Environment=IMGPROXY_BIND=unix:/run/imgproxy/imgproxy.sock
Environment=IMGPROXY_KEY=943b42199f61dcedfb8702d72997d4d71b4f235b3b3964e43b8c0d478b210091
Environment=IMGPROXY_SALT=4943bd3e4f73b6163283235ff64441bc6c4d66ecb754bd3d873450781216d7a9
Environment=IMGPROXY_WORKERS=4
Environment=IMGPROXY_MAX_SRC_RESOLUTION=50
Environment=IMGPROXY_AVIF_SPEED=8
Environment=IMGPROXY_QUALITY=80
Environment=IMGPROXY_GZIP_COMPRESSION=0

# Ограничение ресурсов cgroups v2
MemoryMax=2G
MemoryHigh=1.6G
CPUQuota=300%
LimitNOFILE=65535
Restart=on-failure
RestartSec=3s

ExecStart=/usr/local/bin/imgproxy

[Install]
WantedBy=multi-user.target
```

**2. Запуск сервиса:**
```bash
systemctl daemon-reload
systemctl enable --now imgproxy
systemctl status imgproxy
# → Active: active (running) since ...
# → Status: "Listening on unix:/run/imgproxy/imgproxy.sock"
```

### Сценарий 3: Конфигурация Nginx / Angie для адаптивной доставки и кэширования

Конфигурация объединяет отдачу предварительно сжатой статики (AOT) с проксированием и двухуровневым кэшированием динамических изображений (JIT).

```nginx
# Определение поддерживаемого формата клиентом (Content Negotiation)
map $http_accept $image_suffix {
    default        "";
    "~*image/avif" ".avif";
    "~*image/webp" ".webp";
}

# Пул кэша для динамической графики на NVMe диске
proxy_cache_path /var/cache/nginx/img_cache
                 levels=1:2
                 keys_zone=IMG_CACHE:50m
                 max_size=20g
                 inactive=30d
                 use_temp_path=off;

upstream imgproxy_backend {
    server unix:/run/imgproxy/imgproxy.sock max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 80;
    listen 443 ssl;
    server_name static.example.internal;

    root /var/www/static;

    # 1. Раздача статических изображений (AOT)
    # Запрос /images/hero.jpg при наличии заголовка Accept проверяет hero.jpg.avif -> hero.jpg.webp -> hero.jpg
    location ~* \.(jpe?g|png)$ {
        try_files $uri$image_suffix $uri =404;

        # Критичный заголовок для промежуточных кэшей
        add_header Vary "Accept" always;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Asset-Format $image_suffix always;

        open_file_cache max=10000 inactive=30s;
        open_file_cache_valid 60s;
        open_file_cache_errors on;
    }

    # 2. Раздача динамических изображений через JIT-прокси (imgproxy)
    location /media/transform/ {
        # Формирование ключа кэша с учетом клиентского формата и параметров URL
        proxy_cache IMG_CACHE;
        proxy_cache_key "$scheme$request_method$host$uri$image_suffix";
        proxy_cache_valid 200 302 30d;
        proxy_cache_valid 404 1m;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;

        # Передача запроса в unix-сокет
        proxy_pass http://imgproxy_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;

        # Информирование апстрима о поддерживаемом формате
        proxy_set_header Accept $http_accept;

        # Заголовки ответа
        add_header X-Cache-Status $upstream_cache_status always;
        add_header Vary "Accept" always;
        add_header Cache-Control "public, max-age=2592000" always;
    }
}
```

### Сценарий 4: Оптимизация LCP-изображений на уровне HTML и разметки

Правильное подключение изображений в разметке предотвращает задержки LCP и сдвиги макета (CLS):

```html
<!-- 1. Предзагрузка LCP-изображения в <head> с учетом адаптивных размеров -->
<link rel="preload"
      as="image"
      href="/images/hero-1200w.jpg.avif"
      type="image/avif"
      imagesrcset="/images/hero-600w.jpg.avif 600w, /images/hero-1200w.jpg.avif 1200w"
      imagesizes="(max-width: 768px) 100vw, 1200px"
      fetchpriority="high">

<!-- 2. Разметка с элементами <picture> и fallback-форматами -->
<picture>
  <!-- AVIF для современных браузеров -->
  <source type="image/avif"
          srcset="/images/hero-600w.jpg.avif 600w, /images/hero-1200w.jpg.avif 1200w"
          sizes="(max-width: 768px) 100vw, 1200px">
  
  <!-- WebP fallback -->
  <source type="image/webp"
          srcset="/images/hero-600w.jpg.webp 600w, /images/hero-1200w.jpg.webp 1200w"
          sizes="(max-width: 768px) 100vw, 1200px">

  <!-- Базовый JPEG и предотвращение CLS через явные атрибуты ширины и высоты -->
  <img src="/images/hero-1200w.jpg"
       width="1200"
       height="675"
       alt="Главный баннер"
       fetchpriority="high"
       loading="eager"
       decoding="async"
       style="width: 100%; height: auto; aspect-ratio: 16 / 9;">
</picture>

<!-- 3. Не-LCP изображения ниже первого экрана (Lazy Loading) -->
<img src="/images/catalog/item-480w.jpg"
     loading="lazy"
     decoding="async"
     width="480"
     height="320"
     alt="Товар каталога">
```

## Операции и команды

### Валидация адаптивной доставки и заголовков

```bash
# 1. Запрос клиентом с поддержкой AVIF
curl -sI -H "Accept: image/avif,image/webp,*/*" https://static.example.internal/images/hero.jpg
# → HTTP/2 200
# → content-type: image/avif
# → vary: Accept
# → cache-control: public, max-age=31536000, immutable
# → x-asset-format: .avif

# 2. Запрос клиентом без поддержки AVIF, но с WebP
curl -sI -H "Accept: image/webp,*/*" https://static.example.internal/images/hero.jpg
# → HTTP/2 200
# → content-type: image/webp
# → vary: Accept
# → x-asset-format: .webp

# 3. Запрос устаревшим клиентом или краулером
curl -sI -H "Accept: */*" https://static.example.internal/images/hero.jpg
# → HTTP/2 200
# → content-type: image/jpeg
# → vary: Accept
```

### Проверка трансформации через JIT (imgproxy)

```bash
# Запрос к сокету с проверкой статуса кэша
curl -sI -H "Accept: image/avif" https://static.example.internal/media/transform/insecure/resize:fill:300:200:0/plain/local:///photo.jpg
# → HTTP/2 200
# → content-type: image/avif
# → x-cache-status: MISS

# Повторный запрос должен возвращать статус попадания в кэш
curl -sI -H "Accept: image/avif" https://static.example.internal/media/transform/insecure/resize:fill:300:200:0/plain/local:///photo.jpg
# → HTTP/2 200
# → x-cache-status: HIT
```

### Диагностика метаданных и бинарных заголовков

```bash
# Проверка наличия скрытых метаданных и геолокации в исходном файле
exiftool -a -u -g1 input.jpg | grep -E -i "GPS|Camera|Software|Author"
# → [IFD0] Software: Adobe Photoshop
# → [GPS] GPS Latitude: 55 deg 45' 0.00" N

# Проверка корректности удаления метаданных после сжатия
exiftool -a -u -g1 input.jpg.avif
# → [File] File Type: AVIF
# → [File] Image Width: 1920
# → [File] Image Height: 1080
```

### Мониторинг дисковой зоны кэша Nginx

```bash
# Проверка физического объема и структуры каталога кэша
du -sh /var/cache/nginx/img_cache
# → 4.2G    /var/cache/nginx/img_cache

# Проверка количества элементов в структуре кэша levels=1:2
find /var/cache/nginx/img_cache -type f | wc -l
# → 45120
```

## Диагностика и устранение неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Отравление кэша (Cache Poisoning)** | Отсутствует заголовок `Vary: Accept` в ответе веб-сервера. Браузер без поддержки AVIF получает бинарный AVIF из общего прокси. | `curl -sI https://example.internal/img.jpg \| grep -i vary` | Добавить `add_header Vary "Accept" always;` в блок `server`/`location` веб-сервера. |
| **Клиент получает JPEG вместо AVIF/WebP** | 1. Файл `.avif` отсутствует на диске.<br>2. Ошибка сопоставления пути в `try_files` (например, ожидался `photo.avif`, а лежит `photo.jpg.avif`). | Проверить наличие файлов: `ls -la /var/www/static/images/hero.*`. Проверить `error.log`. | Синхронизировать соглашение именования в CI/CD скрипте и директиве `try_files $uri$image_suffix` (или использовать `regex`-парсинг имени). |
| **Ошибка 415 (Unsupported Media Type)** | Размер файла или разрешение превышает `image_filter_buffer` в Angie или лимиты `imgproxy`. | `tail -f /var/log/nginx/error.log` (сообщение `image_filter: "too big image"`). | Увеличить `image_filter_buffer 30M;` либо настроить параметр `IMGPROXY_MAX_SRC_RESOLUTION` в systemd-юните. |
| **Ошибка 403 / 400 Bad Signature на JIT-прокси** | Несовпадение секретного ключа (`KEY`) и соли (`SALT`) между генератором URL в приложении и сервисом `imgproxy`. | Проверить логи `journalctl -u imgproxy.service` (сообщение `Invalid signature`). | Проверить переменные `IMGPROXY_KEY` и `IMGPROXY_SALT` в окружении приложения и systemd-сервиса. |
| **OOM Killer убивает процесс трансформации** | Поток тяжелых запросов распаковки несжатых растров вызвал превышение лимита памяти cgroups. | `dmesg -T \| grep -i oom` или `journalctl -k \| grep imgproxy`. | 1. Ограничить `IMGPROXY_WORKERS` до количества $N_{\text{CPU}} / 2$.<br>2. Задать `IMGPROXY_MAX_SRC_RESOLUTION=30`.<br>3. Включить `proxy_cache_lock on;` в Nginx для предотвращения Thundering Herd. |
| **Высокий TTFB (> 2.5 с) при первом обращении** | Слишком низкая скорость кодирования AVIF на лету (`speed 0-3`). | Проверить время ответа апстрима `$upstream_response_time` в access-логе Nginx. | Для JIT установить `IMGPROXY_AVIF_SPEED=8` или `9`. Максимальное сжатие (`speed 2-4`) использовать исключительно в AOT (CI/CD). |
| **CLS (Cumulative Layout Shift) > 0.1** | Изображения не имеют зарезервированного пространства в DOM до момента отрисовки файла. | Открыть Chrome DevTools → Performance → Layout Shifts. | Добавить атрибуты `width` и `height` в тег `<img>` и настроить в CSS `aspect-ratio` и `height: auto;`. |

## Рекомендации и лучшие практики

### Для веб-производительности (Web Performance)

1. **Приоритет форматов в 2026 году:** AVIF в качестве основного формата для фотографий и фонов (экономия 50–70% трафика по сравнению с JPEG), WebP — как гарантированный fallback.
2. **Оптимизация LCP:**
   - Не применять `loading="lazy"` к изображениям первого экрана (LCP-элементам). Использовать `loading="eager"` и `fetchpriority="high"`.
   - Добавлять `<link rel="preload" as="image">` в `<head>` документа для критических баннеров.
3. **Устранение сдвигов макета (CLS):** Всегда задавать нативные атрибуты `width` и `height` у тегов `<img>`, позволяя браузеру вычислить пропорции блока до скачивания бинарных данных.
4. **Адаптивные размеры (Responsive):** Использовать сетку `srcset` с шагом 1.5x–2x (например, 480w, 800w, 1200w, 1600w) и точные медиавыражения в `sizes`.

### Для DevOps, SRE и системных администраторов

1. **Разделение AOT и JIT:**
   - Все статические элементы интерфейса, иконки, логотипы и лендинги сжимать на этапе CI/CD (AOT).
   - Динамический пользовательский контент (UGC) трансформировать через JIT-прокси с обязательным кэшированием.
2. **Защита ресурсов хоста:**
   - Развертывать JIT-трансформеры (imgproxy/libvips) в изолированных cgroups v2 с ограничениями `MemoryMax` и `CPUQuota`.
   - Использовать UNIX-сокеты вместо сетевых loopback TCP-интерфейсов для снижения сетевых накладных расходов.
   - Защищать JIT-эндпоинты обязательной HMAC-подписью параметров.
3. **Оптимизация кэширования Nginx / Angie:**
   - Настраивать `proxy_cache_lock on;` и `proxy_cache_use_stale updating;` для предотвращения лавинообразных запросов (Cache Stampede / Thundering Herd) к сервису трансформации при истечении TTL.
   - Использовать `use_temp_path=off;` в директиве `proxy_cache_path`, чтобы временные файлы кэша сохранялись в том же разделе файловой системы без межсекторного копирования.
   - Для Angie 1.9+ применять параметр `file=` в `proxy_cache_path` для сохранения структуры индекса кэша на диске при перезапусках.
4. **Хранение и очистка:**
   - Размещать каталоги кэша на быстрых NVMe-накопителях с файловой системой XFS или ext4 (опции монтирования `noatime`).
   - Настраивать жесткий лимит дискового пространства через параметр `max_size` в `proxy_cache_path`.
5. **Мониторинг ключевых SRE-метрик:**
   - **Cache Hit Ratio:** Доля попаданий в кэш графики (норма в production: $\ge 92\%$).
   - **Upstream Latency (p95/p99):** Время обработки файла сервисом трансформации при MISS-запросе (целевое значение: $\le 250\text{ мс}$).
   - **Коды ответов:** Отслеживание всплесков ошибок 415 (неподдерживаемый/битый файл), 403 (ошибка подписи), 502/504 (падение или зависание трансформера).

## Дополнительная информация

### См. также

- [Адаптивная доставка изображений в Nginx](../../Nginx/Performance/nginx_adaptive_content.md) — детальная настройка Content Negotiation и директивы `map`/`try_files`.
- [Модуль image_filter в Angie](../../Angie/High_Load/image_filter/filter_configuration.md) — конфигурация динамической трансформации встроенными средствами веб-сервера.
- [Кэширование и Web Vitals](./caching.md) — организация многоуровневого кэширования и инвалидация.
- [Компрессия контента на веб-сервере](./server_compression.md) — сжатие текстовых ресурсов (Gzip, Brotli, Zstandard).
- [Оптимизация Core Web Vitals](./web_vitals.md) — измерение и диагностика LCP, CLS, INP.

### RFC и спецификации

- **RFC 9297** — AV1 Image File Format (AVIF).
- **RFC 9561** — The WebP Image Format.
- **RFC 9110** — HTTP Semantics (Раздел 12: Content Negotiation, заголовок `Vary`).
- **ISO/IEC 18181** — JPEG XL Image Coding System.
