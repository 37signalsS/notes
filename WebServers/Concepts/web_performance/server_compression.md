# Компрессия контента на веб-сервере

**Актуально для:** HTTP/1.1–HTTP/3 (RFC 9110, RFC 9114, RFC 9842) / Linux Kernel 5.15+ / 6.x / Nginx 1.26+, Angie 1.8+ / 1.12.x, Envoy 1.30+ / Apache 2.4.60+

## Определения

**Компрессия (сжатие) контента** — процесс уменьшения объема передаваемых данных (преимущественно текстовых или структурированных бинарных) перед их отправкой клиенту по сети. В модели [OSI относится к уровню представления (L6)](../../../Networking/OSI_TCP_IP_Model/presentation_layer.md). Это фундаментальный метод оптимизации [веб-производительности](./overview.md), позволяющий сократить объем исходящего сетевого трафика на 60–90%, снизить задержку передачи полезной нагрузки и улучшить пользовательские метрики LCP (Largest Contentful Paint) и FCP (First Contentful Paint).

**Content-Encoding** — заголовок HTTP-ответа, указывающий конкретный алгоритм сжатия, примененный к телу сообщения. Стандартные значения IANA: `gzip`, `br`, `zstd`, `deflate`, `identity` (отсутствие кодирования). При использовании словарей: `dcb`, `dcz`.

**Accept-Encoding** — заголовок HTTP-запроса, через который клиент объявляет поддерживаемые алгоритмы декомпрессии и их приоритеты посредством весовых коэффициентов (`q-values`): например, `Accept-Encoding: zstd, br;q=0.9, gzip;q=0.8, *;q=0.1`.

**q-value (quality factor)** — относительный весовой коэффициент предпочтительности в диапазоне от 0.0 до 1.0 в заголовке `Accept-Encoding`. Если параметр `q` опущен, по умолчанию принимается значение `1.0`.

**Vary: Accept-Encoding** — обязательный заголовок ответа сервера при наличии альтернативных представлений ресурса. Информирует промежуточные кэширующие узлы (Reverse Proxy, локальные корпоративные шлюзы, браузерный кэш), что кэшируемый ответ жестко привязан к значению заголовка `Accept-Encoding` клиента. Отсутствие этого заголовка приводит к отравлению кэша (Cache Poisoning), когда клиент без поддержки Brotli или Zstd получает бинарно сжатый поток из кэша.

**Предварительное сжатие (pre-compression / static compression)** — процесс генерации сжатых версий статических ассетов (`.gz`, `.br`, `.zst`) на этапе CI/CD или подготовки дистрибутива. Позволяет веб-серверу отдавать готовые файлы напрямую из страничного кэша ядра через системный вызов `sendfile(2)` с нулевыми затратами процессорного времени в runtime.

**Фильтр сжатия (compression filter)** — модуль конвейера обработки HTTP-запросов веб-сервера (Output Filter), перехватывающий потоковые данные ответа перед их передачей в сетевой сокет и выполняющий динамическое сжатие «на лету».

**Уровень сжатия (compression level)** — параметр алгоритма, определяющий баланс между степенью сжатия (размером выхода) и вычислительными затратами процессора (CPU time, RAM window). Экстремальные уровни сжатия нелинейно увеличивают нагрузку на CPU при минимальном дополнительном выигрыше в размере.

**Compression Dictionary Transport (RFC 9842)** — стандарт IETF для контекстного сжатия по протоколу HTTP с использованием внешних словарей (Shared Dictionaries). Клиент сообщает о наличии сохраненного словаря через заголовок `Available-Dictionary`, а сервер передает только дельту изменений, закодированную алгоритмами `dcb` (Dictionary-Compressed Brotli) или `dcz` (Dictionary-Compressed Zstandard).

**Слабый ETag (Weak ETag, `W/"..."`)** — валидатор кэша, гарантирующий семантическую эквивалентность ответа без побайтовой идентичности. При динамическом сжатии Nginx/Angie автоматически преобразует сильный ETag в слабый, чтобы сохранить возможность условных запросов (`If-None-Match`).

**QPACK / HPACK** — специализированные протокольные алгоритмы сжатия HTTP-заголовков для HTTP/3 (RFC 9204) и HTTP/2 (RFC 7541). В отличие от сжатия тела ресурса (`Content-Encoding`), QPACK и HPACK работают на транспортном уровне протокола и используют статические и динамические таблицы для устранения избыточности метаданных.

**Zero-Copy и `sendfile(2)`** — механизм ядра Linux, позволяющий пересылать данные из дискового кэша напрямую в сетевой интерфейс без копирования в адресное пространство процесса (user-space). Совместим со статическим сжатием и принципиально несовместим с динамическим сжатием на лету.

**Основные алгоритмы сжатия контента:**

