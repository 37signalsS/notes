# Оптимизация сжатия в Nginx (Gzip, Brotli, Zstandard)

**Актуально для:** Nginx 1.26+ / 1.28+ (OSS) / Angie 1.6+ / 1.12.x / Linux Kernel 5.15+ / 6.x

## Определения

**HTTP-компрессия (сжатие данных)** — процесс алгоритмического сокращения объема передаваемых по сети данных на уровне представления (L6 OSI) перед их отправкой клиенту. Является ключевым инструментом в [оптимизации веб-производительности](../../Concepts/web_performance/overview.md), снижающим объем исходящего сетевого трафика на 60–85%, уменьшающим время доставки критических ресурсов и улучшающим метрики Core Web Vitals (LCP, FCP).

**Content-Encoding** — HTTP-заголовок ответа, информирующий клиентское ПО о примененном к телу ответа алгоритме сжатия. Стандартные зарегистрированные значения IANA: `gzip`, `br`, `zstd`, `deflate`, `identity` (отсутствие кодирования).

**Accept-Encoding** — HTTP-заголовок запроса, через который клиент сообщает веб-серверу перечень поддерживаемых алгоритмов декомпрессии и их приоритеты с помощью весовых коэффициентов (`q-values`): например, `Accept-Encoding: zstd, br;q=0.9, gzip;q=0.8, *;q=0.1`.

**q-value (quality factor)** — числовой весовой коэффициент предпочтительности в диапазоне от 0.0 до 1.0 в заголовке `Accept-Encoding`. Если параметр `q` не указан, по умолчанию принимается максимальный вес `1.0`.

**Vary: Accept-Encoding** — обязательный HTTP-заголовок ответа при наличии вариативного контента. Информирует промежуточные кэширующие узлы (Reverse Proxy, CDN, локальные браузерные кэши) о том, что закэшированное тело ответа жестко привязано к значению заголовка `Accept-Encoding`. Отсутствие заголовка приводит к отравлению кэша (Cache Poisoning), когда клиент без поддержки Brotli или Zstd получает бинарно сжатый поток из промежуточного кэша.

**Предварительное статическое сжатие (AOT / Pre-compression)** — процесс генерации сжатых версий статических ассетов (`.gz`, `.br`, `.zst`) на этапе CI/CD или сборки дистрибутива. Позволяет веб-серверу отдавать готовые файлы напрямую из страничного кэша ядра через системный вызов `sendfile(2)` с нулевыми затратами процессорного времени (CPU) в runtime.

**Динамическое сжатие на лету (JIT / On-the-fly)** — потоковое сжатие ответа непосредственно в процессе его генерации или передачи через конвейер фильтров Nginx. Является синхронной CPU-bound операцией в контексте рабочего процесса (worker), увеличивает Time to First Byte (TTFB) и несовместимо с механизмом Zero-Copy.

**Фильтр сжатия (Output Filter Chain)** — модуль конвейера обработки HTTP-ответа в архитектуре Nginx/Angie, перехватывающий потоковые буферы данных перед записью в сокет и выполняющий сжатие тела ответа.

**Слабый ETag (Weak ETag, `W/"..."`)** — валидатор кэша, гарантирующий семантическую эквивалентность ответа без побайтовой идентичности. При динамическом сжатии Nginx автоматически преобразует сильный ETag в слабый, чтобы сохранить работоспособность условных запросов (`If-None-Match`). При статическом сжатии сильный ETag сохраняется.

**Модуль Gunzip (`ngx_http_gunzip_module`)** — модуль Nginx, производящий декомпрессию ответов с `Content-Encoding: gzip` на лету для клиентов, не поддерживающих сжатие, если исходные ресурсы хранятся на сервере исключительно в виде архивов `.gz`.

**Zero-Copy (`sendfile`)** — механизм ядра Linux, позволяющий передавать данные из дискового страничного кэша (Page Cache) напрямую в буфер сетевого сокета без копирования в адресное пространство пользовательского процесса Nginx.

**Основные алгоритмы сжатия контента:**

*   **Gzip (DEFLATE, RFC 1952)** — универсальный стандарт на базе алгоритма LZ77 и кодирования Хаффмана с фиксированным размером скользящего окна 32 КБ. Поддерживается 100% браузеров и HTTP-клиентов. Служит обязательным базовым fallback-вариантом.
*   **Brotli (`br`, RFC 7932)** — алгоритм сжатия со статическим словарем (120 КБ часто встречающихся HTML/CSS/JS паттернов) и скользящим окном до 16 МБ. Обеспечивает на 15–25% более высокую степень сжатия текстовых ресурсов по сравнению с Gzip при сопоставимой скорости декомпрессии.
*   **Zstandard (`zstd`, RFC 8878)** — алгоритм сжатия на основе конечных автоматов с энтропией состояний (Finite State Entropy, FSE). Характеризуется экстремальной скоростью декомпрессии (1.5–2.5 ГБ/с на ядро) и высокой скоростью компрессии на низких уровнях (1–3), являясь стандартом для динамического контента и высоконагруженных API.

---

## Основные концепции

