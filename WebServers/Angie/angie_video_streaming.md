# Видеостриминг и работа с медиа в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Angie** — российский высокопроизводительный веб-сервер и почтовый/TCP/UDP прокси-сервер, форк Nginx. Разработан для масштабируемых инфраструктур с сохранением конфигурационной совместимости. Обзор архитектуры — в [Обзор Angie](./angie_overview.md).

**ngx_http_mp4_module** — встроенный модуль Angie для псевдопотоковой отдачи (progressive download / seeking) медиафайлов в контейнерах `.mp4`, `.m4v`, `.m4a`. Поддерживает обработку аргументов `start` и `end` в строке запроса и нарезку атомов `mdat` на лету при наличии структуры faststart.

**ngx_http_flv_module** — встроенный модуль для псевдопотоковой отдачи файлов `.flv` (Flash Video) по смещению времени через аргумент `start`.

> **Статус:** Технология Flash Video и контейнер FLV признаны устаревшими (deprecated). Модуль сохраняется исключительно для поддержки архивных систем; для всех новых развёртываний используются HLS, DASH или MP4.

**ngx_rtmp_module** — динамический модуль Angie (`angie-module-rtmp` в OSS и `angie-pro-module-rtmp` в PRO), добавляющий высокопроизводительный RTMP-сервер с поддержкой живых трансляций, переупаковки в HLS/DASH, управления сессиями, записи потоков и вебхуков авторизации.

**ngx_http_vod_module** — динамический модуль (`angie-module-vod` и `angie-pro-module-vod`) для Video on Demand (VOD). Выполняет транспаковку (remuxing) плоских файлов MP4 в форматы HLS и DASH на лету без предварительного разрезания на диске, поддерживает генерацию адаптивных мультибитрейтных манифестов, миниатюр (thumbnails) и DRM-шифрование.

**ngx_http_slice_module** — встроенный модуль Angie, разбивающий большие HTTP-запросы на мелкие подзапросы фиксированного размера (диапазоны Range), что позволяет эффективно кэшировать тяжелые медиафайлы блоками.

**HLS (HTTP Live Streaming)** — протокол адаптивного потокового вещания на базе HTTP, разработанный Apple. Поток делится на скользящий плейлист (`.m3u8`) и медиа-сегменты (`.ts` или fMP4 `.m4s`).

**DASH (Dynamic Adaptive Streaming over HTTP)** — международный открытый стандарт адаптивной доставки медиа (ISO/IEC 23009-1). Использует XML-манифест (`.mpd`) и сегментированные контейнеры ISO BMFF / fMP4.

**RTMP (Real-Time Messaging Protocol)** — протокол с низкой задержкой на базе TCP (порт 1935), применяемый вещательным ПО (OBS Studio, FFmpeg, аппаратные кодеры) для передачи исходного потока на медиа-сервер (ingest).

**Faststart (moov atom)** — структура метаданных в контейнере MP4, описывающая временные метки, индексы кадров и структуру дорожек. Режим faststart означает физическое размещение заголовка `moov` перед массивом медиаданных `mdat`, что позволяет начать воспроизведение и позиционирование без предварительного скачивания всего файла.

**GOP (Group of Pictures)** — последовательность кадров между соседними ключевыми кадрами (IDR / I-frames). Длительность GOP определяет минимально возможный квант деления потока на сегменты HLS/DASH.

---

## Базовые концепции

### Архитектурные модели доставки видео

Angie поддерживает три архитектурных сценария раздачи медиаконтента:

```
1. Progressive Download (MP4 / FLV):
   [Клиент] --- HTTP GET /video.mp4?start=30 ---> [Angie: ngx_http_mp4_module] ---> [Диск / Хранилище]
            <-- HTTP 200 (перепакованный moov/mdat) --

2. Live Streaming (Ingest + Transmuxing):
   [OBS / FFmpeg] --- RTMP Push (порт 1935) ---> [Angie: ngx_rtmp_module]
                                                      |
                                    [Генерация HLS/DASH в RAM (tmpfs)]
                                                      |
   [Веб-плееры] <--- HTTP GET /hls/live.m3u8, .ts --- [Angie: http engine]

3. Dynamic VOD Packaging (Just-in-Time Muxing):
   [Клиент] --- HTTP GET /hls/movie.mp4/master.m3u8 ---> [Angie: ngx_http_vod_module]
            <-- Динамический HLS/DASH манифест и fMP4 --   (чтение MP4 из хранилища)
```

1. **Статическая отдача с seeking (Progressive Download)** — модули `ngx_http_mp4_module` и `ngx_http_flv_module`. Сервер считывает локальный файл, на лету модифицирует заголовки контейнера и начинает отдачу с запрошенной секунды. Минимальный расход CPU, отсутствие промежуточных файлов.
2. **Лайв-вещание (RTMP Ingest → HLS/DASH Transmuxing)** — модуль `ngx_rtmp_module`. Принимает RTMP-поток от энкодера, в памяти или во временном каталоге фрагментирует медиапоток на чанки (`.ts` / `.m4s`) и обновляет плейлисты. Отдача клиентам выполняется через стандартный пул HTTP-воркеров.
3. **VOD на лету (Just-in-Time Packaging)** — модуль `ngx_http_vod_module`. Исходные файлы хранятся как стандартные монолитные MP4. Модуль принимает запросы HLS/DASH и генерирует чанки fMP4 в оперативной памяти без сохранения на диск.

