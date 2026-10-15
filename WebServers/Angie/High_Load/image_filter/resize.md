# Модуль image_filter в Angie: изменение размеров и трансформация

**Актуально для:** Angie 1.12.x

## Определения

**Resize (Масштабирование с сохранением пропорций, Bounding Box Contain)** — операция пропорционального уменьшения или изменения габаритов изображения, при которой оно полностью вписывается в заданный прямоугольник (`<width>` $\times$ `<height>`) без обрезки содержимого. Если один из параметров задан дефисом (`-`), отсутствующая сторона вычисляется автоматически на основе исходного соотношения сторон.

**Crop (Кадрирование с заполнением, Cover & Center-Crop)** — операция масштабирования изображения до полного покрытия целевых размеров с последующим отсечением выступающих краев от геометрического центра. Гарантирует точное соответствие итоговых размеров заданным значениям без искажения пропорций объектов.

**Convert (Потоковое транскодирование контейнера)** — директива Angie (`image_filter convert <format>`), выполняющая смену формата контейнера и алгоритма сжатия (AVIF, WebP, JPEG, PNG, GIF) «на лету» без обязательного изменения геометрического разрешения.

**Rotate (Геометрический поворот)** — операция поворота растровой матрицы пикселей по часовой стрелке на фиксированный угол (90, 180 или 270 градусов). Выполняется после операций масштабирования и изменяет результирующие значения ширины и высоты для углов 90° и 270°.

**Sharpen (Контурная резкость)** — алгоритмический фильтр постобработки на основе матрицы свертки, компенсирующий размытие мелких деталей, неизбежно возникающее при программном субдискретизировании (даунскейлинге) растра.

**Interlace (Прогрессивная развертка JPEG)** — метод кодирования JPEG-изображений, при котором файл сохраняется слоями с постепенным повышением детализации по мере загрузки. Активируется директивой `image_filter_interlace on` и улучшает субъективную скорость отрисовки на нестабильных каналах связи.

**Буфер декомпрессии (`image_filter_buffer`)** — предельный объем виртуальной памяти, выделяемый воркером Angie под чтение и размещение сжатого файла-оригинала перед его декодированием. Если размер файла на диске или в апстриме превышает это значение, Angie прерывает операцию с кодом `415 Unsupported Media Type`.

**Несжатый растр (RGBA Bitmap)** — представление изображения в оперативной памяти воркера после распаковки библиотекой `libgd`. Объем занимаемой памяти рассчитывается как $\text{Width} \times \text{Height} \times 4$ байта независимо от размера исходного сжатого файла.

**Двухуровневое проксирование (Double Proxying over AF_UNIX)** — архитектурная схема изоляции, при которой внешний фронтенд принимает клиентские запросы, управляет дисковым кэшем (`proxy_cache`) и согласует форматы, а внутренний бэкенд на Unix Domain Socket выполняет ресурсоемкие операции кодирования.

**Fallback-обработка (Content-Aware Error Fallback)** — перехват ошибок трансформации (прежде всего HTTP 415) через директиву `error_page` с возвратом прозрачного пикселя или векторной заглушки без генерации 5xx-кодов для клиентов.

---

## Базовые концепции

Модуль `ngx_http_image_filter_module` в Angie расширяет стандартные возможности Nginx нативной поддержкой современных медиаформатов (AVIF, WebP, чтение HEIC) и специализированной директивой транскодирования `convert`.

### Математика и алгоритмы геометрических трансформаций

#### 1. Алгоритм Resize (Вписывание в границы)

Директива: `image_filter resize <w> <h>;`

Принимает целевые габариты $w$ и $h$. Вычисление итогового размера подчиняется следующим правилам:

- **Оба параметра заданы числами (`resize 800 600`):**
  Сервер вычисляет масштабный коэффициент по обеим осям относительно оригинала ($W_{\text{orig}} \times H_{\text{orig}}$):
  $$k = \min\left(\frac{w}{W_{\text{orig}}}, \frac{h}{H_{\text{orig}}}\right)$$
  Итоговые габариты:
  $$W_{\text{new}} = \text{round}(W_{\text{orig}} \times k), \quad H_{\text{new}} = \text{round}(H_{\text{orig}} \times k)$$
  Изображение гарантированно помещается внутрь блока $w \times h$, при этом одна из сторон может быть меньше заданной.