- **Gzip:** алгоритм на базе стандарта DEFLATE (LZ77 + Кодирование Хаффмана, RFC 1952). Скользящее окно фиксировано размером 32 КБ. Используется как общепринятый универсальный fallback для старых клиентов, legacy-прокси и базовых утилит.
- **Brotli (`br`):** алгоритм от Google (RFC 7932), использующий скользящее окно до 16 МБ и статический словарь (120 КБ часто встречающихся фрагментов HTML/CSS/JS). Обеспечивает наивысшую плотность сжатия для веб-статики на высоких уровнях (10–11).
- **Zstandard (`zstd`):** высокопроизводительный алгоритм от Meta (RFC 8878) на основе конечных автоматов с энтропией состояний (Finite State Entropy, FSE). Характеризуется экстремальной скоростью декомпрессии (1.5–2.5 ГБ/с на ядро) и гибким выбором уровней, являясь стандартом де-факто для динамического контента и высоконагруженных API.

## Архитектура и принципы работы

### Взаимодействие с ядром ОС и конвейер веб-сервера

Процесс отдачи сжатого контента кардинально отличается на системном уровне в зависимости от типа сжатия:

```text
[ Статическое сжатие (AOT / Pre-compressed) ]
Диск (.zst / .br / .gz) ──► Page Cache (Ядро) ──[ sendfile(2) / DMA ]──► Сетевая карта (NIC)
* User-Space веб-сервера не считывает тело файла; CPU загружен на 0% в контуре сжатия.

[ Динамическое сжатие на лету (JIT / On-the-fly) ]
Диск / Upstream (RAW) ──► read(2) ──► User-Space Buffer (Nginx/Angie) ──► CPU Compression Filter
                                                                                  │
Сетевая карта (NIC) ◄──[ writev(2) / SSL_write ]── User-Space Compressed Buffer ◄─┘
* Высокая утилизация CPU; задержка TTFB возрастает на время работы алгоритма; блокировка воркера.
```

1. **Статическая отдача (Pre-compression):**
   - На диске рядом с исходным файлом `bundle.js` размещаются `bundle.js.zst`, `bundle.js.br` и `bundle.js.gz`.
   - При совпадении `Accept-Encoding` веб-сервер открывает уже готовый архив и вызывает `sendfile(2)`.
   - Ядро Linux выполняет прямую передачу страниц из страничного кэша (Page Cache) в кольцевой буфер сетевого адаптера (TX ring buffer) через DMA (Direct Memory Access).
   - В связке с опцией `tcp_nopush` (`TCP_CORK` в Linux) ядро задерживает отправку заголовков и склеивает их с первыми пакетами данных, заполняя MSS (Maximum Segment Size) целиком.

2. **Динамическая компрессия (On-the-fly):**
   - Веб-сервер получает несжатый ответ (от бэкенда FastCGI/uWSGI/HTTP-upstream или генерирует сам).
   - Данные поступают в буферы пользовательского пространства (`gzip_buffers`, `brotli_buffers`, `zstd_buffers`).
   - Фильтр сжатия берет блок байт и выполняет ресурсоемкие математические вычисления (поиск повторов в скользящем окне, энтропийное кодирование).
   - Если размер ответа превышает буфер, сервер переключается на потоковую передачу `Transfer-Encoding: chunked`.
   - Из-за модификации данных в user-space применение `sendfile(2)` невозможно.

3. **Взаимодействие с Kernel TLS (kTLS):**
   - kTLS переносит операцию симметричного шифрования (AES-128/256-GCM, ChaCha20-Poly1305) в ядро ОС Linux (`setsockopt(..., SOL_TLS, ...)`), разгружая user-space.
   - Критическое правило конвейера: **сжатие обязано выполняться ДО передачи данных в kTLS**.
   - Зашифрованный поток данных имеет близкую к единице энтропию (случайное распределение байт), поэтому попытка сжатия после шифрования не дает эффекта и лишь увеличивает размер за счет служебных заголовков.

### Сравнительный анализ алгоритмов сжатия

Выбор алгоритма в DevOps и SRE практике обусловлен компромиссом между эффективностью упаковки, нагрузкой на CPU при компрессии и скоростью декомпрессии на стороне потребителя:

| Параметр | Gzip (DEFLATE) | Brotli (`br`) | Zstandard (`zstd`) |
| :--- | :--- | :--- | :--- |
| **Базовый алгоритм** | LZ77 + Huffman (RFC 1952) | LZ77 + Huffman + 2nd order context + Static Dict (RFC 7932) | FSE (Finite State Entropy) + LZ77 + Huffman (RFC 8878) |
| **Размер скользящего окна** | Фиксировано 32 КБ | От 1 КБ до 16 МБ (до 30 бит) | От 1 КБ до 128 МБ (до 2 ГБ в CLI) |
| **Диапазон уровней** | 1 – 9 | 1 – 11 | 1 – 22 (отрицательные уровни -1..-1313) |
| **Скорость сжатия (умеренный уровень)** | ~30–45 МБ/с (L4–L6) | ~15–25 МБ/с (L4–L5) | ~180–350 МБ/с (L3) |
| **Скорость декомпрессии** | ~250–350 МБ/с | ~300–450 МБ/с | **1500–2500 МБ/с** |
| **Потребление RAM при сжатии** | ~256–512 КБ | До 4–16 МБ (динамика), 160 МБ (L11) | До 8–32 МБ (L3), до сотен МБ (L19+) |
| **Потребление RAM при декомпрессии**| ~40 КБ | Равно размеру окна (до 16 МБ) | Равно размеру окна (обычно 1–8 МБ) |
| **Основное назначение в проде** | Legacy fallback, боты | Статическая веб-статика (JS, CSS, SVG) | Высоконагруженные API, SSR HTML, динамика |