### Внутреннее устройство контейнера MP4 и Faststart

Файл формата MP4 состоит из древовидной структуры атомов (боксов):
- `ftyp` — идентификатор типа файла и совместимости;
- `moov` — таблица метаданных (разрешение, кодеки, временные смещения ключевых кадров `stss`, смещения чанков `stco`/`co64`);
- `mdat` — сырые сжатые аудиотреки и видеокадры.

По умолчанию большинство видеоредакторов и камер записывают `moov` в **конец** файла, так как точный размер и таймкоды дорожек становятся известны только после завершения кодирования. При попытке воспроизвести такой файл через HTTP сервер не может начать стриминг до тех пор, пока клиент не прочитает весь файл до конца (чтобы извлечь `moov`). 

Модуль `ngx_http_mp4_module` проверяет начало файла:
- Если `moov` находится в начале, модуль читает только метаданные, рассчитывает байтовое смещение запрошенной секунды по таблицам `stts`/`stss`, модифицирует временные шкалы в `moov` и сразу отдает поток клиенту.
- Если `moov` в конце, модулю приходится прочитать весь файл с диска в буфер оперативной памяти (`mp4_max_buffer_size`), чтобы переместить метаданные в начало отправляемого ответа. Это вызывает пиковые нагрузки на I/O и память.

### Подсистема ввода-вывода (I/O) и защита Page Cache

При раздаче медиафайлов размером от сотен мегабайт до десятков гигабайт традиционный механизм буферизованного чтения Linux приводит к деградации системы (Page Cache Thrashing): ядро вытесняет полезные страницы памяти других процессов ради временных блоков видео, которые будут прочитаны один раз.

Для решения этой проблемы в Angie комбинируются три механизма:
- `sendfile on;` — нулевое копирование (zero-copy) данных из дискового буфера в сетевой сокет через ядро;
- `directio <размер>;` — переключение в режим прямого чтения с диска в обход системного кэша страниц (O_DIRECT) для файлов, превышающих заданный размер (обычно 4–8 МБ);
- `aio threads[=pool];` — передача блокирующих дисковых операций отдельному пулу фоновых потоков (thread pool). Основной worker-процесс Angie не зависает в системном вызове `read()` и продолжает обслуживать тысячи сетевых соединений.

### Хранилище для Live-сегментов: размещение в RAM (tmpfs)

При трансляции HLS/DASH модуль RTMP непрерывно создает и удаляет тысячи мелких файлов (`.ts` / `.m4s`). Запись этого трафика на классические SSD или NVMe накопители приводит к двум проблемам:
1. Катастрофический износ ячеек памяти (SSD write endurance) из-за постоянной перезаписи кольцевого буфера.
2. Рост задержек дискового ввода-вывода (I/O wait) при пиковых нагрузках.

**Стандарт архитектуры:** каталог временных сегментов HLS/DASH монтируется как оперативная память `tmpfs` (RAM-диск):
```bash
mount -t tmpfs -o size=2G,uid=angie,gid=angie,mode=0750 tmpfs /var/cache/angie/hls
```

### Синхронизация GOP и длительности фрагментов

HLS и DASH могут нарезать сегменты **только по ключевым кадрам (Keyframes / IDR)**. Если кодировщик настроен с GOP в 2 секунды (например, 60 кадров при 30 fps), то параметр `hls_fragment` должен быть кратен GOP (2s, 4s или 6s).

Если задать `hls_fragment 3s;` при GOP 2s, сервер не сможет разрезать видео на 3-й секунде и будет вынужден удлинять сегмент до 4 секунд или дробить его с нарушением индексации. Это вызывает рывки воспроизведения, рассинхронизацию звука и буферизацию на клиентских устройствах.

### Политика HTTP-кэширования медиаданных

В веб-доставке HLS и DASH действует строгое разделение типов данных:
- **Манифесты (`.m3u8`, `.mpd`):** часто обновляются (в live каждые несколько секунд). Должны отдаваться с запретом долговременного кэширования: `Cache-Control: no-cache, no-store, must-revalidate`.
- **Сегменты (`.ts`, `.m4s`, `.mp4`):** неизменяемые статические блоки медиаданных с уникальными именами. Должны кэшироваться агрессивно клиентами, CDN и промежуточными прокси: `Cache-Control: public, max-age=86400, immutable`.

### Таблица поддерживаемых форматов и кодеков