### Архитектура конвейера фильтров (Filter Chain) в Nginx

В Nginx и Angie обработка исходящего ответа построена на конвейере фильтров вывода (Output Filter Chain). Конвейер разделен на две цепочки:
1.  **Header Filters** — фильтры заголовков, определяющие метаданные ответа (MIME-тип, статус, заголовки кэширования, `Content-Encoding`, `Vary`).
2.  **Body Filters** — потоковые фильтры тела ответа, преобразующие байтовые буферы перед отправкой в сетевой сокет.

```text
[ Бэкенд (FastCGI/Proxy) или Файл ] 
               │
               ▼
   [ Header Filter Chain ]
               │  * Проверка Accept-Encoding, MIME-типа, min_length
               │  * Выбор алгоритма (zstd -> brotli -> gzip)
               │  * Установка Content-Encoding и Vary: Accept-Encoding
               ▼
    [ Body Filter Chain ]
               │  * Буферизация и сжатие чанков данных (libz / libbrotli / libzstd)
               ▼
      [ Сетевой сокет ] ──► Клиент
```

**Критический архитектурный фактор для SRE:** Динамическое сжатие является **синхронной блокирующей операцией** в цикле обработки событий (Event Loop) рабочего процесса `worker`. Если рабочий процесс занят компрессией большого динамического JSON или HTML на высоком уровне сжатия, он не может обрабатывать другие сетевые события (accept, read, write) на привязанных сокетах. Это приводит к росту задержек p99 и деградации пропускной способности (RPS).

### Сравнение статической и динамической компрессии на уровне ядра ОС

```text
[ Статическое сжатие (AOT / Pre-compressed) ]
Диск (.zst / .br / .gz) ──► Page Cache (Ядро) ──[ sendfile(2) / DMA ]──► Сетевая карта (NIC)
* User-Space Nginx не считывает тело файла; CPU загружен на 0% в контуре сжатия.

[ Динамическое сжатие (JIT / On-the-fly) ]
Диск / Upstream (RAW) ──► read(2) ──► User-Space буфер Nginx ──► CPU Compression Filter
                                                                        │
Сетевая карта (NIC) ◄──[ writev(2) / SSL_write ]── User-Space Compressed Buffer ◄─┘
* Высокая утилизация CPU; задержка TTFB возрастает; sendfile() невозможен.
```

1.  **Статическая отдача (`*_static on;`):**
    *   При запросе файла `app.js` Nginx проверяет наличие на диске файлов `app.js.zst`, `app.js.br` или `app.js.gz`.
    *   Если сжатый файл найден и поддерживается клиентом, Nginx открывает его дескриптор и передает в сеть через системный вызов `sendfile(2)`.
    *   Ядро Linux передает страницы из Page Cache напрямую в кольцевой буфер сетевого адаптера (TX Ring) через Direct Memory Access (DMA).
    *   В связке с `tcp_nopush on;` заголовки HTTP и начало архивного файла упаковываются в один TCP-пакет, минимизируя накладные расходы протокола.
    *   При использовании **kTLS (Kernel TLS)** ядро производит симметричное шифрование прямо в канале DMA, сохраняя Zero-Copy.
2.  **Динамическая отдача (`gzip on;`, `brotli on;`, `zstd on;`):**
    *   Nginx обязан вычитать ответ в память пользовательского пространства (user-space), пропустить через библиотеку сжатия и записать результат обратно в сокет через `writev()` или OpenSSL.
    *   Системный вызов `sendfile()` и kTLS в этом сценарии неприменимы.

### Согласование контента (Content Negotiation) и приоритет алгоритмов

Когда современный браузер отправляет заголовок:
```http
Accept-Encoding: gzip, deflate, br, zstd
```
Nginx определяет алгоритм на основании порядка фильтров, скомпилированных в бинарный файл, либо порядка директив `load_module`. В стандартной сборке Angie и Nginx с модулями приоритет фильтрации выглядит следующим образом:
1.  **Zstandard (`zstd`)** — наивысший приоритет (если модуль загружен и активен).
2.  **Brotli (`br`)** — второй приоритет.
3.  **Gzip (`gzip`)** — базовый fallback-приоритет.

Если клиент передает явные веса (`q-values`), например `Accept-Encoding: gzip;q=1.0, br;q=0.8`, Nginx отдает предпочтение алгоритму с более высоким `q`.

### Взаимодействие компрессии с кэшированием (Proxy Cache)

При проксировании запросов к бэкендам (Node.js, Go, Python, PHP-FPM) через `proxy_pass` архитектура сжатия требует соблюдения правил:

1.  **Отключение сжатия на апстриме:**
    По умолчанию Nginx сбрасывает клиентский заголовок `Accept-Encoding` при отправке запроса на бэкенд (`proxy_set_header Accept-Encoding "";`). Это сделано намеренно: бэкенд отдает несжатый ответ, Nginx сохраняет его в `proxy_cache` в несжатом виде, а затем динамически сжимает ответ для каждого клиента в соответствии с его персональным `Accept-Encoding`.
