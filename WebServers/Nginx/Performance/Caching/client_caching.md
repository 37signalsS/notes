# Клиентское кэширование в Nginx и Angie

**Актуально для:** Nginx 1.30.x (Stable) / 1.31.x (Mainline), Angie 1.10+ / 1.12.x

## Определения

**Клиентское кэширование (Browser Caching)** — механизм, при котором браузер и промежуточные прокси сохраняют копии HTTP-ресурсов локально, чтобы исключить или минимизировать сетевые запросы при повторных обращениях. Это фундаментальный фактор оптимизации задержек и [производительности веб-приложений](../../../Concepts/web_performance/overview.md).

**Cache-Control** — ключевой HTTP-заголовок (RFC 9111), управляющий жизненным циклом и поведением кэша через набор директив (`max-age`, `immutable`, `no-cache`, `no-store`, `private`, `public` и др.).

**Валидация (Revalidation)** — процесс проверки актуальности закэшированного ресурса на сервере. Если ресурс не изменился, сервер возвращает статус `304 Not Modified` без передачи тела файла, экономя полосу пропускания и время сетевого обмена.

**Условные запросы (Conditional Requests)** — HTTP-запросы с заголовками `If-None-Match` (проверка по ETag) или `If-Modified-Since` (проверка по дате), инициируемые клиентом для валидации устаревшего содержимого.

**Stale-While-Revalidate (SWR)** — директива заголовка `Cache-Control` (RFC 5861), позволяющая браузеру мгновенно отображать устаревший контент из кэша, пока в фоновом асинхронном режиме выполняется запрос на его обновление. Устраняет блокировку отрисовки страницы.

**Stale-If-Error** — директива заголовка `Cache-Control` (RFC 5861), разрешающая клиенту использовать устаревший контент при недоступности бэкенда (ошибки 5xx, обрывы соединений, таймауты). Существенно повышает отказоустойчивость интерфейса.

**Early Hints (HTTP 103)** — механизм предварительной загрузки ресурсов (RFC 8297). Сервер отправляет список критических файлов (CSS, критические шрифты) в промежуточном ответе до того, как бэкенд закончит генерацию основного HTML-документа. Поддерживается в Nginx 1.29+ и Angie 1.10+.

