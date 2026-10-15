# Модуль image_filter в Angie: конфигурация фронтенда

**Актуально для:** Angie 1.12.x

## Определения

**Фронтенд-шлюз изображений (Image Frontend Gateway)** — внешний виртуальный сервер (`server`) в двухконтурной архитектуре Angie, принимающий клиентские соединения, выполняющий терминацию TLS/QUIC, согласование форматов (Content Negotiation), кэширование готовых растровых файлов в `proxy_cache`, ограничение частоты запросов и защиту внутреннего вычислительного конвейера от перегрузок.

**Адаптивная доставка (Adaptive Image Delivery)** — метод отдачи наиболее эффективного формата сжатия (AVIF, WebP или исходный JPEG/PNG) в зависимости от возможностей клиентского агента, декларируемых через HTTP-заголовок `Accept`. Позволяет сократить сетевой трафик веб-ресурса на 30–65% без потери визуального качества графики.

**Согласование контента (Content Negotiation)** — алгоритм выбора формата ответа сервера на основе анализа заголовка `Accept`. В Angie реализуется через директиву `map`, сопоставляющую регулярные выражения поддерживаемых MIME-типов браузера с нормализованным суффиксом файла или маршрутом апстрима.

**Нормализация ключа кэша (Cache Key Normalization)** — преобразование вариативного заголовка `Accept` во внутреннюю детерминированную переменную формата (`$img_suffix`). Предотвращает фрагментацию кэша и катастрофическое падение Hit Ratio из-за различий в строках `Accept` между версиями браузеров.

**Отравление кэша (Cache Poisoning)** — архитектурный дефект кэширования, при котором ответ, сгенерированный для одной категории клиентов (например, AVIF для Google Chrome), сохраняется под общим ключом и отдается клиентам без поддержки данного кодека (например, старым версиям Safari), приводя к поломке отображения страниц.

**Эффект «стада бизонов» (Thundering Herd / Cache Stampede)** — лавинообразный наплыв сотен или тысяч параллельных запросов на один и тот же отсутствующий в кэше объект (MISS) в момент его публикации или истечения TTL, приводящий к одновременному запуску тяжелых математических операций ресайза/кодирования и отказу бэкенда.

**Заголовок Vary (HTTP Vary Negotiation)** — стандартный заголовок HTTP-ответа (`Vary: Accept`), информирующий браузерные и промежуточные кэширующие узлы (CDN, корпоративные forward-прокси), что бинарное содержимое ответа по данному URL зависит от значения клиентского заголовка `Accept`.

**Двухконтурное проксирование (Double Proxy Architecture)** — архитектурный паттерн разделения сетевых и вычислительных обязанностей: внешний контур (фронтенд) обслуживает неблокирующий сетевой ввод-вывод (`epoll`) и отдает кэш, а внутренний контур (бэкенд `image_filter`) выполняет синхронные ресурсоемкие манипуляции с пикселями через изолированный сокет.

**Плавная деградация (Graceful Degradation)** — способность фронтенда сохранять частичную работоспособность при сбоях или перегрузке бэкенда трансформации: автоматическая отдача оригинального изображения без сжатия, векторной заглушки (SVG/WebP placeholder) или прозрачного 1x1 пикселя с кодом `200 OK` вместо аварийного `502 Bad Gateway`.

**Бесшовная перезагрузка (Zero-Downtime Reload)** — обновление конфигурации или TLS-сертификатов Angie с помощью сигнала `SIGHUP` (`systemctl reload angie`), при котором мастер-процесс запускает новое поколение воркеров, а старые процессы корректно завершают активные соединения без сброса TCP/TLS сессий клиентов.

**SRE Golden Signals на фронтенде** — четыре ключевые метрики надежности сервиса: Latency (время отклика кэша и бэкенда), Traffic (RPS и полоса пропускания), Errors (доля 4xx/5xx кодов) и Saturation (утилизация пула воркеров, сокетов и дескрипторов).

---

## Базовые концепции

### Архитектура двухконтурного разделения: Frontend vs Backend

Обработка графики библиотекой `libgd` в модуле `ngx_http_image_filter_module` является синхронной операцией, полностью блокирующей рабочий процесс (worker process) на все время декодирования, масштабирования и кодирования растра.

```
[ Интернет-клиенты ] 
        │ TLS 1.3 / HTTP/2 / HTTP/3 (QUIC)
        ▼
┌─────────────────────────────────────────────────────────────┐
│ ФРОНТЕНД-ШЛЮЗ (Frontend Layer)                              │
│ • Неблокирующий epoll event loop                            │
│ • SSL/TLS Termination + OCSP Stapling                       │
│ • Content Negotiation (нормализация Accept -> $img_suffix)  │
│ • Дисковый кэш (proxy_cache) с защитой proxy_cache_lock     │
│ • Rate Limiting и Connection Throttling                     │
│ • Защита от Thundering Herd (proxy_cache_use_stale)         │
│ • Сбор метрик (status_zone, prometheus)                     │
└──────────────────────────────────────┬──────────────────────┘
                                       │
                      MISS / BYPASS    │ Unix Domain Socket
               (только при промахе)    │ (/var/run/angie/image_filter.sock)
                                       ▼
┌─────────────────────────────────────────────────────────────┐
│ ВНУТРЕННИЙ БЭКЕНД ФИЛЬТРАЦИИ (Backend Layer)                │
│ • Синхронный worker-пул image_filter                        │
│ • libgd: декодирование, resize, crop, rotate                │
│ • libavif / libwebp: ресурсоемкое сжатие                    │
│ • Директива internal: полная изоляция от внешней сети       │
└──────────────────────────────────────┬──────────────────────┘
                                       │ Чтение оригинала
                                       ▼
                         [ Локальное хранилище NVMe ]
```