2.  **Риск отравления кэша при сжатии на апстриме:**
    Если бэкенд сам возвращает сжатый gzip-ответ, а Nginx кэширует его без учета кодировки в `proxy_cache_key`, клиент без поддержки gzip получит бинарные данные. Для предотвращения этого в ключ кэша необходимо включать кодировку:
    ```nginx
    proxy_cache_key "$scheme$request_method$host$request_uri$http_accept_encoding";
    ```
    Однако это снижает эффективность кэша (Cache Hit Ratio). Рекомендуемый SRE-паттерн: **кэшировать на прокси несжатые данные, сжимать на отдаче**.

### Безопасность: атаки BREACH, CRIME и HEIST

*   **CRIME (CVE-2012-4929):** Эксплуатировала компрессию на уровне TLS/SPDY. В современных версиях Nginx компрессия TLS отключена по умолчанию и не поддерживается в TLS 1.3.
*   **BREACH (CVE-2013-3587):** Атака по побочному каналу размера HTTP-ответа. Если страница одновременно содержит:
    1. Отраженные пользовательские входные данные (отраженный XSS, параметры поискового запроса).
    2. Секретные токены (CSRF-токены, токены авторизации, персональные данные).
    3. Включенное HTTP-сжатие (Gzip/Brotli/Zstd) по HTTPS.
    
    Злоумышленник может инжектировать догадки по символам в параметры запроса и по изменению размера сжатого ответа восстановить секретный токен.
*   **Защита на уровне веб-сервера:**
    Отключение сжатия в `location`, отдающих авторизованные ответы с CSRF-токенами и чувствительными данными (`gzip off; brotli off; zstd off;`), либо применение маскирования токенов на уровне приложения.

---

## Практические сценарии

### Предварительные требования: проверка и загрузка модулей

Проверьте поддержку модулей компрессии в установленном бинарном файле Nginx или Angie:

```bash
nginx -V 2>&1 | grep -oE -- '--with-http_gzip_static_module|--with-http_gunzip_module|ngx_brotli|zstd'
# → --with-http_gzip_static_module
# → --with-http_gunzip_module
```

Для Angie или Nginx с динамическими модулями подключите библиотеки в глобальном контексте `/etc/nginx/nginx.conf` (до секции `events` и `http`):

```nginx
# /etc/nginx/nginx.conf

# Подключение динамических модулей Brotli и Zstandard (Angie / Nginx OSS)
load_module modules/ngx_http_brotli_filter_module.so;
load_module modules/ngx_http_brotli_static_module.so;
load_module modules/ngx_http_zstd_filter_module.so;
load_module modules/ngx_http_zstd_static_module.so;

events {
    worker_connections 10240;
    use epoll;
    multi_accept on;
}
```

---

### Сценарий 1: Базовая оптимизация Gzip (встроенный модуль Nginx)

Конфигурация для секции `http` или конкретного `server`. Обеспечивает сжатие для всех клиентов, включая устаревшие системы.

```nginx
# /etc/nginx/conf.d/gzip.conf

http {
    # Включение динамического сжатия Gzip
    gzip on;

    # Уровень сжатия: 4 — оптимальный баланс CPU и экономии трафика для динамики.
    # Уровни 7–9 дают выигрыш в размере <2%, но утилизируют CPU в 3–5 раз сильнее.
    gzip_comp_level 4;

    # Минимальный размер ответа для сжатия (байты).
    # Сжатие ответов меньше 1024 байт неэффективно: накладные расходы заголовков 
    # gzip могут превысить исходный размер файла.
    gzip_min_length 1024;

    # Разрешить сжатие для ответов, проксированных через внешние балансировщики.
    # По умолчанию 'off'. Значение 'any' сжимает ответы независимо от заголовка Via.
    gzip_proxied any;

    # Добавление заголовка Vary: Accept-Encoding для защиты промежуточных кэшей
    gzip_vary on;

    # Минимальная версия HTTP-протокола для сжатия
    gzip_http_version 1.1;

    # Буферы сжатия: 16 страниц памяти по 8 КБ (для x86_64)
    gzip_buffers 16 8k;

    # MIME-типы для сжатия.
    # ВНИМАНИЕ: text/html сжимается ВСЕГДА, его указывать в директиве не требуется.
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/javascript
        application/json
        application/xml
        application/xml+rss
        application/manifest+json
        application/x-font-ttf
        font/opentype
        image/svg+xml
        image/x-icon;
}
```

---

### Сценарий 2: Комплексная конфигурация Brotli и Zstandard

Конфигурация сочетает Zstd для динамических API/HTML и Brotli для статических и динамических текстовых файлов.

