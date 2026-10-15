# Модуль image_filter в Angie: обзор возможностей

**Актуально для:** Angie 1.12.x

## Определения

**Модуль image_filter (`ngx_http_image_filter_module`)** — высокопроизводительный динамический модуль веб-сервера Angie, выполняющий обработку, кадрирование, масштабирование и транскодирование растровых изображений в режиме реального времени. Представляет собой расширенную разработчиками Angie версию стандартного модуля Nginx с нативной поддержкой современных кодеков (AVIF, WebP, HEIC) и директивы потоковой конвертации.

**Адаптивная доставка изображений (Adaptive Image Delivery)** — архитектурная стратегия отдачи статического медиаконтента, при которой сервер динамически отдает изображение в наиболее легковесном и поддерживаемом клиентским ПО формате (AVIF, WebP или JPEG/PNG) на основании HTTP-заголовка `Accept`.

**Согласование контента (Content Negotiation)** — стандартизированный механизм протокола HTTP, позволяющий клиенту передать список предпочтительных MIME-типов (`Accept: image/avif,image/webp,image/*,*/*;q=0.8`), а серверу — сопоставить их с оптимальным форматом ответа через директивы `map`.

**Двухуровневое проксирование (Double Proxying)** — архитектурный паттерн High Load, разделяющий конвейер обработки на два изолированных контура: внешний фронтенд (кэширование, SSL-терминация, rate limiting, отдача готового кэша) и внутренний воркер-бэкенд (выделение памяти, распаковка и ресурсоемкое кодирование). Исключает повторные затраты CPU на один и тот же файл.

**Буфер декомпрессии (`image_filter_buffer`)** — предельный объем оперативной памяти, выделяемый рабочим процессом Angie для считывания исходного сжатого файла в память перед передачей библиотеке `libgd`. Если размер оригинала превышает это значение, сервер возвращает код `415 Unsupported Media Type`.

**Ключ кэширования (`proxy_cache_key`)** — строковый хеш-идентификатор объекта в дисковом кэше `proxy_cache`. При динамической трансформации ключ обязан учитывать запрашиваемые габариты, качество, тип операции и целевой формат изображения, согласованный через `Accept`.

**Внутренний сокет (Unix Domain Socket)** — механизм межпроцессного взаимодействия (IPC) в ОС Linux, используемый для передачи данных между фронтендом и локальным бэкендом трансформации без накладных расходов сетевого стека TCP/IP и потерь на обработку сетевых пакетов.

---

## Базовые концепции

Модуль `ngx_http_image_filter_module` позволяет развернуть полноценный микросервис обработки медиаконтента непосредственно внутри веб-сервера без необходимости привлечения тяжелых внешних сервисов. Это позволяет хранить на дисковой подсистеме только мастер-исходники высокого разрешения, генерируя превью и оптимизированные форматы на лету.

### Ключевые преимущества Angie

1. **Нативная поддержка форматов нового поколения:** Angie поддерживает чтение и запись **AVIF**, **WebP** и **HEIC** при наличии соответствующих системных библиотек (`libavif`, `libwebp`, `libheif`).
2. **Директива Convert:** В отличие от Nginx, где для смены формата требовалось обязательное масштабирование, Angie предоставляет директиву `image_filter convert <format>`, позволяющую менять контейнер (например, JPEG → AVIF/WebP) без изменения геометрических размеров.
3. **Тонкая настройка компрессии и скорости:** Наличие специализированных директив управления скоростью кодирования (`image_filter_avif_speed`), прогрессивной развертки (`image_filter_interlace`) и адаптивного качества для каждого формата.
4. **Метрики и телеметрия в реальном времени:** Бесшовная интеграция с механизмом `status_zone` и встроенной выгрузкой Prometheus (`prometheus`), что дает SRE-инженеру поминутную видимость времени кодирования (P95/P99 latency), кодов ошибок и утилизации ресурсов.
5. **Динамическая модульность:** Модуль распространяется в виде отдельного пакета `angie-module-image-filter` и подключается через `load_module` без перекомпиляции ядра сервера.