**Разделение обязанностей:**
1. **Фронтенд:** держит десятки тысяч открытых соединений клиентов, мультиплексирует HTTP/2 и HTTP/3 потоки, мгновенно отдает закэшированные файлы из `proxy_cache` со скоростью дисковой подсистемы и оперативно троттлит аномальный трафик.
2. **Бэкенд фильтрации:** изолирован от прямого доступа извне директивой `internal`, принимает запросы исключительно при реальном промахе кэша (MISS) через высокоскоростной Unix Domain Socket и работает с жестко ограниченным пулом воркеров.

---

### Согласование контента (Content Negotiation) и нормализация

Современные браузеры запрашивают изображения, передавая составной заголовок `Accept` с весами приоритета:

```http
Accept: image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8
```

Директива `map` в Angie последовательно сопоставляет значение `$http_accept` с регулярными выражениями. Первое совпадение фиксирует значение целевой переменной:

```nginx
# Определение суффикса целевого формата на основе заголовка Accept
map $http_accept $img_suffix {
    "~*image/avif"  ".avif";
    "~*image/webp"  ".webp";
    default         "";
}

# Определение префикса маршрутизации на внутренний контур
map $http_accept $img_prefix {
    "~*image/avif"  "/convert/avif";
    "~*image/webp"  "/convert/webp";
    default         "/resize";
}
```

#### Приоритеты форматов и особенности клиентов:
- **AVIF (`image/avif`):** обеспечивает наивысшую степень сжатия (на 20–30% компактнее WebP и до 50% компактнее JPEG при идентичном визуальном индексе SSIM). Ставится первым в блоке `map`.
- **WebP (`image/webp`):** универсальный современный стандарт с широкой поддержкой (все актуальные версии Chrome, Firefox, Safari, Edge). Ставится вторым.
- **Оригинальный формат (`default`):** если клиент не заявляет поддержку современных кодеков (устаревшие браузеры, мобильные боты, утилиты `curl` без кастомных заголовков), отдается базовый JPEG или PNG без перекодирования.

---

### Антипаттерн сырого `$http_accept` в ключе кэша

Типичной ошибкой при проектировании кэша адаптивных изображений является включение сырой переменной `$http_accept` в строку `proxy_cache_key`:

```nginx
# АНТИПАТТЕРН: приводит к фрагментации кэша
proxy_cache_key "$scheme$request_method$host$uri$is_args$args$http_accept";
```

**Почему это опасно в Production:**
1. **Фрагментация ключей:** Chrome 120 передает `image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8`, Firefox передает `image/avif,image/webp,*/*`, а мобильный браузер — третью комбинацию.
2. **Падение Hit Ratio:** один и тот же файл `photo.jpg.avif` будет сгенерирован и сохранен на диске 5–10 раз под разными ключами для каждого незначительного изменения строки `Accept`.
3. **Истощение дискового пространства и памяти:** сегмент разделяемой памяти `keys_zone` переполняется дубликатами дескрипторов, а кэш-диск заполняется идентичными бинарными копиями.

**Правильное решение:** включение в `proxy_cache_key` строго нормализованной переменной формата (`$img_suffix`):

```nginx
# ЭТАЛОННОЕ РЕШЕНИЕ: детерминированный ключ кэша
proxy_cache_key "$scheme$request_method$host$uri$is_args$args$img_suffix";
```

В результате формируется ровно 3 варианта кэша на одно изображение: `.avif`, `.webp` и исходный (пустой суффикс).

---

### Роль заголовка Vary: Accept

При отдаче разных форматов файлов по одному и тому же URL (например, запрос к `https://example.com/img/800x600/banner.jpg` возвращает AVIF для Chrome и JPEG для legacy-клиентов) обязательно требуется передавать HTTP-заголовок `Vary: Accept`:

```nginx
add_header Vary "Accept" always;
```

> [!IMPORTANT]
> Директива `always` критически важна: без нее Angie опускает заголовок `Vary` при промежуточных кодах статуса (например, `304 Not Modified`).

**Механика работы:**
- **Браузер:** кэширует AVIF в локальном дисковом кэше, ассоциируя его со своим заголовком `Accept`. При открытии страницы другим компонентом системы без поддержки AVIF локальный кэш не будет ошибочно переиспользован.
- **Промежуточные узлы (CDN / Forward-прокси):** заголовок `Vary: Accept` заставляет кэширующие серверы разделять кэш по значению `Accept`. Без него первый клиент с поддержкой AVIF закэширует файл на узле CDN, после чего все клиенты без AVIF получат нечитаемый поток байт (Cache Poisoning).

---

### Защита от Thundering Herd (эффекта «стада бизонов»)

В момент публикации популярного графического материала или при сбросе кэша на фронтенд одновременно поступают сотни запросов на один и тот же URI. Для предотвращения перегрузки бэкенда фильтрации применяется комплексная защита:

