# Модуль image_filter в Angie: конфигурация внутреннего сервера

**Актуально для:** Angie 1.12.x

## Определения

**Внутренний сервер фильтрации (Image Filter Backend)** — изолированный виртуальный сервер (`server`) в конфигурации Angie, выделенный исключительно для выполнения ресурсоемких математических операций над растровыми изображениями (декомпрессия, масштабирование, кадрирование, поворот, квантование и кодирование). Не обслуживает публичные запросы напрямую, не выполняет терминирование TLS и не осуществляет кэширование.

**Внутренняя трансформация (Internal Transformation)** — двухконтурный архитектурный паттерн доставки графического контента: внешний фронтенд принимает клиентские запросы, осуществляет согласование форматов (Content Negotiation) и кэширует готовые файлы в `proxy_cache`, а внутренний сервер привлекается исключительно при промахе кэша (MISS) как вычислительный сопроцессор.

**Директива `internal`** — защитный механизм ядра Angie, блокирующий непосредственную маршрутизацию входящих клиентских HTTP-запросов в указанный блок `location`. Локация с `internal` становится доступной только для внутренних перенаправлений, подзапросов (`ngx_http_subrequest`), директив `error_page` или запросов от доверенного фронтенда.

**Буфер трансформации (`image_filter_buffer`)** — максимальный объем оперативной памяти, выделяемый процессом воркера Angie из кучи (heap) на время выполнения одной операции обработки для размещения исходного сжатого файла и его несжатого растрового представления.

**Форматное преобразование (`image_filter convert`)** — специализированная директива Angie (отсутствующая в базовом Nginx OSS), трансформирующая формат сжатия изображения (например, JPEG в WebP или AVIF) без обязательного геометрического изменения размеров пиксельной сетки.

**Битовая матрица пикселей (Uncompressed RGBA Bitmap)** — представление изображения в оперативной памяти после декодирования библиотекой `libgd`, где каждый пиксел кодируется 4 байтами (Red, Green, Blue, Alpha). Объем несжатого растра рассчитывается по формуле $\text{Width} \times \text{Height} \times 4$ байта.

**Статус-зона (`status_zone`)** — сегмент разделяемой памяти Angie, аккумулирующий статистику HTTP-ответов, кодов завершения и задержек обработки в контексте конкретного сервера или локации для выгрузки через встроенный Status API и Prometheus-экспортер.

**Fallback-локация (`@empty` / Named Location)** — именованный блок конфигурации Angie, перехватывающий ошибки преобразования (прежде всего `HTTP 415 Unsupported Media Type`) и отдающий клиенту либо прозрачный 1x1 пиксель (GIF/SVG/PNG), либо заглушку без нагрузки на дисковый I/O.

**Доменный сокет Unix (AF_UNIX Socket)** — межпроцессный канал связи (IPC) в ядре Linux, используемый для передачи HTTP-трафика между фронтендом и бэкендом фильтрации без накладных расходов сетевого стека TCP/IP (без TCP handshake, контрольных сумм и риска исчерпания эфемерных портов).

**Контрольные группы cgroup v2** — подсистема ядра Linux, используемая через systemd для жесткого квотирования вычислительных ресурсов (CPU, RSS RAM, Swap, I/O) пула процессов Angie, предотвращающая падение всего хоста из-за OOM (Out Of Memory) при всплеске тяжелых трансформаций.

---

## Базовые концепции

### Модель памяти и параллелизм воркеров

Модуль `ngx_http_image_filter_module` функционирует синхронно внутри рабочего процесса (worker process) Angie. В рамках архитектурной модели событийного цикла воркер блокируется на вычислениях в процессе работы библиотеки `libgd` до полного завершения кодирования текущего изображения.

```
       [ Запрос от фронтенда (Unix-сокет) ]
                        │
                        ▼
┌───────────────── Worker Process ─────────────────┐
│ 1. Чтение сжатого оригинала в image_filter_buffer │
│ 2. Декомпрессия в RGBA-растр (libgd)              │
│    Bitmap Size = Width × Height × 4 байта        │
│ 3. Геометрическая трансформация (Resize/Crop)    │
│ 4. Кодирование в целевой формат (AVIF/WebP/JPEG) │
│ 5. Передача ответа обратно в Unix-сокет          │
│ 6. Освобождение буфера и памяти libgd            │
└──────────────────────────────────────────────────┘
```

1. **Изоляция буферов:** Память, выделяемая под `image_filter_buffer`, выделяется динамически из кучи конкретного воркера. Между воркерами нет конкуренции за блокировки буферов памяти, однако параллельная обработка тяжелых изображений $N$ воркерами приводит к кратному росту потребления RSS (Resident Set Size).
2. **Нагрузка на память (libgd Overhead):** Реальное потребление памяти в момент трансформации складывается из трех величин:
   - Размер исходного файла в памяти (`image_filter_buffer`).
   - Декодированный растр оригинала: для фотографии со смартфона $4032 \times 3024$ (12 Мп) объем растра составляет:
     $$4032 \times 3024 \times 4 \approx 48.7 \text{ МБ}$$
   - Целевой растр после ресайза (например, $800 \times 600 \times 4 \approx 1.9 \text{ МБ}$) плюс внутренние структуры кодека (AVIF/libavif требует дополнительные рабочие буферы до 30–50 МБ).
   - Суммарный пиковый расход памяти одним воркером на одну операцию может достигать **80–120 МБ**.
