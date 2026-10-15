# Модуль image_filter в Angie: безопасность и защита от DoS

**Актуально для:** Angie 1.12.x

## Определения

**DoS-атака на image_filter** — тип атаки на отказ в обслуживании (Denial of Service), при котором злоумышленник генерирует специфические или аномальные запросы на обработку изображений (тяжелые геометрические размеры, сжатие ресурсоемкими кодеками, декомпрессионные бомбы, генерация случайных параметров) с целью полного исчерпания вычислительных ресурсов CPU, оперативной памяти (RAM) или пула воркеров веб-сервера.

**Декомпрессионная бомба (Pixel Flood / Decompression Bomb)** — вредоносное изображение с компактным размером сжатого файла на диске (например, 500 КБ JPEG/PNG), но обладающее гигантскими геометрическими габаритами (например, 25 000 × 25 000 пикселей). При распаковке в оперативную память библиотека `libgd` выделяет несжатую RGBA-матрицу (`25 000 × 25 000 × 4 = 2.5 ГБ`), что мгновенно провоцирует дефицит RAM, свопинг и аварийное завершение рабочих процессов по OOM (Out Of Memory).

**Синхронная блокировка воркера (Head-of-Line Blocking в image_filter)** — архитектурная особенность модуля `ngx_http_image_filter_module`, при которой операции декомпрессии, манипуляции с пикселями и сжатия выполняются синхронно в контексте рабочего процесса (worker process). Во время вычислений цикл обработки событий (`epoll event loop`) процесса полностью заблокирован: воркер не принимает новые TCP-соединения, не выполняет TLS-хэндшейки и не обслуживает другие клиентские запросы.

**Cache Busting (сброс кэша)** — атака на обход кэширующего уровня, при которой атакующий генерирует псевдослучайные или постоянно инкрементируемые параметры в URL (`?w=301&h=301`, `?w=301&h=302`), заставляя сервер каждый раз выполнять тяжелую процедуру генерации нового изображения вместо мгновенной отдачи закэшированного файла.

**Проверка подписи (secure_link)** — механизм криптографической валидации параметров HTTP-запроса с использованием симметричного секрета и хэша (HMAC-MD5), делающий невозможным подбор параметров трансформации или времени жизни URL со стороны клиента без знания серверного ключа.

**Двойное проксирование как граница безопасности (Double Proxying)** — архитектурный паттерн High Load, разделяющий конвейер на внешний публичный фронтенд (SSL-терминация, rate limiting, connection limiting, проверка подписи/разрешений, дисковый кэш) и внутренний вычислительный бэкенд (`image_filter`), доступный исключительно через локальный Unix Domain Socket или `127.0.0.1` с директивой `internal`.

**SSRF (Server-Side Request Forgery) в конвейере изображений** — уязвимость, возникающая при получении сервером оригиналов изображений по внешнему URL или из непроверенных хранилищ, в результате чего злоумышленник может заставить Angie отправлять запросы во внутреннюю изолированную инфраструктуру (loopback, локальные сервисы БД, метаданные гипервизоров).

**Ограничение частоты (Rate Limiting) по Leaky Bucket** — алгоритмический контроль интенсивности входящих запросов к вычислительно тяжелым локациям с отсечением аномальных всплесков и возвратом HTTP-статуса `429 Too Many Requests`.

**Ограничение соединений (Connection Limiting)** — директивный контроль числа параллельных TCP-соединений или активных вычислительных задач с одного IP-адреса, предотвращающий монополизацию воркеров атакующим узлом.

**Отравление кэша (Cache Poisoning)** — некорректное сохранение в `proxy_cache` невалидного объекта (например, пустого изображения при сбое, поврежденного файла или AVIF-контейнера для клиентов без поддержки формата) из-за неправильно сформированного `proxy_cache_key` или игнорирования заголовка `Vary: Accept`.

---

## Базовые концепции

### Векторы атак на модуль image_filter

Модуль `image_filter` является одной из наиболее уязвимых точек веб-инфраструктуры к атакам на исчерпание ресурсов из-за высокой вычислительной сложности алгоритмов обработки графики.

```
Входящий запрос → epoll → [Синхронная блокировка воркера]
                               ├── Чтение оригинала в image_filter_buffer
                               ├── libgd: распаковка в RGBA-холст (Pixel Flood?)
                               ├── libgd: билинейный/бикубический ресайз (CPU)
                               └── libavif/libwebp: тяжелое сжатие (CPU 100%)
```

1. **Атака исчерпанием CPU через AVIF/HEIC:**
   Кодирование изображений кодеками нового поколения (AVIF через `libavif`, HEIC через `libheif`) требует в 20–50 раз больше процессорных циклов по сравнению с JPEG. При отсутствии жестких ограничений злоумышленник способен десятком параллельных запросов на конвертацию загрузить все ядра многопроцессорного сервера на 100%.