- **Один из параметров задан дефисом (`resize 800 -` или `resize - 600`):**
  Отсутствующая сторона масштабируется строго пропорционально:
  $$\text{Если } h = -, \text{ то } H_{\text{new}} = \text{round}\left(H_{\text{orig}} \times \frac{w}{W_{\text{orig}}}\right)$$
  $$\text{Если } w = -, \text{ то } W_{\text{new}} = \text{round}\left(W_{\text{orig}} \times \frac{h}{H_{\text{orig}}}\right)$$
- **Поведение при апскейле:** Если оба целевых размера больше размеров оригинала ($w > W_{\text{orig}}$ и $h > H_{\text{orig}}$), Angie не растягивает растр, сохраняя оригинальные размеры, чтобы не допустить деградации качества и пикселизации.

#### 2. Алгоритм Crop (Заполнение и центрированная обрезка)

Директива: `image_filter crop <w> <h>;`

Используется для генерации миниатюр с жестко фиксированными соотношениями сторон (например, квадраты $1:1$ для аватаров):

1. Вычисляется коэффициент покрытия:
   $$k = \max\left(\frac{w}{W_{\text{orig}}}, \frac{h}{H_{\text{orig}}}\right)$$
2. Исходное изображение масштабируется до промежуточного размера $W_{\text{mid}} = W_{\text{orig}} \times k$, $H_{\text{mid}} = H_{\text{orig}} \times k$.
3. Излишки отсекаются симметрично от центра:
   $$\text{Offset}_X = \frac{W_{\text{mid}} - w}{2}, \quad \text{Offset}_Y = \frac{H_{\text{mid}} - h}{2}$$
4. На выходе формируется растр размером ровно $w \times h$. Если одна из сторон задана дефисом, поведение сводится к обычному пропорциональному ресайзу без кадрирования.

#### 3. Алгоритм Rotate (Поворот)

Директива: `image_filter rotate 90 | 180 | 270;`

- Выполняет матричную перестановку пикселей по часовой стрелке.
- Выполняется строго **после** операций `resize` или `crop`.
- При повороте на 90° и 270° ширина и высота результирующего холста меняются местами ($W_{\text{out}} = H_{\text{in}}, H_{\text{out}} = W_{\text{in}}$).

### Порядок обработки в конвейере фильтрации

Обработка запроса в модуле `image_filter` выполняется строго в следующей последовательности:

```
[Исходный файл с диска / апстрима]
                │
                ▼
  [Проверка: размер <= image_filter_buffer?] ──(Нет)──> [HTTP 415 Unsupported Media Type]
                │ (Да)
                ▼
  [Декомпрессия заголовка и растра в RGBA (libgd)]
                │
                ▼
  [Геометрический поворот: rotate (90/180/270)]
                │
                ▼
  [Масштабирование или обрезка: resize / crop]
                │
                ▼
  [Повышение резкости: sharpen (матричная свертка)]
                │
                ▼
  [Кодирование в целевой формат: AVIF / WebP / JPEG / PNG]
  (с учетом quality, avif_speed, interlace, transparency)
                │
                ▼
[Готовый HTTP-ответ клиенту / фронтенду]
```

### Сводная таблица директив модуля

| Директива | Синтаксис / Аргументы | Значение по умолчанию | Рекомендации для High Load | Влияние на систему |
|:---|:---|:---|:---|:---|
| `image_filter` | `off` \| `test` \| `size` \| `rotate 90\|180\|270` \| `resize <w> <h>` \| `crop <w> <h>` \| `convert <fmt>` | `off` | Выносить на выделенный внутренний бэкенд | Задает базовую операцию конвейера |
| `image_filter_buffer` | `<размер>` (например, `20M`) | `1M` | `20M–25M` | Лимит памяти на сжатый файл; дефолтного 1M недостаточно для фото |
| `image_filter_jpeg_quality` | `1–100` | `75` | `80–85` | Баланс между артефактами сжатия и весом файла |
| `image_filter_webp_quality` | `1–100` | `75` | `75–80` | Оптимум для WebP; экономит до 30% объема относительно JPEG |
| `image_filter_avif_quality` | `1–100` | `65` | `60–70` | Значения > 75 резко увеличивают расход CPU без видимой глазом разницы |
| `image_filter_avif_speed` | `0–10` | `8` | `8–10` | 0 — предельное сжатие (очень медленно), 9–10 — быстрый High Load |
| `image_filter_heic_quality` | `1–100` | `75` | `70–75` | Используется при транскодировании мобильных фото Apple |
| `image_filter_sharpen` | `0–100` | `0` | `1–5` (для миниатюр) | Устраняет эффект замыливания; добавляет 15–25% к latency |
| `image_filter_interlace` | `on` \| `off` | `off` | `on` (для JPEG) | Прогрессивный JPEG; улучшает отрисовку на мобильных сетях |
| `image_filter_transparency` | `on` \| `off` | `on` | `on` | Сохраняет альфа-канал PNG/WebP (заменяет фон при `off`) |