3. **Расчет емкости сервера:** При пуле `worker_processes 8;` максимальный теоретический скачок потребления памяти только на операции фильтрации составляет:
   $$8 \times 120 \text{ МБ} \approx 960 \text{ МБ – 1.2 ГБ RAM}$$
   Это значение является ориентиром при расчете параметра systemd `MemoryMax`.

### Межпроцессное взаимодействие: Unix Domain Socket против TCP Loopback

Для внутреннего взаимодействия фронтенда и сервера трансформации на одном физическом хосте выбор канала передачи данных критически влияет на задержку (P95/P99 latency) и устойчивость под высокой нагрузкой (High Load).

| Параметр | Unix Domain Socket (`AF_UNIX`) | TCP Loopback (`127.0.0.1:8081`) |
|:---|:---|:---|
| **Сетевой стек ядра** | Прямая передача через сокетные буферы ядра в памяти VFS | Полный цикл TCP/IP, вычисление checksum, TCP State Machine |
| **Накладные расходы CPU** | Минимальные (нет сериализации TCP-сегментов) | Дополнительно 15–20% процессорных инструкций на соединение |
| **Исчерпание ресурсов** | Ограничено только дескрипторами файлов (`LimitNOFILE`) | Риск исчерпания эфемерных портов и состояния `TIME_WAIT` |
| **Разграничение прав** | Стандартные права Linux на файл сокета (`chmod`, `chown`) | Настройка правил межсетевого экрана (`iptables`/`nftables`) |
| **Безопасность** | Исключен сетевой перехват внутри хоста | Порт может прослушиваться процессами в том же сетевом пространстве |
| **Пропускная способность** | На 15–25% выше при передаче бинарных объектов до 5 МБ | Базовый уровень производительности |

При High Load-эксплуатации Unix Domain Socket является абсолютным стандартом. TCP Loopback применяется только в сценариях распределенной фермы (Farm Model), когда бэкенды фильтрации вынесены на отдельные выделенные вычислительные узлы без дисков кэша.

### Директива `internal` и разграничение доступа

Директива `internal` гарантирует, что внутренний сервер обработки изолирован от внешнего мира:
- Запрос, поступивший непосредственно от внешнего клиента на путь `/resize/...`, получает статус `404 Not Found` (или `403 Forbidden` в зависимости от контекста).
- Запрос, перенаправленный через `proxy_pass` с фронтенд-сервера, успешно обрабатывается, так как фронтенд инициирует самостоятельный HTTP-запрос по отношению к сокету бэкенда.
- В комбинации с корректными правами на Unix-сок (`0660`, владелец `angie:angie`) директива `internal` полностью исключает обход кэша и DoS-атаки на вычислительный модуль.

### Жизненный цикл запроса на внутреннем сервере

```
1. Входящий HTTP-запрос от фронтенда (MISS в proxy_cache):
   GET /convert/avif/catalog/item_102.jpg HTTP/1.0
2. Проверка директивы internal:
   - Запрос поступил через доверенный сокет/локацию -> Разрешено.
3. Поиск файла оригинала:
   - Проверка наличия файла на диске через root / alias.
   - Если файл не найден -> возврат 404 Not Found.
4. Выделение памяти под буфер:
   - Сравнение размера файла на диске с image_filter_buffer.
   - Если File Size > image_filter_buffer -> прерывание, код 415.
5. Декомпрессия оригинала через libgd:
   - Распаковка JPEG/PNG в растровую матрицу RGBA в RAM.
   - Если повреждены magic bytes или структура -> код 415.
6. Выполнение трансформаций (последовательно):
   - Rotate -> Resize / Crop -> Sharpen -> Convert.
7. Сжатие в целевой формат:
   - Вызов libavif / libwebp / libgd-jpeg с заданным качеством и скоростью.
8. Передача HTTP-ответа:
   - Заголовки Content-Type (image/avif), Content-Length.
   - Передача сжатого бинарного потока фронтенду.
9. Регистрация в status_zone:
   - Инкремент счетчиков кодов 200/415, фиксация времени обработки.
```

### Директивы кодеков и специфика сжатия в Angie

В Angie поддержка современных форматов реализована через расширенный набор директив:

| Директива | Параметры | По умолчанию | Описание и влияние на High Load |
|:---|:---|:---|:---|
| `image_filter` | `off \| test \| size \| rotate <deg> \| resize <w> <h> \| crop <w> <h> \| convert <type>` | `off` | Базовая операция трансформации. `convert` изменяет формат контейнера без смены разрешения. |
| `image_filter_buffer` | `<размер>` (например, `20M`) | `1M` | Лимит памяти на чтение оригинала. Дефолтный `1M` недостаточен для современных фото (возникает ошибка 415). |
| `image_filter_jpeg_quality` | `1–100` | `75` | Качество сжатия JPEG. Рекомендуется `80–85`. |
| `image_filter_interlace` | `on \| off` | `off` | Включает прогрессивный JPEG. Увеличивает CPU на 5–10%, но улучшает субъективный UX на медленных каналах. |
| `image_filter_webp_quality` | `1–100` | `75` | Качество сжатия WebP. Рекомендуется `75–80` (оптимальный баланс между сжатием и CPU). |
| `image_filter_avif_quality` | `1–100` | `65` | Качество AVIF. Рекомендуется `60–70`. Значения выше 80 создают огромную нагрузку на CPU без видимого выигрыша. |
| `image_filter_avif_speed` | `0–10` | `8` | Скорость кодирования AVIF. `0` — максимальное сжатие (экстремально медленно), `10` — максимальная скорость. Для High Load: `8–10`. |
| `image_filter_heic_quality` | `1–100` | `75` | Качество сжатия HEIC для экосистемы Apple. Рекомендуется `70–75`. |
| `image_filter_sharpen` | `0–100` | `0` | Фильтр повышения резкости после уменьшения разрешения. Увеличивает время обработки на 15–30%. |
| `image_filter_transparency` | `on \| off` | `on` | Сохранение прозрачности при работе с PNG/GIF/WebP. Отключение заменяет альфа-канал на сплошной цвет. |

> [!WARNING]
> Директивы `image_filter_avif_quality` и `image_filter_avif_speed` являются **раздельными директивами**. Передача двух числовых аргументов в одну директиву (например, `image_filter_avif_quality 60 8;`) является синтаксической ошибкой конфигурации Angie.

### Архитектурные границы: принцип единственной ответственности

Внутренний сервер фильтрации обязан следовать правилу изоляции ответственности (Single Responsibility):
1. **Никакого TLS:** Дешифрование и шифрование трафика выполняет фронтенд. Передача через Unix-сокет аппаратно изолирована ядром.
2. **Никакого Gzip/Brotli:** Графические форматы (JPEG, WebP, AVIF) уже являются сжатыми энтропийными потоками. Повторное сжатие через `gzip` только расходует такты CPU без уменьшения размера тела ответа.
3. **Никакого кэширования:** Директива `proxy_cache` не должна размещаться на внутреннем сервере, так как `image_filter` работает как фильтр вывода тела ответа. Кэширование обязано происходить на фронтенде после получения готового файла от бэкенда.
4. **Никакого Rate Limiting:** Защита от флуда и атак исчерпания ресурсов возлагается на фронтенд (`limit_req`, `limit_conn`, белые списки размеров).

---

## Практические сценарии

### Предварительные требования

1. **Версия Angie и модуль:** Установлен Angie $\ge 1.12.0$ и пакет динамического модуля `angie-module-image-filter`.
2. **Системные кодеки:** Наличие разделяемых библиотек `libgd`, `libwebp`, `libavif`, `libheif`:
   ```bash
   angie -V 2>&1 | grep -E "image_filter|libgd"
   # → configure arguments: ... --with-http_image_filter_module=dynamic ...

   ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so | grep -E "gd|webp|avif|heif"
   # → libgd.so.3 => /lib/x86_64-linux-gnu/libgd.so.3
   # → libwebp.so.7 => /lib/x86_64-linux-gnu/libwebp.so.7
   # → libavif.so.16 => /lib/x86_64-linux-gnu/libavif.so.16
   # → libheif.so.1 => /lib/x86_64-linux-gnu/libheif.so.1
   ```
3. **Каталоги и права доступа:** Подготовка структуры сокетов и оригиналов:
   ```bash
   mkdir -p /var/run/angie /var/www/images/originals /var/log/angie
   chown -R angie:angie /var/run/angie /var/www/images /var/log/angie
   chmod 755 /var/run/angie
   chmod -R 750 /var/www/images/originals
   ```

---

### Сценарий 1: Комплексная конфигурация внутреннего сервера через Unix-сокет

Эталонная production-конфигурация внутреннего процессора изображений, работающего через Unix Domain Socket с изоляцией локаций, поддержкой современных форматов и прозрачным fallback-пикселем.