2. **Атака Pixel Flood (Декомпрессионная бомба):**
   Размер сжатого файла на диске не коррелирует с объемом памяти, требуемым для его обработки. Внутри `libgd` изображение всегда разворачивается в несжатую карту пикселей:
   $$\text{RAM}_{\text{canvas}} = \text{Ширина} \times \text{Высота} \times 4 \text{ байта (RGBA)}$$
   Запрос на обработку файла $10\,000 \times 10\,000$ пикселей требует не менее 400 МБ чистой оперативной памяти на один процесс. 10 одновременных запросов приводят к аллокации 4 ГБ RAM и аварийному срабатыванию ядра Linux Out-Of-Memory (OOM) Killer.

3. **Cache Busting и бесконечное пространство параметров:**
   Если параметры ширины и высоты принимаются напрямую из параметров запроса или регулярного выражения без белого списка или криптографической подписи, злоумышленник обходит кэш, генерируя уникальные пары координат (`100x100`, `100x101`, `100x102`...). Каждый запрос приводит к промаху кэша (MISS) и запуску полного цикла трансформации.

4. **Блокировка пула воркеров (Head-of-Line Blocking):**
   Так как трансформация блокирует event loop воркера, пул из 16 воркеров при 16 одновременных тяжелых трансформациях полностью прекращает обслуживание сетевых событий: отбрасываются новые TCP SYN, зависают TLS-сессии и запросы на отдачу статики.

5. **SSRF при динамическом заборе оригиналов:**
   Если конвейер поддерживает скачивание оригиналов из хранилища (MinIO, локальный S3, внутренние backend-ноды), некорректная фильтрация URL позволяет злоумышленнику сканировать внутренние порты (`127.0.0.1:6379`, `10.0.0.0/8`).

6. **Уязвимости библиотек парсинга (`libgd`, кодеки):**
   Библиотека `libgd` и сторонние кодеки написаны на C и исторически подвержены уязвимостям переполнения буфера (Buffer Overflow), целочисленного переполнения (Integer Overflow) и Out-of-Bounds чтения при парсинге поврежденных заголовков файлов.

### Модель угроз (Threat Model)

| Вектор атаки | Уязвимый компонент | Механизм воздействия | Критичность | Метод нейтрализации |
|:---|:---|:---|:---|:---|
| **Cache Busting** | `proxy_cache` + `image_filter` | Уникальные размеры в URL, 100% промахи кэша | **Критическая** | `secure_link` (HMAC), жесткий `map` белого списка |
| **Pixel Flood** | `libgd` (память воркера) | Экстремальное разрешение оригинала, вызов OOM | **Критическая** | `image_filter_buffer`, валидация габаритов, cgroups v2 |
| **CPU Starvation** | Воркер Angie / CPU ядра | Массовая генерация AVIF/HEIC высокого разрешения | **Высокая** | `limit_req` с `delay`, `limit_conn`, приоритет форматов |
| **Worker Starvation** | `epoll event loop` | Синхронная блокировка воркеров тяжелыми задачами | **Высокая** | Двойное проксирование, изоляция в отдельный systemd-срез |
| **SSRF** | `proxy_pass` к апстриму | Запрос локальных адресов и портов внутренней сети | **Высокая** | `internal`, изоляция `resolver`, запрет RFC 1918 |
| **Cache Stampede** | `proxy_cache` | Наплыв параллельных запросов на один холодный ключ | **Средняя** | `proxy_cache_lock`, `proxy_cache_use_stale updating` |
| **libgd Memory Exploit** | Системный стек `libgd` | Эксплуатация уязвимостей разбора форматов | **Высокая** | Systemd Sandboxing (`ProtectSystem`, `seccomp`), патчи ОС |

### Архитектура эшелонированной защиты (Defense in Depth)

```
[ Публичная сеть (Интернет) ]
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. ВНЕШНИЙ ФРОНТЕНД ANGIE (SSL, Защита L7, Кэш)                             │
│  - limit_req (Leaky Bucket: 5 r/s, burst 10)                                │
│  - limit_conn (Макс. 5 параллельных соединений на IP)                       │
│  - Валидация: secure_link (HMAC-MD5) или map (белый список пресетов)        │
│  - proxy_cache (Дисковый кэш + proxy_cache_lock против Thundering Herd)     │
│  - status_zone: сбор метрик атак и отказов                                  │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │ (Только при CACHE MISS / EXPIRED)
                                     │ Unix Domain Socket (chmod 0660 angie:angie)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. ВНУТРЕННИЙ БЭКЕНД ANGIE (Изолированная трансформация)                    │
│  - listen unix:/run/angie/image_filter.sock                                 │
│  - Директива internal (полный запрет внешнего обращения)                    │
│  - Жесткий лимит буфера: image_filter_buffer 20M                            │
│  - Fallback-обработка ошибок декомпрессии (415 -> отдача оригинала/заглушки)│
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. ХАРДЕНИНГ ОС И ЯДРА LINUX (cgroups v2, systemd sandboxing)               │
│  - MemoryMax=4G, MemoryHigh=3.5G (Предотвращение падения всей ОС по OOM)    │
│  - CPUQuota=400% (Ограничение суммарного потребления ядер процессора)       │
│  - ProtectSystem=strict, PrivateTmp=yes, CapabilityBoundingSet (Изоляция)   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: Двойное проксирование через изолированный Unix Domain Socket

Архитектурное разделение публичного фронтенда и внутреннего процессора исключает блокировку сетевого ввода-вывода и защищает сокет трансформации от несанкционированного доступа.

```bash
# Подготовка защищенного каталога сокетов
sudo mkdir -p /run/angie
sudo chown angie:angie /run/angie
sudo chmod 750 /run/angie
```

**Фрагмент конфигурации `/etc/angie/http.d/image_pipeline.conf`:**

```nginx
# Внутренний бэкенд трансформации (только сокет)
server {
    listen unix:/run/angie/image_filter.sock;
    server_name _;

    # Запрет логирования успешных внутренних операций для снижения I/O
    access_log off;
    status_zone image_backend;

    # Каталог защищенных мастер-оригиналов
    root /var/www/images/originals;

    # Локация трансформации с директивой internal
    location ~* ^/transform/(?<op>[a-z]+)/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
        internal;

        image_filter_buffer 20M;

        # Роутинг операций трансформации
        if ($op = "resize") {
            image_filter resize $w $h;
        }
        if ($op = "crop") {
            image_filter crop $w $h;
        }

        image_filter_jpeg_quality 85;
        image_filter_webp_quality 80;

        # Обработка сбоев трансформации и неподдерживаемых файлов
        error_page 415 = @empty_fallback;
    }

    location @empty_fallback {
        internal;
        empty_gif;
    }
}

