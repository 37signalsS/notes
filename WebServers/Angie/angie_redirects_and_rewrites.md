# Перенаправления и перезапись URI в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

Механизмы перенаправлений и перезаписи URI в **[Angie](./angie_overview.md)** полностью совместимы с **[Nginx](../Nginx/Core/nginx_overview.md)** и базируются на движке регулярных выражений PCRE. Angie расширяет базовый набор директив для упрощения маршрутизации, устранения избыточных регулярных выражений и автоматизации типовых инфраструктурных сценариев.

- **Rewrite (перезапись)** — внутреннее изменение URI запроса сервером на этапе обработки. Процесс происходит прозрачно для клиента: браузер отображает исходный запрошенный URL, но сервер обрабатывает запрос по новому пути.
- **Redirect (редирект)** — внешнее перенаправление. Сервер возвращает ответ клиенту с кодом состояния `3xx` (например, 301, 302, 307 или 308) и HTTP-заголовком `Location`, заставляя браузер или API-клиент выполнить новый запрос по указанному адресу.
- **Try_files (проверка существования)** — директива последовательной проверки наличия файлов или директорий в файловой системе с последующим выполнением внутреннего перенаправления или возвратом определенного HTTP-кода.
- **Auto_redirect (Angie 1.10.0+)** — директива автоматического возврата редиректа `301` с добавлением завершающего слэша (`/path` → `/path/`), если запрошенный URI соответствует физической директории на диске.
- **Goto (Angie 1.12.0+)** — директива безусловного внутреннего перехода в именованный `location` без изменения `$uri` и без повторного запуска фазы сопоставления локаций (`NGX_HTTP_FIND_CONFIG_PHASE`), исключающая циклы перезаписи.
- **Multi-match (Angie 1.12.0+)** — возможность указания нескольких путей через пробел в рамках одного блока `location` (например, `location /api/v1/ /api/v2/`), снижающая дублирование правил.
- **Volatile** — параметр директивы `map`, отключающий кэширование вычисленного значения переменной на протяжении жизненного цикла запроса. Необходим при повторном вычислении переменных после внутреннего перенаправления.
- **Map** — директива контекста `http`, создающая пользовательские переменные на основе значений других переменных с использованием таблиц соответствий и регулярных выражений.
- **Internal redirect cycle** — критическая ошибка сервера (`500 Internal Server Error`), возникающая при превышении лимита внутренних циклических перенаправлений (жесткий лимит ядра — 10 итераций).
- **PCRE JIT (Just-In-Time)** — компилятор регулярных выражений в машинный код на этапе загрузки конфигурации, ускоряющий выполнение правил `rewrite`.
- **Status_zone** — именованная зона разделяемой памяти в Angie для сбора статистики и мониторинга ответов (включая счетчики `3xx` и `500`) в реальном времени.

Базовая спецификация Nginx и исторический контекст описаны в справочнике **[Nginx: Rewrite, Redirect и try_files](../Nginx/Core/nginx_rewrite_rules_and_try_files.md)**.

## Архитектура и базовые концепции

### Фазы обработки HTTP-запроса и модуль Rewrite

Выполнение инструкций перенаправления в Angie жестко привязано к фазам внутреннего конечного автомата обработки HTTP-запроса:

```
  +-------------------------------------------------------------+
  |              1. NGX_HTTP_SERVER_REWRITE_PHASE               |
  |  Выполнение директив rewrite/return в контексте server      |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |               2. NGX_HTTP_FIND_CONFIG_PHASE                 |
  |  Сопоставление нормализованного $uri с блоками location     |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |                 3. NGX_HTTP_REWRITE_PHASE                   |
  |  Выполнение директив rewrite/return внутри блока location   |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |              4. NGX_HTTP_POST_REWRITE_PHASE                 |
  |  Проверка изменения $uri:                                   |
  |  - Если был флаг 'last' -> возврат в FIND_CONFIG_PHASE      |
  |  - Если итераций > 10   -> 500 Internal Server Error        |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |                 5. CONTENT / PRECONTENT PHASES              |
  |  Выполнение try_files, proxy_pass, отдачи статики           |
  +-------------------------------------------------------------+
```

1. **Контекст `server` (`NGX_HTTP_SERVER_REWRITE_PHASE`):** директивы `rewrite` и `return` выполняются **до** сопоставления запроса с какими-либо блоками `location`. Если `rewrite` изменяет URI, поиск блока `location` производится уже по новому значению.
2. **Контекст `location` (`NGX_HTTP_REWRITE_PHASE`):** директивы выполняются последовательно сверху вниз при попадании запроса в данный блок.
3. **Пост-обработка (`NGX_HTTP_POST_REWRITE_PHASE`):** если в результате выполнения правил с флагом `last` URI изменился, Angie увеличивает внутренний счетчик перенаправлений и инициирует новый цикл поиска `location`.

### Порядок выполнения и флаги директивы rewrite

Директива `rewrite` использует синтаксис: `rewrite regex replacement [flag];`.