### Архитектура конвейера обработки

В высоконагруженных окружениях категорически запрещено выполнять трансформацию изображений в том же блоке `location`, где включен `proxy_cache` на внешнем интерфейсе: модуль `image_filter` перехватывает тело ответа *после* дискового кэша, что приводило бы к повторному кодированию на каждый клиентский запрос.

Стандартом является **схема двухуровневого проксирования**:

```
[Клиентский браузер] (Accept: image/avif,image/webp,...)
         │
         ▼
[Фронтенд Angie] ──(Проверка proxy_cache по cache_key)
   │          │
   │ HIT      └── MISS / BYPASS
   │                  │
   ▼                  ▼
[Быстрая отдача]   [Внутренний upstream / Unix Domain Socket]
(из proxy_cache)      │
                      ▼
                   [Бэкенд Angie с image_filter]
                      │
                      ├── Чтение оригинала с локального диска/NFS/хранилища
                      ├── Выделение image_filter_buffer
                      ├── Декодирование в RGBA через libgd
                      ├── Трансформация (resize/crop/rotate)
                      └── Кодирование в целевой формат (libavif/libwebp/libgd)
                      │
                      ▼
                   [Возврат готового бинарного потока]
                      │
                      ▼
                   [Сохранение в proxy_cache фронтенда + Vary: Accept]
                      │
                      ▼
                   [Отдача клиенту]
```

**Ключевые принципы архитектуры:**
- **Изоляция нагрузки:** Тяжелая математика кодирования изолируется в отдельном пуле воркеров, управляемом системными квотами (cgroups / systemd), защищая базовый веб-сервер от деградации.
- **Корректность кэширования:** Фронтенд сохраняет в кэше уже трансформированное изображение. Заголовок `Vary: Accept` гарантирует, что клиенту без поддержки AVIF не будет выдан закэшированный AVIF-файл.
- **Штампозащита (Cache Stampede Protection):** Использование директивы `proxy_cache_lock on` гарантирует, что при одновременном поступлении сотен запросов на один и тот же новый размер, внутренний фильтр выполнит генерацию ровно один раз, а остальные запросы дождутся заполнения кэша.

### Модели развертывания в On-Premise инфраструктуре

| Модель | Описание схемы | Сетевые накладные расходы | Рекомендуемый профиль нагрузки |
|:---|:---|:---|:---|
| **Single-Node (IPC)** | Фронтенд и внутренний фильтр на одном сервере, связь через `unix:/run/angie_img_filter.sock` | Нулевые (передача через память ядра ОС) | До 3 000 rps, компактные серверы |
| **Dedicated Backend Farm** | Вынесенный пул серверов трансформации за балансировщиком Angie с алгоритмом `least_conn` | Минимальные (TCP в 10G/25G локальной сети ЦОД) | 3 000 – 50 000+ rps, масштабирование CPU |
| **Tiered Storage + Compute** | Разделение узлов хранения оригиналов и stateless-воркеров транскодирования с кэшем на быстрых NVMe | Локальная сеть ЦОД, MTU 9000 (Jumbo Frames) | Крупные медиа-порталы, каталоги e-commerce |

### Поддерживаемые форматы и эксплуатационные компромиссы

| Формат | Степень сжатия | Затраты CPU (отн. JPEG) | Системная библиотека | Область применения и рекомендации SRE |
|:---|:---|:---|:---|:---|
| **AVIF** | Максимальная (-30–50% vs WebP) | 10x – 40x | `libavif` + кодеки (`aom`, `rav1e`) | Современные браузеры; обязателен параметр `image_filter_avif_speed 8-10` |
| **WebP** | Высокая (-25–35% vs JPEG) | 2x – 4x | `libwebp` | Стандартный fallback-формат для большинства клиентов |
| **HEIC** | Высокая (контейнер HEIF) | 6x – 15x | `libheif` | Прием и транскодирование загрузок с мобильных устройств Apple |
| **JPEG** | Базовая | 1x (эталон) | Встроено в `libgd` (`libjpeg-turbo`) | Универсальная совместимость; включение `image_filter_interlace on` |
| **PNG** | Без потерь (Lossless) | 1.5x – 2x | Встроено в `libgd` (`libpng`) | Пиктограммы, графика с прозрачностью (`image_filter_transparency on`) |