```nginx
# /etc/nginx/conf.d/modern_compression.conf

http {
    # ----------------------------------------------------
    # Настройки Zstandard (ngx_http_zstd_module)
    # ----------------------------------------------------
    zstd on;
    # Уровень 3 — baseline для динамики (быстрее gzip 4 при лучшей степени сжатия)
    zstd_comp_level 3;
    zstd_min_length 256;
    zstd_vary on;
    zstd_buffers 16 8k;
    zstd_types
        text/plain
        text/css
        application/javascript
        application/json
        application/xml
        image/svg+xml;

    # ----------------------------------------------------
    # Настройки Brotli (ngx_brotli)
    # ----------------------------------------------------
    brotli on;
    # Уровень 4 — оптимален для динамического контента на лету.
    # Уровень 11 категорически запрещен для динамики (вызывает 100% CPU lock)!
    brotli_comp_level 4;
    brotli_min_length 256;
    brotli_window 16m;
    brotli_buffers 16 8k;
    brotli_types
        text/plain
        text/css
        application/javascript
        application/json
        application/xml
        image/svg+xml;

    # Gzip как обязательный fallback-уровень
    gzip on;
    gzip_comp_level 4;
    gzip_min_length 1024;
    gzip_vary on;
    gzip_proxied any;
    gzip_types
        text/plain
        text/css
        application/javascript
        application/json
        application/xml
        image/svg+xml;
}
```

---

### Сценарий 3: Высокопроизводительная раздача статики (AOT Pre-compression + Zero-Copy)

В этом сценарии веб-сервер вообще не тратит процессорные циклы на сжатие в момент запроса. Если клиент поддерживает `zstd`, `br` или `gzip`, Nginx напрямую считывает предварительно сжатый файл с диска и отправляет его клиенту через системный вызов `sendfile(2)`.

> [!IMPORTANT]
> Модули `gzip_static`, `brotli_static` и `zstd_static` работают прозрачно через встроенный обработчик статических файлов Nginx (`ngx_http_static_module`). **Никогда не используйте псевдо-переменные вроде `$uri$gzip_suffix` в директиве `try_files`!** Nginx автоматически выполняет поиск файла с соответствующим суффиксом (`.zst`, `.br`, `.gz`), сохраняет оригинальный заголовок `Content-Type` и добавляет нужный `Content-Encoding`.

```nginx
# /etc/nginx/conf.d/static_vhost.conf

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    http2 on;
    server_name static.example.com;

    root /var/www/static/dist;

    # Включение Zero-Copy и оптимизация сетевых буферов
    sendfile on;
    sendfile_max_chunk 512k;
    tcp_nopush on;
    tcp_nodelay on;

    # Кэширование файловых дескрипторов в памяти воркера для исключения stat-storm
    open_file_cache max=50000 inactive=60s;
    open_file_cache_valid 30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # Обработка неизменяемых статических ассетов (JS, CSS, SVG, шрифты)
    location ~* \.(?:css|js|svg|ttf|otf|eot)$ {
        # Заголовки долгосрочного кэширования для версионированных файлов
        expires 1y;
        add_header Cache-Control "public, immutable";
        add_header Vary "Accept-Encoding";

        # Включение отдачи предварительно сжатых файлов из CI/CD
        zstd_static on;
        brotli_static on;
        gzip_static on;

        # Если на диске нет ни одного сжатого файла, разрешаем динамическое сжатие:
        zstd on;
        brotli on;
        gzip on;

        try_files $uri =404;
    }
}
```

---

### Сценарий 4: Reverse Proxy с декомпрессией Gunzip для legacy-клиентов

Если в хранилище статики или на объектном хранилище файлы хранятся **исключительно** в сжатом виде `.gz` для экономии дискового пространства (`gzip_static always;`), клиенты без поддержки Gzip (старые IoT-устройства, специфические сканеры, утилиты мониторинга) не смогут прочитать контент. Модуль `gunzip` прозрачно распаковывает архив на лету.

```nginx
# /etc/nginx/conf.d/storage_proxy.conf

server {
    listen 80;
    server_name archive.internal.net;
    root /data/precompressed_storage;

    location /packages/ {
        # Всегда отдавать .gz файл, если он есть на диске
        gzip_static always;

        # Если у клиента в запросе отсутствует Accept-Encoding: gzip,
        # Nginx самостоятельно распакует .gz на лету и отдаст чистый поток
        gunzip on;
        gunzip_buffers 16 8k;

        add_header Cache-Control "private, no-transform";
    }
}
```

---

### Сценарий 5: Сегментация и защита от BREACH (отключение сжатия для чувствительных эндпоинтов)

Для предотвращения атак типа BREACH на страницы с секретными токенами сессий и CSRF-ключами компрессия избирательно выключается на уровне конкретных `location`.

```nginx
# /etc/nginx/conf.d/secure_app.conf

server {
    listen 443 ssl;
    server_name app.example.com;

    # Общие настройки сжатия для публичного контента
    gzip on;
    gzip_comp_level 4;
    gzip_types text/plain text/css application/javascript application/json;

    # Статика приложения — безопасна, сжимаем с максимальной эффективностью
    location /static/ {
        root /var/www/app;
        gzip_static on;
        brotli_static on;
        try_files $uri =404;
    }

    # API и авторизованные страницы с CSRF-токенами: СЖАТИЕ ОТКЛЮЧЕНО
    location ~* ^/(auth|login|api/v1/user/checkout|admin) {
        # Защита от BREACH: отключаем все механизмы компрессии
        gzip off;
        brotli off;
        zstd off;

        proxy_pass http://backend_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Запрещаем кэширование чувствительных данных
        add_header Cache-Control "no-store, no-cache, must-revalidate, private" always;
    }

    location / {
        proxy_pass http://backend_upstream;
        proxy_set_header Host $host;
        proxy_set_header Accept-Encoding ""; # Бэкенд отдает сырые данные, Nginx сжимает
    }
}
```