| Флаг | Контекст | Алгоритм обработки сервером |
| :--- | :--- | :--- |
| **`last`** | `server`, `location` | Завершает текущий набор инструкций модуля `rewrite`. Инициирует **новый цикл** поиска подходящего `location` по измененному URI (фаза `NGX_HTTP_FIND_CONFIG_PHASE`). |
| **`break`** | `location` | Завершает выполнение инструкций модуля `rewrite` в текущем блоке. Angie **продолжает** обработку запроса в этом же `location` без повторного поиска. |
| **`redirect`** | любой | Возвращает клиенту временный внешний редирект (`302 Found`). |
| **`permanent`** | любой | Возвращает клиенту постоянный внешний редирект (`301 Moved Permanently`). |

> **Важно:** Если флаг не указан, а строка `replacement` не содержит схемы (`http://` или `https://`), Angie продолжает последовательно выполнять последующие директивы `rewrite` в текущем контексте с модифицированным URI. Это частая причина трудноуловимых логических ошибок.

### Лимит внутренних перенаправлений и цикл итераций

Ядро Angie отслеживает глубину внутренних цепочек перенаправлений:
- Счетчик `uri_changes` инкрементируется при каждом внутреннем перезапуске сопоставления через `rewrite ... last`, переходе по `try_files` или вызове `error_page`.
- Если счетчик превышает **10**, обработка прерывается с кодом `500 Internal Server Error`, а в `error.log` фиксируется сообщение:
  `rewrite or internal redirection cycle while internally redirecting to "/path"`.
- Директива **`goto` (Angie 1.12.0+)** выполняет немедленный переход в именованный `location`, минуя фазу поиска конфигурации, и не расходует лимит счетчика `uri_changes`.

### Обработка строки запроса (Query String)

Строка аргументов запроса (`$args`) обрабатывается по следующим правилам:

1. **Автоматическое сохранение:** По умолчанию при выполнении `rewrite` исходные аргументы автоматически присоединяются к новой строке замены через символ `?`.
2. **Принудительное удаление:** Если в конце строки замены указан символ `?`, исходные аргументы отбрасываются:
   ```nginx
   # Исходный: /catalog/item?ref=partner -> Результат: /item
   rewrite ^/catalog/(.*)$ /$1? permanent;
   ```
3. **Модификация аргументов:** Если в строке замены указаны новые параметры, исходные аргументы конкатенируются через `&`:
   ```nginx
   # Исходный: /page?id=5 -> Результат: /new-page?legacy=true&id=5
   rewrite ^/page$ /new-page?legacy=true permanent;
   ```

### Семантика кодов перенаправления (301, 302, 307, 308)

В SRE и сетевой эксплуатации выбор правильного HTTP-кода критичен для предотвращения потери данных и деградации производительности:

| Код | Название | Кэширование браузерами | Сохранение HTTP-метода (POST/PUT) | Типовое применение в SRE / DevOps |
| :--- | :--- | :--- | :--- | :--- |
| **301** | Moved Permanently | Агрессивное (по умолчанию навсегда) | Нет (исторически меняет POST на GET) | Глобальный переезд домена, канонизация `www`, постоянный HTTP → HTTPS для Web. |
| **302** | Found | Нет (только при явных заголовках) | Нет (исторически меняет POST на GET) | Временный редирект, A/B тестирование, некритичные веб-страницы. |
| **307** | Temporary Redirect | Нет | **Да (метод и тело строго сохраняются)** | Временный перенос микросервисов, сервисные работы API, сохранение payload. |
| **308** | Permanent Redirect | Агрессивное | **Да (метод и тело строго сохраняются)** | Постоянная миграция REST API, смена структуры путей в API без потери POST-данных. |

### Специфические расширения Angie

| Функция | Описание механизма | Версия | Преимущество в эксплуатации |
| :--- | :--- | :--- | :--- |
| **Директива `goto`** | Безусловный переход в именованный `location` без изменения `$uri` и без повторного цикла `find_config`. | 1.12.0+ | Устраняет циклы `500`, снижает нагрузку на CPU, заменяет громоздкие `try_files` и `rewrite`. |
| **Директива `auto_redirect`** | Автоматический `301` редирект на путь с закрывающим слэшем (`/dir` → `/dir/`), если URI является директорией. | 1.10.0+ | Исключает дубли страниц в поисковых системах и ручные блоки `rewrite`. |
| **Multi-match в `location`** | Поддержка перечисления нескольких префиксов или путей через пробел в одном блоке. | 1.12.0+ | Сокращает дублирование серверных директив проксирования и ограничений доступа. |
| **Параметр `volatile` в `map`** | Отключение кэширования результата вычисления переменной в рамках одного запроса. | Все версии | Гарантирует актуальность значений переменных после внутренних перенаправлений. |
| **Метрики в `status_zone`** | Сбор статистики по кодам `3xx`, `4xx`, `5xx` на уровне каждого виртуального хоста. | Все версии | Мгновенный мониторинг аномальных всплесков редиректов через Prometheus. |