> [!WARNING]
> Директивы `image_filter_avif_quality` и `image_filter_avif_speed` являются независимыми параметрами. Попытка передать оба числа в одну директиву (`image_filter_avif_quality 65 9;`) вызовет синтаксическую ошибку валидации конфигурации (`angie -t`).

### Модель памяти и межпроцессное взаимодействие

Модуль `image_filter` блокирует воркер Angie на время выполнения математических операций. В высоконагруженных системах критически важно изолировать этот процесс:

1. **Изоляция контуров:** Фронтенд работает в асинхронном неблокирующем режиме с дисковым кэшем `proxy_cache`. Бэкенд фильтрации запускается на локальном Unix Domain Socket (`AF_UNIX`).
2. **Расчет пикового потребления RAM:**
   Общий объем памяти, требуемый одному рабочему процессу под одну операцию:
   $$\text{RAM}_{\text{req}} = \text{image\_filter\_buffer} + (W_{\text{orig}} \times H_{\text{orig}} \times 4) + \text{Arena}_{\text{codec}}$$
   *Пример:* Фото 12 Мп ($4032 \times 3024$), буфер 25 МБ, кодирование в AVIF:
   $$\text{RAM} \approx 25\text{ МБ} + (4032 \times 3024 \times 4 \approx 48.7\text{ МБ}) + 30\text{ МБ (libavif)} \approx 103.7\text{ МБ на воркер}$$
   При пуле из 16 воркеров пиковый всплеск составляет до 1.6–1.8 ГБ оперативной памяти.
3. **Изоляция через cgroups v2 (systemd):** Для защиты операционной системы от OOM-killer процессу Angie выделяется жесткий лимит памяти в unit-файле systemd:
   ```ini
   # /etc/systemd/system/angie.service.d/override.conf
   [Service]
   MemoryMax=4G
   MemoryHigh=3.5G
   CPUWeight=800
   ```

---

## Практические сценарии

### Предварительные требования

1. **Версия Angie и модуль:** Установлен Angie версии $\ge 1.12.0$ с динамическим модулем `ngx_http_image_filter_module`:
   ```bash
   angie -V 2>&1 | grep -E "image_filter|angie"
   # → angie version: angie/1.12.0
   # → configure arguments: ... --with-http_image_filter_module=dynamic ...
   ```
2. **Системные кодеки (libgd, libwebp, libavif, libheif):**
   ```bash
   ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so | grep -E "gd|webp|avif|heif"
   # → libgd.so.3 => /lib/x86_64-linux-gnu/libgd.so.3
   # → libwebp.so.7 => /lib/x86_64-linux-gnu/libwebp.so.7
   # → libavif.so.16 => /lib/x86_64-linux-gnu/libavif.so.16
   # → libheif.so.1 => /lib/x86_64-linux-gnu/libheif.so.1
   ```
3. **Файловая система и права доступа:**
   ```bash
   mkdir -p /var/run/angie /var/cache/angie/img /var/www/images/originals
   chown -R angie:angie /var/run/angie /var/cache/angie /var/www/images
   chmod 750 /var/run/angie /var/cache/angie/img
   ```

### Сценарий 1: Пропорциональный ресайз с авто-высотой (`resize $w -`) и генерацией AVIF/WebP

Базовый production-паттерн адаптивной отдачи: фронтенд анализирует заголовок `Accept`, проверяет кэш и проксирует запрос на внутренний сокет трансформации с автоматическим расчетом высоты.