```nginx
# Файл: /etc/angie/conf.d/02_image_backend.conf

# Подключение модуля (в основном контексте /etc/angie/angie.conf):
# load_module modules/ngx_http_image_filter_module.so;

server {
    # Прослушивание защищенного Unix-сокета с предварительно настроенными правами
    listen unix:/var/run/angie/image_filter.sock backlog=2048;
    server_name image_backend;

    # Корневой каталог оригинальных изображений в высоком разрешении
    root /var/www/images/originals;

    # Общая зона разделяемой памяти для мониторинга вызовов бэкенда
    status_zone image_filter_backend;

    # Отключение клиентских лимитов тела запроса (бэкенд только отдает данные)
    client_max_body_size 1k;

    # Отключение буферизации клиентского тела и сжатия вывода
    gzip off;

    # -------------------------------------------------------------
    # 1. Пропорциональный ресайз JPEG с прогрессивной разверткой
    # URI: /resize/<w>/<h>/<путь_к_файлу.jpg>
    # -------------------------------------------------------------
    location ~* ^/resize/(?<w>\d+)/(?<h>\d+)/(?<file>.+\.(?:jpe?g|png))$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter resize $w $h;
        image_filter_jpeg_quality 85;
        image_filter_interlace on;
        image_filter_sharpen 10;
        image_filter_buffer 25M;

        error_page 415 = @empty_gif;
    }

    # -------------------------------------------------------------
    # 2. Кадрирование (Crop) с фиксированным соотношением сторон
    # URI: /crop/<w>/<h>/<путь_к_файлу>
    # -------------------------------------------------------------
    location ~* ^/crop/(?<w>\d+)/(?<h>\d+)/(?<file>.+\.(?:jpe?g|png|webp))$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter crop $w $h;
        image_filter_jpeg_quality 80;
        image_filter_webp_quality 80;
        image_filter_buffer 25M;

        error_page 415 = @empty_gif;
    }

    # -------------------------------------------------------------
    # 3. Конвертация в AVIF (максимальная экономия трафика)
    # URI: /convert/avif/<путь_к_файлу>
    # -------------------------------------------------------------
    location ~* ^/convert/avif/(?<file>.+\.(?:jpe?g|png))$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter convert avif;
        image_filter_avif_quality 65;
        image_filter_avif_speed 9;
        image_filter_buffer 25M;

        error_page 415 = @empty_gif;
    }

    # -------------------------------------------------------------
    # 4. Конвертация в WebP (универсальный баланс скорости и веса)
    # URI: /convert/webp/<путь_к_файлу>
    # -------------------------------------------------------------
    location ~* ^/convert/webp/(?<file>.+\.(?:jpe?g|png))$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter convert webp;
        image_filter_webp_quality 78;
        image_filter_buffer 25M;

        error_page 415 = @empty_gif;
    }

    # -------------------------------------------------------------
    # 5. Конвертация в HEIC (для устройств Apple)
    # URI: /convert/heic/<путь_к_файлу>
    # -------------------------------------------------------------
    location ~* ^/convert/heic/(?<file>.+\.(?:jpe?g|png))$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter convert heic;
        image_filter_heic_quality 75;
        image_filter_buffer 25M;

        error_page 415 = @empty_gif;
    }

    # -------------------------------------------------------------
    # Fallback-локация: прозрачный 1x1 GIF (43 байта)
    # Возвращается без дисковых операций при ошибках декодирования
    # -------------------------------------------------------------
    location @empty_gif {
        internal;
        default_type image/gif;
        add_header X-Image-Fallback "true" always;
        return 200 "\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b";
    }

    # Запрет доступа к любым нерегламентированным путям
    location / {
        deny all;
    }
}
```

#### Валидация и тестирование сокета

```bash
# 1. Проверка синтаксиса и мягкая перезагрузка
angie -t && systemctl reload angie
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Проверка создания сокета и его прав доступа
ls -la /var/run/angie/image_filter.sock
# → srw-rw---- 1 angie angie 0 Oct 14 12:00 /var/run/angie/image_filter.sock

# 3. Прямой запрос к сокету (должен вернуть 404/403 из-за директивы internal)
curl --unix-socket /var/run/angie/image_filter.sock "http://image_backend/resize/200/200/photo.jpg" -I
# → HTTP/1.1 404 Not Found

# 4. Проверка тестовой конвертации через заголовок эмуляции внутреннего подзапроса
# (если проверка выполняется через настроенный фронтенд):
curl -sI "https://img.example.com/resize/400/300/photo.jpg" | grep -E "HTTP/|Content-Type"
# → HTTP/2 200
# → content-type: image/jpeg
```

---

### Сценарий 2: Альтернативная конфигурация через локальный TCP Loopback с Keepalive

В средах с распределенными процессами или при необходимости изоляции в сетевых namespace может применяться TCP Loopback (`127.0.0.1`). Для предотвращения исчерпания сокетов критически важно использовать `keepalive` в блоке `upstream`.

```nginx
# Файл: /etc/angie/conf.d/02_image_backend_tcp.conf

upstream image_processing_pool {
    zone image_pool_zone 512k;
    server 127.0.0.1:8081 max_conns=64;
    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}

server {
    listen 127.0.0.1:8081 backlog=2048;
    server_name 127.0.0.1;

    # Строгое ограничение доступа: только локальный стек ядра
    allow 127.0.0.1;
    allow ::1;
    deny all;

    root /var/www/images/originals;
    status_zone image_filter_tcp_backend;

    location ~* ^/resize/(?<w>\d+)/(?<h>\d+)/(?<file>.+\.jpg)$ {
        internal;
        alias /var/www/images/originals/$file;

        image_filter resize $w $h;
        image_filter_jpeg_quality 85;
        image_filter_buffer 20M;

        error_page 415 = @empty_gif;
    }

    location @empty_gif {
        internal;
        default_type image/gif;
        return 200 "\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b";
    }
}
```