**Ключевой вывод для SRE:** Zstandard демонстрирует асимметричную производительность: даже при увеличении степени сжатия скорость распаковки остается практически постоянной и превышает Gzip в 5–8 раз. Для высоконагруженных API и SSR-страниц Zstd уровня 1–3 тратит меньше циклов CPU, чем Gzip уровня 4, обеспечивая при этом на 10–15% меньший размер ответа.

### Механизм согласования контента (Content Negotiation)

Процесс выбора алгоритма между клиентом и веб-сервером подчиняется спецификации RFC 9110:

```text
Клиент                                                    Веб-сервер (Nginx / Angie)
  │                                                                   │
  │── GET /main.js HTTP/1.1 ─────────────────────────────────────────►│
  │   Accept-Encoding: zstd, br;q=0.9, gzip;q=0.8                    │ Проверка модулей в порядке загрузки:
  │                                                                   │ 1. zstd_static / zstd filter -> совпадение!
  │                                                                   │ 2. Проверка наличия main.js.zst на диске
  │◄── HTTP/1.1 200 OK ───────────────────────────────────────────────│
  │   Content-Encoding: zstd                                          │
  │   Vary: Accept-Encoding                                           │
  │   Content-Length: 42150                                           │
```

- **Приоритеты:** Если клиент указал веса (`q-values`), сервер учитывает предпочтения клиента. Если веса равны, выбор определяется внутренним приоритетом веб-сервера. В Nginx/Angie приоритет определяется порядком выполнения фильтров в конвейере сборки (обычно: `ngx_http_zstd_filter` → `ngx_http_brotli_filter` → `ngx_http_gzip_filter`).
- **Нормализация заголовка Accept-Encoding:** Корпоративные реверс-прокси и балансировщики (например, Varnish или Ingress-контроллеры) часто нормализуют заголовок `Accept-Encoding`, приводя его к единому виду (например, если есть `br` — оставлять только `br`, иначе `gzip`). Это максимизирует Cache Hit Ratio в общем кэше, предотвращая фрагментацию одного и того же ресурса по сотням вариантов пользовательских строк `Accept-Encoding`.

### Влияние на HTTP-кэширование, валидаторы и ETags

Сжатие кардинально меняет представление тела сущности (Representation):

1. **Деградация сильных ETags:**
   - Сильный ETag вида `ETag: "65a7d3-1b4"` гарантирует абсолютное побайтовое совпадение контента.
   - При включении динамического сжатия Nginx и Angie автоматически конвертируют сильный ETag в слабый: `ETag: W/"65a7d3-1b4"`.
   - Это легитимно согласно RFC 9110 (слабый ETag удостоверяет семантическую эквивалентность), но полностью ломает байтовые диапазоны: запросы с заголовком `Range: bytes=100-500` отклоняются сервером с возвратом `200 OK` полного тела вместо `206 Partial Content`.
   - **Решение:** Использовать предварительное статическое сжатие (`gzip_static`, `brotli_static`, `zstd_static`). В этом случае каждый статический файл на диске обладает собственным сильным ETag.

2. **Заголовок Vary:**
   - Любой сжатый ответ, зависящий от запроса, обязан сопровождаться заголовком `Vary: Accept-Encoding`.
   - Если сервер отдал клиенту сжатый Gzip-ответ без `Vary`, промежуточный кэш сохранит его как универсальный ответ для данного URL. Следующий клиент, отправивший запрос без `Accept-Encoding` (например, legacy curl или устаревший сервис), получит бинарный DEFLATE-поток и завершится с ошибкой десериализации.

### Сжатие с внешними словарями (Compression Dictionary Transport, RFC 9842)

Стандарт RFC 9842 расширяет возможности Brotli и Zstandard за счет внешних словарей:

```text
[ Исходный запрос: Загрузка словаря или первой версии ]
Client ──► GET /app-v1.js
Server ◄── HTTP/2 200 OK
           Content-Type: application/javascript
           Use-As-Dictionary: match="/app-*.js", id="app-dict-v1"
           Cache-Control: public, max-age=31536000, immutable
           (Клиент сохраняет app-v1.js в кэш словарей)

[ Запрос обновления: Загрузка новой версии бандла ]
Client ──► GET /app-v2.js
           Accept-Encoding: dcz, dcb, zstd, br, gzip
           Available-Dictionary: :47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:
           Dictionary-ID: "app-dict-v1"
Server ◄── HTTP/2 200 OK
           Content-Encoding: dcz
           Content-Length: 1250 (вместо 250 000 байт!)
           (Передана только дифференциальная дельта относительно v1)
```

- **Кодировки `dcb` и `dcz`:** Обозначают Dictionary-Compressed Brotli и Dictionary-Compressed Zstandard. Поток начинается со специализированного фиксированного заголовка (включающего 32-байтный SHA-256 хеш словаря), за которым следует тело сжатой дельты.
- **Применение в SRE:** Обновление JavaScript-бандлов, мобильных API-схем, таблиц стилей. При деплое новой сборки размер передаваемых изменений сокращается на 95–99% по сравнению со стандартным Brotli/Zstandard.