Для детального изучения алгоритмов сопоставления путей и работы с переменными см.:
*   **[Директивы location в Angie](./angie_location_directives.md)** — алгоритмы префиксного дерева, модификаторы и правила вложенности.
*   **[Переменные в Angie](./angie_variables.md)** — архитектура переменных, `map`, `volatile`, ленивые вычисления.

### Производительность и оптимизация маршрутизации

- **Директива `return` всегда производительнее `rewrite`:** для безусловных редиректов (например, HTTP → HTTPS) `return` завершает фазу немедленно, минуя регулярные выражения PCRE.
- **Включение PCRE JIT:** директива `pcre_jit on;` в контексте `main` компилирует регулярные выражения в машинный код во время старта или reload, снижая накладные расходы на обработку каждого входящего запроса до 30–40%.
- **Таблицы `map` против конструкций `if`:** `map` компилируется в хеш-таблицы или префиксные деревья и вычисляется лениво (только при фактическом обращении к переменной), в то время как `if` внутри `location` создает скрытые вложенные контексты и несет риски нестабильной работы.
- **Минимизация использования `volatile`:** флаг `volatile` форсирует пересчет значения переменной при каждом ее чтении, что приводит к дополнительным затратам процессорного времени при многократном обращении к переменной в рамках одного запроса.

## Практические сценарии

### 1. Безусловный канонический редирект HTTP на HTTPS и нормализация домена

**Контекст:** веб-сервер принимает трафик на портах 80 и 443 для доменов `example.com` и `www.example.com`. Требуется направить весь незашифрованный трафик на HTTPS с сохранением оригинального URI и нормализацией доменного имени к каноническому виду без `www`.

**Конфигурация (`/etc/angie/http.d/canonical_redirects.conf`):**

```nginx
# 1. Редирект всего незашифрованного HTTP-трафика на HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # 301 Moved Permanently с сохранением полного оригинального URI
    return 301 https://example.com$request_uri;
}

# 2. Нормализация домена www.example.com -> example.com на HTTPS
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name www.example.com;

    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    return 301 https://example.com$request_uri;
}

# 3. Основной продуктивный виртуальный хост
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name example.com;

    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    status_zone site_main;

    location / {
        root /var/www/example;
        index index.html;
    }
}
```

**Проверка:**

```bash
# Проверка HTTP -> HTTPS
curl -sI http://example.com/catalog?page=2
# → HTTP/1.1 301 Moved Permanently
# → Location: https://example.com/catalog?page=2

# Проверка www -> non-www по HTTPS
curl -sI -k https://www.example.com/api/v1/health
# → HTTP/1.1 301 Moved Permanently
# → Location: https://example.com/api/v1/health
```

### 2. Автоматическое управление завершающим слэшем (auto_redirect, Angie 1.10.0+)

**Контекст:** при обращении к статическим каталогам или документации без завершающего слэша (`/docs`) сервер должен отдавать редирект на `/docs/`, предотвращая дубли контента в поисковых системах.

**Конфигурация:**

```nginx
server {
    listen 80;
    server_name docs.internal;

    location /documentation/ {
        # Автоматический 301 редирект для существующих физических каталогов
        auto_redirect on;
        alias /opt/docs/html/;
        index index.html;
    }
}
```

**Проверка:**

```bash
# Запрос без слэша к существующей директории
curl -sI http://docs.internal/documentation
# → HTTP/1.1 301 Moved Permanently
# → Location: /documentation/
```

### 3. Быстрая внутренняя маршрутизация через goto (Angie 1.12.0+)

**Контекст:** требуется проверить наличие заголовка авторизации или куки сессии и передать запрос в специализированный бэкенд без накладных расходов на регулярные выражения и без риска циклов `rewrite ... last`.

**Конфигурация:**

```nginx
server {
    listen 80;
    server_name portal.internal;

    status_zone portal_zone;

    location / {
        # Если передан заголовок внутреннего сервиса - немедленный переход
        if ($http_x_service_auth) {
            goto @service_backend;
        }

        # Стандартная обработка для пользователей
        goto @user_backend;
    }

    location @service_backend {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }

    location @user_backend {
        proxy_pass http://127.0.0.1:8082;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

**Проверка:**

```bash
# Запрос обычного пользователя
curl -sI http://portal.internal/dashboard
# → HTTP/1.1 200 OK
# → X-Backend: user-cluster