```nginx
# /etc/angie/http.d/image_pipeline.conf

# Согласование форматов (Content Negotiation)
map $http_accept $img_target_format {
    "~*image/avif" avif;
    "~*image/webp" webp;
    default        jpeg;
}

proxy_cache_path /var/cache/angie/img
    levels=1:2
    keys_zone=img_cache:64m
    max_size=20g
    inactive=30d
    use_temp_path=off;

# Внешний фронтенд
server {
    listen 80;
    server_name images.local;

    location ~* ^/resize/(?<w>\d+)/(?<file>.+\.(?:jpe?g|png|webp))$ {
        # Валидация ширины: разрешаем только стандартные сетки
        if ($w !~ ^(320|640|800|1024|1280|1920)$) {
            return 400 "Unsupported width requested\n";
        }

        proxy_cache img_cache;
        proxy_cache_key "$scheme$request_method$host$uri$img_target_format";
        proxy_cache_valid 200 30d;
        proxy_cache_valid 404 415 5m;
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_use_stale error timeout updating;

        add_header X-Cache-Status $upstream_cache_status always;
        add_header Vary "Accept" always;

        proxy_pass http://unix:/var/run/angie/image_filter.sock:/resize/$w/$img_target_format/$file;
    }
}

# Внутренний вычислительный бэкенд
server {
    listen unix:/var/run/angie/image_filter.sock;
    server_name localhost;

    status_zone image_filter_backend;

    # Локация ресайза под AVIF
    location ~* ^/resize/(?<w>\d+)/avif/(?<file>.+)$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter_buffer 25M;
        image_filter resize $w -;
        image_filter convert avif;
        image_filter_avif_quality 65;
        image_filter_avif_speed 9;
        image_filter_sharpen 2;

        error_page 415 = @empty_fallback;
    }

    # Локация ресайза под WebP
    location ~* ^/resize/(?<w>\d+)/webp/(?<file>.+)$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter_buffer 25M;
        image_filter resize $w -;
        image_filter convert webp;
        image_filter_webp_quality 80;
        image_filter_sharpen 2;

        error_page 415 = @empty_fallback;
    }

    # Локация ресайза под Progressive JPEG
    location ~* ^/resize/(?<w>\d+)/jpeg/(?<file>.+)$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter_buffer 25M;
        image_filter resize $w -;
        image_filter_jpeg_quality 85;
        image_filter_interlace on;
        image_filter_sharpen 2;

        error_page 415 = @empty_fallback;
    }

    # Fallback-заглушка 1x1 GIF при ошибках декодирования оригинала
    location @empty_fallback {
        internal;
        default_type image/gif;
        add_header X-Image-Status "fallback-415" always;
        return 200 "\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b";
    }
}
```

**Валидация работы:**
```bash
# 1. Первый запрос с поддержкой AVIF (генерация, промах кэша)
curl -I -H "Accept: image/avif,image/webp,*/*" http://images.local/resize/800/banner.jpg
# → HTTP/1.1 200 OK
# → Content-Type: image/avif
# → Vary: Accept
# → X-Cache-Status: MISS

# 2. Повторный запрос (мгновенная отдача из кэша)
curl -I -H "Accept: image/avif,image/webp,*/*" http://images.local/resize/800/banner.jpg
# → HTTP/1.1 200 OK
# → Content-Type: image/avif
# → X-Cache-Status: HIT

# 3. Запрос от устаревшего клиента без поддержки AVIF (генерация WebP)
curl -I -H "Accept: image/webp,*/*" http://images.local/resize/800/banner.jpg
# → HTTP/1.1 200 OK
# → Content-Type: image/webp
# → X-Cache-Status: MISS
```

### Сценарий 2: Фиксированный квадратный превью-аватар (`crop 300 300`)

Кадрирование пользовательских фотографий и аватарок с автоцентрированием и транскодированием загруженных файлов (включая HEIC-фото с мобильных устройств Apple) в легкий формат WebP.

```nginx
# Внутренний сервер кадрирования аватарок
server {
    listen unix:/var/run/angie/image_filter.sock;
    server_name localhost;

    status_zone image_filter_backend;

    location ~* ^/avatar/(?<size>\d+)/(?<file>.+\.(?:jpe?g|png|heic|webp))$ {
        internal;
        alias /var/www/images/avatars/$file;

        image_filter_buffer 30M;
        image_filter crop $size $size;
        image_filter convert webp;
        image_filter_webp_quality 80;
        image_filter_sharpen 3;

        error_page 415 = @empty_fallback;
    }

    location @empty_fallback {
        internal;
        default_type image/gif;
        return 200 "\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b";
    }
}
```