---

## Операции и команды

### CLI-инструменты пакетного сжатия в CI/CD (DevOps)

Для генерации файлов `.gz`, `.br`, `.zst` на этапе сборки фронтенда используются системные консольные утилиты:

| Утилита | Алгоритм | Оптимальные флаги для AOT статики | Потоки (Threads) | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| `pigz` | Gzip (DEFLATE) | `pigz -k -9 -f` | Многопоточный (`-p N`) | В 4–8 раз быстрее стандартного `gzip` |
| `gzip` | Gzip (DEFLATE) | `gzip -k -9 -f` | 1 поток | Стандартный POSIX fallback |
| `brotli` | Brotli | `brotli -k -q 11 -f` | 1 поток | Наивысшая степень сжатия статики |
| `zstd` | Zstandard | `zstd -k -19 -T0 -f` | Многопоточный (`-T0` — все ядра) | Максимальное сжатие для Zstd-клиентов |

> [!WARNING]
> **Синхронизация mtime:** Директива `gzip_static on;` проверяет время модификации (mtime) файла. Если `.gz` файл имеет mtime **старше**, чем исходный распакованный файл, Nginx сочтет сжатый файл устаревшим и проигнорирует его! При пакетной генерации в CI/CD всегда сохраняйте или синхронизируйте mtime через `touch -r`.

#### Bash-скрипт пакетной прекомпрессии для CI/CD пайплайнов

Скрипт выполняет параллельное сжатие артефактов в три формата с сохранением исходных файлов и синхронизацией mtime:

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-dist}"

echo "Запуск AOT прекомпрессии для каталога: ${TARGET_DIR}"

# Поиск всех текстовых ресурсов крупнее 256 байт
find "${TARGET_DIR}" -type f \( \
    -name "*.js" -o \
    -name "*.css" -o \
    -name "*.html" -o \
    -name "*.svg" -o \
    -name "*.json" -o \
    -name "*.xml" \
\) -size +256c | while read -r file; do
    # 1. Gzip через многопоточный pigz
    if command -v pigz >/dev/null 2>&1; then
        pigz -k -9 -f "$file"
    else
        gzip -k -9 -f "$file"
    fi

    # 2. Brotli на максимальном уровне качества 11
    if command -v brotli >/dev/null 2>&1; then
        brotli -k -q 11 -f "$file"
    fi

    # 3. Zstandard на уровне 19 с использованием всех доступных ядер CPU
    if command -v zstd >/dev/null 2>&1; then
        zstd -k -19 -T0 -q -f "$file"
    fi

    # 4. Критически важно: синхронизация mtime архивов с оригиналом
    [[ -f "${file}.gz" ]]  && touch -r "$file" "${file}.gz"
    [[ -f "${file}.br" ]]  && touch -r "$file" "${file}.br"
    [[ -f "${file}.zst" ]] && touch -r "$file" "${file}.zst"
done

echo "Прекомпрессия успешно завершена."
```

---

### Валидация заголовков и проверка эффективности компрессии

Проверка отдачи соответствующих алгоритмов с помощью `curl`:

```bash
# 1. Проверка поддержки Zstandard
curl -sI -H "Accept-Encoding: zstd, br, gzip" https://example.com/assets/app.js | grep -iE 'content-encoding|vary|etag'
# → content-encoding: zstd
# → vary: Accept-Encoding
# → etag: "66f4a8b2-4521"

# 2. Проверка отдачи Brotli
curl -sI -H "Accept-Encoding: br, gzip" https://example.com/assets/app.js | grep -iE 'content-encoding|vary'
# → content-encoding: br
# → vary: Accept-Encoding

# 3. Проверка отдачи Gzip (fallback)
curl -sI -H "Accept-Encoding: gzip" https://example.com/assets/app.js | grep -iE 'content-encoding|vary'
# → content-encoding: gzip
# → vary: Accept-Encoding

# 4. Проверка клиента без сжатия (запрос сырого контента)
curl -sI https://example.com/assets/app.js | grep -iE 'content-encoding|content-length'
# → content-length: 124580

# 5. Проверка отсечки по gzip_min_length (маленький файл не должен сжиматься)
curl -sI -H "Accept-Encoding: gzip" https://example.com/favicon.ico | grep -i 'content-encoding'
# → (пустой вывод, Content-Encoding отсутствует)
```

---

### Наблюдаемость и мониторинг метрик компрессии (SRE)

#### 1. Логирование коэффициента сжатия в `access_log`

Nginx предоставляет встроенную переменную `$gzip_ratio`, которая содержит коэффициент сжатия для ответа (например, `3.85`). Настройте специальный формат лога в `nginx.conf`:

```nginx
# /etc/nginx/nginx.conf