# Запрос доверенного сервиса с заголовком
curl -sI -H "X-Service-Auth: token_secret" http://portal.internal/dashboard
# → HTTP/1.1 200 OK
# → X-Backend: service-cluster
```

### 4. Консолидация версий API через Multi-match (Angie 1.12.0+)

**Контекст:** старые клиенты обращаются по путям `/api/v1/`, `/legacy/api/` и `/rest/api/`. Необходимо направить их на единый обработчик `/api/v2/`, отсекая дублирующиеся блоки `location`.

**Конфигурация:**

```nginx
server {
    listen 80;
    server_name api.internal;

    # Объединение нескольких префиксов путей в одной директиве (Angie 1.12.0+)
    location /legacy/api/ /rest/api/ {
        rewrite ^/(?:legacy|rest)/api/(.*)$ /api/v2/$1 break;
        proxy_pass http://backend_api_v2;
        proxy_set_header Host $host;
    }

    location /api/v2/ {
        proxy_pass http://backend_api_v2;
        proxy_set_header Host $host;
    }
}
```

**Проверка:**

```bash
# Обращение по устаревшему пути
curl -sI http://api.internal/legacy/api/users/10
# → HTTP/1.1 200 OK (проксировано на backend_api_v2 по пути /api/v2/users/10)
```

### 5. Высокопроизводительный роутинг и массовые редиректы через map

**Контекст:** при миграции сайта требуется поддерживать таблицу из 10 000 старых URL-адресов. Использование тысяч директив `rewrite` в блоке `server` катастрофически замедляет обработку каждого запроса. Таблица `map` обеспечивает поиск за время $O(1)$.

**Файл карты `/etc/angie/maps/redirects.map`:**

```nginx
# Исходный относительный URI -> Целевой URL
/old-about-us.html       /about;
/company/history.php     /about/history;
/products/archive/item1  /catalog/current/item1;
/contact-support         /support;
```

**Конфигурация виртуального хоста:**

```nginx
http {
    # Загрузка карты редиректов
    map $uri $target_redirect {
        default "";
        include /etc/angie/maps/redirects.map;
    }

    server {
        listen 80;
        server_name enterprise.internal;

        status_zone redirects_zone;

        # Проверка наличия целевого редиректа в карте
        if ($target_redirect != "") {
            return 301 $target_redirect$is_args$args;
        }

        location / {
            root /var/www/enterprise;
            try_files $uri $uri/ =404;
        }
    }
}
```

**Проверка:**

```bash
# Проверка сопоставления по карте с сохранением аргументов
curl -sI "http://enterprise.internal/old-about-us.html?utm_source=direct"
# → HTTP/1.1 301 Moved Permanently
# → Location: /about?utm_source=direct

# Проверка стандартного запроса без совпадения в карте
curl -sI http://enterprise.internal/unmapped-page
# → HTTP/1.1 404 Not Found
```

### 6. Внутренний редирект с пересчетом динамических переменных (volatile)

**Контекст:** в конфигурации используется внутренняя перезапись URI. Требуется, чтобы служебная переменная, зависящая от `$uri`, гарантированно обновлялась после срабатывания `rewrite ... last`.

**Конфигурация:**

```nginx
http {
    # Параметр volatile отключает кэширование переменной на время жизни запроса
    map $uri $routing_tier volatile {
        default     "standard";
        ~^/premium/ "priority";
        ~^/internal/ "admin";
    }

    server {
        listen 80;
        server_name routing.internal;

        location /dispatch {
            # Внутренняя перезапись URI
            rewrite ^/dispatch/vip/(.*)$ /premium/$1 last;
            rewrite ^/dispatch/ops/(.*)$ /internal/$1 last;
            return 404;
        }

        location /premium/ {
            # Благодаря volatile переменная $routing_tier пересчитана и равна 'priority'
            add_header X-Tier $routing_tier always;
            return 200 "Tier: $routing_tier\n";
        }

        location /internal/ {
            add_header X-Tier $routing_tier always;
            return 200 "Tier: $routing_tier\n";
        }
    }
}
```

**Проверка:**

```bash
curl -sI http://routing.internal/dispatch/vip/report
# → HTTP/1.1 200 OK
# → X-Tier: priority
```

### 7. Режим обслуживания (Maintenance Mode) с изоляцией служебных проверок

**Контекст:** необходимо перевести сервис в режим регламентных работ с отдачей HTTP-кода `503`, сохранив доступность проверок работоспособности (`/healthz`, `/ready`) для систем мониторинга и балансировщиков.

**Конфигурация:**

```nginx
http {
    # Переменная состояния: 1 - работы активны, 0 - штатный режим
    map $uri $is_maintenance_path {
        default 1;
        /healthz 0;
        /ready   0;
    }

    server {
        listen 80;
        server_name app.internal;

        # Флаг обслуживания переключается файлом-триггером
        set $maintenance_mode 1;

        # Проверка: если режим включен и путь не является health-check
        if ($maintenance_mode = 1) {
            set $block_request "${is_maintenance_path}";
        }

        if ($block_request = "1") {
            return 503;
        }

        error_page 503 @maintenance_notice;

        location @maintenance_notice {
            root /var/www/maintenance;
            rewrite ^(.*)$ /503.html break;
            add_header Retry-After 1800 always;
        }

        location /healthz {
            return 200 "OK\n";
        }

        location / {
            proxy_pass http://app_cluster;
        }
    }
}
```

**Проверка:**

```bash
# Обращение к приложению во время работ
curl -sI http://app.internal/orders
# → HTTP/1.1 503 Service Temporarily Unavailable
# → Retry-After: 1800

