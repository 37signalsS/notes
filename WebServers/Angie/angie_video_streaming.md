# Видеостриминг и работа с медиа в Angie

## Определения

**Angie** — российский высокопроизводительный веб-сервер, форк Nginx, разработанный для расширения функциональности при сохранении полной обратной совместимости. Обзор и история проекта — в [Обзор Angie](./angie_overview.md).

**ngx_http_mp4_module** — встроенный модуль потоковой отдачи файлов `.mp4`. Позволяет клиентской стороне запрашивать фрагменты файла (seeking) без полного скачивания, при условии, что файл подготовлен с **faststart** (moov-атом в начале). Поддерживает параметры `start` и `end` в строке запроса для вырезки диапазона.

**ngx_http_flv_module** — встроенный модуль для отдачи файлов `.flv` (Flash Video). Предоставляет базовую поддержку seeking через параметр `start` в URL. Формат устаревающий, модуль сохраняется для совместимости.

**ngx_rtmp_module** — сторонний модуль, добавляющий поддержку протокола RTMP и трансляции в форматах HLS и MPEG-DASH. Принимает RTMP-поток от энкодеров (OBS, FFmpeg) и автоматически генерирует плейлисты и сегменты для HTTP-отдачи. Входит в поставку как `angie-module-rtmp` (Open Source) и `angie-pro-module-rtmp` (PRO).

**ngx_http_vod_module** — сторонний модуль для **Video on Demand (VOD)**. Переупаковывает статические MP4-файлы в HLS, HDS, MSS и DASH на лету, поддерживает генерацию миниатюр и DRM-шифрование. Входит в поставку как `angie-module-vod` и `angie-pro-module-vod`.

**HLS (HTTP Live Streaming)** — протокол потоковой отдачи, разработанный Apple. На сервере создаётся плейлист `.m3u8` и сегменты видео `.ts`, которые отдаются через обычный HTTP.

**DASH (Dynamic Adaptive Streaming over HTTP)** — открытый стандарт адаптивного стриминга. На сервере генерируется манифест `.mpd` и медиа-сегменты, обычно в контейнере MP4 (`.m4v`/`.m4a`).

**VOD (Video on Demand)** — модель доставки видео, при которой пользователь запрашивает конкретный файл и получает его в потоковом или прогрессивном режиме.

**RTMP (Real-Time Messaging Protocol)** — протокол для потоковой передачи аудио/видео между энкодером и медиа-сервером. Работает поверх TCP, обычно на порту 1935.

## Базовые концепции

### Архитектура потоковой отдачи в Angie

Angie поддерживает три уровня работы с видео:

1. **Статическая отдача с seeking** — встроенные модули `mp4` и `flv`. Требуют минимальных ресурсов, не создают промежуточных файлов. Подходят для VOD-сценариев с низкой нагрузкой или когда не нужна адаптивная битрейтность.
2. **Лайв-трансляция (RTMP + HLS/DASH)** — модуль `ngx_rtmp_module` добавляет контекст `rtmp {}` поверх стандартных `http {}` и `events {}`. Принимает RTMP-инкапсулированный поток, переупаковывает в HLS/DASH и отдаёт через HTTP-локации.
3. **VOD-стриминг (HLS/DASH на лету)** — модуль `ngx_http_vod_module` отдаёт статические MP4-файлы через HLS/DASH без предварительного сегментирования. Подходит для каталогов видео по запросу.

### Форматы и кодек

| Формат | Видеокодек | Аудиокодек | Применение |
| :--- | :--- | :--- | :--- |
| MP4 | H.264, H.265, AV1, VP8/VP9 | AAC, MP3, Opus, FLAC, AC-3, E-AC-3, DTS | Статика, VOD, DASH-сегменты |
| FLV | H.264, H.263, VP6 | AAC, MP3, Speex, Opus | Устаревший, RTMP-запись |
| MPEG-TS | H.264, H.265 | AAC, MP3 | Внутренний формат RTMP-модуля для HLS/DASH сегментов |