# Внешний фронтенд
server {
    listen 443 ssl;
    server_name img.example.com;

    status_zone image_frontend;

    # Кэширование сжатых результатов
    location / {
        proxy_pass http://unix:/run/angie/image_filter.sock;
        proxy_set_header Host $host;

        proxy_cache img_cache;
        proxy_cache_key "$scheme$request_method$host$request_uri";
        proxy_cache_valid 200 30d;
        proxy_cache_valid 415 1m;

        # Защита от Cache Stampede
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_use_stale error timeout updating;

        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

**Валидация:**
```bash
# 1. Проверка прав и типа сокета
ls -la /run/angie/image_filter.sock
# → srw-rw---- 1 angie angie 0 Oct 14 13:30 /run/angie/image_filter.sock

# 2. Попытка прямого вызова внутренней локации через сокет из консоли
curl --unix-socket /run/angie/image_filter.sock "http://localhost/transform/resize/200x200/photo.jpg"
# → HTTP/1.1 404 Not Found (директива internal отклоняет прямой внешний запрос)
```

---

### Сценарий 2: Криптографическая защита от Cache Busting через secure_link

Модуль `ngx_http_secure_link_module` гарантирует, что запрос на генерацию миниатюры сгенерирован доверенным бэкендом приложения. Попытка изменить хотя бы один пиксель в габаритах или имя файла возвращает ошибку без запуска фильтра.

**Схема HMAC-хэширования:**
$$\text{MD5} = \text{Base64URL}\Big(\text{MD5}\big(\text{expires} + \text{URI} + \text{secret\_key}\big)\Big)$$

**Конфигурация `/etc/angie/http.d/secure_link.conf`:**

```nginx
server {
    listen 443 ssl;
    server_name img.example.com;

    location ~* ^/thumb/(?<md5>[a-zA-Z0-9_-]+)/(?<expires>\d+)/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
        # Валидация подписи и срока жизни
        secure_link $md5,$expires;
        secure_link_md5 "$secure_link_expires$uri secret_salt_phrase_2026";

        if ($secure_link = "") {
            # Хэш не совпадает или подделан
            return 403;
        }

        if ($secure_link = "0") {
            # Срок действия ссылки (TTL) истек
            return 410;
        }

        # Защита от передачи экстремальных размеров, если ключ скомпрометирован
        if ($w > 2000) { return 400; }
        if ($h > 2000) { return 400; }

        proxy_pass http://unix:/run/angie/image_filter.sock:/transform/resize/${w}x${h}/$file;
        proxy_cache img_cache;
        proxy_cache_key "$uri";
        proxy_cache_valid 200 30d;
    }
}
```

**Генератор валидной тестовой подписи в CLI:**
```bash
# Параметры запроса
SECRET="secret_salt_phrase_2026"
EXPIRES=$(date -d "+1 day" +%s)
URI="/thumb"
PARAMS="200x200/sample.jpg"

# Вычисление MD5 в base64 url-safe формате
RAW_URI="/thumb/${EXPIRES}/${PARAMS}"
TOKEN=$(echo -n "${EXPIRES}/thumb/TOKEN_PLACEHOLDER/${EXPIRES}/${PARAMS} ${SECRET}" | openssl md5 -binary | openssl base64 | tr '+/' '-_' | tr -d '=')
```

**Валидация:**
```bash
# 1. Запрос с фальшивым токеном
curl -I "https://img.example.com/thumb/badtoken123/1893456000/200x200/sample.jpg"
# → HTTP/2 403

# 2. Запрос с просроченным сроком жизни (expires=1000000000)
curl -I "https://img.example.com/thumb/validlookingtoken/1000000000/200x200/sample.jpg"
# → HTTP/2 410

# 3. Легитимный подписанный запрос
curl -I "https://img.example.com/thumb/${TOKEN}/${EXPIRES}/200x200/sample.jpg"
# → HTTP/2 200
```

---

### Сценарий 3: Закрытый белый список пресетов размеров через map

Если использование криптографической подписи невозможно (публичный каталог без генерации токенов на бэкенде), применяется строгий белый список допустимых разрешений.

**Конфигурация `/etc/angie/http.d/whitelist_sizes.conf`:**

```nginx
# Хэш-таблица разрешенных геометрических пресетов
map $arg_size $valid_image_preset {
    default       0;
    "thumb"       1; # 150x150
    "medium"      1; # 640x480
    "large"       1; # 1280x720
    "avatar"      1; # 80x80
}

# Сопоставление алиаса с реальными физическими координатами
map $arg_size $preset_dimensions {
    "thumb"       "150/150";
    "medium"      "640/480";
    "large"       "1280/720";
    "avatar"      "80/80";
}

server {
    listen 443 ssl;
    server_name img.example.com;

    location ~* ^/media/(?<file>.+\.(?:jpg|jpeg|png|webp))$ {
        # Жесткое отсечение произвольных размеров
        if ($valid_image_preset = 0) {
            return 400;
        }

        # Разделение координат
        rewrite ^ "/internal_proc/$preset_dimensions/$file" last;
    }

    location ~* ^/internal_proc/(?<w>\d+)/(?<h>\d+)/(?<file>.+)$ {
        internal;

        proxy_pass http://unix:/run/angie/image_filter.sock:/transform/resize/${w}x${h}/$file;
        proxy_cache img_cache;
        proxy_cache_key "$file$valid_image_preset";
        proxy_cache_valid 200 30d;
    }
}
```

**Валидация:**
```bash
# 1. Попытка передать произвольный размер для обхода кэша (Cache Busting)
curl -I "https://img.example.com/media/banner.jpg?size=641x481"
# → HTTP/2 400

# 2. Попытка запроса без параметра размера
curl -I "https://img.example.com/media/banner.jpg"
# → HTTP/2 400

# 3. Легитимный запрос из белого списка
curl -I "https://img.example.com/media/banner.jpg?size=medium"
# → HTTP/2 200
```

---

### Сценарий 4: Защита от декомпрессионных бомб (Pixel Flood) и исчерпания RAM

Предотвращение OOM-сбоев при загрузке или обработке файлов сверхвысокого разрешения.

**Конфигурация `/etc/angie/http.d/memory_limits.conf`:**

```nginx
# Ограничение размера принимаемого тела запроса (при загрузке оригиналов)
client_max_body_size 15M;
client_body_buffer_size 256k;

server {
    listen unix:/run/angie/image_filter.sock;
    server_name _;

    root /var/www/images/originals;

    location ~* ^/transform/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
        internal;

        # 1. Буфер чтения сжатого файла в память воркера
        # Превышение вызывает мгновенный возврат 415 без декодирования
        image_filter_buffer 15M;

        # 2. Ограничение предельного разрешения на выходе трансформации
        # Отсекает попытки ресайза в гигантские полотна
        image_filter resize $w $h;

        # Перехват ошибки переполнения буфера
        error_page 415 = @buffer_overflow_handler;
    }

    location @buffer_overflow_handler {
        internal;
        # Возврат кода 413 Payload Too Large вместо 415 для корректного мониторинга
        return 413 '{"error": "Original image exceeds maximum allowed buffer size"}';
    }
}
```

**Валидация:**
```bash
# 1. Запрос файла размером 22 МБ (превышает image_filter_buffer 15M)
curl -I "https://img.example.com/resize/300x300/huge_photo.jpg"
# → HTTP/2 413 (или HTTP/2 415 при стандартном поведении)

# 2. Проверка метрики ошибок 415 в status_zone
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_backend | jq '.responses.codes."415"'
# → 1
```

---

### Сценарий 5: Защита CPU от тяжелых кодеков (AVIF/WebP) через Rate и Connection Limiting

Поскольку кодирование AVIF потребляет максимум ресурсов процессора, для запросов с форматом AVIF применяются раздельные строгие лимиты алгоритма Leaky Bucket с фазой задержки (`delay`).

**Конфигурация `/etc/angie/http.d/rate_limiting.conf`:**

```nginx
# Зона ограничения частоты по IP-адресу клиента (10 МБ = ~160 000 IP-адресов)
limit_req_zone $binary_remote_addr zone=img_general_req:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=img_avif_req:10m rate=2r/s;

# Зона ограничения параллельных вычислительных сессий
limit_conn_zone $binary_remote_addr zone=img_conn_limit:10m;

# Определение целевого формата по заголовку Accept
map $http_accept $is_avif_request {
    default                  0;
    "~*image/avif"           1;
}

server {
    listen 443 ssl;
    server_name img.example.com;

    # Возврат статусов защиты
    limit_req_status 429;
    limit_conn_status 503;

    location /images/ {
        # Общий лимит параллельных соединений (не более 4 с одного IP)
        limit_conn img_conn_limit 4;

        # Базовый лимит частоты: допускает всплеск до 15 запросов,
        # из них первые 5 без задержки, далее с замедлением (delay)
        limit_req zone=img_general_req burst=15 delay=5;

        # Селективный строгий лимит для ресурсоемкого AVIF
        # Если клиент запросил AVIF, лимит снижается до 2 r/s с жестким burst=3
        limit_req zone=img_avif_req burst=3 nodelay if=$is_avif_request;

        proxy_pass http://unix:/run/angie/image_filter.sock;
        proxy_cache img_cache;
        proxy_cache_key "$scheme$request_method$host$request_uri$is_avif_request";
        proxy_cache_valid 200 30d;

        # Добавление заголовка ожидания при получении 429
        error_page 429 = @rate_limited;
    }

    location @rate_limited {
        add_header Retry-After 5 always;
        return 429 '{"error": "Too Many Image Requests. Slow down."}';
    }
}
```

**Валидация:**
```bash
# 1. Имитация высокоинтенсивного флуда запросами на AVIF
seq 1 10 | xargs -n1 -P5 curl -s -o /dev/null -w "%{http_code}\n" -H "Accept: image/avif" "https://img.example.com/images/banner.jpg?w=800"
# → 200
# → 200
# → 200
# → 429
# → 429
# → 429
```

---

### Сценарий 6: Защита от SSRF при заборе исходных изображений из MinIO / S3

Если конвейер скачивает оригиналы из хранилища по переданному пути, необходимо предотвратить обращение к чувствительным сетевым ресурсам (интерфейсы управления, локальные БД).

**Конфигурация `/etc/angie/http.d/ssrf_protection.conf`:**

```nginx
# Изоляция DNS: использование только выделенного внутреннего DNS-сервера
# с отключенным рекурсивным поиском во внешней сети
resolver 192.168.10.5 valid=30s ipv6=off;
resolver_timeout 3s;

server {
    listen unix:/run/angie/image_filter.sock;
    server_name _;

    # Запрет обращений к служебным адресам и приватным подсетям RFC 1918
    location ~* ^/fetch_origin/(?<storage_bucket>assets|products)/(?<path>[a-zA-Z0-9_\-\./]+)$ {
        internal;

        # Строгая фиксация хоста и порта апстрима (без переменных в имени хоста!)
        proxy_pass http://minio-internal.storage.local:9000/$storage_bucket/$path;

        # Отключение передачи клиентских заголовков, способных вызвать подделку
        proxy_set_header Host minio-internal.storage.local;
        proxy_set_header X-Real-IP "";
        proxy_set_header X-Forwarded-For "";
        proxy_pass_request_headers off;

        # Тайм-ауты на случай Slowloris со стороны хранилища
        proxy_connect_timeout 2s;
        proxy_read_timeout 4s;
    }

    # Локация-ловушка для попыток SSRF-обхода (path traversal, localhost, metadata)
    location ~* (127\.0\.0\.1|localhost|169\.254|0\.0\.0\.0|\.\.) {
        internal;
        return 403;
    }
}
```

**Валидация:**
```bash
# 1. Попытка передачи Path Traversal для выхода за пределы бакета
curl -I "https://img.example.com/fetch_origin/assets/../../etc/passwd"
# → HTTP/2 403 (или HTTP/2 400 Bad Request)

# 2. Попытка запроса неразрешенного бакета
curl -I "https://img.example.com/fetch_origin/admin_secrets/backup.tar.gz"
# → HTTP/2 404 (локация не совпала с белым списком assets|products)
```

---

### Сценарий 7: Харденинг на уровне ядра Linux и systemd (cgroups v2)

Ограничение привилегий и ресурсов рабочего процесса Angie на уровне операционной системы исключает падение всей ноды при DoS-атаке.

**Создание drop-in файла `/etc/systemd/system/angie.service.d/hardening.conf`:**

```ini
[Service]
# --- Ограничение ресурсов (cgroups v2) ---
# Лимит физической памяти: при превышении 3.5 ГБ ядро начинает агрессивный reclaim,
# при достижении 4.0 ГБ срабатывает OOM только внутри cgroup сервиса
MemoryHigh=3500M
MemoryMax=4000M

# Ограничение CPU: не более 4 полных ядер (400%)
CPUQuota=400%

# Ограничение количества процессов и потоков воркеров
TasksMax=128

# Лимит открытых файловых дескрипторов
LimitNOFILE=65536

# --- Песочница файловой системы (Sandboxing) ---
# Файловая система доступна только для чтения, кроме явно разрешенных путей кэша и логов
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/cache/angie /var/log/angie /run/angie

# Изолированный временный каталог /tmp для каждого сервиса
PrivateTmp=yes

# Запрет доступа к физическим устройствам (/dev)
PrivateDevices=yes

# Запрет модификации параметров ядра (/proc/sys, /sys)
ProtectKernelTunables=yes
ProtectControlGroups=yes
ProtectKernelModules=yes

# Запрет повышения привилегий через SUID/SGID биты
NoNewPrivileges=yes

# Минимально необходимый набор Linux Capabilities
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID
AmbientCapabilities=CAP_NET_BIND_SERVICE
```

**Применение и валидация:**
```bash
# 1. Перезагрузка конфигурации systemd и перезапуск Angie
sudo systemctl daemon-reload
sudo systemctl restart angie

# 2. Проверка примененных ограничений cgroups v2
systemctl show angie.service -p MemoryMax -p CPUQuota -p TasksMax
# → MemoryMax=4194304000
# → CPUQuotaPerSecUSec=4s
# → TasksMax=128

# 3. Мониторинг потребления ресурсов срезом
systemd-cgtop -n 1 | grep angie
# → /system.slice/angie.service    12    0.0    142.5M    -    -
```

---

### Сценарий 8: Мониторинг безопасности и алертинг через Prometheus

Настройка сбора телеметрии через встроенный модуль `prometheus` и генерация алертов при обнаружении DoS-атак.

**Конфигурация `/etc/angie/http.d/monitoring.conf`:**

```nginx
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    # Экспорт метрик Prometheus
    location /p8s {
        prometheus;
        allow 127.0.0.1;
        deny all;
    }

    # REST API консоли Angie
    location /api/ {
        api /status/;
        allow 127.0.0.1;
        deny all;
    }
}
```

**Правила Prometheus Alertmanager (`/etc/prometheus/rules/angie_image_filter_security.yml`):**

```yaml
groups:
  - name: image_filter_security_alerts
    rules:
      # Атака декомпрессионными бомбами / превышение буфера
      - alert: ImageFilterBufferOverflowSpike
        expr: sum(rate(angie_zone_responses_codes{zone="image_backend", code="415"}[2m])) > 5
        for: 1m
        labels:
          severity: critical
          service: media-pipeline
        annotations:
          summary: "Всплеск ошибок 415 (image_filter_buffer exhaustion) на {{ $labels.instance }}"
          description: "Частота ошибок 415 превышает 5 req/s. Возможна атака декомпрессионными бомбами или загрузка некорректных форматов."

      # Атака Cache Busting / отказ Rate Limiter
      - alert: ImageFilterRateLimitExceeded
        expr: sum(rate(angie_zone_responses_codes{zone="image_frontend", code="429"}[2m])) > 20
        for: 1m
        labels:
          severity: warning
          service: media-pipeline
        annotations:
          summary: "Массовое срабатывание Rate Limiting (HTTP 429) на {{ $labels.instance }}"
          description: "Более 20 запросов в секунду отбрасываются с кодом 429. Источник: аномальный трафик к image_filter."

      # Деградация задержки из-за перегрузки CPU кодеками
      - alert: ImageFilterP95LatencyDegradation
        expr: histogram_quantile(0.95, sum(rate(angie_zone_responses_time_bucket{zone="image_backend"}[5m])) by (le)) > 0.8
        for: 3m
        labels:
          severity: critical
          service: media-pipeline
        annotations:
          summary: "P95 задержка трансформации изображений > 800 мс на {{ $labels.instance }}"
          description: "Воркеры перегружены кодированием (AVIF/WebP) или заблокированы в synchronously event loop."
```

**Валидация:**
```bash
# 1. Проверка доступности метрик в формате Prometheus
curl -s http://127.0.0.1:8080/p8s | grep -E "angie_zone_responses_codes.*image"
# → angie_zone_responses_codes{code="200",zone="image_backend"} 1542
# → angie_zone_responses_codes{code="415",zone="image_backend"} 3

# 2. Запрос текущей загрузки зоны через REST API
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_backend | jq '.responses.codes'
# → { "200": 1542, "415": 3 }
```

---

## Операции и команды

### Синтаксическая валидация и аудит прав

```bash
# Тестирование синтаксиса конфигурации Angie
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка владельца и прав доступа к Unix-сокету
stat -c "%A %U:%G %n" /run/angie/image_filter.sock
# → srw-rw---- angie:angie /run/angie/image_filter.sock
```

### Тестирование защитных барьеров через CLI

```bash
# 1. Тестирование отсечения невалидного размера (белый список map)
curl -s -o /dev/null -w "%{http_code}\n" "https://img.example.com/media/test.jpg?size=999x999"
# → 400

# 2. Тестирование криптографической подписи (поддельный токен)
curl -s -o /dev/null -w "%{http_code}\n" "https://img.example.com/thumb/fake_token/1893456000/200x200/test.jpg"
# → 403

# 3. Тестирование защищенности внутреннего сокета от сетевого доступа
curl -s -o /dev/null -w "%{http_code}\n" "https://img.example.com/transform/resize/200x200/test.jpg"
# → 404

# 4. Проверка срабатывания Rate Limiting (флуд в 20 потоков)
seq 1 20 | xargs -n1 -P10 curl -s -o /dev/null -w "%{http_code}\n" "https://img.example.com/images/test.jpg" | sort | uniq -c
# → 5 200
# → 15 429
```

### Диагностика лимитов и состояния разделяемой памяти

```bash
# Просмотр статистики срабатывания Rate Limiter зон через API
curl -s http://127.0.0.1:8080/api/6/http/limit_reqs/img_avif_req | jq .
# → { "passed": 120, "delayed": 14, "rejected": 45 }

# Просмотр активных соединений в зоне limit_conn
curl -s http://127.0.0.1:8080/api/6/http/limit_conns/img_conn_limit | jq .
# → { "passed": 850, "rejected": 12 }
```

### Мониторинг системных ресурсов и изоляции процесса

```bash
# Контроль текущего расхода памяти воркерами Angie
ps -o pid,user,%cpu,%mem,rss,vsz,comm -C angie
# →   PID USER      %CPU %MEM    RSS    VSZ COMMAND
# → 14201 angie      0.0  0.2  18432 120450 angie
# → 14202 angie     18.5  1.8 148920 250100 angie

# Проверка событий троттлинга и OOM внутри cgroup v2
cat /sys/fs/cgroup/system.slice/angie.service/memory.events
# → low 0
# → high 0
# → max 0
# → oom 0
# → oom_kill 0
```

---

## Устранение неисправностей (Troubleshooting)

| Симптом | Вероятная причина | Диагностика | Регламент решения |
|:---|:---|:---|:---|
| **Массовые HTTP 415** | Размер оригинала превышает `image_filter_buffer` или поврежден заголовок файла | `curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_backend \| jq '.responses.codes."415"'` | Увеличить `image_filter_buffer` до 25M–30M, либо настроить возврат HTTP 413 / fallback на оригинал |
| **HTTP 403 Forbidden у легитимных клиентов** | Некорректно сгенерирован HMAC в `secure_link` (рассинхронизация секретного ключа или порядка аргументов) | `tail -f /var/log/angie/error.log \| grep secure_link` | Сверить порядок конкатенации строки в приложении и в `secure_link_md5`, проверить URL-safe кодирование Base64 |
| **HTTP 410 Gone** | Истекло время жизни ссылки `$secure_link_expires` (рассинхронизация времени NTP на хостах) | Проверить системное время `chronyc tracking` и текущий таймстемп `$arg_expires` | Настроить синхронизацию времени по NTP; увеличить TTL ссылки в приложении |
| **Падение воркеров (SIGKILL / OOM)** | Обработка изображения экстремального разрешения (Pixel Flood), исчерпание RAM | `dmesg -T \| grep -i "oom[-_]killer"` или `journalctl -u angie -g "killed"` | Включить `MemoryMax` в systemd; ввести ограничение габаритов в `map`/regex; уменьшить буферы |
| **P99 задержка > 2с, зависание запросов** | Head-of-Line Blocking: синхронная конвертация AVIF заблокировала все воркеры | `top -b -n 1 \| grep angie` (100% CPU на всех воркерах) | Увеличить `image_filter_avif_speed 6`; снизить `limit_req` для AVIF; разнести фронтенд и бэкенд на разные пулы |
| **Ошибки 502 Bad Gateway на фронтенде** | Внутренний Unix-сокет перегружен, переполнен `listen backlog`, либо сброшены права доступа | `ls -la /run/angie/image_filter.sock` и `netstat -xl \| grep image_filter` | Увеличить `listen unix:... backlog=2048`; проверить права `chown angie:angie` |
| **HTTP 429 Too Many Requests у пользователей** | Слишком жесткий порог `limit_req` при загрузке каталога с сотнями превью | `tail -f /var/log/angie/error.log \| grep "limiting requests"` | Увеличить параметр `burst` с добавлением директивы `delay` (двухфазный лимитер) |

---

## Лучшие практики

1. **Обязательная криптографическая авторизация параметров:**
   В любых публичных контурах используйте `secure_link` (HMAC-MD5) со сроком жизни URL (`expires`). Если подпись невозможна, используйте закрытый белый список фиксированных пресетов через `map`. Полностью исключите прием произвольных габаритов из URL.

2. **Принцип двухслойного проксирования (Double Proxying):**
   Никогда не размещайте директивы `image_filter` в публичном блоке `server`. Фронтенд должен отвечать только за неблокирующий I/O, отдачу кэша и проверку прав. Вычисления изолируйте на Unix Domain Socket с директивой `internal`.

3. **Защита от эффекта стада (Thundering Herd / Cache Stampede):**
   При инвалидации популярного оригинала сотни клиентов могут одновременно запросить один и тот же файл. Всегда настраивайте `proxy_cache_lock on;`, `proxy_cache_lock_timeout 5s;` и `proxy_cache_use_stale updating;`, чтобы только один запрос уходил на конвертацию, а остальные ожидали результата.

4. **Ограничение геометрических габаритов (Pixel Flood Defense):**
   Никогда не разрешайте трансформацию в разрешения выше $2000 \times 2000$ пикселей. Ограничивайте размер `image_filter_buffer` значением не более $20\text{--}30$ МБ.

5. **Изоляция ресурсов на уровне OS (cgroups v2):**
   Настраивайте `MemoryMax`, `MemoryHigh` и `CPUQuota` в systemd-юните Angie. Это гарантирует, что даже при успешной DoS-атаке пострадает только изолированный сервис медиа, а системные демоны (SSH, базы данных, мониторинг) продолжат функционировать.

6. **Двухфазный Rate Limiting с задержкой (delay):**
   Для улучшения UX легитимных пользователей настраивайте `limit_req` с директивой `delay`. Небольшие всплески (открытие страницы с 15 изображениями) будут обслужены с минимальной микрозадержкой без грубой отдачи ошибки 429.

7. **Регулярный аудит и обновление сторонних библиотек:**
   Уязвимости CVE в `libgd3`, `libavif` и `libwebp` появляются регулярно. Настройте автоматический мониторинг безопасности пакетов ОС (`unattended-upgrades` в Debian/Ubuntu или `dnf-automatic` в RHEL/Rocky Linux).

---

## Дополнительная информация

### Математика расхода памяти в libgd

В отличие от сжатых форматов на диске, в процессе работы `image_filter` память расходуется на трех независимых этапах:

$$\text{RAM}_{\text{total}} = \text{Buffer}_{\text{file}} + \text{Matrix}_{\text{input}} + \text{Matrix}_{\text{output}} + \text{Buffer}_{\text{codec}}$$

Где:
*   $\text{Buffer}_{\text{file}}$ — оперативная память, ограниченная директивой `image_filter_buffer` (файл в сжатом виде).
*   $\text{Matrix}_{\text{input}}$ — несжатая матрица пикселей оригинала в формате RGBA: $\text{Width}_{\text{in}} \times \text{Height}_{\text{in}} \times 4\text{ байта}$.
*   $\text{Matrix}_{\text{output}}$ — промежуточный холст результата: $\text{Width}_{\text{out}} \times \text{Height}_{\text{out}} \times 4\text{ байта}$.
*   $\text{Buffer}_{\text{codec}}$ — рабочие буферы квантования и энкодера кодека (для AVIF/WebP от 5 до 30 МБ на поток).

**Таблица расхода оперативной памяти при трансформации одного изображения:**

| Разрешение оригинала | Размер сжатого файла | Формат RGBA (`W × H × 4`) | Целевое превью | Потребление RAM воркером |
|:---|:---|:---|:---|:---|
| **$1920 \times 1080$ (Full HD)** | ~1.5 МБ | 8.3 МБ | $300 \times 300$ | ~15 МБ |
| **$3840 \times 2160$ (4K UHD)** | ~4.5 МБ | 33.2 МБ | $800 \times 600$ | ~45 МБ |
| **$7680 \times 4320$ (8K UHD)** | ~12.0 МБ | 132.7 МБ | $1200 \times 800$ | ~160 МБ |
| **$15000 \times 15000$ (Pixel Bomb)**| ~1.2 МБ (сжатый) | **900.0 МБ** | Любое | **> 950 МБ** |

Из таблицы видно, что атака декомпрессионной бомбой $15\,000 \times 15\,000$ при 4 параллельных запросах потребует 3.8 ГБ оперативной памяти, что гарантированно активирует OOM Killer при отсутствии лимитов cgroups.

### SRE Runbook: Регламент реагирования на инцидент DoS / Pixel Flood

**Триггер инцидента:**
Срабатывание алерта `ImageFilterP95LatencyDegradation` или `ImageFilterBufferOverflowSpike`, резкий рост CPU до 100%, всплеск HTTP 504 / 429.

**Шаг 1: Идентификация источника атаки**
```bash
# Топ IP-адресов, генерирующих запросы к локациям изображений за последние 2 минуты
sudo tail -n 10000 /var/log/angie/access.log | awk '$7 ~ /^\/(thumb|media|images)/ {print $1}' | sort | uniq -c | sort -nr | head -n 10
```

**Шаг 2: Временная блокировка вредоносного трафика на уровне ядра**
```bash
# Блокировка атакующего IP через nftables (нулевой оверхед на веб-сервер)
sudo nft add element inet filter blackhole { 203.0.113.50 }
```

**Шаг 3: Проверка состояния воркеров и OOM-событий**
```bash
# Проверка завершения процессов по OOM
dmesg -T | grep -E "Out of memory|oom_reaper" | tail -n 10
# Проверка загрузки среза systemd
systemd-cgtop -n 1
```

**Шаг 4: Аварийный режим деградации сервиса (Graceful Degradation)**
Если атака распределенная (DDoS) и блокировка по IP не помогает, переведите фронтенд в режим отдачи оригиналов без трансформации, сняв нагрузку с CPU:

```nginx
# Временный хотфикс в конфигурации фронтенда:
location /images/ {
    # Прямая отдача оригинала из хранилища без проксирования на image_filter
    root /var/www/images/originals;
    try_files $uri =404;
    add_header X-Emergency-Degradation "Active" always;
}
```

```bash
# Бесшовная перезагрузка конфигурации
sudo angie -t && sudo angie -s reload
```

---

### См. также

- [Обзор модуля image_filter](./overview.md) — базовые возможности и синтаксис директив.
- [Конфигурация директив фильтрации](./filter_configuration.md) — параметры качества и кодеков.
- [Масштабирование и обрезка изображений](./resize.md) — механика операций resize и crop.
- [Стратегии кэширования](./caching.md) — настройка `proxy_cache` и инвалидация.
- [Производительность и масштабирование](./performance.md) — бенчмарки и оптимизация Tail Latency.
- [Защита от DoS-атак в Angie](../dos_protection.md) — глобальная эшелонированная защита веб-сервера.
- [Безопасность systemd: Изоляция и защита сервисов](../../../../Linux/Security/Concepts/systemd_security.md) — справочник по харденингу unit-файлов и cgroups.