```nginx
# 1. Блокировка параллельных запросов к бэкенду
proxy_cache_lock on;
proxy_cache_lock_timeout 5s;
proxy_cache_lock_age 10s;

# 2. Отдача устаревшего контента при обновлении или сбое
proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;

# 3. Асинхронное фоновое обновление устаревших элементов
proxy_cache_background_update on;
```

**Последовательность обработки:**
1. Первый запрос на изображение с промахом кэша захватывает блокировку в разделяемой памяти и отправляется к сокету бэкенда фильтрации.
2. Все последующие параллельные запросы к этому же объекту переводятся в состояние ожидания на срок до `proxy_cache_lock_timeout 5s;`.
3. Если за 5 секунд первый запрос успешно прогрел кэш, все ожидающие клиенты мгновенно получают готовый ответ из `proxy_cache` со статусом `HIT`.
4. Если объект уже был в кэше, но его TTL истек, первый клиент запускает фоновую генерацию новой версии (`proxy_cache_background_update on`), а всем остальным клиентам мгновенно отдается существующая копия со статусом `UPDATING`, сводя задержку (Tail Latency P99) к долям миллисекунды.

---

### Межпроцессное взаимодействие (IPC): Unix Domain Socket vs TCP Loopback

Для передачи трафика между фронтендом и бэкендом фильтрации в рамках одного физического хоста используются Unix Domain Sockets:

| Критерий | Unix Domain Socket (`unix:/run/...`) | TCP Loopback (`127.0.0.1:8081`) |
|:---|:---|:---|
| **Сетевой стек ядра** | Обход протоколов TCP/IP (прямое копирование через буфер ядра) | Полный проход стека: TCP handshake, подсчет контрольных сумм, ACK |
| **Накладные расходы CPU** | Минимальные (на 15–25% ниже TCP) | Заметные при высоких RPS |
| **Таблица conntrack** | Не задействуется | Риск переполнения таблицы состояний `nf_conntrack` |
| **Эфемерные порты** | Не требуются | Риск исчерпания диапазона портов при тайм-аутах `TIME_WAIT` |
| **Безопасность** | Права доступа файловой системы Linux (chown/chmod) | Необходимость директив `allow 127.0.0.1; deny all;` |
| **Отказоустойчивость пула** | Требуется блок `upstream` с директивой `keepalive` | Требуется блок `upstream` с директивой `keepalive` |

---

## Практические сценарии

### Сценарий 1: Высоконагруженный эталонный фронтенд с кэшированием и адаптивной доставкой

Эталонная рабочая конфигурация фронтенда, обеспечивающая терминацию современных протоколов TLS 1.3 / HTTP/2 / HTTP/3, согласование форматов контента, кэширование на быстром накопителе с индексацией и мониторингом.

```nginx
# Файл: /etc/angie/conf.d/01_image_frontend.conf

# 1. Нормализация клиентского заголовка Accept
map $http_accept $img_suffix {
    "~*image/avif"  ".avif";
    "~*image/webp"  ".webp";
    default         "";
}

# 2. Определение префикса маршрутизации к внутреннему серверу
map $http_accept $img_prefix {
    "~*image/avif"  "/convert/avif";
    "~*image/webp"  "/convert/webp";
    default         "/resize";
}

# 3. Балансировочная группа к локальному процессору изображений
upstream image_filter_backend {
    zone image_filter_backend 512k;
    server unix:/var/run/angie/image_filter.sock max_fails=3 fail_timeout=10s;
    keepalive 32;
    keepalive_timeout 60s;
}

# 4. Настройка зоны дискового кэша (в блоке http)
# proxy_cache_path /var/cache/angie/images 
#                  levels=1:2 
#                  keys_zone=img_cache:64m 
#                  max_size=40g 
#                  inactive=30d 
#                  use_temp_path=off 
#                  file=/var/lib/angie/img_cache.zone;

server {
    listen 443 ssl;
    listen 443 quic reuseport;
    server_name images.example.com;

    # Современные протоколы мультиплексирования
    http2 on;
    http3 on;
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # TLS-конфигурация
    ssl_certificate /etc/ssl/certs/images.example.com.crt;
    ssl_certificate_key /etc/ssl/private/images.example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL_IMG:20m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;

    # HSTS
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;

    # Сбор метрик по виртуальному хосту
    status_zone image_frontend;

    # Корневая локация: запрет прямого листинга
    location / {
        return 404;
    }

    # Основной обработчик запросов динамических изображений
    # URL вид: /img/800x600/catalog/item123.jpg
    location ~* ^/img/(?<w>\d+)x(?<h>\d+)/(?<file>.+\.(?:jpe?g|png))$ {
        # Обязательный заголовок для промежуточных кэшей
        add_header Vary "Accept" always;
        add_header X-Cache-Status $upstream_cache_status always;
        add_header X-Image-Format $img_suffix always;

        # Настройки кэширования
        proxy_cache img_cache;
        proxy_cache_key "$scheme$request_method$host$uri$is_args$args$img_suffix";

        # Сроки хранения ответов
        proxy_cache_valid 200 30d;
        proxy_cache_valid 404 15m;
        proxy_cache_valid 415 1h;

        # Защита от эффекта стада бизонов
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_lock_age 10s;

        # Фоновое обновление устаревших данных
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;

        # Таймауты обращения к вычислительному сокету
        proxy_connect_timeout 2s;
        proxy_send_timeout 5s;
        proxy_read_timeout 10s;

        # Параметры проксирования на постоянных соединениях
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Маршрутизация на Unix Domain Socket
        proxy_pass http://image_filter_backend$img_prefix/$w/$h/$file;

        # Клиентское кэширование в браузере
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }
}
```