# Служебная проверка балансировщика остается доступной
curl -sI http://app.internal/healthz
# → HTTP/1.1 200 OK
```

### 8. Маршрутизация Single Page Application (SPA) через try_files и именованные локации

**Контекст:** веб-приложение на React/Vue/Angular использует клиентский роутинг (HTML5 History API). Необходимо отдавать существующие статические ресурсы напрямую, а любые несуществующие маршруты передавать на `/index.html` без возникновения циклов внутренних перенаправлений.

**Конфигурация:**

```nginx
server {
    listen 80;
    server_name spa.internal;

    root /var/www/spa-dist;
    index index.html;

    # Статические ассеты с жестким кэшированием (с префиксом /assets/)
    location ^~ /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    # Корневой обработчик
    location / {
        # 1. Точный файл ($uri)
        # 2. Директория с index ($uri/)
        # 3. Переход в именованный fallback (@spa_router)
        try_files $uri $uri/ @spa_router;
    }

    location @spa_router {
        # Внутренний переход без изменения внешнего URL
        rewrite ^ /index.html break;
    }
}
```

**Проверка:**

```bash
# Запрос существующего JS-файла
curl -sI http://spa.internal/assets/bundle.js
# → HTTP/1.1 200 OK
# → Cache-Control: public, immutable

# Запрос несуществующего статического ассета возвращает 404, а не HTML страницу
curl -sI http://spa.internal/assets/missing.css
# → HTTP/1.1 404 Not Found

# Запрос клиентского маршрута отдает index.html
curl -sI http://spa.internal/profile/settings
# → HTTP/1.1 200 OK
# → Content-Type: text/html
```

### 9. Безопасная внутренняя отдача защищенных файлов (X-Accel-Redirect)

**Контекст:** приложение авторизует скачивание конфиденциальных отчетов или архивов, но саму передачу большого файла с диска должен осуществлять Angie без участия бэкенда (zero-copy через `sendfile`).

**Конфигурация:**

```nginx
server {
    listen 80;
    server_name storage.internal;

    # Закрытая директория: прямой клиентский доступ заблокирован (404)
    location /internal_storage/ {
        internal;
        alias /data/secured_archives/;
        sendfile on;
        tcp_nopush on;
        add_header X-Content-Type-Options nosniff always;
    }

    # Входная точка приложения
    location /download/ {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        # Если бэкенд возвращает заголовок X-Accel-Redirect,
        # Angie перехватывает управление и отдает файл из /internal_storage/
    }
}
```

**Проверка:**

```bash
# Попытка прямого доступа снаружи блокируется
curl -sI http://storage.internal/internal_storage/confidential.pdf
# → HTTP/1.1 404 Not Found

# Авторизованный запрос через приложение
curl -sI http://storage.internal/download/file?id=9921
# → HTTP/1.1 200 OK
# → Content-Type: application/pdf
# → Content-Disposition: attachment; filename="confidential.pdf"
```

### 10. Поэтапная миграция REST API с сохранением HTTP-методов (307/308)

**Контекст:** микросервис перемещен на новый домен или префикс. Клиенты отправляют запросы `POST`, `PUT` и `PATCH` с телом в формате JSON. Традиционные редиректы `301` или `302` приведут к тому, что клиент преобразует метод в `GET` и отбросит тело запроса.

**Конфигурация:**

```nginx
server {
    listen 80;
    server_name old-api.internal;

    # Редирект 308 гарантирует сохранение исходного HTTP-метода и тела запроса
    location /v1/transactions {
        return 308 https://new-api.internal/v2/transactions;
    }

    # Временный перенос на период технических работ (307)
    location /v1/batch-upload {
        return 307 https://temp-worker.internal/v1/batch-upload;
    }
}
```

**Проверка:**

```bash
# Отправка POST-запроса с отслеживанием редиректа (-L) и сохранением метода (--post301/--post302 не требуются для 308)
curl -s -X POST "http://old-api.internal/v1/transactions" \
     -H "Content-Type: application/json" \
     -d '{"amount": 1000, "currency": "RUB"}' \
     -w "\nHTTP Code: %{http_code}\nFinal URL: %{url_effective}\n"
# → {"status":"success","id":"tx_7721"}
# → HTTP Code: 200
# → Final URL: https://new-api.internal/v2/transactions
```

## Операции и команды

### Валидация и проверка конфигурации

Перед применением правил перенаправления и перезаписи обязательно выполняется валидация синтаксиса:

```bash
# Полная проверка синтаксиса конфигурационных файлов
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Дамп активной конфигурации с поиском директив rewrite, return, goto
sudo angie -T | grep -E -n "rewrite|return|goto|auto_redirect"
# → 142:    return 301 https://example.com$request_uri;
# → 189:    auto_redirect on;
# → 231:    rewrite ^/api/v1/(.*)$ /api/v2/$1 break;
# → 267:    goto @service_backend;
```

### Отладка правил перезаписи и логирование

Для выявления скрытых циклов и анализа работы регулярных выражений включается отладочный лог:

```nginx
# /etc/angie/conf.d/debug.conf
server {
    listen 80;
    server_name debug.internal;

    # Включение логирования преобразований URI (требует уровня notice)
    rewrite_log on;
    error_log /var/log/angie/rewrite_debug.log notice;
}
```

Применение конфигурации и просмотр журнала в реальном времени:

```bash
# Перезагрузка без разрыва соединений
sudo systemctl reload angie