### Модель памяти и расчет ресурсов

Обработка растровой графики в Angie требует строгого разделения двух уровней потребления памяти:
1. **Буфер чтения (`image_filter_buffer`):** Оперативная память для удержания всего входящего сжатого файла. По умолчанию равен `1M`, чего недостаточно для современных фотографий со смартфонов (типичный вес 4–15 МБ). При недостатке буфера Angie немедленно прерывает обработку с HTTP 415.
2. **Пиксельная матрица в куче `libgd`:** После чтения файл декомпрессируется в несжатый массив пикселей цветового пространства RGBA (4 байта на пиксель).

**Формула расчета оперативной памяти на один поток трансформации:**
```
RAM_потока = image_filter_buffer + (Ширина × Высота × 4 байта) + Выходной_буфер_сжатия
```

*Пример:*
- Исходное фото: разрешение $4032 \times 3024$ (12 Мп), сжатый файл JPEG весит 8 МБ.
- Входной буфер: `image_filter_buffer 20M;`
- Несжатая матрица в RAM: $4032 \times 3024 \times 4 \approx 48.7$ МБ.
- Итого на одну активную операцию требуется: $20 + 48.7 + 5 \approx 74$ МБ оперативной памяти.
- При 40 параллельных запросах на трансформацию в пике потребуется: $40 \times 74 \approx 2.96$ ГБ RAM.

---

## Практические сценарии

### Сценарий 1: Двухуровневое проксирование через Unix Domain Socket

Классическая production-конфигурация на одном физическом сервере. Внешний сервер кэширует готовые файлы и нормализует заголовки, внутренний выполняет адаптивную конвертацию.

**Предварительные требования:**
- Установлен пакет `angie-module-image-filter`
- Директория сокетов `/run/angie` с правами пользователя `angie`

```nginx
# /etc/angie/angie.conf
load_module modules/ngx_http_image_filter_module.so;

user angie;
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 8192;
    use epoll;
    multi_accept on;
}

http {
    include /etc/angie/mime.types;
    default_type application/octet-stream;

    # Зона кэширования на быстром локальном диске (NVMe/SSD)
    proxy_cache_path /var/cache/angie/images
                     levels=1:2
                     keys_zone=img_cache:64m
                     max_size=20g
                     inactive=30d
                     use_temp_path=off;

    # Определение поддержки современных форматов клиентом
    map $http_accept $target_image_format {
        default         "original";
        "~*image/avif"  "avif";
        "~*image/webp"  "webp";
    }

    # Внешний фронтенд-сервер
    server {
        listen 80;
        listen 443 ssl default_server;
        server_name media.example.internal;

        ssl_certificate     /etc/ssl/certs/media.example.crt;
        ssl_certificate_key /etc/ssl/private/media.example.key;

        status_zone frontend_media_zone;

        # Обработка с изменением геометрии и адаптивным форматом
        location ~* ^/resize/(?<width>\d+)x(?<height>\d+)/(?<image_path>.+)$ {
            # Валидация разрешенных габаритов для защиты от перегрузки CPU
            if ($width !~ "^(150|300|600|1200)$") {
                return 400 "Invalid width dimension\n";
            }
            if ($height !~ "^(150|300|600|1200)$") {
                return 400 "Invalid height dimension\n";
            }

            proxy_cache img_cache;
            # Ключ учитывает геометрию, путь и целевой формат
            proxy_cache_key "$scheme$host$uri$target_image_format";
            proxy_cache_valid 200 30d;
            proxy_cache_valid 404 415 5m;

            # Защита от штамп-эффекта и отдача устаревшего кэша при обновлении
            proxy_cache_lock on;
            proxy_cache_lock_timeout 5s;
            proxy_cache_use_stale error timeout updating;

            # Обязательный заголовок для промежуточных прокси
            add_header Vary "Accept" always;
            add_header X-Cache-Status $upstream_cache_status always;

            # Проксирование во внутренний Unix-сокет
            proxy_pass http://unix:/run/angie/image_transformer.sock:/transform/$target_image_format/$width/$height/$image_path;
        }

        # Прямая отдача оригиналов без трансформации
        location /originals/ {
            alias /var/www/media/originals/;
            expires 30d;
            add_header Cache-Control "public, no-transform";
        }
    }

    # Внутренний сервер трансформации (изолированный бэкенд)
    server {
        listen unix:/run/angie/image_transformer.sock;
        server_name internal_transformer;

        status_zone image_filter_backend;

        # Доступ разрешен только внутренним процессам
        root /var/www/media/originals;

        location ~* ^/transform/(?<fmt>avif|webp|original)/(?<w>\d+)/(?<h>\d+)/(?<file>.+)$ {
            alias /var/www/media/originals/$file;

            # Буфер декомпрессии под современные фото (до 25 МБ сжатого файла)
            image_filter_buffer 25M;
            image_filter resize $w $h;

            # Условная конвертация в зависимости от URL
            set $apply_format $fmt;
            if ($apply_format = "avif") {
                image_filter convert avif;
            }
            if ($apply_format = "webp") {
                image_filter convert webp;
            }

            # Тонкая настройка качества кодирования
            image_filter_avif_quality 68;
            image_filter_avif_speed   9;
            image_filter_webp_quality 78;
            image_filter_jpeg_quality 82;
            image_filter_interlace    on;
            image_filter_sharpen      5;

            # Корректная обработка неподдерживаемых файлов
            error_page 415 = @unsupported_format;
        }

        location @unsupported_format {
            return 415 "Unsupported Image Media Type or Buffer Exceeded\n";
        }
    }
}
```