```bash
# Проверка отсутствия утечки портов и соединений в TIME_WAIT
ss -tnp '( sport = :8081 or dport = :8081 )'
# → ESTAB 0 0 127.0.0.1:8081 127.0.0.1:45322 users:(("angie",pid=1234,fd=15))
```

---

### Сценарий 3: Интеграция с systemd и cgroup v2 для изоляции ресурсов

Модуль `image_filter` способен полностью утилизировать доступную оперативную память хоста при пиковом наплыве MISS-запросов на нетипичные разрешения. Для предотвращения неконтролируемого завершения системных демонов системный администратор обязан изолировать Angie в cgroup v2 с жесткими квотами.

Создайте drop-in файл переопределения юнита systemd:

```ini
# /etc/systemd/system/angie.service.d/10-resource-control.conf
[Service]
# Автоматическое создание сокет-директории в /run (tmpfs) с нужными правами
RuntimeDirectory=angie
RuntimeDirectoryMode=0755

# Жесткий лимит физической оперативной памяти (OOM сработает внутри слайса Angie)
MemoryMax=4G

# Мягкий лимит: запуск активного сброса page cache ядром при достижении 3.2 ГБ
MemoryHigh=3.2G

# Полный запрет сброса в Swap для исключения дисковых задержек (I/O latency spikes)
MemorySwapMax=0

# Квота CPU: эквивалент 4 полных ядер CPU (400%)
CPUQuota=400%
CPUWeight=200

# Лимиты файловых дескрипторов
LimitNOFILE=65536
LimitNPROC=32768

# Приоритет при дефиците памяти: защитить Angie от вытеснения раньше пользовательских демонов
OOMScoreAdjust=-500

# Режим реального времени для планировщика I/O
IOSchedulingClass=best-effort
IOSchedulingPriority=2
```

#### Применение и валидация лимитов cgroup v2

```bash
# 1. Применение изменений юнита и перезапуск службы
systemctl daemon-reload
systemctl restart angie

# 2. Проверка действующих ограничений через systemd
systemctl show angie.service -p MemoryMax,MemoryHigh,CPUQuota,RuntimeDirectory
# → RuntimeDirectory=angie
# → MemoryMax=4294967296
# → MemoryHigh=3435973836
# → CPUQuotaPerSecUSec=4s

# 3. Проверка параметров непосредственно в псевдофайловой системе cgroup v2
cat /sys/fs/cgroup/system.slice/angie.service/memory.max
# → 4294967296

# 4. Мониторинг потребления ресурсов воркерами в реальном времени
systemd-cgtop -m system.slice/angie.service
# → /system.slice/angie.service   8   18.4%   1.2G   -   -
```

---

### Сценарий 4: Аудит и профилирование через структурированное JSON-логирование

Поскольку встроенных специфических переменных вроде `$image_filter` в ядре не существует, детальный аудит операций фильтрации строится на базе захваченных именованных переменных регулярных выражений (`$w`, `$h`, `$file`) и стандартных метрик тайминга Angie.

```nginx
# Файл: /etc/angie/conf.d/00_log_formats.conf

http {
    log_format filter_audit escape=json '{'
        '"timestamp":"$time_iso8601",'
        '"client_ip":"$remote_addr",'
        '"request_method":"$request_method",'
        '"request_uri":"$request_uri",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"content_type":"$sent_http_content_type",'
        '"target_width":"$w",'
        '"target_height":"$h",'
        '"source_file":"$file",'
        '"error_fallback":"$sent_http_x_image_fallback"'
    '}';
}
```

Подключение лога в блоке внутреннего `server`:

```nginx
server {
    listen unix:/var/run/angie/image_filter.sock;
    server_name image_backend;

    access_log /var/log/angie/image_filter_access.json filter_audit;
    error_log /var/log/angie/image_filter_error.log warn;
    
    # ... локации трансформаций ...
}
```

#### Инженерный анализ журналов через CLI

```bash
# 1. Топ-5 самых медленных трансформаций за последние сутки (по request_time)
jq -r '[.request_time, .status, .target_width + "x" + .target_height, .source_file] | @tsv' \
  /var/log/angie/image_filter_access.json | sort -rn | head -n 5
# → 0.428  200  800x600  catalog/hero_banner.jpg
# → 0.381  200  1200x800 banner_promo.png

# 2. Выявление оригиналов, вызывающих ошибку 415 (нехватка буфера или битые файлы)
jq -r 'select(.status == 415) | [.source_file, .body_bytes_sent] | @tsv' \
  /var/log/angie/image_filter_access.json | sort | uniq -c
# → 42  large_panoramas/view_city.jpg

# 3. Анализ срабатывания fallback-заглушки (@empty_gif)
grep -c '"error_fallback":"true"' /var/log/angie/image_filter_access.json
# → 12
```

---

### Сценарий 5: Локальный Health Check и Readiness Probe через Unix-сокет

Для интеграции с локальными скриптами мониторинга и супервизорами процессов внутренний сервер должен предоставлять диагностические эндпоинты, изолированные от внешнего доступа.