### Почему не работает обычная отдача MP4 без подготовки

Файл `.mp4` содержит метаданные (moov-атом) обычно в конце файла. Без faststart-подготовки сервер должен прочитать весь файл, чтобы выдать заголовки, что делает seeking невозможным. Модуль `mp4` решает эту задачу, но требует, чтобы moov-атом был в начале.

### Асинхронный ввод-вывод (aio)

При высокой нагрузке на диск модуль `mp4` может работать в связке с `aio on;` или `aio threads;`. Это позволяет отдавать видео, не блокируя worker-процессы на ожидании диска. Режим `aio threads` использует пул потоков для параллельных операций чтения.

## Практические сценарии

### Сценарий 1: Отдача MP4 с seeking и лимитом полосы

Встроенный модуль `mp4` активируется директивой `mp4` в `location`. Параметры `start` и `end` передаются клиентом в строке запроса.

```nginx
location /videos/ {
    root /srv/media;
    mp4;
    mp4_start_key_frame on;
    mp4_max_buffer_size 32m;

    # Лимит скорости отдачи: первые 20 МБ — без ограничения,
    # после — не более 2 МБ/с (≈16 Мбит/с)
    limit_rate_after 20m;
    limit_rate 2m;

    # Асинхронный ввод-вывод при высокой нагрузке на диск
    aio threads;
    directio 4m;                  # для файлов > 4 МБ обходит page cache
}
```

Проверка:

```bash
curl "http://angie.example.com/videos/sample.mp4?start=120&end=130" -o part.mp4
# → HTTP 200, в частичном файле — кадры с 120-й по 130-ю секунды
```

### Сценарий 2: Отдача FLV с seeking

Модуль `flv` активируется директивой `flv`. Поддерживается только параметр `start`.

```nginx
location /streams/ {
    root /srv/media;
    flv;
}
```

Проверка:

```bash
curl "http://angie.example.com/streams/old_video.flv?start=60" -o clip.flv
# → HTTP 200, воспроизведение начинается с 60-й секунды
```

### Сценарий 3: Лайв-трансляция через RTMP → HLS

Модуль `ngx_rtmp_module` создаёт контекст `rtmp {}` для приёма потока и генерирует HLS-артефакты, которые отдаются через стандартный `http {}`.

**Шаг 1. Загрузка модуля** (обычно в `/etc/angie/angie.conf`):

```nginx
load_module modules/ngx_rtmp_module.so;
```

**Шаг 2. Конфигурация RTMP и HTTP:**

```nginx
rtmp {
    server {
        listen 1935;
        chunk_size 4096;

        application live {
            live on;

            # HLS
            hls on;
            hls_path /tmp/hls;
            hls_fragment 3s;
            hls_playlist_length 30s;
            hls_cleanup on;
            hls_nested on;

            # DASH
            dash on;
            dash_path /tmp/dash;
            dash_fragment 3s;
            dash_playlist_length 30s;
            dash_cleanup on;

            # Запись трансляции (не очищается автоматически)
            record all;
            record_path /tmp/recordings;
            record_unique on;
        }
    }
}

http {
    server {
        listen 80;
        server_name stream.example.com;

        location /hls {
            root /tmp;
            add_header Cache-Control no-cache always;
            add_header Access-Control-Allow-Origin * always;

            types {
                application/vnd.apple.mpegurl m3u8;
                video/mp2t ts;
            }
            default_type application/vnd.apple.mpegurl;
        }

        location /dash {
            root /tmp;
            add_header Cache-Control no-cache always;

            types {
                application/dash+xml mpd;
                video/mp4 mp4;
            }
            default_type application/dash+xml;
        }
    }
}
```

Проверка:

```bash
# Отправка тестового потока через FFmpeg
ffmpeg -re -i sample.mp4 -c copy -f flv rtmp://localhost/live/stream1
# → В /tmp/hls/ появляется stream1.m3u8 и сегменты .ts

# Получение плейлиста
curl -s http://stream.example.com/hls/stream1.m3u8
# → #EXTM3U ... #EXTINF:3.0, ...
```

### Сценарий 4: VOD через модуль VOD (HLS/DASH на лету)

Модуль `ngx_http_vod_module` переупаковывает MP4-файлы в HLS или DASH по запросу клиента без предварительной подготовки.

**Шаг 1. Загрузка модуля:**

```nginx
load_module modules/ngx_http_vod_module.so;
```

**Шаг 2. Конфигурация:**

```nginx
http {
    server {
        listen 80;
        server_name vod.example.com;

        location /hls/ {
            vod hls;
            vod_hls_encryption_key_format "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed";
            vod_last_modified_types *;
            add_header Access-Control-Allow-Origin * always;
        }

        location /dash/ {
            vod dash;
            vod_last_modified_types *;
        }

        location /thumb/ {
            vod hls;
            vod_thumbnail_format jpeg;
            vod_thumbnail_size 320;
        }
    }
}
```

Проверка:

```bash
# Запрос плейлиста HLS для конкретного файла
curl -s http://vod.example.com/hls/path/to/movie.mp4/playlist.m3u8
# → #EXTM3U ... #EXTINF: ...

# Запрос миниатюры (первый кадр, 320px по ширине)
curl -s http://vod.example.com/thumb/path/to/movie.mp4/00000001.jpg -o thumb.jpg
# → JPEG-изображение первого кадра
```

### Сценарий 5: Запись трансляции и управление артефактами

```nginx
rtmp {
    server {
        listen 1935;
        application live {
            live on;
            record all;
            record_path /var/cache/angie/recordings;
            record_max_size 1g;          # новый файл после 1 ГБ
            record_suffix _%d-%m-%Y_%H-%M-%S.flv;
        }
    }
}
```

> **Важно:** Файлы записываются вручную и **не очищаются автоматически**. Для ротации используйте `logrotate`, `systemd-tmpfiles` или внешний cron, который удаляет файлы старше нужного порога.

### Сценарий 6: Использование slice для диапазонных запросов к большим файлам

Модуль `slice` позволяет кэшировать и отдавать отдельные диапазоны больших файлов (включая видео) при проксировании:

```nginx
slice 1m;
proxy_cache_path /var/cache/angie/slice keys_zone=slice:20m max_size=10g;

server {
    location ~ \.(mp4|zip)$ {
        slice 1m;
        proxy_cache slice;
        proxy_cache_valid 200 24h;
        proxy_set_header Range $slice_range;
        proxy_pass http://files_backend;
    }
}
```

При Range-запросе клиенту отдаётся только запрошенный диапазон, что снижает нагрузку на канал и диск при перемотке видео.

## Операции и команды

### Встроенные модули (mp4 / flv)

| Директива / Параметр | Уровень | Назначение |
| :--- | :--- | :--- |
| `mp4;` | `location` | Включить обработчик MP4-файлов с поддержкой seeking |
| `mp4_start_key_frame on;` | `location` | Начинать каждый фрагмент с ключевого кадра |
| `mp4_max_buffer_size <размер>;` | `location` | Максимальный буфер для чтения moov-атома (обычно `16m`–`32m`) |
| `flv;` | `location` | Включить обработчик FLV-файлов |
| `?start=<сек>` | URL | Начать воспроизведение с указанной секунды (mp4, flv) |
| `?end=<сек>` | URL | Ограничить воспроизведение указанной секундой (только mp4) |
| `limit_rate <скорость>;` | `http`, `server`, `location` | Ограничение скорости отдачи в байтах/с (абсолютное значение) |
| `limit_rate_after <размер>;` | `http`, `server`, `location` | Размер, после которого включается `limit_rate` |
| `aio on;` | `location` | Асинхронный ввод-вывод (non-threaded) |
| `aio threads;` | `location` | Асинхронный ввод-вывод через пул потоков |
| `directio <размер>;` | `location` | Обход page cache для файлов больше указанного размера |