**Проверка и валидация:**
```bash
# 1. Проверка прав доступа и создания Unix-сокета
ls -la /run/angie/image_transformer.sock
# → srw-rw---- 1 angie angie 0 Oct 14 12:00 /run/angie/image_transformer.sock

# 2. Первичный запрос с поддержкой AVIF (ожидаем MISS и генерацию)
curl -s -I -H "Accept: image/avif,image/webp,*/*" https://media.example.internal/resize/300x300/catalog/item1.jpg
# → HTTP/2 200
# → content-type: image/avif
# → vary: Accept
# → x-cache-status: MISS

# 3. Повторный запрос того же ресурса (ожидаем мгновенный HIT из кэша)
curl -s -I -H "Accept: image/avif,image/webp,*/*" https://media.example.internal/resize/300x300/catalog/item1.jpg
# → HTTP/2 200
# → content-type: image/avif
# → x-cache-status: HIT

# 4. Запрос от устаревшего клиента без поддержки AVIF (ожидаем WebP либо JPEG)
curl -s -I -H "Accept: image/webp,*/*" https://media.example.internal/resize/300x300/catalog/item1.jpg
# → HTTP/2 200
# → content-type: image/webp
# → x-cache-status: MISS
```

---

### Сценарий 2: Горизонтальное масштабирование на выделенную ферму бэкендов

При нагрузках свыше 5 000 rps операции транскодирования AVIF выносятся на выделенный кластер bare-metal серверов с мощными многоядерными CPU.

```nginx
# Конфигурация балансировщика на узле фронтенда
upstream image_backend_farm {
    # Балансировка по наименьшему числу активных соединений
    least_conn;

    server 192.168.10.21:8081 max_fails=3 fail_timeout=10s max_conns=64;
    server 192.168.10.22:8081 max_fails=3 fail_timeout=10s max_conns=64;
    server 192.168.10.23:8081 max_fails=3 fail_timeout=10s max_conns=64;

    # Пул постоянных TCP-соединений для устранения сетевых задержек
    keepalive 32;
}

server {
    listen 80;
    server_name images.local;

    location ~* ^/thumb/(?<params>.+)$ {
        proxy_cache img_cache;
        proxy_cache_key "$uri$http_accept";
        proxy_cache_valid 200 14d;

        proxy_pass http://image_backend_farm;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;

        # Таймауты с учетом пиковых затрат времени на сжатие AVIF
        proxy_connect_timeout 2s;
        proxy_read_timeout    10s;
        proxy_send_timeout    5s;
    }
}
```