# Просмотр шагов преобразования URI
sudo tail -f /var/log/angie/rewrite_debug.log
# → 2026/10/14 16:40:12 [notice] 4210#0: *1 rewrite: "/old/catalog" -> "/new/catalog", server: debug.internal
# → 2026/10/14 16:40:12 [notice] 4210#0: *1 using location "/new/catalog"
```

### Диагностика и аудит цепочек редиректов через curl

```bash
# 1. Проверка конкретного заголовка Location без скачивания тела
curl -s -o /dev/null -D - http://example.com/source | grep -E "HTTP/|Location:"
# → HTTP/1.1 301 Moved Permanently
# → Location: https://example.com/source

# 2. Аудит всей цепочки редиректов с таймингами и статусами
curl -sIL -w "\n[Summary]\nStatus: %{http_code}\nHops: %{num_redirects}\nTarget: %{url_effective}\nTotal Time: %{time_total}s\n" http://example.com/old-url
# → HTTP/1.1 301 Moved Permanently
# → Location: https://example.com/old-url
# → HTTP/2 301 
# → location: https://example.com/new-url
# → HTTP/2 200 
# → [Summary]
# → Status: 200
# → Hops: 2
# → Target: https://example.com/new-url
# → Total Time: 0.045s

# 3. Проверка сохранения параметров строки запроса
curl -sI "http://example.com/page?ref=partner&tracking=true" | grep -i "Location:"
# → Location: https://example.com/page?ref=partner&tracking=true
```

### Мониторинг метрик редиректов в Angie

Если в блоках объявлена директива `status_zone`, сбор и анализ распределения статусов ответов выполняется через встроенный API и Prometheus:

```bash
# Получение счетчиков 3xx и 5xx по зонам через REST API Angie
curl -s http://127.0.0.1:8888/status/http/status_zones/ | jq '.[] | {zone: .name, codes_3xx: .responses."3xx", codes_5xx: .responses."5xx"}'
# → {
# →   "zone": "site_main",
# →   "codes_3xx": 14205,
# →   "codes_5xx": 2
# → }

# Экспорт метрик для Prometheus
curl -s http://127.0.0.1:8888/p8s | grep -E "angie_http_responses_total.*(301|302|307|308|500)"
# → angie_http_responses_total{status="301",zone="site_main"} 14205
# → angie_http_responses_total{status="500",zone="site_main"} 2
```

### Управление процессами Angie

```bash
# Плавная перезагрузка конфигурации (graceful reload)
sudo systemctl reload angie