### RTMP-модуль

| Директива | Уровень | Назначение |
| :--- | :--- | :--- |
| `load_module modules/ngx_rtmp_module.so;` | `main` | Загрузка модуля |
| `rtmp {}` | `main` | Топ-уровневый контекст модуля |
| `server { listen 1935; }` | `rtmp` | RTMP-сервер |
| `application <имя> {}` | `rtmp server` | Логическое приложение для приёма/отдачи потока |
| `live on;` | `application` | Включить жилую трансляцию |
| `hls on;` | `application` | Включить генерацию HLS |
| `hls_path <путь>;` | `application` | Директория для `.m3u8` и `.ts` |
| `hls_fragment <время>;` | `application` | Длительность сегмента (по умолчанию `5s`) |
| `hls_playlist_length <время>;` | `application` | Окно сегментов в плейлисте |
| `hls_cleanup on;` | `application` | Автоматическое удаление старых сегментов |
| `dash on;` | `application` | Включить генерацию DASH |
| `dash_path <путь>;` | `application` | Директория для `.mpd` и сегментов |
| `dash_fragment <время>;` | `application` | Длительность DASH-сегмента |
| `record all;` | `application` | Записывать весь трансляция |
| `record_path <путь>;` | `application` | Директория для записей |
| `record_max_size <размер>;` | `application` | Максимальный размер одного файла записи |

### VOD-модуль

| Директива | Уровень | Назначение |
| :--- | :--- | :--- |
| `load_module modules/ngx_http_vod_module.so;` | `main` | Загрузка модуля |
| `vod hls;` | `location` | Включить VOD-режим с отдачей HLS |
| `vod dash;` | `location` | Включить VOD-режим с отдачей DASH |
| `vod_hls_encryption_key_format <строка>;` | `location` | Формат ключа для AES-128 шифрования HLS |
| `vod_drm_enabled on;` | `location` | Включить DRM-шифрование |
| `vod_thumbnail_format jpeg;` | `location` | Формат миниатюр (`jpeg`, `png`) |
| `vod_thumbnail_size <px>;` | `location` | Ширина миниатюры в пикселях |

### Проверка конфигурации

```bash
# Проверка синтаксиса
sudo angie -t
# → syntax is ok
# → test is successful

# Проверка загруженных модулей
angie -V 2>&1 | grep -oE "http_mp4|http_flv|http_rtmp|http_vod"
# → http_mp4 (встроен)
# → http_flv (встроен)
# модули rtmp и vod появятся только после load_module (отображаются как ngx_rtmp_module / ngx_http_vod_module в логе)
```

### Управление записью

```bash
# Проверка наличия записанных файлов
ls -lah /tmp/recordings/
# → stream1_24-09-2026_14-30-00.flv

# Очистка записей старше 7 дней (в cron)
find /tmp/recordings/ -type f -mtime +7 -delete
```

## Устранение неисправностей

### MP4 не поддерживает seeking (пауза/перемотка не работают)

**Причина:** файл не подготовлен с faststart (moov-атом в конце, а не в начале).
**Решение:** переконвертировать с перемещением moov-атома в начало:

```bash
ffmpeg -i input.mp4 -c copy -movflags +faststart output.mp4
# → moov-атом перемещается в начало, seeking работает
```

### FLV/MP4 возвращает 416 или неверный диапазон

**Причина:** `end` меньше `start`, или параметры переданы без модуля `mp4`/`flv`.
**Решение:** проверить, что директива модуля активна, и `start < end`.

### Лимит скорости не применяется

**Причина:** `limit_rate` задан в абсолютных байтах/с, а не как множитель к битрейту. Ошибка в конфигурации — например, `limit_rate 2;` без единицы измерения.
**Решение:** указать единицы явно:

```nginx
limit_rate 2m;      # 2 мегабайта в секунду
```

### RTMP-поток не появляется в HLS

**Причина:**
1. `hls on;` не установлен в `application` или `hls_path` указывает на несуществующую/недоступную директорию.
2. Энкодер отправляет кодек, неподдерживаемый клиентом (например, H.265 Baseline для старых iOS).
**Решение:** проверить права на запись в `hls_path`, убедиться, что плейлист формируется, и кодек соответствует целевым устройствам.

### Записи трансляции накапливаются, диск заполняется

**Причина:** модуль RTMP не удаляет старые записи автоматически.
**Решение:** настроить внешний механизм ротации (cron + `find`, `logrotate`, или `systemd-tmpfiles`).

### VOD-модуль не генерирует миниатюры

**Причина:** `vod_thumbnail_format` не указан или запрашиваемый URL не совпадает с `location`.
**Решение:** проверить, что `location` совпадает, и модуль загружен (`load_module`).

### Ошибка «could not build the server_names_hash» при масштабировании VOD-серверов

**Причина:** большое количество `server_name` или длинные имена в `map`.
**Решение:** увеличить `server_names_hash_bucket_size` и `map_hash_bucket_size` (см. [Вспомогательные HTTP-модули Angie](./angie-http-utility-modules.md)).

## Лучшие практики

1. **Подготавливайте MP4 с faststart** для any seeking-сценариев: `ffmpeg -movflags +faststart`.
2. **Не полагайтесь на `limit_rate` как на множитель битрейта:** задавайте абсолютное значение в байтах/с (`2m`, `512k`).
3. **Используйте `hls_cleanup on`** в RTMP-модуле, чтобы сегменты удалялись автоматически; для записей настройте внешнюю ротацию.
4. **Разделяйте RTMP-приёмы и HTTP-отдачу** по разным портам/серверам; не смешивайте их в одном `server {}`.
5. **Для production-стриминга отдавайте HLS/DASH через отдельный статический `location`** с `add_header Cache-Control no-cache always;`, чтобы плеер всегда получал актуальный плейлист.
6. **Указывайте `chunk_size` в `rtmp server`** (например, `4096`), чтобы оптимизировать буферизацию при высоких битрейтах.
7. **Используйте `aio threads`** на высоконагруженных серверах с HDD для модуля `mp4`; на SSD достаточно `aio on;` или даже синхронного I/O.
8. **Для VOD с DRM** храните ключи шифрования за пределами документа корня и защищайте доступ к ним (mTLS, `allow` по внутренней подсети).
9. **Мониторьте размер `/tmp/hls` и `/tmp/dash`** — при разрыве потока сегменты могут перестать удаляться; настройте alerts по дисковому пространству.
10. **Верифицируйте модули при развёртывании:** `angie -V 2>&1 | grep -oE "http_mp4|http_flv"` и `ls /usr/lib/angie/modules/ | grep -E "rtmp|vod"`.

## Дополнительная информация

- Встроенные модули `mp4`/`flv` и утилита `slice` разобраны в [Вспомогательные HTTP-модули Angie](./angie-http-utility-modules.md).
- Управление скоростью и лимитирование в общем случае — в [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md) и [Оптимизация производительности Nginx](../Nginx/Performance/nginx_performance_tuning.md).
- Запись и управление логами Angie — в [Логирование Angie](./angie_logging.md).
- Для работы с RTMP-модулем требуется пакет `angie-module-rtmp` или `angie-pro-module-rtmp`. Подробнее об установке пакетов — в [Установка Angie](./angie_installation.md).
- Официальная документация: [RTMP module](https://en.angie.software/angie/docs/configuration/modules/external-modules/rtmp.md), [VOD module](https://en.angie.software/angie/docs/configuration/modules/external-modules/vod.md).

## См. также

- [Вспомогательные HTTP-модули Angie](./angie-http-utility-modules.md)
- [Установка Angie](./angie_installation.md)
- [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)