**Проверка состояния соединений бэкенда:**
```bash
# Проверка установленных keepalive соединений с узлами фермы
ss -tan 'sport = :8081 or dport = :8081' | grep ESTAB | wc -l
# → 24
```

---

### Сценарий 3: Наблюдаемость и мониторинг через Prometheus и Angie Console

Непрерывный контроль производительности модуля `image_filter` через встроенный в Angie модуль статистики.

```nginx
# Внутренний административный порт мониторинга
server {
    listen 127.0.0.1:8088;
    server_name localhost;

    # REST API метрик в формате JSON
    location /api/ {
        api /;
        allow 127.0.0.1;
        allow 192.168.10.0/24;
        deny all;
    }

    # Метрики Prometheus для сборщика (Prometheus / VictoriaMetrics)
    location /metrics {
        prometheus;
        allow 127.0.0.1;
        allow 192.168.10.0/24;
        deny all;
    }

    # Веб-консоль Angie
    location /console/ {
        auto_redirect on;
        alias /usr/share/angie-console-light/html/;
    }
}
```

**Скрипт проверки ключевых метрик SRE:**
```bash
# 1. Проверка времени обработки в зоне трансформации через API
curl -s http://127.0.0.1:8088/api/http/status_zones/image_filter_backend | jq '.responses.time'
# → {
# →   "mean": 142,
# →   "p95": 280,
# →   "p99": 410
# → }

# 2. Мониторинг ошибок 415 (нехватка image_filter_buffer или битые файлы)
curl -s http://127.0.0.1:8088/api/http/status_zones/image_filter_backend | jq '.responses.codes."415"'
# → 0

# 3. Инспекция экспорта в формате Prometheus
curl -s http://127.0.0.1:8088/metrics | grep -E "angie_zone_responses_time_seconds|angie_cache" | head -n 5
# → angie_zone_responses_time_seconds_bucket{zone="image_filter_backend",le="0.1"} 1420
# → angie_zone_responses_time_seconds_bucket{zone="image_filter_backend",le="0.5"} 3890
# → angie_cache_size_bytes{cache="img_cache"} 12492849152
```

---

### Сценарий 4: Планирование емкости и изоляция ресурсов в systemd / cgroups v2

Для предотвращения падения сервера от OOM Killer при лавинообразных запросах на декомпрессию крупных изображений настраивается изоляция ресурсов сервиса Angie в Linux.

Создание drop-in конфигурации systemd:
```ini
# /etc/systemd/system/angie.service.d/limits.conf
[Service]
# Лимитирование памяти (cgroups v2)
MemoryAccounting=yes
MemoryHigh=6G
MemoryMax=8G

# Лимитирование нагрузки на ядра CPU (например, резерв до 800% = 8 ядер)
CPUAccounting=yes
CPUQuota=800%

# Защита от исчерпания файловых дескрипторов
LimitNOFILE=131072
LimitNPROC=32768

# Предотвращение убийства воркера системным OOM Killer раньше остальных процессов
OOMScoreAdjust=-500
```

**Применение и валидация системных ограничений:**
```bash
# Перечитывание конфигурации systemd и перезапуск
systemctl daemon-reload
systemctl restart angie

# Проверка примененных ограничений памяти в cgroups v2
cat /sys/fs/cgroup/system.slice/angie.service/memory.max
# → 8589934592

# Мониторинг текущего потребления памяти демоном
systemctl status angie | grep Memory
# → Memory: 1.4G (max: 8.0G, high: 6.0G)
```

---

### Сценарий 5: Аварийный режим и деградация (Graceful Degradation)

При перегрузке CPU или недоступности сокета трансформации система обязана продолжать отдавать оригиналы изображений клиентам без генерации ошибки HTTP 502/504.