### Безопасность и атаки по побочным каналам (CRIME, TIME, BREACH)

Сжатие в зашифрованных соединениях порождает фундаментальную уязвимость класса **Side-Channel Attack**:

1. **CRIME (Compression Ratio Info-leak Made Easy):**
   - Эксплуатировала компрессию на уровне протоколов TLS и SPDY.
   - Атакующий инжектировал свои данные в заголовки и по длине зашифрованного TLS-пакета вычислял секреты (куки сессии).
   - **Статус:** TLS-сжатие полностью запрещено во всех стандартах начиная с TLS 1.3 (RFC 8446) и отключено по умолчанию в OpenSSL/BoringSSL.

2. **BREACH (Browser Reconnaissance and Exfiltration via Adaptive Compression of Hypertext):**
   - Эксплуатирует HTTP-сжатие тела ответа (`Content-Encoding: gzip/br/zstd`).
   - Условия успешной атаки:
     1. Страница отдается по HTTPS с включенным сжатием тела.
     2. Страница отражает пользовательский ввод (параметры GET/POST, URL-параметры).
     3. Страница содержит секрет (CSRF-токен, персональные данные, API-ключ).
   - Принцип: Если предположение злоумышленника о первом символе секрета совпадает с реальным символом, размер сжатого ответа уменьшается благодаря словарному сжатию LZ77. Знак за знаком секрет полностью восстанавливается за несколько сотен запросов.
   - **Защита на уровне инфраструктуры:**
     - Отключение сжатия для путей, отдающих авторизационные токены и секреты (`location /auth/`, `location /api/v1/tokens`).
     - Не включать `text/html` или `application/json` в список сжатия для приватных API без токеновой маскировки (Masked CSRF Tokens / breast-padding на бэкенде).

### Что НЕ следует сжимать

Повторная компрессия форматов, в которые уже заложены алгоритмы энтропийного кодирования, контрпродуктивна:
- **Растровые изображения:** JPEG, PNG, WebP, AVIF.
- **Видео и аудиоконтейнеры:** MP4, WebM, Ogg, MP3, AAC.
- **Архивы и сжатые бинарные форматы:** ZIP, GZ, TGZ, 7z, ZST, WOFF2 (шрифты WOFF2 сжаты внутренним Brotli).
- **Файлы меньше порога `min_length` (1024 байта):** Затраты на служебный заголовок сжатия, дерево Хаффмана и контрольные суммы превышают объем сэкономленных данных.

## Практические сценарии и конфигурация

### Предварительные требования

Для развертывания комплексного сжатия в Linux (Ubuntu 22.04/24.04, Debian 12, Rocky/RHEL 9) требуются:
- Пакеты компрессоров: `gzip`, `pigz` (многопоточный gzip), `brotli`, `zstd`.
- Утилиты диагностики: `curl`, `wrk`, `pidstat` (пакет `sysstat`), `tshark`.
- Веб-сервер:
  - **Angie 1.8+ / 1.12.x:** нативная встроенная поддержка модулей Gzip, Brotli и Zstandard (пакеты `angie-module-brotli`, `angie-module-zstd`).
  - **Nginx 1.26+:** штатный модуль `ngx_http_gzip_module`; модули Brotli (`ngx_brotli`) и Zstandard (`ngx_http_zstd_filter_module`) собираются динамически или подключаются из репозиториев дистрибутива.

Установка инструментов в Debian/Ubuntu:

```bash
apt-get update && apt-get install -y gzip pigz brotli zstd curl wrk sysstat
# → Пакеты успешно установлены
```

### Сценарий 1: Комплексная конфигурация веб-сервера (Gzip + Brotli + Zstandard)

Архитектурный стандарт для производственного обратного прокси или веб-сервера статики:

```nginx
# /etc/nginx/nginx.conf или /etc/angie/angie.conf
load_module modules/ngx_http_brotli_filter_module.so;
load_module modules/ngx_http_brotli_static_module.so;
load_module modules/ngx_http_zstd_filter_module.so;
load_module modules/ngx_http_zstd_static_module.so;

http {
    include       mime.types;
    default_type  application/octet-stream;

    # Системная оптимизация передачи файлов из Page Cache
    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;

    # ---------------------------------------------------------
    # 1. Zstandard — высший приоритет для современных клиентов
    # ---------------------------------------------------------
    zstd on;
    zstd_comp_level 3;          # Оптимум для динамики: высокая скорость при лучшем сжатии
    zstd_min_length 1024;       # Игнорировать мелкие пакеты
    zstd_static on;             # Раздача готовых .zst файлов через sendfile
    zstd_vary on;               # Добавление Vary: Accept-Encoding
    zstd_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/javascript
        application/json
        application/xml
        application/rss+xml
        image/svg+xml;

    # ---------------------------------------------------------
    # 2. Brotli — максимальное сжатие для поддерживающих клиентов
    # ---------------------------------------------------------
    brotli on;
    brotli_comp_level 4;        # Уровень 4 для динамики (уровни >6 критично нагружают CPU)
    brotli_min_length 1024;
    brotli_static on;           # Раздача готовых .br файлов через sendfile
    brotli_vary on;
    brotli_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/javascript
        application/json
        application/xml
        image/svg+xml;

    # ---------------------------------------------------------
    # 3. Gzip — универсальный fallback для устаревших клиентов
    # ---------------------------------------------------------
    gzip on;
    gzip_comp_level 4;          # Баланс между CPU и степенью сжатия
    gzip_min_length 1024;
    gzip_buffers 16 8k;
    gzip_http_version 1.1;
    gzip_proxied any;           # Сжимать ответы для проксированных запросов
    gzip_vary on;
    gzip_static on;             # Раздача готовых .gz файлов
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/javascript
        application/json
        application/xml
        application/x-javascript
        image/svg+xml;

    server {
        listen 443 ssl default_server;
        server_name example.internal;

        root /var/www/site/dist;
        index index.html;

        # Статические ресурсы (AOT сжатие через CI/CD)
        location /assets/ {
            expires 1y;
            add_header Cache-Control "public, immutable";
            try_files $uri =404;
        }

        # Динамический API (JIT сжатие с изоляцией чувствительных путей)
        location /api/ {
            proxy_pass http://127.0.0.1:8080;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;

            # Отключаем Accept-Encoding к апстриму для предотвращения двойного сжатия
            proxy_set_header Accept-Encoding "";
        }

        # Защита от BREACH: отключаем сжатие для эндпоинтов авторизации
        location /api/auth/ {
            proxy_pass http://127.0.0.1:8080;
            gzip off;
            brotli off;
            zstd off;
        }
    }
}
```