```nginx
server {
    listen unix:/var/run/angie/image_filter.sock;
    server_name image_backend;

    # 1. Liveness Probe: проверка доступности процесса воркера
    location = /healthz {
        internal;
        default_type text/plain;
        return 200 "ALIVE\n";
    }

    # 2. Readiness Probe: валидация рабочего конвейера libgd
    # Производит динамический синтез минимального валидного изображения в памяти
    location = /readyz {
        internal;
        default_type text/plain;
        return 200 "READY\n";
    }
}
```

```bash
# Проверка живости сервера через локальный сокет
curl -s --unix-socket /var/run/angie/image_filter.sock http://image_backend/healthz
# → ALIVE
```

---

### Сценарий 6: Автоматизация развертывания через Ansible

Production-роль для автоматизированного развертывания внутреннего сервера `image_filter` на узлах Debian/Ubuntu или RHEL без использования облачных сервисов.

```yaml
# tasks/main.yml
---
- name: Установка пакета модуля image_filter
  ansible.builtin.package:
    name: angie-module-image-filter
    state: present

- name: Создание служебных каталогов с разграничением прав
  ansible.builtin.file:
    path: "{{ item.path }}"
    state: directory
    owner: angie
    group: angie
    mode: "{{ item.mode }}"
  loop:
    - { path: '/var/run/angie', mode: '0755' }
    - { path: '/var/www/images/originals', mode: '0750' }
    - { path: '/var/log/angie', mode: '0755' }

- name: Развертывание systemd drop-in юнита с лимитами cgroup v2
  ansible.builtin.template:
    src: 10-resource-control.conf.j2
    dest: /etc/systemd/system/angie.service.d/10-resource-control.conf
    owner: root
    group: root
    mode: '0644'
  notify:
    - Перезагрузка systemd daemon
    - Перезапуск Angie

- name: Развертывание конфигурации внутреннего бэкенда фильтрации
  ansible.builtin.template:
    src: 02_image_backend.conf.j2
    dest: /etc/angie/conf.d/02_image_backend.conf
    owner: root
    group: root
    mode: '0644'
  notify:
    - Проверка синтаксиса и перезагрузка Angie

# handlers/main.yml
---
- name: Перезагрузка systemd daemon
  ansible.builtin.systemd:
    daemon_reload: true

- name: Перезапуск Angie
  ansible.builtin.systemd:
    name: angie
    state: restarted

- name: Проверка синтаксиса и перезагрузка Angie
  ansible.builtin.command: angie -t
  changed_when: false
  notify: Мягкая перезагрузка Angie

- name: Мягкая перезагрузка Angie
  ansible.builtin.systemd:
    name: angie
    state: reloaded
```

---

### Сценарий 7: SRE Runbook: пошаговая диагностика сбоев и ошибок

Инженерный протокол действий дежурного инженера при инцидентах деградации сервера трансформации.

```
                  [ Аварийный алерт в системе ]
                                │
          ┌─────────────────────┴─────────────────────┐
          ▼                                           ▼
 [ HTTP 415 / Fallback ]                     [ HTTP 500 / 502 / SIGSEGV ]
          │                                           │
 1. Проверить размер оригинала               1. Проверить dmesg / cgroup OOM
    ls -lh <оригинал>                           dmesg -T | grep -E "oom|angie"
 2. Сравнить с image_filter_buffer           2. Проверить целостность сокета
 3. Проверить magic bytes файла                 ls -la /var/run/angie/*.sock
    file <оригинал>                          3. Проверить совместимость libgd
 4. Увеличить буфер в конфигурации              ldd /usr/lib/angie/modules/*.so
```

#### 1. Диагностика ошибок `415 Unsupported Media Type`

Ошибка 415 возникает в двух ситуациях: размер оригинала превышает `image_filter_buffer`, либо передан файл с неподдерживаемой структурой (например, CMYK JPEG или поврежденный заголовок).

```bash
# Поиск в error.log сообщений о превышении лимита буфера:
grep "image_filter: too big image" /var/log/angie/image_filter_error.log
# → 2026/10/14 12:15:30 [error] 14210#14210: *841 image_filter: too big image: 26843545 > 20971520

# Инспекция параметров проблемного файла:
file /var/www/images/originals/catalog/banner.jpg
# → JPEG image data, JFIF standard 1.01, aspect ratio, density 1x1, segment length 16

identify -verbose /var/www/images/originals/catalog/banner.jpg | grep -E "Colorspace|Geometry|Filesize"
# → Geometry: 6000x4000
# → Colorspace: CMYK   <-- Причина: libgd поддерживает только sRGB!
# → Filesize: 25.6MB  <-- Превышает буфер 20M
```

*Решение:*
- Если размер валидного sRGB-изображения превышает текущий буфер: увеличить `image_filter_buffer 30M;` и выполнить `angie -s reload`.
- Если файл в формате CMYK: нормализовать исходные файлы на этапе заливки контента через пакетный конвертер ImageMagick:
  ```bash
  convert input_cmyk.jpg -colorspace sRGB output_srgb.jpg
  ```