```nginx
# Конфигурация фронтенда с отказоустойчивым переключением
server {
    listen 80;
    server_name media.example.internal;

    location ~* ^/img/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
        proxy_cache img_cache;
        proxy_cache_key "$uri$http_accept";
        proxy_cache_valid 200 30d;

        # Перехват системных ошибок апстрима
        proxy_intercept_errors on;
        error_page 502 503 504 415 = @fallback_original;

        proxy_pass http://unix:/run/angie/image_transformer.sock;
    }

    # Резервная отдача исходного файла при аварии трансформатора
    location @fallback_original {
        root /var/www/media/originals;
        try_files /$file =404;

        add_header X-Degraded-Mode "True" always;
        add_header Cache-Control "public, max-age=3600";
    }
}
```

**Тестирование аварийного переключения:**
```bash
# Имитируем остановку сокета трансформации
systemctl stop angie-transformer.service

# Клиент получает оригинальный файл вместо ошибки 502
curl -s -I https://media.example.internal/img/400x300/banner.jpg
# → HTTP/2 200
# → x-degraded-mode: True
# → content-type: image/jpeg
```

---

### Сценарий 6: Эксплуатационное управление и перезагрузка без простоя (Zero-Downtime)

Безопасное внесение изменений в директивы качества, добавление форматов и перечитывание конфигурации в проде.

```bash
# 1. Тщательная валидация синтаксиса и путей к модулям перед применением
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Плавная перезагрузка воркеров без разрыва открытых клиентских соединений
systemctl reload angie

# 3. Контроль системных логов на отсутствие ошибок компиляции регулярных выражений и сокетов
journalctl -u angie --no-pager -n 20 | grep -E "reload|worker"
# → Oct 14 12:30:00 srv-app-01 systemd[1]: Reloaded Angie - high performance HTTP and reverse proxy server.
# → Oct 14 12:30:00 srv-app-01 angie[41200]: [notice] 41200#41200: start graceful process cycle
```

---

## Операции и команды

Справочная таблица типовых команд системного инженера при эксплуатации модуля `image_filter`:

| Задача | Команда | Ожидаемый результат / Примечание |
|:---|:---|:---|
| Проверка сборки модуля | `angie -M \| grep image_filter` | `# → ngx_http_image_filter_module` |
| Проверка загруженных библиотек кодеков | `ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so \| grep -E "avif\|webp\|heif\|gd"` | `# → libavif.so.16 => /lib/x86_64-linux-gnu/libavif.so.16`<br>`# → libwebp.so.7 => ...` |
| Проверка установленного пакета в ОС (Debian/Ubuntu) | `dpkg -l \| grep angie-module-image-filter` | `# → ii angie-module-image-filter 1.12.0-...` |
| Проверка установленного пакета в ОС (RHEL/Rocky/Alma) | `rpm -qa \| grep angie-module-image-filter` | `# → angie-module-image-filter-1.12.0-...` |
| Тест адаптивной отдачи (AVIF) | `curl -s -o /dev/null -w "%{http_code} %{content_type}\n" -H "Accept: image/avif" http://127.0.0.1/resize/300x300/test.jpg` | `# → 200 image/avif` |
| Тест адаптивной отдачи (WebP) | `curl -s -o /dev/null -w "%{http_code} %{content_type}\n" -H "Accept: image/webp" http://127.0.0.1/resize/300x300/test.jpg` | `# → 200 image/webp` |
| Поиск оригиналов, превышающих лимит буфера | `find /var/www/media/originals -type f -size +20M` | `# → /var/www/media/originals/heavy_raw.png` (кандидаты на 415) |
| Очистка закэшированного файла вручную | `find /var/cache/angie/images -type f -delete` | Полный сброс дискового кэша |
| Проверка утилизации Unix-сокета | `ss -xlp \| grep image_transformer` | Инспекция очереди пакетов Send-Q / Recv-Q |

---

## Устранение неисправностей (Troubleshooting)