Проверка конфигурации и применение:

```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

systemctl reload nginx
# → служба перечитала конфигурацию без разрыва соединений
```

### Сценарий 2: Автоматизация Pre-Compression в CI/CD (Bash / GitLab Runner)

Скрипт предварительного сжатия артефактов фронтенда перед публикацией в production. Сжатие выполняется с максимальными уровнями качества:

```bash
#!/usr/bin/env bash
# precompress.sh — скрипт подготовки ассетов в CI/CD
set -euo pipefail

TARGET_DIR="${1:-dist/assets}"

if [[ ! -d "$TARGET_DIR" ]]; then
    echo "Ошибка: Директория $TARGET_DIR не существует." >&2
    exit 1
fi

echo "Запуск статической компрессии в: $TARGET_DIR"

# 1. Поиск текстовых ассетов размером более 1024 байт
find "$TARGET_DIR" -type f \( \
    -name "*.js" -o \
    -name "*.css" -o \
    -name "*.svg" -o \
    -name "*.json" -o \
    -name "*.xml" \
\) -size +1024c | while read -r file; do

    # Gzip сжатие максимального уровня (pigz с 4 потоками)
    if command -v pigz >/dev/null 2>&1; then
        pigz -k -f -9 -p 4 "$file"
    else
        gzip -k -f -9 "$file"
    fi

    # Brotli сжатие экстремального качества (уровень 11)
    brotli -k -f -q 11 "$file"

    # Zstandard сжатие архивного качества (уровень 19, многопоточный режим)
    zstd -k -f -19 -T0 --quiet "$file"

    # Проверка эффективности: если сжатый файл оказался больше исходного, удаляем его
    orig_size=$(stat -c%s "$file")
    for ext in gz br zst; do
        compressed_file="${file}.${ext}"
        if [[ -f "$compressed_file" ]]; then
            comp_size=$(stat -c%s "$compressed_file")
            if (( comp_size >= orig_size )); then
                rm -f "$compressed_file"
            fi
        fi
    done
done

echo "Компрессия успешно завершена:"
ls -lh "$TARGET_DIR" | grep -E "\.(js|css)(\.gz|\.br|\.zst)?$" | head -n 8
# → -rw-r--r-- 1 runner runner 245K Oct 14 12:00 app.js
# → -rw-r--r-- 1 runner runner  51K Oct 14 12:00 app.js.gz
# → -rw-r--r-- 1 runner runner  38K Oct 14 12:00 app.js.br
# → -rw-r--r-- 1 runner runner  36K Oct 14 12:00 app.js.zst
```

### Сценарий 3: Настройка Compression Dictionaries (RFC 9842) в Nginx/Angie

Настройка раздачи статического словаря для дифференциального обновления бандлов:

```nginx
location /assets/dict/ {
    root /var/www/site/dist;
    # Объявляем файл словарем для будущих версий скриптов
    add_header Use-As-Dictionary 'match="/assets/*.js", id="v1-dict"';
    add_header Cache-Control "public, max-age=31536000, immutable";
    add_header Vary "Accept-Encoding";
}

location /assets/ {
    root /var/www/site/dist;
    # Отдаем ссылку на предварительную загрузку словаря
    add_header Link '</assets/dict/v1.dat>; rel="compression-dictionary"';
    add_header Vary "Available-Dictionary, Accept-Encoding";

    # При наличии предсобранных дельт .dcz и .dcb
    try_files $uri =404;
}
```

### Сценарий 4: Разгрузка бэкенда и предотвращение Double Compression

В высоконагруженных микросервисных архитектурах сжатие на бэкендах (Node.js, Python FastAPI, Go) приводит к избыточной нагрузке на runtime приложений. Правильный паттерн — сжатие на пограничном Edge-сервере:

```nginx
upstream application_backend {
    server 10.0.1.10:8000 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8000 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 80;
    server_name api.internal;

    location / {
        proxy_pass http://application_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # ВАЖНО: обнуляем Accept-Encoding при запросе к бэкенду.
        # Бэкенд отдает сырой JSON без затрат CPU.
        proxy_set_header Accept-Encoding "";

        # Веб-сервер сам выполняет эффективное сжатие Zstd/Brotli/Gzip
        zstd on;
        zstd_comp_level 3;
        zstd_types application/json;

        brotli on;
        brotli_comp_level 4;
        brotli_types application/json;

        gzip on;
        gzip_comp_level 4;
        gzip_types application/json;
    }
}
```

### Сценарий 5: Тюнинг параметров ядра Linux для отдачи сжатого трафика

Для отдачи сотен тысяч соединений со сжатыми данными в `/etc/sysctl.d/99-network-performance.conf`:

```ini
# Разрешение масштабирования TCP-окон (RFC 7323)
net.ipv4.tcp_window_scaling = 1

# Буферы приема и отправки TCP (мин / по умолчанию / макс)
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216

# Максимальный размер системных сокет-буферов
net.core.wmem_max = 16777216
net.core.rmem_max = 16777216

# Увеличение длины очереди соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 3240000

# Включение BBR контроля перегрузок
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
```

Применение параметров ядра:

```bash
sysctl --system
# → * Applying /etc/sysctl.d/99-network-performance.conf ...
# → net.ipv4.tcp_window_scaling = 1
# → net.ipv4.tcp_wmem = 4096 65536 16777216
# → net.core.default_qdisc = fq
# → net.ipv4.tcp_congestion_control = bbr
```

## Операции и команды

### Инспекция HTTP-согласования и алгоритмов сжатия

Проверка приоритетного выбора алгоритмов клиентом:

```bash
# 1. Запрос с поддержкой Zstd, Brotli и Gzip
curl -sI -H "Accept-Encoding: zstd, br, gzip" https://example.internal/assets/app.js | grep -iE "(content-encoding|vary|content-length)"
# → content-encoding: zstd
# → vary: Accept-Encoding
# → content-length: 36864

# 2. Запрос только с поддержкой Brotli
curl -sI -H "Accept-Encoding: br" https://example.internal/assets/app.js | grep -iE "(content-encoding|vary|content-length)"
# → content-encoding: br
# → vary: Accept-Encoding
# → content-length: 38912

# 3. Запрос старого клиента только с Gzip (fallback)
curl -sI -H "Accept-Encoding: gzip" https://example.internal/assets/app.js | grep -iE "(content-encoding|vary|content-length)"
# → content-encoding: gzip
# → vary: Accept-Encoding
# → content-length: 52224

# 4. Запрос без сжатия (проверка отдачи чистого контента)
curl -sI https://example.internal/assets/app.js | grep -iE "(content-encoding|content-length)"
# → content-length: 250880
```

### Валидация целостности данных и декомпрессии через CLI

Проверка распаковки потока «на лету» без сохранения на диск для верификации отсутствия искажений:

```bash
# Проверка декомпрессии zstd
curl -s -H "Accept-Encoding: zstd" https://example.internal/assets/app.js | zstd -d | sha256sum
# → 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08  -

# Проверка декомпрессии brotli
curl -s -H "Accept-Encoding: br" https://example.internal/assets/app.js | brotli -d | sha256sum
# → 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08  -

# Сравнение с оригиналом на сервере
sha256sum /var/www/site/dist/assets/app.js
# → 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08  /var/www/site/dist/assets/app.js
```

### Нагрузочное тестирование и бенчмаркинг CPU overhead

Сравнение влияния алгоритмов сжатия на пропускную способность (RPS) и задержку с помощью утилиты `wrk`:

```bash
# Бенчмарк Zstandard
wrk -t4 -c100 -d30s -H "Accept-Encoding: zstd" https://example.internal/api/data.json
# → Running 30s test @ https://example.internal/api/data.json
# →   4 threads and 100 connections
# →   Latency     1.42ms    0.85ms  18.20ms   92.40%
# →   Req/Sec   38240.12     1.20k

# Бенчмарк Gzip
wrk -t4 -c100 -d30s -H "Accept-Encoding: gzip" https://example.internal/api/data.json
# → Running 30s test @ https://example.internal/api/data.json
# →   4 threads and 100 connections
# →   Latency     2.85ms    1.62ms  32.10ms   88.10%
# →   Req/Sec   21450.45     0.95k

# Мониторинг утилизации CPU воркерами Nginx/Angie во время теста
pidstat -u -p $(pgrep -d',' -f "(nginx|angie): worker") 1 3
# → 12:00:01      UID       PID    %usr %system  %guest   %wait    %CPU   CPU  Command
# → 12:00:02     1001     14201   18.00    6.00    0.00    0.00   24.00     2  nginx
# → 12:00:02     1001     14202   17.00    7.00    0.00    0.00   24.00     3  nginx
```

### Анализ эффективности сжатия по логам доступа

Настройка формата расширенного логирования для мониторинга коэффициента сжатия:

```nginx
log_format compression_metrics '$remote_addr - $remote_user [$time_local] '
                               '"$request" $status $bytes_sent $body_bytes_sent '
                               '"$http_accept_encoding" "$sent_http_content_encoding" '
                               'ratio=$gzip_ratio rt=$request_time';

access_log /var/log/nginx/compression_access.log compression_metrics;
```

Расчет среднего коэффициента сжатия через конвейер Bash:

```bash
awk -F'ratio=' '{print $2}' /var/log/nginx/compression_access.log | awk '{print $1}' | grep -v "-" | awk '{sum+=$1; count++} END {if (count > 0) print "Средний коэффициент сжатия:", sum/count; else print "Нет данных"}'
# → Средний коэффициент сжатия: 4.85
```

## Диагностика и устранение неисправностей

| Неисправность / Симптом | Вероятная причина | Методология диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| **ERR_CONTENT_DECODING_FAILED в браузере** | Двойное сжатие (Double Compression) или повреждение буфера прокси | `curl -s -v -H "Accept-Encoding: gzip" https://site/api \| head -c 20` | Указать `proxy_set_header Accept-Encoding "";` на пограничном Nginx/Angie, чтобы бэкенд не сжимал тело повторно. |
| **Отсутствует Content-Encoding в ответе** | Размер файла меньше `min_length`, либо MIME-тип не входит в директиву `types` | `curl -sI -H "Accept-Encoding: gzip" https://site/file.js`<br>Проверить `Content-Type` и `Content-Length` | Проверить директиву `*_types` в конфиге (убедиться, что указан точный MIME-тип, например `application/javascript`, а не только `text/javascript`). |
| **Всплеск TTFB и 100% CPU на worker процессах** | Завышенный уровень динамического сжатия (Brotli >6 или Gzip >7) | `top -b -n 1 \| grep nginx`<br>`perf top -p <worker_pid>` | Снизить `brotli_comp_level` до 4–5, `gzip_comp_level` до 4, либо переключить API на `zstd` с уровнем 3. |
| **Отравление кэша (Cache Poisoning)** | Отсутствует заголовок `Vary: Accept-Encoding` | `curl -sI https://site/style.css \| grep -i vary` | Добавить директивы `gzip_vary on;`, `brotli_vary on;`, `zstd_vary on;`. |
| **Поломка докачки файлов (Range Requests / 206 Partial Content)** | Динамическое сжатие ломает байтовые диапазоны и конвертирует сильный ETag | `curl -sI -H "Range: bytes=0-100" https://site/archive.iso` | Использовать статическое сжатие (`*_static on;`) либо отключать сжатие для бинарных и тяжелых файлов. |
| **Директива zstd on вызывает ошибку неизвестной команды** | Модуль `ngx_http_zstd_filter_module` не скомпилирован или не загружен | `nginx -t`<br>`nginx -V 2>&1 \| grep zstd` | Добавить `load_module modules/ngx_http_zstd_filter_module.so;` в начало `nginx.conf` или использовать Angie со встроенным модулем. |
| **Файл .br или .zst не отдается из директории** | Веб-сервер не имеет прав на чтение сжатого файла, либо время модификации (mtime) не совпадает | `ls -la dist/assets/app.js*`<br>Сравнить права доступа и `mtime` | Убедиться, что `chmod 644` применен ко всем файлам, а CI/CD пайплайн сохраняет одинаковый mtime (`touch -r app.js app.js.br`). |
| **Ответ отдается без сжатия при наличии прокси** | `gzip_proxied` настроен некорректно или запрос идет по HTTP/1.0 | `curl -sI --http1.0 -H "Accept-Encoding: gzip" https://site/` | Установить `gzip_proxied any;` и `gzip_http_version 1.1;` (или `1.0` при наличии legacy клиентов). |

### Методология пошаговой диагностики инцидентов со сжатием

```text
[ Шаг 1: Проверка заголовков L7 ]
Выполнить curl -sI с явным Accept-Encoding: zstd / br / gzip.
└── Если Content-Encoding отсутствует:
    ├── Проверить соответствие Content-Type спискам gzip_types / brotli_types / zstd_types.
    └── Проверить размер тела (должен быть строго больше *_min_length).

[ Шаг 2: Проверка целостности потока ]
Выполнить curl с конвейерной декомпрессией (zstd -d / brotli -d / gzip -dc).
└── Если декодер сообщает "Corrupt data" или "Invalid magic number":
    ├── Проверить наличие двойного сжатия апстримом (double encoding).
    └── Проверить промежуточные прокси-буферы (proxy_buffers).

[ Шаг 3: Проверка состояния ОС и CPU ]
Запустить pidstat -u 1 или perf top при пиковом трафике.
└── Если воркеры потребляют >80% CPU в функциях brotli_compress / deflate:
    ├── Немедленно перевести статику на pre-compression (*_static on).
    └── Для динамики снизить comp_level до безопасных значений (Zstd: 3, Gzip: 4, Brotli: 4).
```

## Рекомендации и Best Practices

### Эксплуатационный чеклист инженера SRE / DevOps