**Валидация геометрии полученного аватара:**
```bash
# Проверка габаритов через curl и imagemagick identify
curl -s --unix-socket /var/run/angie/image_filter.sock "http://localhost/avatar/300/user102.heic" > /tmp/avatar_test.webp
magick identify /tmp/avatar_test.webp
# → /tmp/avatar_test.webp WEBP 300x300 300x300+0+0 8-bit sRGB 12450B
```

### Сценарий 3: Комплексный пайплайн (Rotate 90 + Resize + Sharpen + Progressive JPEG)

Сценарий нормализации ориентации фотографий и последующего уменьшения до размера $800 \times 600$ с повышением четкости и прогрессивной разверткой.

```nginx
server {
    listen unix:/var/run/angie/image_filter.sock;
    server_name localhost;

    status_zone image_filter_backend;

    location ~* ^/rotate-and-resize/(?<deg>90|180|270)/(?<w>\d+)/(?<h>\d+)/(?<file>.+)$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter_buffer 25M;
        image_filter rotate $deg;
        image_filter resize $w $h;
        image_filter_jpeg_quality 85;
        image_filter_interlace on;
        image_filter_sharpen 2;

        error_page 415 = @empty_fallback;
    }

    location @empty_fallback {
        internal;
        default_type image/gif;
        return 200 "\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b";
    }
}
```

**Валидация результата:**
```bash
curl -s --unix-socket /var/run/angie/image_filter.sock "http://localhost/rotate-and-resize/90/800/600/photo.jpg" > /tmp/transformed.jpg
file /tmp/transformed.jpg
# → /tmp/transformed.jpg: JPEG image data, JFIF standard 1.01, aspect ratio, density 1x1, segment length 16, progressive, precision 8, 600x800, frames 3

# Проверка прогрессивной структуры JPEG через identify
magick identify -verbose /tmp/transformed.jpg | grep -i interlace
# → Interlace: JPEG
```

### Сценарий 4: Белые списки пресетов геометрии (Защита от CPU DoS)

Ограничение доступных комбинаций разрешения через директиву `map`. Исключает атаки исчерпания памяти и процессорных ресурсов произвольными запросами вида `/resize/123x456/`.

```nginx
# Определение допустимых пресетов геометрии
map "$w:$h" $is_valid_geometry {
    "160:120"   1;
    "320:240"   1;
    "640:480"   1;
    "800:600"   1;
    "1280:720"  1;
    "1920:1080" 1;
    default     0;
}

server {
    listen 80;
    server_name cdn.local;

    location ~* ^/media/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
        if ($is_valid_geometry = 0) {
            return 403 "Dimension preset not allowed. Use standard profiles.\n";
        }

        proxy_cache img_cache;
        proxy_cache_key "$host$uri$is_args$args";
        proxy_cache_valid 200 30d;
        proxy_cache_lock on;

        proxy_pass http://unix:/var/run/angie/image_filter.sock:/media_backend/$w/$h/$file;
    }
}
```

**Валидация защиты:**
```bash
# 1. Запрос недопустимого размера
curl -I http://cdn.local/media/333x555/banner.jpg
# → HTTP/1.1 403 Forbidden

# 2. Запрос легитимного пресета
curl -I http://cdn.local/media/800x600/banner.jpg
# → HTTP/1.1 200 OK
```

---

## Операции и команды

Сводка команд системного инженера и SRE для валидации, мониторинга и отладки работы модуля:

### 1. Проверка состояния сокета и очередей соединений

```bash
# Проверка Unix Domain Socket и текущей длины очереди слушателя
ss -xl '( sport = "/var/run/angie/image_filter.sock" )'
# → Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port
# → u_str LISTEN 0     128    /var/run/angie/image_filter.sock 58249 * 0

# Проверка прав и владельца сокета
ls -la /var/run/angie/image_filter.sock
# → srwxr-xr-x 1 angie angie 0 Oct 14 13:20 /var/run/angie/image_filter.sock
```

### 2. Замер задержки генерации и отклика кэша