#### Валидация и проверка через curl:

```bash
# 1. Проверка синтаксиса конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Запрос от браузера с поддержкой AVIF (первый запрос: MISS)
curl -sI -H "Accept: image/avif,image/webp,*/*" https://images.example.com/img/400x300/photo.jpg | grep -E "HTTP|x-cache|x-image-format|vary|content-type"
# → HTTP/2 200
# → vary: Accept
# → x-cache-status: MISS
# → x-image-format: .avif
# → content-type: image/avif

# 3. Повторный запрос от браузера с AVIF (должен быть HIT)
curl -sI -H "Accept: image/avif,image/webp,*/*" https://images.example.com/img/400x300/photo.jpg | grep -E "HTTP|x-cache|x-image-format"
# → HTTP/2 200
# → x-cache-status: HIT
# → x-image-format: .avif

# 4. Запрос от браузера только с поддержкой WebP (первый запрос WebP: MISS)
curl -sI -H "Accept: image/webp,*/*" https://images.example.com/img/400x300/photo.jpg | grep -E "HTTP|x-cache|x-image-format|content-type"
# → HTTP/2 200
# → x-cache-status: MISS
# → x-image-format: .webp
# → content-type: image/webp

# 5. Запрос от legacy-клиента без поддержки современных форматов (MISS базового JPEG)
curl -sI https://images.example.com/img/400x300/photo.jpg | grep -E "HTTP|x-cache|content-type"
# → HTTP/2 200
# → x-cache-status: MISS
# → content-type: image/jpeg
```

---

### Сценарий 2: Многослойный фоллбэк и Graceful Degradation при отказах бэкенда

При пиковых нагрузках, исчерпании буфера памяти или сбоях кодеков недопустимо отдавать клиенту страницу с ошибкой `502 Bad Gateway` или битым изображением. На фронтенде организуется каскадный перехват ошибок.

```nginx
# Файл: /etc/angie/conf.d/02_image_fallback.conf

server {
    listen 443 ssl;
    server_name images.example.com;
    http2 on;

    status_zone image_frontend_fallback;

    location ~* ^/img/(?<w>\d+)x(?<h>\d+)/(?<file>.+\.(?:jpe?g|png))$ {
        add_header Vary "Accept" always;
        add_header X-Cache-Status $upstream_cache_status always;

        proxy_cache img_cache;
        proxy_cache_key "$scheme$request_method$host$uri$is_args$args$img_suffix";
        proxy_cache_valid 200 30d;

        # Перехват ошибок внутреннего сервера на фронтенде
        proxy_intercept_errors on;
        error_page 502 504 = @fallback_original;
        error_page 415 500 = @fallback_placeholder;

        proxy_connect_timeout 1s;
        proxy_read_timeout 3s;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_pass http://image_filter_backend$img_prefix/$w/$h/$file;
    }

    # Фоллбэк 1: Отдача оригинального полноразмерного файла при отказе фильтра
    location @fallback_original {
        internal;
        root /var/www/images/originals;
        try_files /$file @fallback_placeholder;
        add_header X-Fallback "original-unmodified" always;
        add_header Cache-Control "public, max-age=300";
    }

    # Фоллбэк 2: Легковесный векторный SVG-placeholder без дискового I/O
    location @fallback_placeholder {
        internal;
        default_type image/svg+xml;
        add_header X-Fallback "vector-placeholder" always;
        add_header Cache-Control "public, max-age=60";
        return 200 '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 400 300"><rect fill="#f1f5f9" width="400" height="300"/><text fill="#94a3b8" font-family="sans-serif" font-size="16" dy="10.5" font-weight="bold" x="50%" y="50%" text-anchor="middle">Изображение временно недоступно</text></svg>';
    }
}
```

#### Валидация деградации при остановленном бэкенде:

```bash
# 1. Симуляция падения бэкенда (удаление или блокировка сокета)
sudo chmod 000 /var/run/angie/image_filter.sock

# 2. Выполнение запроса клиентом (ожидается возврат плейсхолдера с кодом 200)
curl -sI https://images.example.com/img/600x400/nonexistent_orig.jpg | grep -E "HTTP|x-fallback|content-type"
# → HTTP/2 200
# → x-fallback: vector-placeholder
# → content-type: image/svg+xml

# 3. Восстановление прав на сокет
sudo chmod 660 /var/run/angie/image_filter.sock
sudo chown angie:angie /var/run/angie/image_filter.sock
```

---

### Сценарий 3: Дифференцированный Rate Limiting и защита от исчерпания ресурсов

Фронтенд должен пропускать запросы со статусом `HIT` из кэша с максимальной производительностью без троттлинга, но жестко ограничивать частоту обращений к операциям, генерирующим `MISS` или `BYPASS`, чтобы защитить процессорные ядра сервера.