| Протокол / Модуль | Входной контейнер / формат | Выходной формат | Видеокодеки | Аудиокодеки | Применение в инфраструктуре |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ngx_http_mp4_module` | MP4, M4V, M4A, MOV | MP4 (progressive) | H.264, H.265 (HEVC), AV1, VP9 | AAC, MP3, Opus, AC-3, E-AC-3 | Простые плееры, промо-ролики, подкасты |
| `ngx_http_flv_module` | FLV | FLV | H.264, Sorenson Spark | MP3, AAC | Устаревшие архивные системы |
| `ngx_rtmp_module` | RTMP (порт 1935) | RTMP, HLS, MPEG-DASH | H.264, H.265 | AAC, MP3 | Live-трансляции, вебинары, стриминг с OBS |
| `ngx_http_vod_module` | MP4 (локальный/удаленный) | HLS, DASH, MSS, HDS | H.264, H.265, AV1, VP8, VP9 | AAC, AC-3, E-AC-3, Opus, MP3 | Онлайн-кинотеатры, каталоги VOD, архивы |
| `ngx_http_slice_module` | Любой HTTP-ответ | Range-блоки | Агностичен | Агностичен | Кэширование тяжелого видео на CDN-нодах |

---

## Практические сценарии

### Предварительные требования

Для работы со сценариями требуются:
1. Установленный сервер Angie (OSS или PRO) версии 1.12.x на базе Linux (Debian, Ubuntu, RHEL, AlmaLinux).
2. Установленные пакеты динамических модулей и утилит:
   - Debian/Ubuntu: `sudo apt-get install -y angie-module-rtmp angie-module-vod ffmpeg`
   - RHEL/AlmaLinux: `sudo dnf install -y angie-module-rtmp angie-module-vod ffmpeg`
3. Выделенный непривилегированный пользователь `angie` и группа `angie`.
4. Каталоги для кэша и сегментов с корректными правами доступа.

---

### Сценарий 1: Высокопроизводительная отдача MP4 с seeking и пулом потоков

Настройка статической отдачи видеотеки с поддержкой перемотки, ограничением пиковой скорости после начальной буферизации и обходом дискового кэша страниц.

```nginx
# /etc/angie/http.d/mp4_streaming.conf

# Определение пула потоков для асинхронного дискового ввода-вывода
thread_pool video_pool threads=32 max_queue=65536;

server {
    listen 80;
    listen 443 ssl;
    server_name media.example.com;

    ssl_certificate     /etc/pki/tls/certs/media.example.com.crt;
    ssl_certificate_key /etc/pki/tls/private/media.example.com.key;

    # Каталог с подготовленными видеофайлами
    root /srv/media/vod;

    location /videos/ {
        # Активация обработчика MP4
        mp4;
        mp4_buffer_size      4m;
        mp4_max_buffer_size  64m;
        mp4_start_key_frame  on;

        # Ограничение полосы: первые 15 МБ отдаются на максимальной скорости
        # для мгновенного старта плеера, далее скорость ограничивается 3 МБ/с (~24 Мбит/с)
        limit_rate_after 15m;
        limit_rate 3m;

        # Тюнинг I/O для предотвращения блокировки воркеров
        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;

        # Для файлов крупнее 4 МБ используем directio с пулом потоков
        directio 4m;
        aio threads=video_pool;

        # Заголовки кэширования статики
        add_header Cache-Control "public, max-age=604800, immutable" always;
        add_header Accept-Ranges bytes always;
    }
}
```

Проверка сценария:

```bash
# 1. Запрос метаданных с поддержкой Range
curl -I "http://media.example.com/videos/sample.mp4"
# → HTTP/1.1 200 OK
# → Accept-Ranges: bytes
# → Content-Type: video/mp4

# 2. Запрос нарезки диапазона через аргументы модуля
curl -I "http://media.example.com/videos/sample.mp4?start=10&end=20"
# → HTTP/1.1 200 OK
# → Content-Type: video/mp4

# 3. Запрос стандартного HTTP Range (RFC 7233)
curl -I -r 0-1048575 "http://media.example.com/videos/sample.mp4"
# → HTTP/1.1 206 Partial Content
# → Content-Range: bytes 0-1048575/...
```

---

### Сценарий 2: Отдача устаревшего формата FLV с seeking (Legacy)

Конфигурация для архивных хранилищ flash-видео.

```nginx
# /etc/angie/http.d/flv_archive.conf

server {
    listen 80;
    server_name archive.example.com;

    location /archive/flv/ {
        root /srv/media;
        flv;

        limit_rate_after 5m;
        limit_rate 1m;

        sendfile on;
        tcp_nopush on;
    }
}
```

Проверка сценария:

```bash
curl -I "http://archive.example.com/archive/flv/legacy_recording.flv?start=30"
# → HTTP/1.1 200 OK
# → Content-Type: video/x-flv
```

> **Рекомендация по миграции:** Для отказа от FLV выполните пакетное перекодирование архива в MP4 без пересжатия видеопотока:
> `ffmpeg -i input.flv -c:v copy -c:a aac -movflags +faststart output.mp4`

---

### Сценарий 3: Production Live-вещание (RTMP Ingest → HLS/DASH) на tmpfs с авторизацией

Полнофункциональный контур приёма live-потока по RTMP, проверки прав публикатора через backend-вебхук, генерации HLS/DASH в оперативной памяти и раздачи клиентам с CORS.

**Шаг 1. Загрузка динамического модуля в `/etc/angie/angie.conf`:**

```nginx
# /etc/angie/angie.conf (в глобальном контексте main)
load_module modules/ngx_rtmp_module.so;
```

**Шаг 2. Настройка RTMP и HTTP контекстов:**

```nginx
# /etc/angie/angie.conf или отдельный include