| Симптом | Первопричина | Метод диагностики | Способ устранения |
|:---|:---|:---|:---|
| **HTTP 415 Unsupported Media Type** | Размер файла оригинала превышает лимит `image_filter_buffer` | `grep "image_filter: image buffer is too small" /var/log/angie/error.log` | Увеличить `image_filter_buffer` (например, с `1M` до `25M`) в блоке `server` бэкенда |
| **HTTP 415 Unsupported Media Type** | Файл поврежден либо передан неподдерживаемый формат (например, SVG, TIFF, CMYK JPEG) | `file -b --mime-type /path/to/original` | Обеспечить валидацию расширений и форматов на уровне приложения; пропускать векторные файлы мимо фильтра |
| **Всплеск Latency > 1.5 с, полка по CPU** | Чрезмерно медленное кодирование AVIF при параметре `image_filter_avif_speed < 8` | `top -b -n 1 \| grep angie`<br>`curl ... /api/http/status_zones/image_filter_backend` | Установить `image_filter_avif_speed 9` или `10`; снизить `image_filter_avif_quality` до 65 |
| **HTTP 502 Bad Gateway на фронтенде** | Упал внутренний воркер или отсутствуют права на Unix-сокет | `ls -la /run/angie/*.sock`<br>`grep "Permission denied" /var/log/angie/error.log` | Проверить директиву `user` в `angie.conf`, права на каталог сокетов (`chmod 770 /run/angie`, `chown -R angie:angie /run/angie`) |
| **Аварийное завершение воркера (SIGSEGV/SIGKILL)** | Нехватка системной RAM; срабатывание OOM Killer ядра Linux | `dmesg -T \| grep -i -E "oom[-_]killer\|killed process"` | Увеличить физическую память хоста, настроить лимиты в `cgroups/systemd`, уменьшить число одновременных трансформаций (`limit_conn`) |
| **Ошибка при старте: `module signature mismatch`** | Пакет `angie-module-image-filter` собран для другой минорной сборки ядра Angie | `angie -v`<br>`journalctl -u angie \| grep signature` | Синхронизировать версии ядра и модуля (`apt update && apt install --only-upgrade angie angie-module-image-filter`) |
| **Одинаковый формат отдается всем клиентам** | Отсутствует `Vary: Accept` или ключ `proxy_cache_key` не содержит переменную формата | `curl -I -H "Accept: image/jpeg" https://...`<br>Проверка ответа на заголовок `Vary` | Включить `add_header Vary Accept always;` и добавить `$target_image_format` в `proxy_cache_key` |

---

## Лучшие практики

1. **Строгое двухуровневое разделение:** Никогда не выполняйте директивы `image_filter` на публичном фронтенде. Кэш должен защищать процессор от повторной работы.
2. **Белые списки габаритов (Whitelist Dimensions):** Исключите передачу произвольных чисел в URL (`/resize/$w/$h`). Разрешайте только фиксированную сетку разрешений (например, 150x150, 300x300, 600x600, 1200x1200), сопоставляемую через директиву `map`. Это предотвращает атаки исчерпания ресурсов (Cache Flooding / CPU DoS).
3. **Ограничение конкурентных трансформаций (`limit_conn`):** На внутреннем сервере трансформаций ограничивайте число одновременных запросов с одного IP или к одному URI с помощью `limit_conn_zone`, защищая воркеры от блокировки.
4. **Оптимизация параметров кодеков под High Load:**
   - Для **AVIF**: `image_filter_avif_speed 9;` и `image_filter_avif_quality 65-70;` (дает выигрыш до 40% по объему при адекватных затратах CPU).
   - Для **WebP**: `image_filter_webp_quality 75-80;`.
   - Для **JPEG**: `image_filter_interlace on;` и `image_filter_jpeg_quality 80-85;`.
5. **Синхронизация буфера:** Устанавливайте `image_filter_buffer` на уровне 20–30 МБ, контролируя лимиты памяти через systemd (`MemoryMax`).
6. **Быстрый локальный диск под кэш:** Хранилище `proxy_cache_path` должно размещаться на высокоскоростных накопителях NVMe в файловых системах `ext4` (с опцией монтирования `noatime`) или `XFS`.

---

## Дополнительная информация