```nginx
# Файл: /etc/angie/conf.d/03_image_ratelimit.conf

# Зона ограничения запросов для промахов кэша (10 МБ памяти = ~160 000 IP-адресов)
limit_req_zone $binary_remote_addr zone=image_transform_limit:10m rate=15r/s;

# Зона ограничения одновременных сетевых соединений с одного адреса
limit_conn_zone $binary_remote_addr zone=image_conn_limit:10m;

server {
    listen 443 ssl;
    server_name images.example.com;
    http2 on;

    status_zone image_frontend_secured;

    location ~* ^/img/(?<w>\d+)x(?<h>\d+)/(?<file>.+\.(?:jpe?g|png))$ {
        # Ограничение параллельных TCP-сессий с одного IP
        limit_conn image_conn_limit 20;

        # Проверка кэша
        proxy_cache img_cache;
        proxy_cache_key "$scheme$request_method$host$uri$is_args$args$img_suffix";

        # Ограничение частоты запросов с возвратом 429 при исчерпании всплеска
        limit_req zone=image_transform_limit burst=30 nodelay;
        limit_req_status 429;

        # Директива status_zone для отслеживания срабатывания лимитов
        status_zone image_delivery_zone;

        proxy_pass http://image_filter_backend$img_prefix/$w/$h/$file;
    }

    # Кастомная страница ошибки 429 с инструкциями для клиента
    error_page 429 = @rate_limited_response;

    location @rate_limited_response {
        internal;
        default_type application/json;
        add_header Retry-After 5 always;
        return 429 '{"error":"TooManyRequests","message":"Превышен лимит запросов на трансформацию изображений. Повторите попытку через 5 секунд."}';
    }
}
```

#### Нагрузочное тестирование троттлинга:

```bash
# Запуск нагрузочного генератора на 100 параллельных запросов
ab -n 200 -c 20 https://images.example.com/img/1200x800/heavy_photo.jpg
# → Complete requests:      200
# → Failed requests:        155
# → Non-2xx responses:      155 (HTTP 429)

# Проверка счетчика отброшенных запросов в системном логе
grep "limiting requests" /var/log/angie/error.log | tail -n 3
# → [error] 1234#1234: *567 limiting requests, excess: 30.500 by zone "image_transform_limit", client: 192.168.1.50
```

---

### Сценарий 4: Наблюдаемость, SRE Golden Signals и экспорт метрик в Prometheus

Интеграция фронтенда со встроенными модулями мониторинга Angie: экспорт метрик OpenMetrics для Prometheus/VictoriaMetrics и REST Status API для инспекции состояния в реальном времени.

```nginx
# Файл: /etc/angie/conf.d/04_image_monitoring.conf

server {
    listen 127.0.0.1:8080;
    server_name localhost;

    # Изоляция административного интерфейса
    allow 127.0.0.1;
    allow 10.0.0.0/8;
    allow 192.168.0.0/16;
    deny all;

    # 1. Нативный экспорт OpenMetrics для Prometheus
    location /metrics {
        prometheus all;
        access_log off;
    }

    # 2. RESTful JSON Status API ядра Angie
    location /status/ {
        api /status/;
        api_config_files on;
        access_log off;
    }

    # 3. Традиционный легковесный статус
    location = /basic_status {
        stub_status;
        access_log off;
    }
}
```

#### Формулы PromQL для расчета SRE Golden Signals на фронтенде:

1. **Cache Hit Ratio (Эффективность кэширования):**
   $$\text{HitRatio} = \frac{\sum(\text{rate}(\text{angie\_http\_cache\_responses\_total}\{\text{status}="HIT"\}[5m]))}{\sum(\text{rate}(\text{angie\_http\_cache\_responses\_total}[5m]))} \times 100\%$$
   *Целевое значение для статической графики:* $> 95\%$.

2. **Доля ошибок бэкенда (Upstream Error Rate):**
   $$\text{Upstream5xxRate} = \frac{\sum(\text{rate}(\text{angie\_http\_upstream\_peers\_responses\_total}\{\text{code}="\text{5xx}"\}[5m]))}{\sum(\text{rate}(\text{angie\_http\_upstream\_peers\_requests\_total}[5m]))}$$

3. **Среднее время ответа бэкенда фильтрации (Backend Latency):**
   $$\text{AvgBackendLatency} = \frac{\text{rate}(\text{angie\_http\_upstream\_peers\_response\_time\_seconds\_sum}[5m])}{\text{rate}(\text{angie\_http\_upstream\_peers\_response\_time\_seconds\_count}[5m])}$$

#### Валидация сбора метрик через CLI:

```bash
# 1. Проверка структуры статуса кэша через JSON API
curl -s "http://127.0.0.1:8080/status/http/caches/img_cache" | jq '{size: .size, max_size: .max_size, hit_ratio: ((.responses.hit / (.responses.hit + .responses.miss)) * 100)}'
# → {
# →   "size": 1548293120,
# →   "max_size": 42949672960,
# →   "hit_ratio": 96.84
# → }

# 2. Проверка метрик зон статуса в формате Prometheus
curl -s "http://127.0.0.1:8080/metrics" | grep -E "angie_http_status_zone.*image_frontend" | head -n 4
# → angie_http_status_zone_requests_total{zone="image_frontend"} 482910
# → angie_http_status_zone_responses_total{zone="image_frontend",code="2xx"} 479102
# → angie_http_status_zone_responses_total{zone="image_frontend",code="4xx"} 3201
# → angie_http_status_zone_responses_total{zone="image_frontend",code="5xx"} 607
```