rtmp {
    server {
        listen 1935;
        chunk_size 4096;
        ping 30s;
        ping_timeout 10s;
        max_message 10m;

        application live {
            live on;
            meta copy;

            # Вебхук авторизации: при попытке публикации поток проверяется бэкендом.
            # Если бэкенд вернет HTTP 2xx — публикация разрешена, 4xx/5xx — обрыв.
            on_publish http://127.0.0.1:8080/api/v1/stream/auth;
            on_publish_done http://127.0.0.1:8080/api/v1/stream/done;

            # HLS настройки (генерация в RAM)
            hls on;
            hls_path /var/cache/angie/hls;
            hls_fragment 3s;
            hls_playlist_length 30s;
            hls_cleanup on;
            hls_nested on;
            hls_fragment_naming system;

            # DASH настройки
            dash on;
            dash_path /var/cache/angie/dash;
            dash_fragment 3s;
            dash_playlist_length 30s;
            dash_cleanup on;
            dash_nested on;
        }
    }
}

http {
    server {
        listen 80;
        listen 443 ssl;
        server_name stream.example.com;

        ssl_certificate     /etc/pki/tls/certs/stream.example.com.crt;
        ssl_certificate_key /etc/pki/tls/private/stream.example.com.key;

        # Раздача HLS плейлистов и сегментов
        location /hls/ {
            alias /var/cache/angie/hls/;

            # CORS заголовки для воспроизведения в браузерах
            add_header Access-Control-Allow-Origin * always;
            add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
            add_header Access-Control-Expose-Headers "Content-Length, Content-Range" always;

            # Плейлисты нельзя кэшировать
            location ~ \.m3u8$ {
                add_header Cache-Control "no-cache, no-store, must-revalidate" always;
                add_header Access-Control-Allow-Origin * always;
                types {
                    application/vnd.apple.mpegurl m3u8;
                }
            }

            # Сегменты .ts кэшируются на короткое время
            location ~ \.ts$ {
                add_header Cache-Control "public, max-age=60, immutable" always;
                add_header Access-Control-Allow-Origin * always;
                types {
                    video/mp2t ts;
                }
            }
        }

        # Раздача DASH манифестов и сегментов
        location /dash/ {
            alias /var/cache/angie/dash/;

            add_header Access-Control-Allow-Origin * always;

            location ~ \.mpd$ {
                add_header Cache-Control "no-cache, no-store, must-revalidate" always;
                add_header Access-Control-Allow-Origin * always;
                types {
                    application/dash+xml mpd;
                }
            }

            location ~ \.m4s$ {
                add_header Cache-Control "public, max-age=60, immutable" always;
                add_header Access-Control-Allow-Origin * always;
                types {
                    video/iso.segment m4s;
                }
            }
        }
    }
}
```

Проверка сценария:

```bash
# 1. Запуск тестового вещания через FFmpeg с передачей ключа авторизации
ffmpeg -re -i /srv/media/sample.mp4 -c:v copy -c:a copy -f flv "rtmp://127.0.0.1:1935/live/ch1?token=secret123"

# 2. Проверка появления HLS-плейлиста в tmpfs
curl -s http://stream.example.com/hls/ch1/index.m3u8
# → #EXTM3U
# → #EXT-X-VERSION:3
# → #EXT-X-TARGETDURATION:3
# → #EXTINF:3.000,
# → 1718000001.ts
```

---

### Сценарий 4: Адаптивный мультибитрейтный Live-стриминг (ABR) через FFmpeg exec_push

Трансляция с аппаратным или программным транскодированием исходного видеопотока на сервере в 3 профиля разрешения (1080p, 720p, 480p) с генерацией общего HLS Master Playlist.

```nginx
# /etc/angie/conf.d/rtmp_transcode.conf

rtmp {
    server {
        listen 1935;

        # Входная точка для энкодера (скрытая)
        application raw_in {
            live on;

            # Запуск транскодирования через системный бинарник FFmpeg при появлении потока
            exec_push /usr/bin/ffmpeg -i rtmp://127.0.0.1:1935/raw_in/$name
                -c:a aac -b:a 128k -ar 44100
                -c:v libx264 -preset veryfast -b:v 4000k -maxrate 4200k -bufsize 8000k -s 1920x1080 -g 60 -f flv rtmp://127.0.0.1:1935/hls_out/$name_hi
                -c:a aac -b:a 96k  -ar 44100
                -c:v libx264 -preset veryfast -b:v 2000k -maxrate 2200k -bufsize 4000k -s 1280x720  -g 60 -f flv rtmp://127.0.0.1:1935/hls_out/$name_mid
                -c:a aac -b:a 64k  -ar 44100
                -c:v libx264 -preset veryfast -b:v 800k  -maxrate 900k  -bufsize 1600k -s 854x480   -g 60 -f flv rtmp://127.0.0.1:1935/hls_out/$name_low;
        }

        # Выходная точка формирования HLS
        application hls_out {
            live on;
            hls on;
            hls_path /var/cache/angie/hls;
            hls_fragment 2s;
            hls_playlist_length 20s;
            hls_cleanup on;
            hls_nested on;

            # Автоматическая генерация Master Playlist
            hls_variant _hi  BANDWIDTH=4128000 RESOLUTION=1920x1080;
            hls_variant _mid BANDWIDTH=2096000 RESOLUTION=1280x720;
            hls_variant _low BANDWIDTH=864000  RESOLUTION=854x480;
        }
    }
}
```

Проверка сценария:

```bash
# Получение мастер-плейлиста
curl -s http://stream.example.com/hls/ch1.m3u8
# → #EXTM3U
# → #EXT-X-STREAM-INF:BANDWIDTH=4128000,RESOLUTION=1920x1080
# → ch1_hi/index.m3u8
# → #EXT-X-STREAM-INF:BANDWIDTH=2096000,RESOLUTION=1280x720
# → ch1_mid/index.m3u8
# → #EXT-X-STREAM-INF:BANDWIDTH=864000,RESOLUTION=854x480
# → ch1_low/index.m3u8
```

---

### Сценарий 5: VOD-стриминг на лету через модуль ngx_http_vod_module

Организация раздачи каталога монолитных MP4-файлов в виде HLS и DASH без предварительной конвертации с кэшированием метаданных в оперативной памяти.

**Шаг 1. Загрузка модуля в `/etc/angie/angie.conf`:**

```nginx
load_module modules/ngx_http_vod_module.so;
```

**Шаг 2. Конфигурация VOD в контексте `http`:**

```nginx
# /etc/angie/http.d/vod_streaming.conf