# Просмотр ошибок ядра и циклов маршрутизации в системном журнале
sudo journalctl -u angie -n 50 --no-pager | grep -E "rewrite|cycle|loop|syntax"
```

## Устранение неисправностей

### Цикл внутренних перенаправлений (500 Internal Server Error)

**Симптом:** клиенты получают ответ `500 Internal Server Error`. В журнале `/var/log/angie/error.log` фиксируется запись вида:
`rewrite or internal redirection cycle while internally redirecting to "/index.html"`.

**Причина:**
1. Директива `rewrite ^ /index.html last;` приводит к тому, что `/index.html` снова попадает в префиксный блок `location /`, где повторно выполняется правило `last`.
2. Взаимные ссылки между `try_files` и `error_page`.
3. Превышен лимит в 10 внутренних итераций.

**Диагностика:**
```bash
grep -E "rewrite or internal redirection cycle" /var/log/angie/error.log
# → 2026/10/14 16:45:00 [error] 4210#0: *1 rewrite or internal redirection cycle while internally redirecting to "/index.html"
```

**Решение:**
- Замените флаг `last` на `break`, если запрос должен остаться в текущем контексте:
  ```nginx
  location / {
      rewrite ^ /index.html break;
  }
  ```
- Для SPA используйте именованный `location @name`: именованные локации не участвуют в цикле сопоставления префиксов URI.
- В Angie 1.12.0+ перейдите на директиву `goto @target_block;`, которая выполняет мгновенный переход без повторного сопоставления.

### Потеря тела запроса или смена HTTP-метода при редиректе

**Симптом:** при отправке `POST`/`PUT` запросов на адрес с редиректом бэкенд получает метод `GET` с пустым телом, либо операция завершается ошибкой `405 Method Not Allowed`.

**Причина:** коды `301 Moved Permanently` и `302 Found` согласно стандартам HTTP/1.1 (RFC 7231) и исторической реализации в браузерах трансформируют исходный метод `POST` в `GET`, отбрасывая тело запроса.

**Диагностика:**
```bash
curl -X POST -d '{"key":"value"}' http://api.internal/v1/data -sI | grep -E "HTTP/|Location:"
# → HTTP/1.1 301 Moved Permanently
```

**Решение:**
Для API используйте коды **`307 Temporary Redirect`** (для временных перемещений) или **`308 Permanent Redirect`** (для постоянных). Они строго запрещают клиенту менять HTTP-метод и принуждают повторить передачу тела:
```nginx
# Было: return 301 https://api.internal/v2/data;
# Стало:
return 308 https://api.internal/v2/data;
```

### Непреднамеренная потеря или дублирование Query String

**Симптом:** после выполнения `rewrite` или внешнего редиректа теряются GET-параметры (`?utm_source=...`), либо параметры дублируются.

**Причина:**
- Ошибочное добавление знака вопроса в конце строки замены (`rewrite ^/old$ /new? permanent;`), что приводит к удалению всех параметров.
- Ручная конкатенация `$args` при отсутствии завершающего знака вопроса (`rewrite ^/old$ /new?$args permanent;`), приводящая к двойной подстановке аргументов (`/new?param=1&param=1`).

**Решение:**
1. Если требуется **сохранить** исходные параметры:
   ```nginx
   # Достаточно НЕ указывать '?' на конце строки замены:
   rewrite ^/old$ /new permanent;
   ```
2. Если требуется **полностью очистить** параметры:
   ```nginx
   # Знак '?' на конце без указания переменных:
   rewrite ^/old$ /new? permanent;
   ```
3. При использовании `return` формируйте строку явно:
   ```nginx
   # Сохранение исходного пути и параметров
   return 301 https://$host$request_uri;

   # Замена пути с сохранением параметров через $is_args$args
   return 301 https://$host/new-path$is_args$args;
   ```

### Браузерное кэширование постоянных редиректов (301/308)

**Симптом:** конфигурация на сервере исправлена или откачена назад, но браузеры клиентов продолжают перенаправлять на старый ошибочный адрес.

**Причина:** ответы с кодами `301` и `308` кэшируются браузерами в локальном постоянном дисковом кэше без повторного обращения к серверу.

**Диагностика:**
```bash
# Проверка поведения через curl без использования кэша
curl -sI http://example.com/test-path
# → HTTP/1.1 200 OK (на сервере ответ корректен, но браузер все еще отдает 301)
```

**Решение:**
- **На этапе миграции и тестирования:** всегда используйте временные коды `302` или `307`. Переключайтесь на постоянные `301` или `308` только после завершения валидации в течение 24–48 часов.
- **Предотвращение агрессивного кэширования:** при отдаче `301`/`308` во время переходных периодов передавайте заголовки управления кэшем:
  ```nginx
  location /temporary-switch {
      add_header Cache-Control "no-cache, no-store, must-revalidate";
      return 301 https://example.com/new;
  }
  ```

### Ошибки и непредвиденное поведение директивы if («If is Evil»)

**Симптом:** при использовании `if` внутри блока `location` перестают работать директивы `proxy_pass`, `add_header` или `try_files`, либо происходят сбои в рабочих процессах (worker segfault).

**Причина:** в архитектуре Nginx/Angie директива `if` внутри `location` создает анонимный вложенный блок конфигурации. Директивы модулей контента не наследуются в этот блок обычным образом.

**Решение:**
- Внутри `location` в блоке `if` безопасно использовать **исключительно** директивы модуля `rewrite`: `return` или `rewrite ... last/break`.
- Для любой условной логики заменяйте `if` на директиву `map` в контексте `http` или используйте `goto` (Angie 1.12.0+):
  ```nginx
  # Антипаттерн:
  # location / {
  #     if ($http_user_agent ~* "Mobile") {
  #         proxy_pass http://mobile_backend;
  #     }
  # }

  # Корректный подход:
  map $http_user_agent $backend_pool {
      default              http://desktop_backend;
      "~*iphone|android"   http://mobile_backend;
  }

  server {
      location / {
          proxy_pass $backend_pool;
      }
  }
  ```

### Конфликт alias и try_files (ошибка 404)

**Симптом:** при совместном использовании `alias` и `try_files` сервер возвращает `404 Not Found`, хотя файл физически присутствует на диске.

**Причина:** механизм сопоставления пути в `try_files` исторически ориентирован на директиву `root`. При использовании `alias` замена префикса URI может формировать некорректный абсолютный путь к файлу.

**Решение:**
- Заменяйте связку `alias` + `try_files` на использование `root` с корректной структурой каталогов.
- Если замена `root` невозможна, передавайте fallback через именованный `location`:
  ```nginx
  location /static/ {
      alias /var/www/my_assets/;
      try_files $uri $uri/ @static_fallback;
  }

  location @static_fallback {
      return 404;
  }
  ```

### Устаревшие значения переменных при внутреннем редиректе

**Симптом:** после выполнения внутреннего `rewrite` или перехода через `try_files` переменная, сформированная через `map`, содержит значение, вычисленное для исходного `$uri`.

**Причина:** по умолчанию значения переменных, вычисленные через `map`, кэшируются на весь период обработки HTTP-запроса (per-request caching).

**Решение:**
Добавьте параметр `volatile` в объявление `map`, чтобы форсировать пересчет значения переменной при каждом обращении:
```nginx
map $uri $dynamic_target volatile {
    default     0;
    /target1    1;
    /target2    2;
}
```

## Лучшие практики

### Иерархия инструментов маршрутизации

При проектировании правил перенаправления придерживайтесь следующей приоритетности:

```
  1. return 3xx      (Максимальная производительность, без PCRE)
        │
        ▼
  2. map + return    (Высокая скорость O(1), чистый конфиг, масштабируемость)
        │
        ▼
  3. auto_redirect   (Нативная обработка слэшей директорий в Angie)
        │
        ▼
  4. goto @named     (Эффективные переходы без циклов, Angie 1.12.0+)
        │
        ▼
  5. try_files       (Стандартная статика и SPA, без использования if)
        │
        ▼
  6. rewrite         (Применяется ТОЛЬКО при необходимости модификации части URI через PCRE)