---

### Сценарий 5: Структурированное JSON-логирование и анализ эффективности кэша

Настройка высокоинформативного журнала доступа с переменными времени обработки, статуса кэша и форматов адаптивной доставки.

```nginx
# Файл: /etc/angie/conf.d/05_image_logging.conf

log_format image_analytics_json escape=json '{'
    '"time_local":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"request_method":"$request_method",'
    '"request_uri":"$request_uri",'
    '"status":$status,'
    '"bytes_sent":$bytes_sent,'
    '"request_time":$request_time,'
    '"upstream_response_time":"$upstream_response_time",'
    '"upstream_cache_status":"$upstream_cache_status",'
    '"img_format":"$img_suffix",'
    '"http_accept":"$http_accept",'
    '"http_user_agent":"$http_user_agent"'
'}';

server {
    listen 443 ssl;
    server_name images.example.com;
    http2 on;

    access_log /var/log/angie/images_access.json image_analytics_json buffer=64k flush=5s;
    error_log  /var/log/angie/images_error.log warn;
}
```

#### Ротация логов (`/etc/logrotate.d/angie-images`):

```text
/var/log/angie/images_access.json
/var/log/angie/images_error.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 angie adm
    sharedscripts
    postrotate
        /bin/kill -USR1 $(cat /run/angie/angie.pid 2>/dev/null) 2>/dev/null || true
    endscript
}
```

#### Однострочники Sysadmin/SRE для экспресс-анализа:

```bash
# 1. Расчет реального Hit Ratio по логу за последние 10 000 строк
tail -n 10000 /var/log/angie/images_access.json | jq -r '.upstream_cache_status' | awk '
    { total++; if ($1 == "HIT") hit++ } 
    END { printf "Total: %d | HIT: %d | Hit Ratio: %.2f%%\n", total, hit, (hit/total)*100 }'
# → Total: 10000 | HIT: 9680 | Hit Ratio: 96.80%

# 2. Распределение форматов адаптивной доставки (AVIF vs WebP vs Исходный)
tail -n 10000 /var/log/angie/images_access.json | jq -r '.img_format' | awk '
    { if ($1 == ".avif") avif++; else if ($1 == ".webp") webp++; else orig++ } 
    END { printf "AVIF: %d (%.1f%%) | WebP: %d (%.1f%%) | Исходный: %d (%.1f%%)\n", 
          avif, (avif/NR)*100, webp, (webp/NR)*100, orig, (orig/NR)*100 }'
# → AVIF: 7210 (72.1%) | WebP: 2140 (21.4%) | Исходный: 650 (6.5%)

# 3. Поиск наиболее медленных операций трансформации (P99 Latency на бэкенде)
tail -n 10000 /var/log/angie/images_access.json | jq -r 'select(.upstream_response_time != "-") | [.upstream_response_time, .request_uri] | @tsv' | sort -rn | head -n 5
# → 0.482   /img/2400x1600/catalog/hero_banner.jpg
# → 0.451   /img/2000x2000/products/macro_lens.jpg
```

---

### Сценарий 6: CI/CD автоматизация валидации и Zero-Downtime Reload

Скрипт предрелизной валидации конфигурации фронтенда и процедура безопасного применения изменений с автоматическим контролем поколения процессов в Status API.

```bash
#!/usr/bin/env bash
# validate-and-reload.sh — Валидация и бесшовный деплой конфигурации Angie
set -euo pipefail

STATUS_API="http://127.0.0.1:8080/status"
DOMAIN="images.example.com"

echo "=== [1/5] Проверка синтаксиса конфигурации ==="
sudo angie -t
echo "OK: Синтаксис валиден."

echo "=== [2/5] Проверка доступности сокета бэкенда ==="
if [[ ! -S /var/run/angie/image_filter.sock ]]; then
    echo "ERROR: Unix-сокет /var/run/angie/image_filter.sock не существует!" >&2
    exit 1
fi
echo "OK: Сокет бэкенда активен."

echo "=== [3/5] Получение текущего поколения мастера ==="
PREV_GEN=$(curl -sf "${STATUS_API}/angie/generation" || echo "0")
echo "Текущее поколение процессов: ${PREV_GEN}"

echo "=== [4/5] Применение новой конфигурации (SIGHUP) ==="
sudo systemctl reload angie

echo "=== [5/5] Контроль запуска нового поколения ==="
sleep 1
NEW_GEN=$(curl -sf "${STATUS_API}/angie/generation" || echo "0")

if [[ "$NEW_GEN" -gt "$PREV_GEN" ]]; then
    echo "SUCCESS: Angie успешно переключился на поколение ${NEW_GEN} без разрыва сессий."
else
    echo "WARNING: Поколение процессов не изменилось (${NEW_GEN}). Проверьте системный журнал!" >&2
    journalctl -u angie --no-pager -n 20
    exit 1
fi
```

#### Процедура автоматического отката (Rollback Pipeline):

```bash
# При возникновении аномалий или росте 5xx ошибок
echo "Выполняется откат конфигурации..."
sudo cp /etc/angie/conf.d/01_image_frontend.conf.bak /etc/angie/conf.d/01_image_frontend.conf
sudo angie -t && sudo systemctl reload angie
echo "Конфигурация возвращена к предыдущей стабильной версии."
```