http {
    log_format compression_metrics escape=json
        '{'
        '"time_local":"$time_iso8601",'
        '"remote_addr":"$remote_addr",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"accept_encoding":"$http_accept_encoding",'
        '"content_encoding":"$sent_http_content_encoding",'
        '"gzip_ratio":"$gzip_ratio"'
        '}';

    access_log /var/log/nginx/compression_access.log compression_metrics;
}
```

#### 2. Анализ эффективности сжатия через консоль

Расчет среднего коэффициента сжатия и распределения кодировок по логам Nginx:

```bash
# Расчет распределения используемых алгоритмов сжатия
awk -F'"content_encoding":' '{print $2}' /var/log/nginx/compression_access.log \
  | awk -F'[,"]' '{print ($2 == "" ? "identity (none)" : $2)}' \
  | sort | uniq -c | sort -nr
# → 14520 zstd
# →  8940 br
# →  3100 gzip
# →   450 identity (none)

# Расчет среднего коэффициента сжатия для Gzip ответов
grep -oE '"gzip_ratio":"[0-9\.]+"' /var/log/nginx/compression_access.log \
  | awk -F'"' '{sum += $4; count++} END {if (count > 0) print "Средний gzip_ratio:", sum/count; else print "Нет данных"}'
# → Средний gzip_ratio: 4.12
```

#### 3. Мониторинг утилизации CPU воркерами Nginx

Для выявления перегрузки процессора из-за завышенных уровней динамической компрессии:

```bash
# Мониторинг воркеров Nginx в реальном времени
top -b -n 1 -p $(pgrep -d',' -f "nginx: worker")
# → PID  USER  PR  NI  VIRT   RES   SHR S  %CPU  %MEM   TIME+  COMMAND
# → 1042 nginx 20   0  182M  45M  12M R  98.4   0.3  12:44.20 nginx

# Профилирование функций компрессии в ядре и user-space процесса
perf top -p $(pgrep -n -f "nginx: worker")
# При проблемной динамической компрессии в топе будут: deflate, zlib_*, BrotliEncoderCompressStream
```

#### 4. Нагрузочное тестирование влияния компрессии на RPS и Latency

Сравнение производительности с помощью `wrk` при динамическом сжатии и при раздаче прекомпрессированной статики:

```bash
# Тест 1: Запрос со сжатием
wrk -t4 -c100 -d30s -H "Accept-Encoding: gzip, br, zstd" https://example.com/api/data
# → Running 30s test @ https://example.com/api/data
# →   4 threads and 100 connections
# →   Thread Stats   Avg      Stdev     Max   +/- Stdev
# →     Latency     8.45ms    2.10ms  45.12ms   88.20%
# →     Req/Sec     2.95k   320.10     3.80k    72.50%
# →   352400 requests in 30.05s, 142.10MB read
# → Requests/sec:  11727.12
# → Transfer/sec:      4.73MB