### Подключение и системная интеграция

Модуль устанавливается штатным пакетным менеджером операционной системы:

```bash
# Для Debian / Ubuntu
apt-get update && apt-get install -y angie-module-image-filter

# Для RHEL / Rocky Linux / AlmaLinux
dnf install -y angie-module-image-filter
```

Активация модуля производится на глобальном уровне в `/etc/angie/angie.conf` до блока `http`:

```nginx
load_module modules/ngx_http_image_filter_module.so;
```

### Архитектурные ограничения модуля

1. **Синхронно-блокирующий характер обработки:** Вызов `libgd` и сжатие выполняются синхронно в контексте рабочего процесса (worker process). Во время конвертации тяжелого кадра воркер заблокирован и не может обрабатывать другие события в цикле epoll. Именно поэтому критично распределять нагрузку по ядрам через `worker_processes auto;` и масштабировать воркеры горизонтально.
2. **Невозможность потоковой передачи:** Модуль принципиально не может отдавать изображение чанками (chunked transfer) по мере считывания. Требуется полный сбор байтов в `image_filter_buffer`, полная трансформация и последующая отдача.
3. **Ограничение по форматам анимации:** Модуль не предназначен для конвертации многокадровых анимированных изображений (Animated GIF / Animated WebP) с сохранением динамики — трансформация применяется только к первому кадру.

### Типовой регламент инцидента (Runbook)

**Симптом:** Рост задержки отдачи медиа (P95 > 800 мс) или лавинообразные ошибки HTTP 415 / 502.

**Шаги диагностики и локализации:**
```bash
# Шаг 1. Проверка состояния сервиса и системного OOM Killer
systemctl status angie
dmesg -T | grep -i oom | tail -n 10

# Шаг 2. Анализ кодов ответов в зоне бэкенда
curl -s http://127.0.0.1:8088/api/http/status_zones/image_filter_backend | jq '.responses.codes'

# Шаг 3. Оценка загрузки очередей Unix-сокета
ss -xl '( sport = "*/image_transformer.sock" )'

# Шаг 4. Проверка процента попадания в кэш на фронтенде (Cache Hit Ratio)
curl -s http://127.0.0.1:8088/api/http/caches/img_cache | jq '{hit: .responses.hit, miss: .responses.miss}'
```

**Регламент устранения:**
1. Если растут ошибки **415**: временно увеличить `image_filter_buffer` до `35M`, выполнить `angie -t && systemctl reload angie`.
2. Если CPU утилизирован на 100% из-за кодека AVIF: переключить `image_filter_avif_speed` на `10`, снизить `image_filter_avif_quality` до `60`.
3. При отказе пула бэкендов: активировать аварийный режим отдачи оригиналов (Сценарий 5).

### Регламент отката изменений (Rollback)

Для оперативного отключения динамической трансформации без прерывания обслуживания трафика:
1. Замените секцию `location ~* ^/resize/` на фронтенде прямой раздачей директорией `alias /var/www/media/originals;` с директивой `try_files`.
2. Выполните проверку конфигурации `angie -t` и перезагрузите сервер: `systemctl reload angie`.
3. При необходимости освобождения дискового пространства очистите кэш: `rm -rf /var/cache/angie/images/*`.

### См. также

- [Установка и эксплуатационная настройка](./installation.md) — компиляция, зависимости libgd, пакетная база и валидация ABI
- [Конфигурация директив image_filter](./filter_configuration.md) — детальный справочник параметров качества и масштабирования
- [Стратегии кэширования медиаконтента](./caching.md) — организация дискового кэша, ключи, purge и блокировки
- [Изменение размеров и трансформация](./resize.md) — режимы resize, crop, rotate и директива convert
- [Безопасность и защита от DoS](./security.md) — rate limiting, signed URLs (HMAC), валидация параметров
- [Производительность и тюнинг](./performance.md) — оптимизация CPU, NUMA-узлы, ускорение AVIF/WebP
- [Конфигурация фронтенда и сайтов](./site_configuration.md) — production-конфигурации виртуальных хостов и интеграция с хранилищами