---

### Сценарий 7: Системный тюнинг ядра Linux и systemd для On-Premise инфраструктуры

Фронтенд высоконагруженной отдачи медиаконтента требует тюнинга очередей сетевого стека, параметров сокетов и лимитов ядра Linux.

#### 1. Тюнинг сетевой подсистемы (`/etc/sysctl.d/99-angie-frontend.conf`):

```ini
# Максимальный размер очереди соединений ядра Linux
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# Повторное использование TCP-сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1

# Расширение диапазона эфемерных портов
net.ipv4.ip_local_port_range = 10240 65535

# Увеличение размеров очередей сетевых карт
net.core.netdev_max_backlog = 32768

# Автоматическое масштабирование буферов TCP (read/write)
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Увеличение максимального числа открытых дескрипторов системы
fs.file-max = 2097152

# Защита от SYN Flood атак
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_fin_timeout = 15
```

Применение параметров:
```bash
sudo sysctl --system
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_tw_reuse = 1
# → fs.file-max = 2097152
```

#### 2. Тюнинг юнита systemd (`/etc/systemd/system/angie.service.d/override.conf`):

```ini
[Service]
# Снятие ограничений на открытые файловые дескрипторы для воркеров
LimitNOFILE=1048576

# Блокировка памяти воркеров (предотвращение сброса в swap)
LimitMEMLOCK=infinity

# Разрешение параллельного запуска потоков
TasksMax=infinity

# Приоритет ввода-вывода (Real-Time I/O)
Nice=-10
```

Применение настроек systemd:
```bash
sudo systemctl daemon-reload
sudo systemctl restart angie
```

---

## Операции и команды

Сводная таблица повседневных регламентных команд инженера SRE и системного администратора:

| Операция | Команда | Ожидаемый результат |
|:---|:---|:---|
| **Проверка синтаксиса** | `sudo angie -t` | `# → syntax is ok`<br>`# → test is successful` |
| **Мягкая перезагрузка** | `sudo systemctl reload angie` | `# → (код завершения 0, логи без ошибок)` |
| **Проверка поколения master** | `curl -s http://127.0.0.1:8080/status/angie/generation` | `# → 14` |
| **Тест Content Negotiation (AVIF)** | `curl -sI -H "Accept: image/avif" https://images.example.com/img/100x100/p.jpg \| grep x-image-format` | `# → x-image-format: .avif` |
| **Тест Content Negotiation (WebP)** | `curl -sI -H "Accept: image/webp" https://images.example.com/img/100x100/p.jpg \| grep x-image-format` | `# → x-image-format: .webp` |
| **Проверка заголовка Vary** | `curl -sI https://images.example.com/img/100x100/p.jpg \| grep -i vary` | `# → vary: Accept` |
| **Инспекция состояния кэша** | `curl -s http://127.0.0.1:8080/status/http/caches/img_cache \| jq .` | `# → JSON с полями size, responses.hit, miss` |
| **Инспекция сокета бэкенда** | `sudo ss -xlpn \| grep image_filter.sock` | `# → u_str LISTEN 0 2048 /var/run/angie/image_filter.sock` |
| **Инспекция сетевых соединений** | `sudo ss -s` | `# → Total: 412, TCP: 184 (estab 95, closed 12)` |
| **Сброс точечного URL из кэша** | `curl -s -X PURGE https://images.example.com/img/800x600/photo.jpg` | `# → HTTP/2 200 (или 204 No Content)` |
| **Мониторинг RPS зоны фронтенда** | `watch -n 1 'curl -s http://127.0.0.1:8080/status/http/status_zones/image_frontend \| jq .requests'` | `# → {"total": 51280, "current": 340}` |

---

## Устранение неисправностей (Troubleshooting)