- [ ] **Статика всегда предсжата (AOT):** Все JS, CSS, SVG, JSON файлы сборки должны сжиматься на этапе CI/CD в три формата (`.gz`, `.br`, `.zst`) с максимальными уровнями упаковки.
- [ ] **Zero-Copy активен:** Убедиться, что в блоке `http` включен `sendfile on;` и `tcp_nopush on;`.
- [ ] **Безопасные уровни для динамики (JIT):** Ни при каких условиях не выставлять `brotli_comp_level > 5` или `gzip_comp_level > 5` на живом динамическом трафике.
- [ ] **Vary заголовок включен:** Проверить наличие `Vary: Accept-Encoding` во всех ответах через автоматизированный integration test.
- [ ] **Изоляция авторизационных путей:** Отключить сжатие для всех эндпоинтов, возвращающих токены авторизации, куки сессий или CSRF-ключи (защита от BREACH).
- [ ] **Отключение сжатия на бэкендах:** Убедиться, что пограничные прокси отправляют `proxy_set_header Accept-Encoding "";` на внутренние микросервисы.
- [ ] **Контроль минимального размера:** Установить порог отсечения `min_length` не менее 1024 байт.
- [ ] **Синхронизация mtime:** В CI/CD пайплайне генерировать сжатые файлы с одинаковым штампом времени `mtime`, чтобы модули `*_static` не отбраковывали их как устаревшие.

### Сводная матрица уровней компрессии

| Алгоритм | Динамическое сжатие (JIT) | Статическое сжатие (AOT / CI/CD) | Рекомендованный порог `min_length` |
| :--- | :--- | :--- | :--- |
| **Gzip** | Уровень 3–4 | Уровень 9 | 1024 байта |
| **Brotli** | Уровень 4–5 | Уровень 11 | 1024 байта |
| **Zstandard** | Уровень 1–3 | Уровень 19 (с `-T0`) | 1024 байта (256 байт для компактных JSON API) |

### План отката конфигурации при нештатных ситуациях

В случае всплеска 502/504 ошибок или деградации CPU после изменения параметров компрессии:

```bash
# 1. Быстрое отключение динамического сжатия через оверрайд-файл
cat << 'EOF' > /etc/nginx/conf.d/00-emergency-compression-off.conf
gzip off;
brotli off;
zstd off;
EOF

# 2. Валидация и перезагрузка
nginx -t && systemctl reload nginx
# → Сжатие на лету мгновенно отключено; CPU воркеров высвобожден

# 3. Откат изменений через git в репозитории конфигурации
cd /etc/nginx && git checkout HEAD~1 .
nginx -t && systemctl reload nginx
```

## Дополнительная информация

### Нормативные стандарты и RFC

- **[RFC 9110 (HTTP Semantics)](https://www.rfc-editor.org/rfc/rfc9110)** — спецификация заголовков `Content-Encoding`, `Accept-Encoding`, `Vary` и валидаторов представления.
- **[RFC 9842 (Compression Dictionary Transport)](https://www.rfc-editor.org/rfc/rfc9842)** — стандарт IETF для контекстного сжатия HTTP с внешними словарями (`Use-As-Dictionary`, `Available-Dictionary`, `dcb`, `dcz`).
- **[RFC 8878 (Zstandard Compression)](https://www.rfc-editor.org/rfc/rfc8878)** — спецификация механизма и формата данных Zstandard.
- **[RFC 7932 (Brotli Compressed Data Format)](https://www.rfc-editor.org/rfc/rfc7932)** — спецификация формата сжатия Brotli.
- **[RFC 1952 (GZIP file format specification version 4.3)](https://www.rfc-editor.org/rfc/rfc1952)** — классический стандарт сжатия DEFLATE / GZIP.
- **[RFC 9204 (QPACK: Field Compression for HTTP/3)](https://www.rfc-editor.org/rfc/rfc9204)** — сжатие метаданных и заголовков в протоколе HTTP/3.
- **[RFC 7541 (HPACK: Header Compression for HTTP/2)](https://www.rfc-editor.org/rfc/rfc7541)** — сжатие заголовков в протоколе HTTP/2.

### См. также

- **[Оптимизация сжатия в Nginx/Angie](../../Nginx/Performance/nginx_compression.md)** — исчерпывающее руководство по синтаксису и директивам модулей Nginx и Angie.
- **[Кэширование контента](./caching.md)** — согласование `Vary: Accept-Encoding`, валидация кэша и ETags.
- **[Протоколы HTTP/2 и HTTP/3](./http2_http3.md)** — реализация сжатия заголовков HPACK и QPACK.
- **[Тюнинг производительности TLS](./tls_optimization.md)** — разгрузка вычислений, kTLS и взаимодействие с сетевым стеком.
- **[Zero-Downtime Deployment](./zero_downtime_deployment.md)** — прогрев кэша и доставка статических ассетов без простоя.
- **[Structured Logging для Performance](./structured_logging_for_performance.md)** — мониторинг метрик производительности и времени ответа.
- **[Обзор оптимизации веб-производительности](./overview.md)** — фундаментальные принципы и стек метрик Core Web Vitals.
- **[Утилиты сжатия файлов в Linux](../../../Linux/SystemAdministration/file-compression.md)** — работа с утилитами `gzip`, `bzip2`, `xz`, `zstd` в системном администрировании.
- **[Уровень представления OSI (L6)](../../../Networking/OSI_TCP_IP_Model/presentation_layer.md)** — теоретические основы и инкапсуляция сжатых и шифрованных данных.