http {
    # Пулы оперативной памяти для кэширования парсинга видеофайлов
    vod_metadata_cache metadata_cache 512m;
    vod_response_cache response_cache 128m;
    vod_mapping_cache  mapping_cache  32m;

    # Общие параметры упаковщика
    vod_last_modified_types *;
    vod_segment_duration 4000; # 4000 мс = 4 секунды
    vod_align_segments_to_key_frames on;

    server {
        listen 80;
        server_name vod.example.com;

        # Локальный каталог исходных видеофайлов MP4
        root /srv/media/movies;

        # Режим отдачи: local (файлы читаются с локального диска или NFS)
        vod_mode local;

        # HLS эндпоинт
        location /hls/ {
            vod hls;

            add_header Access-Control-Allow-Origin * always;
            add_header Access-Control-Expose-Headers "Content-Length, Content-Range" always;

            # Формат сегментов: MPEG-TS или fMP4
            vod_manifest_segment_durations_mode accurate;
        }

        # DASH эндпоинт
        location /dash/ {
            vod dash;
            add_header Access-Control-Allow-Origin * always;
        }

        # Генерация превью/миниатюр кадров на лету
        location /thumbnails/ {
            vod thumb;
            vod_thumbnail_format jpeg;
            vod_thumbnail_size 320;
        }
    }
}
```

Проверка сценария:

```bash
# 1. Запрос динамически сгенерированного плейлиста HLS
curl -s "http://vod.example.com/hls/trailers/sample.mp4/master.m3u8"
# → #EXTM3U
# → #EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=...,RESOLUTION=1920x1080
# → index.m3u8

# 2. Запрос миниатюры кадра на 10-й секунде (10000 мс)
curl -s "http://vod.example.com/thumbnails/trailers/sample.mp4/thumb-10000-w320.jpg" -o /tmp/thumb.jpg
file /tmp/thumb.jpg
# → /tmp/thumb.jpg: JPEG image data, baseline, precision 8, 320x180
```

---

### Сценарий 6: Кэширующий обратный прокси для видео с ngx_http_slice_module

При проксировании тяжелых медиафайлов клиенты часто запрашивают фрагменты через `Range`. Без `slice` Angie был бы вынужден скачивать весь файл с бэкенда. Модуль `slice` запрашивает и кэширует контент чанками (по 2 МБ).

```nginx
# /etc/angie/http.d/video_cache_proxy.conf

proxy_cache_path /var/cache/angie/video_cache
                 levels=1:2
                 keys_zone=video_slice_zone:64m
                 max_size=50g
                 inactive=30d
                 use_temp_path=off;

server {
    listen 80;
    server_name cdn-edge.example.com;

    location /stream/ {
        # Размер одного чанка
        slice 2m;

        proxy_cache video_slice_zone;
        proxy_cache_key $uri$slice_range;
        proxy_cache_valid 200 206 7d;
        proxy_cache_valid 404 1m;

        # Передача диапазона на исходный медиасервер
        proxy_set_header Range $slice_range;

        # Блокировка параллельных запросов на один и тот же некэшированный чанк
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_lock_age 10s;

        # Разрешить клиентам запрашивать свои диапазоны поверх кэшированных слайсов
        proxy_force_ranges on;

        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_pass http://storage_origin_backend;

        add_header X-Cache-Status $upstream_cache_status always;
        add_header Accept-Ranges bytes always;
    }
}
```

Проверка сценария:

```bash
# Первый запрос: промах кэша (MISS), подгрузка только слайса 0-2097151
curl -I -r 0-100000 "http://cdn-edge.example.com/stream/movie.mp4"
# → HTTP/1.1 206 Partial Content
# → X-Cache-Status: MISS
# → Content-Range: bytes 0-100000/104857600