```bash
# Замер времени обработки первого запроса (MISS, трансформация CPU)
curl -s -o /dev/null -w "HTTP: %{http_code} | Type: %{content_type} | Time: %{time_total}s\n" \
  -H "Accept: image/avif" http://images.local/resize/800/banner.jpg
# → HTTP: 200 | Type: image/avif | Time: 0.142s

# Замер времени повторного запроса (HIT, отдача из дискового кэша)
curl -s -o /dev/null -w "HTTP: %{http_code} | Type: %{content_type} | Time: %{time_total}s\n" \
  -H "Accept: image/avif" http://images.local/resize/800/banner.jpg
# → HTTP: 200 | Type: image/avif | Time: 0.002s
```

### 3. Инспекция параметров сгенерированного файла

```bash
# Проверка MIME-типа, геометрии и глубины цвета утилитой ImageMagick
magick identify -format "Format: %m | Size: %wx%h | Geometry: %g | Depth: %z-bit\n" /tmp/avatar_test.webp
# → Format: WEBP | Size: 300x300 | Geometry: 300x300+0+0 | Depth: 8-bit

# Инспекция метаданных и Exif-тегов через exiftool (проверка удаления приватных GPS/Exif тегов)
exiftool /tmp/avatar_test.webp | grep -E "Image Width|Image Height|GPS"
# → Image Width                     : 300
# → Image Height                    : 300
```

### 4. Мониторинг утилизации ресурсов воркерами

```bash
# Потребление CPU и RSS RAM процессами воркеров Angie во время стресс-трансформации
ps -eo pid,user,comm,%cpu,%mem,rss,vsz --sort=-rss | grep -E "angie|COMMAND" | head -n 10
# →   PID USER     COMMAND         %CPU %MEM   RSS    VSZ
# → 12401 angie    angie: worker    85.2  1.8 148200 482100
# → 12402 angie    angie: worker    78.4  1.6 132400 479800
```

### 5. Телеметрия зоны фильтрации через REST API Angie

```bash
# Получение счетчиков кодов ответов (контроль 415 ошибок) и времени обработки
curl -s http://127.0.0.1:8080/api/http/status_zones/image_filter_backend | jq '.responses'
# → {
# →   "1xx": 0,
# →   "2xx": 45120,
# →   "3xx": 0,
# →   "4xx": 12,
# →   "5xx": 0,
# →   "codes": {
# →     "200": 45120,
# →     "415": 12
# →   },
# →   "total": 45132
# → }
```

---

## Устранение неисправностей (Troubleshooting)

| Проблема / Симптом | Вероятная причина | Диагностика | Решение |
|:---|:---|:---|:---|
| **Код ошибки `415 Unsupported Media Type`** | 1. Размер входящего сжатого оригинала превышает `image_filter_buffer`.<br>2. Исходный файл поврежден или не является поддерживаемым растром. | Проверить логи:<br>`grep "image buffer is too small" /var/log/angie/error.log`<br>Проверить размер оригинала:<br>`stat -c %s original.jpg` | 1. Увеличить `image_filter_buffer` в `server` бэкенда до `20M–30M`.<br>2. Проверить целостность файла утилитой `file` или `identify`. |
| **Код `415` при валидных файлах AVIF/WebP/HEIC** | В системной библиотеке `libgd` отсутствует скомпилированная поддержка кодеков `libavif`, `libwebp` или `libheif`. | Выполнить проверку линковки:<br>`ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so` | Установить актуальные системные пакеты `libgd3`, `libavif16`, `libheif1`, переустановить пакет модуля `angie-module-image-filter`. |
| **Код ошибки `502 Bad Gateway` на фронтенде** | 1. Отсутствуют права на чтение/запись Unix-сокета.<br>2. Воркер бэкенда завершился аварийно (OOM-killer). | 1. Проверить ошибки:<br>`grep "Permission denied" /var/log/angie/error.log`<br>2. Проверить системный лог:<br>`dmesg -T \| grep -i "oom-killer"` | 1. Назначить права: `chown angie:angie /var/run/angie/image_filter.sock` и `chmod 750`.<br>2. Увеличить лимит `MemoryMax` в unit-файле systemd Angie. |
| **Код `504 Gateway Time-out` при генерации AVIF** | Время кодирования тяжелого изображения превысило `proxy_read_timeout` фронтенда. | Измерить latency зоны:<br>`curl .../status_zones/image_filter_backend \| jq .responses.time`<br>Проверить лог:<br>`grep "upstream timed out" /var/log/angie/error.log` | 1. Увеличить `image_filter_avif_speed` до `9` или `10`.<br>2. Снизить `image_filter_avif_quality` до `60–65`.<br>3. Увеличить `proxy_read_timeout` на фронтенде до `5s–10s`. |
| **Размытые (нечеткие) миниатюры после ресайза** | Потеря высокочастотных деталей при математическом сжатии растра (билинейная/бикубическая фильтрация). | Визуальный анализ превью $300 \times 300$ на экранах с высокой плотностью пикселей (HiDPI / Retina). | Добавить директиву `image_filter_sharpen 2;` (или `3–5` для микро-превью) в локацию ресайза. |
| **Отравление кэша (Cache Poisoning) — клиенты без поддержки AVIF получают AVIF** | В ключе `proxy_cache_key` отсутствует переменная формата, либо пропущен заголовок `Vary: Accept`. | Проверить ответ фронтенда:<br>`curl -I http://images.local/resize/800/photo.jpg`<br>Убедиться в наличии заголовка `Vary: Accept`. | 1. Добавить `add_header Vary "Accept" always;`.<br>2. Включить переменную формата (`$img_target_format`) в строку `proxy_cache_key`. |
| **Черный фон вместо прозрачности у логотипов PNG/WebP** | Отключена директива сохранения прозрачности или старая версия `libgd`. | Проверить конфигурацию на наличие `image_filter_transparency off;`. | Убедиться, что параметр `image_filter_transparency on;` активен (по умолчанию включен). |
| **Всплеск нагрузки на CPU и падение пропускной способности** | Клиенты запрашивают произвольные разрешения, вызывая непрерывные кэш-промахи (Cache Churn / DoS). | Проанализировать access-лог на уникальность URI:<br>`awk '{print $7}' /var/log/angie/access.log \| cut -d'/' -f3 \| sort \| uniq -c \| sort -nr` | Внедрить строгий белый список допустимых геометрических пресетов через директиву `map` (см. Сценарий 4). |