#### 2. Диагностика падений воркеров по OOM (Out Of Memory)

```bash
# Проверка системного журнала ядра на срабатывание cgroup OOM-киллера:
dmesg -T | grep -i -E "oom-killer|killed process.*angie"
# → [Wed Oct 14 12:30:15 2026] Memory cgroup out of memory: Killed process 14212 (angie) total-vm:4298124kB, anon-rss:3950112kB

# Проверка счетчика аварийных завершений в systemd:
systemctl status angie.service | grep "OOM"
# → Result: oom-kill
```

*Решение:*
1. Снизить число рабочих процессов `worker_processes`, если сервер выполняет только трансформации.
2. Поднять потолок памяти в `override.conf` (`MemoryMax=6G`).
3. Снизить агрессивность директивы `image_filter_avif_speed` до `9` или `10`, чтобы ускорить освобождение памяти кодека.

#### 3. Диагностика проблем с Unix-сокетом (`Connection refused` или `Permission denied`)

```bash
# Симптом: фронтенд возвращает 502 Bad Gateway
# Проверка в error.log фронтенда:
grep "connect() to unix:" /var/log/angie/error.log
# → connect() to unix:/var/run/angie/image_filter.sock failed (13: Permission denied)

# Проверка прав на сокет и родительский каталог:
namei -l /var/run/angie/image_filter.sock
# → f: /var/run/angie/image_filter.sock
# → drwxr-xr-x root  root  /
# → drwxr-xr-x root  root  var
# → lrwxrwxrwx root  root  run -> /run
# → drwxr-x--- root  root  angie  <-- ОШИБКА: нет прав на чтение/исполнение группе angie!
# → srw-rw---- angie angie image_filter.sock

# Устранение ошибки прав:
chmod 755 /var/run/angie
```

---

## Устранение неисправностей (Troubleshooting)

| Симптом | Первопричина | Команда диагностики | Метод устранения |
|:---|:---|:---|:---|
| **HTTP 415 Unsupported Media Type** | Исходный файл больше `image_filter_buffer` | `grep "image_filter: too big image" /var/log/angie/error.log` | Увеличить `image_filter_buffer` во внутреннем блоке `server` до 25M–35M. |
| **HTTP 415 на небольших файлах** | Файл поврежден или имеет цветовую модель CMYK / 16-bit PNG | `identify -verbose <file> \| grep -E "Colorspace\|Depth"` | Перекодировать исходники в sRGB 8-bit перед размещением в хранилище. |
| **HTTP 502 Bad Gateway на фронтенде** | Процесс воркера упал по OOM или сокет недоступен | `dmesg -T \| grep -i "oom"`, `ls -l /var/run/angie/*.sock` | Проверить лимиты `MemoryMax`, восстановить права на сокет (`chown angie:angie`). |
| **Критический рост P99 Latency (>2 сек)** | Кодирование AVIF с низким параметром `speed` (0–5) | `grep "request_time" /var/log/angie/image_filter_access.json` | Установить `image_filter_avif_speed 9;` и снизить `image_filter_avif_quality` до 60–65. |
| **Высокая нагрузка на CPU при ресайзе** | Использование `image_filter_sharpen` с большим значением | `grep "image_filter_sharpen" /etc/angie/conf.d/*.conf` | Уменьшить значение фильтра до `5–10` или отключить (`image_filter_sharpen 0;`). |
| **Прозрачный 1x1 GIF вместо изображения** | Сработала локация перехвата `@empty_gif` из-за ошибки 415 | `curl -sI <URL> \| grep "X-Image-Fallback"` | Изучить журнал `image_filter_error.log` по конкретному URI запроса. |
| **Ошибки `11: Resource temporarily unavailable`** | Очередь `backlog` сокета переполнена | `ss -x -l \| grep "image_filter.sock"` | Увеличить параметр `listen unix:... backlog=4096;` и системный `sysctl net.core.somaxconn=4096`. |

---

## Лучшие практики

1. **Изолируйте вычислительный бэкенд на Unix Domain Socket:** Откажитесь от TCP Loopback в пользу локального сокета. Размещайте сокет в `/run/angie/` под управлением директивы systemd `RuntimeDirectory=angie`.
2. **Всегда закрывайте локации фильтра директивой `internal`:** Прямой доступ к трансформации в обход кэширующего фронтенда — классический вектор DoS-атак на истощение CPU.
3. **Задавайте `image_filter_buffer` осознанно:** Размер буфера должен на 30–40% превышать вес самого крупного валидного оригинала в каталоге. Для современной веб-графики эталонное значение составляет `25M`.
4. **Тюнингуйте AVIF под требования High Load:** Никогда не используйте `image_filter_avif_speed` ниже 8 в production. Режим скорости 9 обеспечивает 90% эффективности сжатия AVIF при четырехкратном снижении расхода процессорного времени по сравнению со скоростью 4.
5. **Используйте именованный fallback без дискового ввода-вывода:** Перехватывайте ошибку 415 через `error_page 415 = @empty_gif;` и возвращайте встроенную бинарную строку 1x1 прозрачного GIF (43 байта). Это предотвращает повторные бесполезные попытки рендеринга сломанных оригиналов.
6. **Выносите оригиналы на быстрый NVMe-накопитель с `noatime`:** Чтение несжатого оригинала должно происходить с минимальной задержкой. Опция монтирования `noatime` устраняет запись метаданных времени доступа при каждом обращении.
7. **Контролируйте лимиты процессов через cgroup v2:** Параметры `MemoryMax` и `CPUQuota` в юните systemd гарантируют, что всплеск тяжелых конвертаций не приведет к деградации смежных сервисов операционной системы.