# Второй запрос того же диапазона: попадание в кэш (HIT)
curl -I -r 50000-150000 "http://cdn-edge.example.com/stream/movie.mp4"
# → HTTP/1.1 206 Partial Content
# → X-Cache-Status: HIT
```

---

### Сценарий 7: Ротация записей и очистка диска через systemd-tmpfiles

Модуль RTMP умеет сохранять запись стримов (`record all;`), но не выполняет ротацию старых файлов. Использование cron с прямым удалением `rm` не всегда безопасно. Надежный стандарт Linux — юнит `systemd-tmpfiles`.

**Шаг 1. Конфигурация записи в RTMP:**

```nginx
application live {
    live on;
    record all;
    record_path /var/archive/angie/records;
    record_unique on;
    record_suffix _%Y%m%d_%H%M%S.flv;
    record_max_size 2048m;
}
```

**Шаг 2. Конфигурация правила очистки в `/etc/tmpfiles.d/angie-recordings.conf`:**

```ini
# Тип  Путь                           Режим  Владелец  Группа  Возраст
# d    /var/cache/angie/hls           0750   angie     angie   1h
# d    /var/archive/angie/records     0750   angie     angie   14d

d /var/cache/angie/hls 0750 angie angie 1h
d /var/archive/angie/records 0750 angie angie 14d
```

Применение и валидация:

```bash
# Ручная проверка применения правил очистки без перезагрузки ОС
sudo systemd-tmpfiles --clean /etc/tmpfiles.d/angie-recordings.conf
# → Удаляются файлы записей старше 14 дней и остаточные сегменты старше 1 часа
```

---

### Сценарий 8: Системный тюнинг ядра Linux для серверов видеостриминга

Медиасерверы генерируют высокий исходящий сетевой трафик и удерживают десятки тысяч открытых соединений. Необходима калибровка сетевого стека Linux в `/etc/sysctl.d/99-angie-media.conf`.

```ini
# /etc/sysctl.d/99-angie-media.conf

# Увеличение очереди подключений к сокетам
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 32768

# Размеры сетевых буферов для передачи высокобитрейтных потоков
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Алгоритм контроля перегрузки сети (BBR рекомендуется для стриминга)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Защита от исчерпания файловых дескрипторов
fs.file-max = 2097152

# Быстрая утилизация FIN-сокетов
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
```

Применение:

```bash
sudo sysctl -p /etc/sysctl.d/99-angie-media.conf
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_congestion_control = bbr
```

---

## Операции и команды

### Установка пакетов модулей

Установка динамических модулей для медиавещания из официального репозитория:

```bash
# Для Debian / Ubuntu:
sudo apt-get update
sudo apt-get install -y angie-module-rtmp angie-module-vod

# Для RHEL / AlmaLinux / Rocky Linux / РЕД ОС:
sudo dnf install -y angie-module-rtmp angie-module-vod
```

### Проверка загрузки и совместимости модулей

```bash
# 1. Проверка синтаксиса конфигурации с загруженными директивами
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Проверка наличия встроенных модулей mp4 и flv в бинарнике
angie -V 2>&1 | grep -oE "with-http_(mp4|flv|slice)_module"
# → with-http_mp4_module
# → with-http_flv_module
# → with-http_slice_module

# 3. Проверка установленных динамических библиотек модулей
ls -l /usr/lib/angie/modules/ | grep -E "(rtmp|vod)"
# → -rwxr-xr-x 1 root root ngx_rtmp_module.so
# → -rwxr-xr-x 1 root root ngx_http_vod_module.so
```

### Мониторинг RTMP и управление потоками (rtmp_stat и rtmp_control)

Для отслеживания активных издателей и зрителей настраивается служебный HTTP-эндпоинт:

```nginx
# В секции http -> server (например, порт 8080 для внутренних систем мониторинга):
location /stat {
    rtmp_stat all;
    rtmp_stat_stylesheet stat.xsl;
    allow 127.0.0.1;
    allow 10.0.0.0/8;
    deny all;
}

location /control {
    rtmp_control all;
    allow 127.0.0.1;
    deny all;
}
```

Диагностические команды SRE:

```bash
# 1. Получение статистики в формате XML (для Prometheus / Zabbix скрейперов)
curl -s http://127.0.0.1:8080/stat | grep -oE "<client>.*</client>"

# 2. Принудительный сброс зависшего публикатора через rtmp_control
# Синтаксис: /control/drop/publisher?app=<app>&name=<stream_name>
curl -s "http://127.0.0.1:8080/control/drop/publisher?app=live&name=ch1"
# → 1 (сессия разорвана)

# 3. Ручной старт записи потока без перезагрузки сервера
curl -s "http://127.0.0.1:8080/control/record/start?app=live&name=ch1"
# → /var/archive/angie/records/ch1_20261014_183000.flv
```

### Подготовка медиафайлов утилитами ffprobe и ffmpeg

```bash
# 1. Проверка расположения moov-атома в MP4 (проверка faststart)
ffprobe -v trace /srv/media/sample.mp4 2>&1 | grep -E -m 2 "type:'(moov|mdat)'"
# Если первой строкой выводится 'moov' — файл готов к progressive download!
# Если первой строкой идет 'mdat' — требуется оптимизация.

# 2. Перемещение moov-атома в начало файла без перекодирования видео/аудио
ffmpeg -i /srv/media/input.mp4 -c copy -movflags +faststart /srv/media/output.mp4