---

## Лучшие практики

1. **Двухуровневая изоляция контуров:** Никогда не совмещайте директиву `proxy_cache` и директивы `image_filter` в рамках одного блока `location`. Модуль `image_filter` работает как выходной фильтр тела ответа: при совмещении трансформация будет выполняться повторно на каждый запрос мимо кэша.
2. **Белые списки пресетов геометрии:** Категорически запрещайте передачу произвольных чисел в качестве параметров ширины и высоты. Разрешайте только фиксированную сетку разрешений (например, 160, 320, 640, 800, 1024, 1280, 1920).
3. **Оптимизация параметров кодеков под High Load:**
   - Для AVIF: `image_filter_avif_speed 9;` и `image_filter_avif_quality 65;`. Дает 90% экономии веса относительно JPEG при 5–7-кратном снижении нагрузки на процессор по сравнению со значением `speed 6`.
   - Для WebP: `image_filter_webp_quality 78;`.
   - Для JPEG: `image_filter_jpeg_quality 85;` и `image_filter_interlace on;`.
4. **Защита от шквала запросов (Cache Stampede):** Обязательно активируйте на фронтенде директивы `proxy_cache_lock on;`, `proxy_cache_lock_timeout 5s;` и `proxy_cache_use_stale updating error timeout;`. Это гарантирует, что при одновременном обращении 1 000 клиентов за новой картинкой в бэкенд уйдет ровно **один** запрос, а остальные 999 подождут заполнения кэша.
5. **Безопасный буфер декомпрессии:** Устанавливайте `image_filter_buffer 20M–25M;`. Буфер меньшего объема гарантированно приведет к сбоям при обработке современных фото со смартфонов.
6. **Квотирование ресурсов в systemd (cgroups v2):** На bare-metal серверах всегда ограничивайте оперативную память Angie через `MemoryMax` и `MemoryHigh`. Это предотвратит падение соседних сервисов (СУБД, мониторинг) при аварийном наплыве тяжелых трансформаций.
7. **Процедура регламентного отката (Zero-Downtime Rollback):**
   - Для экстренного отключения динамического ресайза переключите фронтенд на раздачу оригиналов директивой `try_files $uri =404;`.
   - Примените изменения без разрыва соединений: `angie -t && systemctl reload angie`.
   - Сбросьте закэшированные файлы через удаление директории кэша: `rm -rf /var/cache/angie/img/*`.

---

## Дополнительная информация

### Расчет емкости вычислительных ресурсов (Hardware Capacity Sizing)