# Тест 2: Запрос без сжатия (проверка пропускной способности сети vs CPU)
wrk -t4 -c100 -d30s https://example.com/api/data
# → Requests/sec:  18450.40
# → Transfer/sec:     28.40MB
```

---

## Устранение неполадок

### Сводная таблица типичных инцидентов

| Симптом | Вероятная причина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| Отсутствует `Content-Encoding` в ответе | Размер файла < `gzip_min_length` или MIME-тип не в `*_types` | `curl -sI -H "Accept-Encoding: gzip" URL` | Сверить `Content-Type` ответа со списком в `gzip_types`; уменьшить `gzip_min_length` |
| `Content-Encoding` пропадает за балансировщиком | Запрос идет с заголовком `Via`, а `gzip_proxied` в значении `off` | `curl -sI -H "Via: 1.1 proxy" -H "Accept-Encoding: gzip" URL` | Указать `gzip_proxied any;` в `nginx.conf` |
| Условные запросы возвращают `200 OK` вместо `304 Not Modified` | Динамическое сжатие превращает сильный ETag в слабый `W/"..."` | `curl -sI URL \| grep -i etag` | Перевести раздачу статики на прекомпрессию (`gzip_static on; brotli_static on;`) |
| Директива `gzip_static on` не отдает существующий `.gz` | Время модификации (mtime) архива `.gz` старше оригинального файла | `ls -l --time-style=full-iso file file.gz` | Синхронизировать mtime: `touch -r file file.gz` |
| 100% CPU воркеров при низком RPS | Завышен уровень сжатия динамического контента (`brotli_comp_level 11` или `gzip_comp_level 9`) | `top`, `perf top` | Снизить уровень динамического сжатия: Brotli до 4, Gzip до 4, Zstd до 3 |
| Ошибка конфигурации `unknown directive "zstd"` или `"brotli"` | Модуль не загружен директивой `load_module` | `nginx -t` | Добавить `load_module modules/ngx_http_zstd_filter_module.so;` в начало `nginx.conf` |
| Клиенты получают нечитаемый бинарный мусор | Отсутствует `Vary: Accept-Encoding`, кэш отдал сжатые данные клиенту без сжатия | `curl -sI URL \| grep -i vary` | Добавить `gzip_vary on;`, `brotli_vary on;`, `zstd_vary on;` |
| Буферизация и задержка передачи SSE / WebSocket | Динамический gzip буферизует бесконечный потоковый ответ | `curl -N -H "Accept-Encoding: gzip" URL/events` | Отключить сжатие для SSE-эндпоинтов (`gzip off; proxy_buffering off;`) |

---

### Подробный разбор диагностических кейсов

#### Кейс 1: Рассинхронизация mtime при отдаче предварительно сжатых файлов

**Симптомы:** В каталоге присутствуют файлы `bundle.js` и `bundle.js.gz`. В конфигурации указано `gzip_static on;`, однако `curl -H "Accept-Encoding: gzip"` возвращает несжатый файл или вызывает динамическое сжатие со слабым ETag.

**Причина:** Согласно исходному коду модуля `ngx_http_gzip_static_module`, Nginx сравнивает время последней модификации (st_mtime) оригинального файла и файла архива:
```c
/* ngx_http_gzip_static_module.c */
if (of.fs_mtime < sb.st_mtime) {
    /* Если архив старше исходника, архив считается невалидным */
    return NGX_DECLINED;
}
```
Если сборщик фронтенда перезаписал `bundle.js`, но сохранил старый `bundle.js.gz`, Nginx отклоняет архив.

**Диагностика:**
```bash
stat -c "%n: mtime %y (%Y)" /var/www/static/dist/bundle.js*
# → bundle.js:    mtime 2026-10-16 10:00:00 (1760608800)
# → bundle.js.gz: mtime 2026-10-16 09:55:00 (1760608500)
# Архив старше оригинала на 300 секунд!
```

**Решение:** Выполнить синхронизацию временных меток в сборочном конвейере:
```bash
touch -r /var/www/static/dist/bundle.js /var/www/static/dist/bundle.js.gz
```

---

#### Кейс 2: Превращение сильного ETag в слабый при динамической компрессии

**Симптомы:** Клиент передает `If-None-Match: "66f4a8b2-4521"`, но сервер вместо статуса `304 Not Modified` возвращает полный ответ `200 OK`, что увеличивает трафик и нагрузку на сервер.

**Причина:** При динамическом сжатии Nginx преобразует сильный ETag `ETag: "66f4a8b2-4521"` в слабый `ETag: W/"66f4a8b2-4521"`, так как байтовое представление сжатого потока не равно исходному файлу на диске.

**Диагностика:**
```bash
curl -sI -H "Accept-Encoding: gzip" https://example.com/style.css | grep -i etag
# → etag: W/"66f4a8b2-4521"
```

**Решение:**
1. Для статических файлов включить AOT прекомпрессию (`gzip_static on; brotli_static on;`). При статической прекомпрессии Nginx читает файл `.gz` напрямую и сохраняет сильный валидатор ETag.
2. Убедиться, что клиент и промежуточные узлы корректно обрабатывают слабые валидаторы в заголовке `If-None-Match`.

---

#### Кейс 3: Зависание Server-Sent Events (SSE) из-за буферизации сжатия

**Симптомы:** При подключении к эндпоинту потоковых событий `/api/stream` события поступают не мгновенно, а пачками по 4–8 КБ либо с задержкой в несколько десятков секунд.

**Причина:** Фильтр сжатия Nginx собирает данные в буфер (`gzip_buffers`), ожидая заполнения страницы памяти перед применением алгоритма компрессии.

**Решение:** Полностью отключить сжатие и буферизацию для потоковых эндпоинтов:
```nginx
location /api/stream {
    proxy_pass http://backend_stream;
    
    # Отключение компрессии для потока
    gzip off;
    brotli off;
    zstd off;

    # Отключение буферизации прокси
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
}
```

---

## Лучшие практики

### Матрица стратегии компрессии по типам контента

| Категория контента | MIME-типы | Режим сжатия | Рекомендуемый алгоритм и уровень |
| :--- | :--- | :--- | :--- |
| **Сборки скриптов и стилей** | `application/javascript`, `text/css` | AOT Pre-compression (CI/CD) | Brotli 11 + Zstd 19 + Gzip 9 |
| **Векторная графика и шрифты** | `image/svg+xml`, `application/x-font-ttf` | AOT Pre-compression (CI/CD) | Brotli 11 + Gzip 9 |
| **Динамический HTML / SSR** | `text/html` | Динамический (JIT) | Zstandard 3 → Brotli 4 → Gzip 4 |
| **REST / gRPC / JSON API** | `application/json`, `application/xml` | Динамический (JIT) | Zstandard 3 → Gzip 4 |
| **Растровая графика** | `image/jpeg`, `image/png`, `image/webp`, `image/avif` | **НЕ СЖИМАТЬ В NGINX** | Исключить из `*_types` (данные уже сжаты энтропийными кодеками) |
| **Медиафайлы и архивы** | `video/*`, `audio/*`, `application/zip`, `application/gzip` | **НЕ СЖИМАТЬ В NGINX** | Исключить из `*_types` |

---

### Архитектурный чек-лист для DevOps и SRE

1.  **Статика — только через Pre-compression:** Никогда не сжимайте тяжелые библиотеки (`bundle.js`, `vendor.css`) на лету в runtime. Компилируйте `.gz`, `.br` и `.zst` на этапе CI/CD сборки контейнера или артефакта.
2.  **Задействуйте Zero-Copy:** Всегда используйте связку директив:
    ```nginx
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    ```
    Это обеспечивает передачу предварительно сжатых файлов из Page Cache в сетевой интерфейс без участия user-space.
3.  **Защита Page Cache через `open_file_cache`:** При использовании `gzip_static` и `brotli_static` веб-сервер проверяет наличие нескольких файлов на диске на каждый запрос. Настройте `open_file_cache` (минимум на 10 000 дескрипторов), чтобы исключить лавину системных вызовов `stat(2)` (stat-storm).
4.  **Уровни динамического сжатия:**
    *   `gzip_comp_level`: не выше **4–5**. Уровни 7–9 утилизируют CPU на 250–400% сильнее ради экономии 1–1.5% байт.
    *   `brotli_comp_level`: не выше **4–5** для динамики. Уровень 11 предназначен исключительно для офлайн-сборки в CI/CD.
    *   `zstd_comp_level`: уровень **3** является идеальным стандартом де-факто для динамического контента.
5.  **Обязательное присутствие `Vary: Accept-Encoding`:** Всегда включайте директивы `gzip_vary on;`, `brotli_vary on;`, `zstd_vary on;` во избежание отравления кэшей промежуточных прокси и CDN.
6.  **Исключение чувствительных эндпоинтов (BREACH mitigation):** Отключайте сжатие (`gzip off; brotli off; zstd off;`) на эндпоинтах авторизации, личных кабинетов и платежных шлюзов, возвращающих секретные токены.

---

## Дополнительная информация

### Сравнительные характеристики алгоритмов сжатия

| Характеристика | Gzip (DEFLATE) | Brotli (`br`) | Zstandard (`zstd`) |
| :--- | :--- | :--- | :--- |
| **Основа алгоритма** | LZ77 + Кодирование Хаффмана | LZ77 + Статический словарь + Huffman | Finite State Entropy (FSE) + Huff0 |
| **Размер скользящего окна** | 32 КБ | До 16 МБ | От 32 КБ до нескольких ГБ |
| **Степень сжатия статики** | Базовая (эталон) | **Наивысшая (+15–25% к Gzip)** | Высокая (+10–18% к Gzip) |
| **Скорость динамического сжатия** | Средняя (20–40 МБ/с на ядро) | Низкая на q>6 (10–15 МБ/с) | **Экстремальная (150–300 МБ/с на ур. 3)** |
| **Скорость декомпрессии** | Высокая (250–350 МБ/с) | Высокая (250–400 МБ/с) | **Рекордная (1200–2500 МБ/с на ядро)** |
| **Поддержка в браузерах** | 100% клиентов | Chrome 50+, FF 44+, Safari 11+ | Chrome 123+, Firefox 126+, Edge 123+ |
| **Рекомендуемая сфера** | Fallback для legacy | **AOT статика (JS, CSS, шрифты)** | **Динамика (HTML, JSON API, gRPC)** |

---

### Официальные стандарты и RFC

*   [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110) — стандарты согласования контента (раздел 12.5.1 `Accept-Encoding`, раздел 12.5.5 `Vary`).
*   [RFC 1952: GZIP File Format Specification](https://www.rfc-editor.org/rfc/rfc1952) — спецификация формата и заголовков Gzip/DEFLATE.
*   [RFC 7932: Brotli Compressed Data Format](https://www.rfc-editor.org/rfc/rfc7932) — алгоритм сжатия Brotli и статический предопределенный словарь.
*   [RFC 8878: Zstandard Compression and the 'application/zstd' Media Type](https://www.rfc-editor.org/rfc/rfc8878) — спецификация формата Zstandard.
*   [RFC 9842: Compression Dictionary Transport](https://www.rfc-editor.org/rfc/rfc9842) — спецификация использования внешних предзагруженных словарей через HTTP.

---

### Связанные темы в базе знаний

*   [Тюнинг производительности Nginx](nginx_performance_tuning.md) — системная оптимизация ядра Linux, `sendfile`, `tcp_nopush` и kTLS.
*   [Адаптивная доставка изображений в Nginx](nginx_adaptive_content.md) — оптимизация форматов медиаконтента (AVIF, WebP) и согласование заголовка `Accept`.
*   [Отдача статических файлов в Nginx](../Core/Location/serving_files.md) — параметры директив `root`, `alias`, `open_file_cache` и отдачи ассетов.
*   [Кэширование в Nginx и Angie: Обзор и концепции](./Caching/overview.md) — взаимодействие компрессии с хранилищем `proxy_cache`.
*   [Клиентское кэширование в Nginx](./Caching/client_caching.md) — управление заголовками `Cache-Control`, `Expires`, валидаторами ETag и `Vary`.
*   [Концепция серверной компрессии контента](../../Concepts/web_performance/server_compression.md) — архитектурные принципы и сравнительный анализ серверов.
*   [Обзор веб-сервера Angie](../../Angie/angie_overview.md) — нативные модули Zstandard и Brotli в Angie.