# 3. Проверка длительности ключевых кадров (GOP)
ffprobe -select_streams v:0 -show_frames -show_entries frame=pict_type,pts_time /srv/media/sample.mp4 \
  | grep -B 1 "pict_type=I" | head -n 10
```

### Бесшовная перезагрузка конфигурации

Стриминговые соединения (RTMP, длинные HTTP Range) не должны сбрасываться при обновлении конфигурации. Angie выполняет graceful reload:

```bash
sudo systemctl reload angie
# или напрямую через сигнал master-процессу:
sudo angie -s reload
```

---

## Устранение неисправностей

### 1. MP4 не поддерживает seeking (перемотка приводит к перезапуску с начала)

- **Симптом:** При передаче `?start=60` в URL или перемотке в веб-плеере видео всегда стартует с 0 секунды.
- **Причина:** Заголовок `moov` находится в конце файла; файл не оптимизирован с `faststart`.
- **Диагностика:**
  ```bash
  ffprobe -v trace /srv/media/video.mp4 2>&1 | head -n 30 | grep -o "type:'moov'"
  # → Вывод пустой, так как атом moov находится в конце файла
  ```
- **Решение:** Выполнить перепаковку файла с флагом `faststart`:
  ```bash
  ffmpeg -i /srv/media/video.mp4 -c copy -movflags +faststart /srv/media/video_fast.mp4
  mv /srv/media/video_fast.mp4 /srv/media/video.mp4
  ```

---

### 2. Ошибка "mp4 moov atom is too large" в error.log

- **Симптом:** В журнале ошибок появляется запись:
  `[error] ... mp4 moov atom is too large: 35651584, you may want to increase mp4_max_buffer_size in ...`
- **Причина:** Для длинных видеофайлов (более 2–3 часов) или файлов с большим количеством дорожек таблица индексов `moov` превышает стандартный лимит буфера Angie (10 МБ).
- **Решение:** Увеличить размер буфера в блоке `location /videos/`:
  ```nginx
  mp4_max_buffer_size 64m;
  mp4_buffer_size     8m;
  ```

---

### 3. Зависание worker-процессов и высокий iowait при раздаче тяжелых файлов

- **Симптом:** Метрика `load average` растет, утилита `top` фиксирует высокий процент `%wa` (I/O wait), сетевая отдача проседает, запросы к статике висят в очереди.
- **Причина:** Большое количество клиентов запрашивают видео с вращающихся дисков (HDD). Синхронные вызовы `read()` блокируют поток обработки событий воркера.
- **Решение:** Включить асинхронный пул потоков и обход page cache:
  ```nginx
  # В секции http:
  thread_pool media_pool threads=16 max_queue=32768;

  # В секции location:
  aio threads=media_pool;
  directio 4m;
  ```

---

### 4. Ошибка авторизации RTMP публикации (Publish stream fails)

- **Симптом:** OBS Studio выдает ошибку соединения «Failed to publish stream», в журнале Angie:
  `[error] ... rtmp on_publish: client rejected by backend with code 403`
- **Причина:** Бэкенд авторизации отклонил токен или недоступен.
- **Диагностика:**
  ```bash
  # Проверка доступности бэкенда авторизации
  curl -I -X POST "http://127.0.0.1:8080/api/v1/stream/auth" -d "name=ch1&token=secret"
  ```
- **Решение:** Проверить сетевую связность между Angie и сервисом авторизации, корректность URL в директиве `on_publish` и формат возвращаемого HTTP-статуса (должен быть строго 2xx).

---

### 5. Рывки, заикания и пропуски кадров при воспроизведении HLS Live

- **Симптом:** Видео в плеере замирает каждые несколько секунд, таймлайн прыгает.
- **Причина:** Несоответствие длительности `hls_fragment` и шага опорных кадров (GOP) энкодера.
- **Диагностика:**
  ```bash
  # Проверить реальную длительность сегментов в плейлисте:
  curl -s http://stream.example.com/hls/live/index.m3u8 | grep "#EXTINF"
  # Если вместо стабильных 3.000 приходят 1.200, 4.800, 2.100 — GOP энкодера плавает!
  ```
- **Решение:** В энкодере (OBS / FFmpeg) зафиксировать Keyframe Interval:
  `-g 60 -keyint_min 60 -sc_threshold 0` (при 30 fps это ровно 2.0 секунды), а в Angie задать `hls_fragment 2s;` или `4s;`.

---

### 6. Переполнение оперативной памяти (tmpfs out of space)

- **Симптом:** Диск `/var/cache/angie/hls` заполнен на 100%, новые сегменты не создаются, трансляция останавливается.
- **Причина:** Отключена или не срабатывает директива `hls_cleanup on;`, либо завершившиеся потоки оставили за собой не удаленные каталоги.
- **Диагностика:**
  ```bash
  df -h /var/cache/angie/hls
  ls -la /var/cache/angie/hls | wc -l
  ```
- **Решение:**
  1. Убедиться, что в `rtmp -> application` включены директивы `hls_cleanup on;` и `hls_playlist_length 30s;`.
  2. Настроить периодическую очистку через `systemd-tmpfiles` (см. Сценарий 7).
  3. Увеличить размер tmpfs в `/etc/fstab`, если количество параллельных каналов возросло.

---

### 7. Ошибки CORS при воспроизведении в веб-браузерах (No 'Access-Control-Allow-Origin')

- **Симптом:** Браузерная консоль отображает блокировку Cross-Origin Request для манифестов `.m3u8` или чанков `.ts`.
- **Причина:** В конфигурации `location` отсутствуют CORS-заголовки или отсутствует параметр `always` (при ошибках 404/500 заголовки без `always` не отправляются).
- **Решение:** Добавить в блок отдачи HLS:
  ```nginx
  add_header Access-Control-Allow-Origin * always;
  add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
  add_header Access-Control-Expose-Headers "Content-Length, Content-Range" always;
  ```

---

## Лучшие практики

1. **Размещайте HLS/DASH фрагменты в tmpfs:** Никогда не пишите скользящие фрагменты живых трансляций на физические SSD/HDD. Монтируйте `/var/cache/angie/hls` как `tmpfs` в оперативной памяти.
2. **Всегда подготавливайте файлы с faststart:** Для любых статических видеотек запускайте пакетный пайплайн `ffmpeg -movflags +faststart` перед публикацией контента в webroot.
3. **Согласовывайте GOP энкодера с `hls_fragment`:** Длительность HLS-сегмента должна быть строго кратна интервалу между ключевыми кадрами кодировщика.
4. **Изолируйте дисковый ввод-вывод через `aio threads`:** На серверах с гибридными или шпиндельными хранилищами используйте `directio 4m;` и `aio threads=pool;` для предотвращения вытеснения полезного кэша ОС и зависания воркеров.
5. **Защищайте Live-публикацию вебхуками:** Не оставляйте RTMP порт открытым без директивы `on_publish`. Авторизуйте издателей по ключу или токену.
6. **Четко разделяйте заголовки Cache-Control:** Для плейлистов (`.m3u8`, `.mpd`) отдавайте `no-cache, no-store`, для медиа-сегментов (`.ts`, `.m4s`) — `public, max-age=86400, immutable`.
7. **Используйте `ngx_http_slice_module` на кэширующих прокси:** Для Range-запросов разбивайте тяжелые видеофайлы на блоки по 1–2 МБ (`slice 2m;`), чтобы исключить выкачивание терабайтных файлов целиком при коротких просмотрах.
8. **Автоматизируйте ротацию архивов записей:** Модуль RTMP не удаляет постоянные записи. Используйте `systemd-tmpfiles` для контроля возраста файлов в каталогах записей.
9. **Включайте алгоритм TCP BBR в ядре:** Для сетевых интерфейсов серверов видеотрансляций активируйте `net.ipv4.tcp_congestion_control = bbr`, снижающий задержки и буферизацию у пользователей на мобильных и нестабильных сетях.
10. **Мониторьте состояние стримов через `rtmp_stat`:** Экспортируйте метрики активных потоков, битрейта и числа подключений в Prometheus / Zabbix через защищенный эндпоинт `/stat`.

---

## Дополнительная информация

### Внутренние ссылки базы знаний

- [Обзор Angie](./angie_overview.md) — общая архитектура, отличия от Nginx, сборки и лицензирование.
- [Установка Angie](./angie_installation.md) — детальная настройка официальных репозиториев, управление пакетами и установка динамических модулей.
- [Вспомогательные HTTP-модули Angie](./angie-http-utility-modules.md) — использование утилиты `slice`, модуля подстановок `sub` и разграничения доступа `referer`.
- [Оптимизация производительности Angie](./High_Load/performance_optimization.md) — тонкая настройка рабочих процессов, буферов сокетов и системных лимитов.
- [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md) — организация кластеров раздачи трафика и кэширования.
- [Обратный прокси в Angie](./angie_reverse_proxy.md) — настройка кэширования, проброс заголовков Range и оптимизация keepalive.
- [Логирование Angie](./angie_logging.md) — структурированные логи и сбор метрик потоковой отдачи.
- [Утилитные модули Nginx: WebDAV, видео и SSI](../Nginx/Operations/nginx_webdav_and_media.md) — сравнение медиа-модулей в классическом Nginx.
- [Оптимизация производительности Nginx](../Nginx/Performance/nginx_performance_tuning.md) — системные параметры ядра и тюнинг TCP-стека.

### Официальная документация и ресурсы

- [Документация модуля RTMP в Angie](https://en.angie.software/angie/docs/configuration/modules/external-modules/rtmp/) — синтаксис директив и управление сессиями.
- [Документация модуля VOD в Angie](https://en.angie.software/angie/docs/configuration/modules/external-modules/vod/) — режимы упаковки HLS/DASH на лету.
- [Репозиторий Kaltura nginx-vod-module](https://github.com/kaltura/nginx-vod-module) — исходный код и спецификация JSON-маппинга.
- [RFC 8216: HTTP Live Streaming](https://datatracker.ietf.org/doc/html/rfc8216) — спецификация протокола HLS.

---

## См. также

- [Установка Angie](./angie_installation.md)
- [Оптимизация производительности Angie](./High_Load/performance_optimization.md)
- [Вспомогательные HTTP-модули Angie](./angie-http-utility-modules.md)
- [Обратный прокси в Angie](./angie_reverse_proxy.md)