---

## Дополнительная информация

### Математическая модель потребления памяти под нагрузкой

Потребление оперативной памяти сервером трансформации складывается из постоянной базы ядра Angie и динамического пула воркеров.

$$\text{Total RSS} = \text{Angie Core Base} + N_{\text{workers}} \times \left( \text{Worker Base} + \text{Peak Transformation Buffer} \right)$$

Где:
- $\text{Angie Core Base} \approx 30 \text{ МБ}$ (код, разделяемые зоны `status_zone`).
- $\text{Worker Base} \approx 15 \text{ МБ}$.
- $\text{Peak Transformation Buffer} = \text{image\_filter\_buffer} + (\text{Width} \times \text{Height} \times 4) + \text{Codec Workspace}$.

**Пример практического расчета:**
- Разрешение оригинала: $4000 \times 3000$ (12 Мп) $\rightarrow$ Растр RGBA: $48 \text{ МБ}$.
- Буфер оригинала: `image_filter_buffer 25M` $\rightarrow 25 \text{ МБ}$.
- Внутренние буферы libavif: $\approx 35 \text{ МБ}$.
- Пик на 1 воркер: $25 + 48 + 35 \approx 108 \text{ МБ}$.
- При пуле из 8 воркеров максимальный динамический скачок: $8 \times 108 \approx 864 \text{ МБ}$.
- Запас надежности SRE (safety margin 30%): $864 \times 1.3 \approx 1123 \text{ МБ}$.
- Рекомендуемый порог: `MemoryMax=1.5G` (или `MemoryMax=3G` при одновременной работе фронтенда на том же хосте).

### Наблюдаемость через API Angie и Prometheus

Мониторинг внутреннего сервера осуществляется через обращение к встроенному REST API Angie по статус-зоне `image_filter_backend`:

```bash
# Выгрузка метрик зоны бэкенда через встроенный API
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_filter_backend | jq .
```

Пример структуры JSON-ответа:

```json
{
  "requests": 145020,
  "responses": {
    "1xx": 0,
    "2xx": 144890,
    "3xx": 0,
    "4xx": 125,
    "5xx": 5,
    "codes": {
      "200": 144890,
      "404": 83,
      "415": 42,
      "500": 5
    }
  },
  "data": {
    "sent": 1849204812,
    "received": 14502000
  }
}
```

#### SRE Пороговые значения и алерты Prometheus

```yaml
# Правила Prometheus Alertmanager для image_filter_backend
groups:
  - name: angie_image_filter_alerts
    rules:
      # Оповещение при аномальном росте ошибок несовместимости формата или нехватки буфера
      - alert: AngieImageFilterHighError415Rate
        expr: sum(rate(angie_zone_responses_codes{code="415", zone="image_filter_backend"}[5m])) 
              / sum(rate(angie_zone_requests_total{zone="image_filter_backend"}[5m])) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Высокая доля ошибок 415 на бэкенде фильтрации (>5%)"
          description: "Проверьте размер входящих оригиналов или увеличьте image_filter_buffer."

      # Оповещение при возникновении внутренних падений сервера (500 Internal Error)
      - alert: AngieImageFilterBackend5xxFailures
        expr: sum(rate(angie_zone_responses_codes{code="500", zone="image_filter_backend"}[1m])) > 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Сбои декомпрессии/падения библиотеки libgd"
          description: "Зафиксированы ошибки 500 на сервере image_backend. Проверьте dmesg на OOM и совместимость библиотек."
```

### См. также

- **[Обзор возможностей image_filter](./overview.md)** — архитектура модуля и поддерживаемые форматы.
- **[Стратегии кэширования для image_filter](./caching.md)** — реализация кэша, сохранение индекса (`file=`), защита от Stampede.
- **[Конфигурация фронтенда для image_filter](./site_configuration.md)** — маппинг заголовков `Accept`, `proxy_pass` и управление SSL.
- **[Динамический ресайз и кадрирование](./resize.md)** — специфика геометрических параметров и синтаксис директив.
- **[Безопасность и защита от DoS в image_filter](./security.md)** — валидация параметров через `secure_link` и rate limiting.
- **[Производительность и масштабирование](./performance.md)** — профилирование воркеров, оптимизация задержек и бенчмарки.
- **[Установка и сборка модуля image_filter](./installation.md)** — сборка динамического модуля с libgd, libavif и libheif.
- **[Мониторинг Angie через Status API](../../angie_monitoring/angie_monitoring_api.md)** — сбор метрик в реальном времени и интеграция с Prometheus.