**Cache Busting** — стратегия управления статикой, при которой имя файла содержит уникальный хэш содержимого (например, `main.a1b2c3d4.js`). Любое изменение кода генерирует новое имя файла, что делает старую копию невалидной и позволяет кэшировать ресурс навсегда. Подробнее о реализации в пайплайнах см. **[Стратегии Cache Busting в CI/CD](../../../../CI-CD/Frontend_CI_CD/frontend_pipeline_specifics.md#стратегии-cache-busting)**.

**No-Transform** — директива `Cache-Control`, запрещающая промежуточным прокси (включая операторов связи и мобильные шлюзы) изменять или пересжимать контент. Гарантирует целостность и неизменность передаваемых данных.

**Эвристическое кэширование (Heuristic Caching)** — поведение браузеров и разделяемых прокси согласно RFC 9111, при котором при отсутствии явных заголовков `Cache-Control` или `Expires`, но наличии `Last-Modified`, кэш рассчитывает время свежести самостоятельно (обычно 10% от разницы между `Date` и `Last-Modified`). В production часто приводит к непредсказуемому «залипанию» старых версий HTML и скриптов.

**Clear-Site-Data** — заголовок ответа (W3C), предписывающий браузеру очистить локально сохраненные данные (кэш, cookies, storage) для источника. Критичен для сценариев logout и сброса авторизованных сессий.

**Vary** — HTTP-заголовок ответа, информирующий кэширующие узлы о том, какие заголовки входящего запроса определяют уникальность версии ресурса (`Accept-Encoding`, `Accept`, `Origin`).

## Архитектура и принципы работы

### Архитектура клиентского кэширования

Клиентское кэширование оперирует на трех уровнях изоляции:
1.  **Браузер (Private Cache):** Локальное изолированное хранилище клиентского устройства (Disk Cache / Memory Cache). Доступно только конкретному пользователю; регулируется директивой `Cache-Control: private`.
2.  **Промежуточные прокси (Shared Cache):** Корпоративные прокси-серверы, кэши провайдеров и публичные шлюзы. Сохраняют копии только для ресурсов с модификатором `public` (или без `private`/`no-store`).
3.  **Reverse Proxy / Edge Gateway (Nginx / Angie):** Пограничная инфраструктура приложения, управляющая генерацией, переопределением или пробросом клиентских заголовков кэширования.

```
+-----------------------------------------------------------------------------------+
| Браузер (Private Cache)                                                           |
| [Memory Cache / Disk Cache]                                                      |
+-----------------------------------------------------------------------------------+
       |                                       ^
       | 1. Запрос ресурса                     | 4. 200 OK (с телом) или 304 Not Modified
       v                                       |
+-----------------------------------------------------------------------------------+
| Промежуточные прокси (Shared Cache, если public)                                  |
+-----------------------------------------------------------------------------------+
       |                                       ^
       | 2. Запрос при MISS/Revalidate         | 3. Заголовки: Cache-Control, ETag, Vary
       v                                       |
+-----------------------------------------------------------------------------------+
| Nginx / Angie (Reverse Proxy & Static Web Server)                                 |
| - Отдача статики (mtime, size -> ETag)                                            |
| - Управление заголовками: expires, add_header ... always                          |
| - Нормализация заголовков от бэкенда: proxy_hide_header                           |
+-----------------------------------------------------------------------------------+
```

### Жизненный цикл объекта в кэше

*   **Fresh (Свежий):** Ресурс находится в локальном кэше, и его TTL (`max-age`) не истек. Браузер извлекает его мгновенно (`200 OK (from disk cache)` или `(from memory cache)`) без отправки сетевых пакетов на сервер.
*   **Stale (Устаревший):** TTL истек. При наличии директивы `stale-while-revalidate` браузер мгновенно возвращает пользователю устаревший объект, параллельно выполняя асинхронный фоновый запрос на валидацию.
*   **Revalidation (Валидация):** При истечении TTL браузер выполняет условный HTTP-запрос (`If-None-Match` и/или `If-Modified-Since`). Если ресурс на сервере не менялся, возвращается `304 Not Modified` без тела ответа, и срок жизни кэша обновляется.
*   **Eviction / Purge (Вытеснение и сброс):** Удаление объекта из кэша при нехватке места на диске клиента по LRU, принудительном обновлении пользователем (Ctrl+F5 / Shift+Reload), смене хэша в URL (Cache Busting) или получении заголовка `Clear-Site-Data`.

### Ключевые директивы Nginx и Angie

| Директива | Контекст | Назначение |
| :--- | :--- | :--- |
| **`expires`** | `http`, `server`, `location` | Рассчитывает и добавляет заголовки `Expires` и `Cache-Control: max-age=...`. Принимает относительное (`1y`, `30d`, `2h`, `max`, `off`) или абсолютное (`@24h`) время. Отрицательные значения (`expires -1` или `expires epoch`) устанавливают `Cache-Control: no-cache`. |
| **`add_header`** | `http`, `server`, `location` | Добавляет произвольные заголовки в ответ (например, `Cache-Control`, `Clear-Site-Data`, `Vary`). Модификатор `always` гарантирует отправку заголовка для любых кодов ответа, включая ошибки 4xx и 5xx. |
| **`etag`** | `http`, `server`, `location` | Включает (`on`, по умолчанию) или отключает (`off`) автоматическую генерацию заголовка `ETag` для статических файлов. |
| **`early_hints`** | `http`, `server`, `location` | Активирует отправку промежуточного статуса `103 Early Hints` со списком заголовков `Link: ...; rel=preload`. Поддерживается в Nginx 1.29+ и Angie 1.10+. |
| **`open_file_cache`** | `http`, `server`, `location` | Кэширует в оперативной памяти дескрипторы открытых файлов, их размеры и время модификации (`mtime`). Радикально снижает число системных вызовов `stat()` при потоке условных запросов валидации (`304 Not Modified`). |
| **`proxy_hide_header`** | `http`, `server`, `location` | Скрывает заголовок, пришедший от апстрима (например, `Cache-Control` или `Expires`), предотвращая отправку клиенту дублирующихся или конфликтующих директив. |
| **`proxy_ignore_headers`**| `http`, `server`, `location` | Запрещает обработку определенных заголовков от бэкенда подсистемой кэширования Nginx. |

### Механизмы валидации: ETag и Last-Modified

#### Алгоритм формирования ETag в Nginx
Nginx вычисляет сильный ETag для статических файлов на основе времени модификации (`mtime`) и размера файла (`content_length`), форматируя их в шестнадцатеричном виде:
```c
/* Исходный код Nginx: ngx_http_core_module.c */
r->headers_out.etag->value.len = ngx_sprintf(r->headers_out.etag->value.data,
                                             "\"%xT-%xT\"",
                                             r->headers_out.last_modified_time,
                                             r->headers_out.content_length_n)
                                 - r->headers_out.etag->value.data;
```
Пример: файл с `mtime = 1713254400` (`0x661e2900`) и размером `24576` байт (`0x6000`) получит заголовок `ETag: "661e2900-6000"`.

> [!IMPORTANT]
> **Nginx не использует номер inode при формировании ETag** (в отличие от настроек по умолчанию в Apache HTTP Server). Однако в балансируемом кластере из нескольких серверов Nginx критически важно сохранять неизменными атрибуты времени модификации (`mtime`) при сборке и деплое. Если `mtime` файла на узлах различается хотя бы на секунду, клиент будет получать `200 OK` с полным телом вместо `304 Not Modified` при каждом переключении между балансируемыми серверами.

#### Деградация сильного ETag при динамическом сжатии
Сильный ETag гарантирует побайтовое совпадение контента. Если на веб-сервере включено сжатие «на лету» (модули `gzip`, `brotli`), сжатый поток байт не идентичен исходному файлу на диске. В соответствии с RFC 9110 Nginx автоматически конвертирует сильный ETag в слабый, добавляя префикс `W/` (например, `ETag: W/"661e2900-6000"`).
*   **Последствия:** Некоторые прокси-серверы и устаревшие клиенты не поддерживают условную валидацию по слабым ETag.
*   **Решение:** Применение предварительного статического сжатия (`gzip_static on;`, `brotli_static on;`). При статической прекомпрессии Nginx считывает готовый архивный файл и сохраняет сильный ETag, одновременно разгружая процессор сервера от повторного сжатия. Подробнее см. в руководстве по **[оптимизации сжатия в Nginx](../nginx_compression.md)**.

### Особенности поведения директивы `add_header`

#### 1. Модификатор `always`
По умолчанию директива `add_header` добавляет заголовки только для ответов со статусами 200, 201, 204, 206, 301, 302, 303, 304, 307 или 308. При кодах ошибок (404 Not Found, 500 Internal Server Error, 502/503) заголовки игнорируются. Если на странице 404 или 503 не отправлен заголовок `Cache-Control: no-store, no-cache, must-revalidate`, промежуточные прокси могут закэшировать ошибку эвристически. Модификатор `always` гарантирует присутствие заголовка при любых HTTP-статусах:

```nginx
add_header Cache-Control "no-store, no-cache, must-revalidate" always;
```

#### 2. Ловушка ненаследования `add_header` (Inheritance Trap)
В архитектуре Nginx директивы `add_header` наследуются с предыдущего уровня конфигурации (`http` или `server`) в текущий блок (`location`) **только в том случае, если на текущем уровне не объявлено ни одной директивы `add_header`**.

Если на уровне `server` заданы общие заголовки безопасности (HSTS, CSP, X-Frame-Options), а внутри `location /static/` добавлен локальный `add_header Cache-Control ...`, **все заголовки безопасности уровня `server` будут полностью исключены из ответа для этого `location`**.

```nginx
server {
    # Общие заголовки безопасности
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    location /static/ {
        # ВНИМАНИЕ: это объявление аннулирует HSTS, X-Content-Type-Options и X-Frame-Options!
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        
        # Решение: повторно включить конфигурационный файл с общими заголовками
        include /etc/nginx/snippets/security-headers.conf;
    }
}
```

### Взаимодействие с вышестоящими бэкендами (Reverse Proxy)

Если Nginx работает в режиме обратного прокси (`proxy_pass`), бэкенд (Node.js, Go, Python, PHP) может передавать собственные заголовки `Cache-Control` или `Expires`.
*   Если Nginx содержит собственную директиву `add_header Cache-Control ...`, клиенту будут отправлены **оба** заголовка. Клиентский браузер получит строку вида `Cache-Control: private, no-cache, public, max-age=31536000`, что порождает непредсказуемое поведение.
*   Для замещения политики бэкенда на уровне Nginx необходимо использовать директиву `proxy_hide_header`:

```nginx
location /api/cached-summary/ {
    proxy_pass http://backend_upstream;
    
    # Скрыть заголовок кэширования от бэкенда
    proxy_hide_header Cache-Control;
    proxy_hide_header Expires;
    
    # Установить собственную клиентскую политику
    add_header Cache-Control "public, max-age=60, stale-while-revalidate=300" always;
}
```

## Практические сценарии

### Сценарий 1: Версионированная статика (Immutable Assets)

Применяется для скриптов, стилей, шрифтов и медиафайлов, имена которых содержат хэш содержимого (результат сборки Vite, Webpack, esbuild). Такие файлы никогда не модифицируются: при изменении кода генерируется файл с новым хэшем.

```nginx
# /etc/nginx/conf.d/static_assets.conf

# Оптимизация системных вызовов stat() для статики
open_file_cache          max=20000 inactive=60s;
open_file_cache_valid    30s;
open_file_cache_min_uses 2;
open_file_cache_errors   on;

server {
    listen 443 ssl;
    server_name example.com;
    root /var/www/production/current/public;

    # Версионированные ассеты (CSS, JS, шрифты, медиа с хэшем в имени)
    location ~* ^/assets/.+\.[0-9a-fA-F]{8,64}\.(?:css|js|woff2?|png|jpe?g|webp|avif|svg)$ {
        # 1. Отдача прекомпрессированных версий без деградации ETag
        gzip_static on;
        brotli_static on;

        # 2. Срок жизни — 1 год. Флаг immutable запрещает условные запросы при перезагрузке (F5)
        # Директива no-transform запрещает промежуточным шлюзам пересжимать медиа
        add_header Cache-Control "public, max-age=31536000, immutable, no-transform" always;

        # 3. Решение проблемы ненаследования security-заголовков
        include /etc/nginx/snippets/security-headers.conf;

        # 4. Снижение дисковой нагрузки: отключение логирования успешных запросов
        access_log off;
        log_not_found off;
    }
}
```

**Ожидаемое поведение и валидация:**
*   Первый запрос: ответ `200 OK` с телом файла и заголовком `Cache-Control: public, max-age=31536000, immutable, no-transform`.
*   Повторные запросы и перезагрузка страницы (F5): ответ формируется браузером из локального хранилища `200 OK (from disk cache)`. Сетевой запрос к Nginx не отправляется благодаря `immutable`.

### Сценарий 2: HTML-документы и SPA с поддержкой SWR

Для динамических страниц и оболочек SPA (`index.html`) контент должен обновляться оперативно, но без блокировки рендеринга для пользователя.

```nginx
# /etc/nginx/conf.d/spa_frontend.conf

server {
    listen 443 ssl;
    server_name example.com;
    root /var/www/production/current/public;

    # Активация Early Hints (Nginx 1.29+, Angie 1.10+)
    early_hints on;

    location / {
        try_files $uri $uri/ /index.html;

        # 1. no-cache требует обязательной валидации ETag/Last-Modified перед отдачей
        # 2. stale-while-revalidate позволяет мгновенно показать кэш, пока идет фоновый запрос
        # 3. stale-if-error отдает кэшированную версию при сбое бэкенда/сервера
        add_header Cache-Control "no-cache, stale-while-revalidate=604800, stale-if-error=86400" always;

        # Подсказка браузеру начать параллельную загрузку критического бандла
        add_header Link "</assets/main.c83a12bf.css>; rel=preload; as=style" always;
        add_header Link "</assets/vendor.9df123a1.js>; rel=modulepreload; as=script" always;

        # Вариативность ответа по алгоритму сжатия
        add_header Vary "Accept-Encoding" always;

        include /etc/nginx/snippets/security-headers.conf;
    }
}
```

**Ожидаемое поведение:**
*   Первый визит: `200 OK` с полной передачей тела HTML.
*   Повторный визит: браузер отправляет условный запрос с заголовком `If-None-Match: "661e2900-1b4"`.
*   Если HTML не изменился: Nginx возвращает статус `304 Not Modified` без тела ответа.
*   При временной недоступности сервера клиент отображает страницу из локального кэша (`stale-if-error`).

### Сценарий 3: Защищенные API, персональные данные и авторизованные сессии

Для личных кабинетов, платежных форм и чувствительных API-эндпоинтов кэширование должно быть жестко запрещено на всех уровнях.

```nginx
# /etc/nginx/conf.d/private_api.conf

location /api/private/ {
    proxy_pass http://api_backend;

    # Полное подавление сохранения на стороне клиента и промежуточных прокси
    add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0" always;
    add_header Pragma "no-cache" always;
    add_header Expires "0" always;

    # Принудительная очистка клиентского кэша и cookie при завершении сессии
    # Применяется на эндпоинтах logout
    location = /api/private/auth/logout {
        proxy_pass http://api_backend;
        add_header Clear-Site-Data '"cache", "cookies", "storage"' always;
        add_header Cache-Control "no-store, max-age=0" always;
    }

    include /etc/nginx/snippets/security-headers.conf;
}
```

### Сценарий 4: Режим обслуживания (Maintenance) и изоляция страниц ошибок

При включении планового обслуживания или аварийных работ недопустимо, чтобы браузер или корпоративный прокси закэшировал страницу `503 Service Unavailable` или `500 Internal Server Error`, заблокировав пользователю доступ после восстановления системы.

```nginx
# /etc/nginx/conf.d/maintenance.conf

server {
    listen 443 ssl;
    server_name example.com;

    # Проверка флага обслуживания
    if (-f /var/run/nginx/maintenance.flag) {
        return 503;
    }

    error_page 503 @maintenance_mode;

    location @maintenance_mode {
        root /var/www/errors;
        rewrite ^(.*)$ /maintenance.html break;

        # Запрет кэширования ошибки и рекомендация клиенту повторить попытку через 10 минут
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
        add_header Retry-After "600" always;
        add_header X-Service-Status "Under Maintenance" always;
    }
}
```

### Сценарий 5: Централизованное управление политиками через `map` (SRE-паттерн)

В высоконагруженных и многомодульных конфигурациях определение директив `add_header` в десятках отдельных блоков `location` приводит к дублированию кода и риску потери security-заголовков. Паттерн вычисления политики кэширования через модуль `map` на уровне контекста `http` решает эту задачу декларативно:

```nginx
# /etc/nginx/conf.d/caching_policy_map.conf

http {
    # Сопоставление расширений файлов с политиками Cache-Control
    map $request_uri $custom_cache_control {
        default                                                 "no-cache, stale-while-revalidate=86400";
        ~*^/assets/.+\.[0-9a-fA-F]{8,64}\.(?:js|css|woff2?|svg) "public, max-age=31536000, immutable, no-transform";
        ~*^/images/.+\.(?:png|jpe?g|webp|avif)$                 "public, max-age=2592000, no-transform";
        ~*^/api/private/                                        "no-store, no-cache, must-revalidate, max-age=0";
        ~*^/api/public/                                         "public, max-age=60, stale-while-revalidate=120";
    }

    server {
        listen 443 ssl;
        server_name example.com;

        # Единая точка добавления заголовков безопасности и кэширования
        add_header Cache-Control $custom_cache_control always;
        include /etc/nginx/snippets/security-headers.conf;

        location / {
            try_files $uri $uri/ /index.html;
        }

        location /api/ {
            proxy_pass http://api_backend;
            proxy_hide_header Cache-Control;
        }
    }
}
```

## Операции и команды

| Операция | Команда | Ожидаемый результат / Пояснение |
| :--- | :--- | :--- |
| **Проверка синтаксиса** | `nginx -t` | `syntax is ok && test is successful` |
| **Бесшовное применение** | `nginx -s reload` | Применение новой конфигурации без разрыва активных TCP-сессий |
| **Проверка заголовков статики** | `curl -s -I https://example.com/assets/app.c83a12bf.js` | Ответ содержит `Cache-Control: public, max-age=31536000, immutable, no-transform` |
| **Проверка условного GET (ETag)** | `ETAG=$(curl -s -I https://example.com/assets/app.c83a12bf.js \| awk -F': ' '/[Ee][Tt]ag/ {print $2}' \| tr -d '\r')`<br>`curl -s -I -H "If-None-Match: $ETAG" https://example.com/assets/app.c83a12bf.js` | `# → HTTP/2 304 Not Modified`<br>Тело ответа не передается |
| **Проверка условного GET (Date)** | `DATE=$(curl -s -I https://example.com/index.html \| awk -F': ' '/[Ll]ast-[Mm]odified/ {print $2}' \| tr -d '\r')`<br>`curl -s -I -H "If-Modified-Since: $DATE" https://example.com/index.html` | `# → HTTP/2 304 Not Modified` |
| **Проверка модификатора `always`** | `curl -s -I https://example.com/non-existent-page-404` | Заголовок `Cache-Control` присутствует в ответе со статусом 404 |
| **Проверка Early Hints** | `curl -s -I --http2 -H "Accept: text/html" https://example.com/` | `# → HTTP/2 103 Early Hints`<br>Присутствуют промежуточные заголовки `Link: ...; rel=preload` |
| **Проверка сжатия и ETag** | `curl -s -I -H "Accept-Encoding: gzip" https://example.com/assets/app.js` | Наличие `Content-Encoding: gzip`. Если ETag имеет префикс `W/`, сжатие выполнено динамически; если сильный — сработал `gzip_static` |
| **Аудит заголовков пула URL** | `for u in / /assets/main.css /api/private/me; do echo "=== $u ==="; curl -s -I "https://example.com$u" \| grep -iE '^(http|cache-control|etag|last-modified|vary|clear-site-data)'; done` | Массовый аудит ключевых директив для критических разделов сайта |

### Наблюдаемость: Логирование заголовков клиентского кэширования

Для мониторинга эффективности клиентского кэширования в системах сбора логов (Elasticsearch, Vector, Loki) рекомендуется включить регистрацию исходящих заголовков в `log_format`:

```nginx
# /etc/nginx/conf.d/logging.conf

log_format cache_audit_json escape=json '{'
    '"time_local":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"status":$status,'
    '"request_method":"$request_method",'
    '"request_uri":"$request_uri",'
    '"sent_cache_control":"$sent_http_cache_control",'
    '"sent_etag":"$sent_http_etag",'
    '"http_if_none_match":"$http_if_none_match",'
    '"http_if_modified_since":"$http_if_modified_since",'
    '"bytes_sent":$bytes_sent,'
    '"request_time":$request_time'
'}';

access_log /var/log/nginx/access_cache.log cache_audit_json;
```

## Troubleshooting

### 1. Заголовок `Cache-Control` не передается при ошибках (404, 500, 503)

*   **Симптом:** При выполнении `curl -I https://example.com/missing-page` возвращается код `404 Not Found`, но заголовок `Cache-Control` отсутствует. Промежуточные прокси кэшируют страницу ошибки на неопределенный срок.
*   **Причина:** Директива `add_header` задана без обязательного модификатора `always`. По умолчанию Nginx отправляет заголовки только для ограниченного списка успешных HTTP-статусов.
*   **Диагностика:**
    ```bash
    curl -s -I https://example.com/not-found-test | grep -i "cache-control"
    # Пустой вывод подтверждает отсутствие заголовка
    ```
*   **Решение:** Добавьте ключевое слово `always` в конце директивы:
    ```nginx
    add_header Cache-Control "no-store, no-cache, must-revalidate" always;
    ```

### 2. Исчезновение заголовков безопасности при добавлении кэширования в `location`

*   **Симптом:** Браузер сообщает об отсутствии HSTS (`Strict-Transport-Security`) или блокирует загрузку из-за отсутствия CSP, но только при обращении к статическим файлам в `/assets/`.
*   **Причина:** Ловушка наследования `add_header`: появление `add_header Cache-Control ...` внутри блока `location` полностью отключает наследование всех директив `add_header` с уровней `http` и `server`.
*   **Диагностика:**
    ```bash
    curl -s -I https://example.com/assets/style.css | grep -iE "(strict-transport|x-content-type|x-frame)"
    # Отсутствие заголовков указывает на перекрытие контекста
    ```
*   **Решение:** Вынесите базовые security-заголовки в общий файл и подключайте через `include`:
    ```nginx
    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        include /etc/nginx/snippets/security-headers.conf;
    }
    ```

### 3. Рассинхронизация ETag в балансируемом кластере Nginx

*   **Симптом:** Клиент отправляет условный запрос `If-None-Match`, но случайным образом получает то `304 Not Modified`, то `200 OK` с полной передачей тела файла, увеличивая трафик и нагрузку на сервер.
*   **Причина:** Nginx генерирует ETag из времени модификации (`mtime`) и размера файла (`content_length`). Если при деплое статики через `git pull`, CI/CD-скрипты или архивную распаковку атрибут `mtime` на веб-серверах за балансировщиком выставился в момент выполнения команды, он будет отличаться между серверами:
    ```
    Сервер А: mtime = 1713254401 -> ETag: "661e2901-400"
    Сервер Б: mtime = 1713254405 -> ETag: "661e2905-400"
    ```
*   **Диагностика:**
    ```bash
    for ip in 192.168.1.11 192.168.1.12; do
        curl -s -I --resolve example.com:443:$ip https://example.com/assets/app.js | grep -i etag
    done
    ```
*   **Решение:**
    1. Использовать в CI/CD сохранение меток времени (утилита `git-restore-mtime` перед сборкой или флаг `rsync -a -t`).
    2. Если синхронизация `mtime` невозможна, отключить ETag (`etag off;`) и полагаться на уникальные хэши в именах файлов (Cache Busting) с заголовком `immutable`.

### 4. Дублирование заголовка `Cache-Control` при обратном проксировании

*   **Симптом:** Ответ веб-сервера содержит два заголовка `Cache-Control` с противоречивыми указаниями, например:
    ```http
    Cache-Control: private, max-age=0
    Cache-Control: public, max-age=31536000, immutable
    ```
*   **Причина:** Апстрим (бэкенд) сформировал собственный заголовок, а Nginx через `add_header` добавил второй. В Nginx директива `add_header` не заменяет существующие заголовки бэкенда, а присоединяет новые.
*   **Решение:** Подавите заголовок бэкенда с помощью `proxy_hide_header`:
    ```nginx
    location /api/v1/public-report/ {
        proxy_pass http://backend_pool;
        proxy_hide_header Cache-Control;
        proxy_hide_header Expires;
        add_header Cache-Control "public, max-age=300, stale-while-revalidate=600" always;
    }
    ```

### 5. Деградация сильного ETag в слабый (`W/`) и отказ условных запросов

*   **Симптом:** Сервер всегда отдает `ETag: W/"..."`. Промежуточный кэш или клиент не валидирует контент и запрашивает файл повторно.
*   **Причина:** Включено динамическое сжатие `gzip on;` или `brotli on;`. Nginx переводит сильный ETag в слабый, так как поток байтов в сжатом виде отличается от исходного несжатого файла на диске.
*   **Решение:** Выполняйте предварительное сжатие на этапе сборки в CI/CD и используйте модули `gzip_static` и `brotli_static`:
    ```nginx
    location ~* \.(?:css|js)$ {
        gzip_static on;
        brotli_static on;
        etag on;
    }
    ```

### 6. «Залипание» старой версии из-за эвристического кэширования

*   **Симптом:** После релиза пользователи видят устаревший интерфейс, хотя в конфигурации Nginx заголовок `Cache-Control` вообще не был настроен для HTML-файлов.
*   **Причина:** Браузер применил эвристическое кэширование (Heuristic Caching по RFC 9111), рассчитав TTL как 10% от разницы между текущей датой и `Last-Modified`.
*   **Решение:** Никогда не оставляйте HTML-документы без явной директивы кэширования. Всегда передавайте `no-cache`:
    ```nginx
    location ~* \.html$ {
        add_header Cache-Control "no-cache, must-revalidate" always;
    }
    ```

## Best Practices

1.  **Всегда указывайте модификатор `always`:** Используйте `add_header ... always;` для всех директив управления кэшем, чтобы гарантировать отдачу заголовков при ошибках (4xx/5xx) и исключить эвристическое кэширование сбоев.
2.  **Архитектурное разделение статики и документов:**
    *   **Версионированная статика (хэш в имени):** `Cache-Control: public, max-age=31536000, immutable, no-transform`.
    *   **HTML и точки входа (SPA):** `Cache-Control: no-cache, stale-while-revalidate=604800, stale-if-error=86400`.
    *   **Персональные данные и API:** `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`.
3.  **Изоляция наследования заголовков:** Помните о правиле перекрытия `add_header`. Используйте единые файлы включений (`include /etc/nginx/snippets/security-headers.conf;`) во всех блоках `location`, где задается `Cache-Control`, либо используйте паттерн вычисления политик через `map`.
4.  **Синхронизация `mtime` в CI/CD:** Для стабильности и консистентности ETag в кластерах Nginx фиксируйте атрибуты времени модификации статических файлов в пайплайнах деплоя (`git-restore-mtime` или `rsync -a -t`).
5.  **Использование статической прекомпрессии:** Для высоконагруженных ресурсов совмещайте `gzip_static on;` и `brotli_static on;`. Это разгружает процессор сервера и сохраняет сильные валидаторы ETag.
6.  **Явное использование `Vary`:** Всегда передавайте `Vary: Accept-Encoding` для сжимаемых ресурсов и `Vary: Accept` для адаптивной графики (WebP/AVIF), чтобы предотвратить отдачу неподдерживаемого формата из промежуточных прокси.
7.  **Защита от модификации операторами (`no-transform`):** Включайте директиву `no-transform` для критической статики, чтобы исключить искажение скриптов и изображений сторонними оптимизаторами мобильных провайдеров.
8.  **Очистка хранилищ при смене сессии:** Реализуйте заголовок `Clear-Site-Data: "cache", "cookies", "storage"` на эндпоинтах выхода из системы (`/logout`).
9.  **Оптимизация системных вызовов (`open_file_cache`):** Включайте кэширование дескрипторов файлов и их атрибутов в Nginx для снижения нагрузки на VFS ядра Linux при массовых запросах условной валидации (`304 Not Modified`).
10. **Подавление апстрим-заголовков (`proxy_hide_header`):** При проксировании всегда скрывайте заголовки `Cache-Control` и `Expires` бэкенда, если Nginx формирует собственную политику кэширования для клиентов.

## Дополнительная информация

### Сравнение поддержки директив клиентского кэширования

| Директива / Возможность | Nginx OSS 1.30.x (Stable) | Nginx OSS 1.31.x (Mainline) | Angie 1.10+ / 1.12.x |
| :--- | :--- | :--- | :--- |
| `expires` | Да | Да | Да |
| `add_header ... always` | Да | Да | Да |
| `early_hints` (HTTP 103) | Да (с 1.29+) | Да | Да (с 1.10+) |
| `etag` (генерация mtime-size) | Да | Да | Да |
| `stale-while-revalidate` (клиентский) | Да (проброс/генерация) | Да (проброс/генерация) | Да (проброс/генерация) |
| `stale-if-error` (клиентский) | Да (проброс/генерация) | Да (проброс/генерация) | Да (проброс/генерация) |
| `immutable` | Да (в заголовке) | Да (в заголовке) | Да (в заголовке) |
| `no-transform` | Да (в заголовке) | Да (в заголовке) | Да (в заголовке) |
| `Clear-Site-Data` | Да (в заголовке) | Да (в заголовке) | Да (в заголовке) |
| `gzip_static` / `brotli_static` | Да | Да | Да |
| `open_file_cache` | Да | Да | Да |

### Различия формирования ETag: Nginx против Apache

| Веб-сервер | Формула по умолчанию | Использование Inode | Поведение в кластере |
| :--- | :--- | :--- | :--- |
| **Nginx / Angie** | `hex(mtime) + "-" + hex(size)` | **Нет** (inode не учитывается) | Стабилен при идентичном `mtime` и размере файла на всех узлах |
| **Apache HTTP Server** | `INode + MTime + Size` (директива `FileETag`) | **Да** (по умолчанию) | Ломается в кластере из-за разных inode на разных серверах, если не задано `FileETag MTime Size` |

### См. также

*   [Обзор кэширования в Nginx и Angie](./overview.md) — классификация архитектуры кэширования и базовые концепции.
*   [Серверное кэширование (Proxy Cache) в Nginx и Angie](./proxy_caching.md) — оптимизация хранения ответов бэкенда на стороне сервера.
*   [Мониторинг кэширования в Nginx и Angie](./monitoring.md) — метрики, анализ статусов и аудит Page Cache.
*   [Оптимизация сжатия в Nginx](../nginx_compression.md) — gzip, brotli, zstd и статическая прекомпрессия.
*   [Отдача статических файлов в Nginx](../../Core/Location/serving_files.md) — тонкая настройка `sendfile`, `tcp_nopush` и `open_file_cache`.
*   [HTTP-кэширование (Протокол)](../../../../Networking/Protocols/HTTP/http_caching.md) — спецификация RFC 9111, условные запросы и директивы.