| Симптом / Проблема | Вероятная причина | Диагностика | Решение |
|:---|:---|:---|:---|
| **Отравление кэша (Safari получает нечитаемый AVIF)** | В ключе кэша отсутствует `$img_suffix` либо отсутствует заголовок `Vary: Accept` | `curl -sI https://images.example.com/img/400/p.jpg`<br>Проверить отсутствие `vary: Accept` и соответствие `content-type` | 1. Добавить `add_header Vary "Accept" always;`.<br>2. Включить нормализованный `$img_suffix` в `proxy_cache_key`.<br>3. Очистить поврежденную зону кэша. |
| **Низкий Hit Ratio (<50%) при стабильном трафике** | Использование сырого `$http_accept` вместо нормализованной переменной в ключе кэша | `grep proxy_cache_key /etc/angie/conf.d/*.conf`<br>Анализ лога на разнообразие значений `$http_accept` | Заменить `$http_accept` в `proxy_cache_key` на `$img_suffix`, сформированный через `map`. |
| **502 Bad Gateway от бэкенда** | Бэкенд фильтрации завершился аварийно (OOM/segfault) либо сокет недоступен по правам | `tail -n 20 /var/log/angie/error.log`<br>Проверка `13: Permission denied` или `Connection refused` | 1. Проверить права: `chown angie:angie /var/run/angie/image_filter.sock`.<br>2. Проверить системный лог: `dmesg \| grep -i oom-killer`. |
| **504 Gateway Time-out при трансформации** | Превышен `proxy_read_timeout` из-за тяжелой операции сжатия в AVIF/HEIC | `curl -s http://127.0.0.1:8080/status/http/upstreams/image_filter_backend \| jq .` | 1. Увеличить `image_filter_avif_speed 9;` на бэкенде.<br>2. Увеличить `proxy_read_timeout 10s;` на фронтенде.<br>3. Ограничить максимальные размеры исходных файлов. |
| **Thundering Herd / скачки задержки при инвалидации** | Отключен `proxy_cache_lock` либо отсутствует фоновое обновление | Зафиксировать всплеск RPS на апстрим через API: `curl -s .../upstreams/image_filter_backend` | Включить директивы `proxy_cache_lock on;`, `proxy_cache_use_stale updating;` и `proxy_cache_background_update on;`. |
| **Зависание соединений (Head-of-Line Blocking воркеров)** | Использование модуля `image_filter` напрямую на внешнем сервере без изоляции | `mpstat -P ALL 1`<br>Все ядра загружены на 100%, новые TLS-хэндшейки отбрасываются | Немедленно вынести вызовы `image_filter` на внутренний сервер за Unix-сокет по двухконтурной схеме. |
| **Ошибка 24: Too many open files** | Достигнут системный лимит открытых дескрипторов процесса воркера | `cat /proc/$(pgrep -f "angie: worker" \| head -1)/limits \| grep "open files"` | 1. Задать `LimitNOFILE=1048576` в systemd override.<br>2. Задать директиву `worker_rlimit_nofile 1048576;` в `angie.conf`. |
| **Катастрофический I/O Wait при старте сервера** | Отсутствует сериализация индекса кэша; процесс `cache loader` сканирует диск | `top -b -n 1 \| grep loader`<br>Наблюдается высокий `%iowait` дисковой подсистемы | Добавить параметр `file=/var/lib/angie/img_cache.zone` в директиву `proxy_cache_path`. |

---

## Лучшие практики

1. **Никогда не выполняйте image_filter на фронтенде:** Внешний фронтенд обязан служить исключительно шлюзом маршрутизации, терминации TLS и отдачи кэша. Любые манипуляции с графикой должны быть делегированы внутреннему серверу.
2. **Всегда нормализуйте ключ кэша:** Исключите использование сырой переменной `$http_accept` в `proxy_cache_key`. Допустима только детерминированная переменная формата (`$img_suffix`), полученная через директиву `map`.
3. **Всегда передавайте Vary: Accept с директивой always:** Отсутствие флага `always` приводит к потере заголовка при ответах `304 Not Modified`, что разрушает логику промежуточных кэшей и CDN.
4. **Обязательно активируйте защиту от Thundering Herd:** Комбинация `proxy_cache_lock on;`, `proxy_cache_use_stale updating` и `proxy_cache_background_update on;` гарантирует отсутствие всплесков latency при ротации популярных изображений.
5. **Используйте Unix Domain Sockets с Keepalive:** Подключение к бэкенду через сокет файловой системы в связке с блоком `upstream` и директивой `keepalive 32;` исключает сетевой оверхед и снимает нагрузку с подсистемы `netfilter/conntrack`.
6. **Настраивайте Graceful Degradation:** Перехватывайте ошибки `502`, `504` и `415` через `proxy_intercept_errors on;` с отдачей векторных SVG-плейсхолдеров, сохраняя визуальную целостность пользовательских страниц.
7. **Контролируйте SRE Golden Signals в реальном времени:** Мониторьте Hit Ratio (цель $> 95\%$) и перцентили задержки (P95/P99) через нативные метрики `status_zone` и встроенный модуль `prometheus all;`.
8. **Автоматизируйте Zero-Downtime Reload:** Все обновления конфигурации и сертификатов должны производиться через `angie -t` и сигнал `SIGHUP` (`systemctl reload angie`) с верификацией смены поколения (`generation`) в Status API.

---

## Дополнительная информация

### Взаимосвязь компонентов подсистемы image_filter

Конфигурация фронтенда является связующим звеном между клиентским окружением и внутренними механизмами обработки данных. Для комплексного развертывания конвейера обработки графики обратитесь к специализированным руководствам базы знаний:

- **[Конфигурация внутреннего сервера фильтрации](./filter_configuration.md)** — развертывание изолированного процессора `image_filter` на Unix-сокетах, директива `image_filter convert`, управление качеством AVIF/WebP и буферами `image_filter_buffer`.
- **[Стратегии кэширования графического контента](./caching.md)** — глубокая настройка директивы `proxy_cache_path`, сохранение индекса `file=`, оптимизация двухуровневого кэша (RAM tmpfs + NVMe) и механизм PURGE.
- **[Безопасность и защита от DoS-атак](./security.md)** — валидация параметров через модуль `secure_link`, белые списки геометрии, предотвращение декомпрессионных бомб (Pixel Flood) и защита от Cache Busting.
- **[Оптимизация производительности и бенчмаркинг](./performance.md)** — тюнинг пула воркеров, оптимизация алгоритмов сжатия `libavif`/`libwebp` и сайзинг системных ресурсов.
- **[Геометрические трансформации и Resize](./resize.md)** — синтаксис директив `resize`, `crop`, `rotate`, пропорциональное масштабирование и работа с альфа-каналами.