```

### Матрица выбора кодов редиректа для SRE

| Критерий | 301 | 302 | 307 | 308 |
| :--- | :--- | :--- | :--- | :--- |
| **Срок действия** | Постоянный | Временный | Временный | Постоянный |
| **Кэширование клиентами** | Длительное | Отсутствует | Отсутствует | Длительное |
| **Поведение для GET-запросов** | Редирект на новый URL | Редирект на новый URL | Редирект на новый URL | Редирект на новый URL |
| **Поведение для POST/PUT/DELETE** | Метод меняется на GET | Метод меняется на GET | **Метод и тело сохраняются** | **Метод и тело сохраняются** |
| **Рекомендуемый контекст** | HTML-страницы, домены | A/B-тесты, авторизация | Временный роутинг API | Постоянная миграция API |

### Оптимизация производительности

1. **Глобальный JIT:** обязательно включайте `pcre_jit on;` на уровне контекста `main` в файле `/etc/angie/angie.conf`.
2. **Якорные символы в регулярных выражениях:** всегда привязывайте паттерны к началу строки (`^`) и/или концу строки (`$`). Непривязанные регулярные выражения (`rewrite /item/ /new/`) приводят к полному перебору всей строки URI движком PCRE.
3. **Отключение `rewrite_log` в production:** директива `rewrite_log on;` в сочетании с уровнем `notice` создает значительную дисковую нагрузку. Включайте ее только для локальной отладки проблем.
4. **Использование точных локаций (`location = /path`):** для частых редиректов (например, `/health`, `/favicon.ico`) используйте точное сопоставление `=`, которое немедленно прерывает поиск по конфигурации.

### Безопасность и защита от уязвимостей

1. **Защита от Open Redirect (открытых перенаправлений):**
   Никогда не выполняйте редирект на значение пользовательского параметра без валидации:
   ```nginx
   # ОПАСНО: уязвимость Open Redirect
   # return 302 $arg_redirect_to;

   # БЕЗОПАСНО: проверка по белому списку доверенных доменов через map
   map $arg_redirect_to $safe_redirect {
       default                    "";
       "~^https://example\.com/"  $arg_redirect_to;
       "~^https://auth\.internal/" $arg_redirect_to;
   }

   server {
       location /login {
           if ($safe_redirect != "") {
               return 302 $safe_redirect;
           }
           return 302 https://example.com/dashboard;
       }
   }
   ```
2. **Защита внутренних ресурсов директивой `internal`:** все эндпоинты, предназначенные для отдачи через `X-Accel-Redirect` или страницы `error_page`, должны содержать директиву `internal;`, блокирующую прямой вызов клиентом.
3. **Скрытие серверных версий:** держите включенной директиву `server_tokens off;` в контексте `http`, чтобы скрыть версию Angie в HTTP-заголовках ответов `3xx` и `5xx`.

### Эксплуатационные регламенты (SRE Runbook)

1. **Предрелизная валидация:** автоматизируйте запуск `angie -t` в CI/CD конвейерах развертывания конфигурации перед выполнением `systemctl reload angie`.
2. **Безопасная раскатка правил:** при массовой смене структуры URL на боевом трафике изначально запускайте правила с кодом `302`. Контролируйте графики ответов в течение суток, и только при отсутствии всплесков ошибок `404` и `500` переключайте директивы на `301`.
3. **Мониторинг аномалий:** настройте алерты в мониторинге на резкий рост отношения ответов `3xx` к общему количеству запросов (возможный признак шторма редиректов) и появление единичных ошибок `500` с текстом `redirection cycle`.

## Дополнительная информация

### См. также

*   **[Обзор Angie](./angie_overview.md)** — архитектура форка, базовые отличия от Nginx, модульная структура.
*   **[Директивы location в Angie](./angie_location_directives.md)** — приоритеты сопоставления, специфика префиксного дерева, Multi-match и директива `goto`.
*   **[Переменные в Angie](./angie_variables.md)** — жизненный цикл переменных, ленивые вычисления, `map` и директива `volatile`.
*   **[Nginx: Rewrite, Redirect и try_files](../Nginx/Core/nginx_rewrite_rules_and_try_files.md)** — теоретический базис Nginx, модуль `ngx_http_rewrite_module`.
*   **[Логирование в Angie](./angie_logging.md)** — настройка форматов журналов, раздельные логи для отладки и мониторинг.
*   **[Мониторинг Angie через Prometheus](./angie_monitoring/angie_monitoring_prometheus.md)** — экспорт метрик `status_zone`, анализ кодов ответов `3xx` и `5xx`.