Для сайзинга выделенного сервера трансформации изображений на bare-metal платформе используются следующие базовые ориентиры:

#### 1. Оценка процессорной мощности (CPU Sizing)

На одном процессорном ядре с базовой частотой 3.0 GHz среднее время выполнения операций составляет:

| Тип операции и целевой формат | Среднее время кодирования (Latency) | Максимальный RPS на 1 ядро CPU |
|:---|:---|:---|
| **JPEG → WebP** ($800 \times 600$, `quality 80`) | 35–45 мс | ~22–28 rps |
| **JPEG → AVIF** ($800 \times 600$, `speed 9, quality 65`) | 120–160 мс | ~6–8 rps |
| **JPEG → AVIF** ($800 \times 600$, `speed 6, quality 65`) | 450–700 мс | ~1.4–2.2 rps |
| **Rotate 90 + Resize** ($800 \times 600$) | 50–65 мс | ~15–20 rps |
| **Накладные расходы Sharpen** (`sharpen 2`) | +15–20 мс | — |

**Формула расчета количества ядер для промахов кэша:**
$$N_{\text{cores}} = \frac{\text{RPS}_{\text{miss}} \times \text{Latency}_{\text{avg}}}{0.7}$$
*(где $0.7$ — коэффициент допустимой утилизации CPU без деградации очередей).*

*Пример:* Пиковый поток кэш-промахов составляет 50 rps на трансформацию в AVIF (`speed 9`, задержка 0.15 с):
$$N_{\text{cores}} = \frac{50 \times 0.15}{0.7} \approx 10.7 \implies \text{требуется не менее 12 выделенных процессорных ядер}.$$

#### 2. Оценка оперативной памяти (RAM Sizing)

$$\text{RAM}_{\text{total}} = N_{\text{workers}} \times \left(\text{image\_filter\_buffer} + W_{\text{max}} \times H_{\text{max}} \times 4 + \text{Arena}_{\text{libavif}}\right) + \text{OS\_Base}$$

Для сервера с 16 воркерами и максимальным разрешением оригинала 12 Мп ($4032 \times 3024$):
$$\text{RAM}_{\text{total}} \approx 16 \times (25\text{ МБ} + 48.7\text{ МБ} + 30\text{ МБ}) + 2048\text{ МБ} \approx 3.7\text{ ГБ RAM}$$

### Метрики Prometheus и правила алертинга

Модуль телеметрии Angie экспортирует метрики зон статуса в формате Prometheus. Ниже приведены проверенные правила мониторинга:

```yaml
# /etc/prometheus/rules/angie_image_filter.yml
groups:
  - name: angie_image_filter_alerts
    rules:
      # Предупреждение о нехватке буфера или поврежденных файлах
      - alert: AngieImageFilterHighError415Rate
        expr: sum(rate(angie_zone_responses_codes{zone="image_filter_backend", code="415"}[5m])) > 5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Высокая частота ошибок HTTP 415 в зоне image_filter_backend"
          description: "Частота ошибок 415 превышает 5 req/s. Проверьте image_filter_buffer и корректность загружаемых оригиналов."

      # Предупреждение о деградации времени генерации изображений
      - alert: AngieImageFilterHighLatencyP95
        expr: histogram_quantile(0.95, sum(rate(angie_zone_responses_time_bucket{zone="image_filter_backend"}[5m])) by (le)) > 0.5
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Высокая задержка P95 трансформации изображений (> 500ms)"
          description: "P95 времени обработки изображений превышает 500 мс. Проверьте параметры avif_speed и утилизацию CPU хоста."
```

### См. также

- **[Обзор модуля image_filter](./overview.md)** — архитектура модуля, поддерживаемые форматы и форматы нового поколения.
- **[Конфигурация внутреннего сервера фильтрации](./filter_configuration.md)** — глубокая настройка параметров воркеров, сокетов и модели памяти.
- **[Стратегии кэширования изображений](./caching.md)** — ключи кэша, защита от отравления кэша и инвалидация.
- **[Производительность и тюнинг](./performance.md)** — оптимизация скорости кодеков, бенчмаркинг и трехуровневая архитектура.
- **[Безопасность и защита от DoS](./security.md)** — ограничение частоты запросов, белые списки и цифровая подпись HMAC.
- **[Установка и сборка модуля](./installation.md)** — компиляция и установка системных библиотек libgd, libavif, libwebp.
