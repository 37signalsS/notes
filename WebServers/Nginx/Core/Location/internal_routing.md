# Nginx: внутренняя маршрутизация

**Актуально для:** Nginx 1.26.x (Stable) / 1.27.x (Mainline)

## Определения

**Внутренняя маршрутизация (Internal Routing)** — комплекс встроенных механизмов Nginx, позволяющий перенаправлять обработку HTTP-запроса между конфигурационными блоками `location`, генерировать вторичные запросы или передавать управление отдачей контента без отправки внешнего HTTP-редиректа (301/302/307/308) клиенту. URL в адресной строке клиента остается неизменным.

**Внутренний редирект (Internal Redirect)** — повторный запуск конвейера фаз обработки запроса (`ngx_http_internal_redirect`) внутри Nginx с новым URI. Вызывается директивами `rewrite ... last`, `try_files`, `error_page`, а также при получении управляющего заголовка `X-Accel-Redirect` от апстрима.

**Именованный `location` (`@name`)** — конфигурационный блок, обозначаемый префиксом `@`, полностью исключенный из стандартного сопоставления URI (не участвует в поиске по Trie и PCRE regex). Вызывается исключительно напрямую из директив `try_files`, `error_page` и устаревшей `post_action`.

**Подзапрос (Subrequest)** — дочерний экземпляр структуры запроса (`ngx_http_request_t`), порождаемый Nginx в процессе обработки родительского запроса через `ngx_http_subrequest`. Выполняется асинхронно в цикле событий воркера, используется в модулях `auth_request`, `mirror`, `ssi` и `addition`.

**Директива `internal`** — директива модуля `ngx_http_core_module`, устанавливающая флаг доступности блока `location` только для внутренних запросов. Прямой запрос от внешнего клиента блокируется с возвратом статуса `404 Not Found` (начиная с Nginx 1.25.x; в устаревших версиях возвращался `403 Forbidden`).

**Заголовок `X-Accel-Redirect`** — служебный HTTP-заголовок ответа апстрима (FastCGI, uWSGI, HTTP proxy), указывающий Nginx перехватить управление и выполнить внутренний редирект на указанный внутренний URI для прямой высокопроизводительной отдачи ресурса.

**Zero-Copy (Нулевое копирование)** — системная передача данных из кэша страниц ядра Linux (`page cache`) напрямую в сетевой сокет через системный вызов `sendfile(2)`, исключающая копирование байтов в буферы пользовательского пространства процесса Nginx.

**Лимит внутренних перенаправлений (`NGX_HTTP_MAX_URI_CHANGES`)** — жестко заданная в исходном коде Nginx (`ngx_http_core_module.h`) константа со значением **10**. Защищает воркер от исчерпания стека и зависания при возникновении циклических перенаправлений; при превышении Nginx аварийно прерывает запрос со статусом `500 Internal Server Error`.

---

## Архитектура и базовые концепции

### Жизненный цикл и механизм `ngx_http_internal_redirect`

В архитектуре Nginx внутренний редирект не порождает новый сетевой сокет или отдельное клиентское соединение. Функция ядра `ngx_http_internal_redirect(r, uri, args)` выполняет следующие действия:

```
[Входящий клиентский запрос] ───► [Поиск location] ───► [Обработка в Content Phase]
                                         ▲                         │
                                         │  (try_files / rewrite / │
                                         │   error_page / X-Accel) │
                                         └───── Внутренний ────────┘
                                                редирект
                                         (r->uri_changes++)
```

1. **Инкремент счетчика перенаправлений:** Поле `r->uri_changes` увеличивается на 1. Если значение превышает 10, генерация прерывается:
   ```c
   /* ngx_http_core_module.c */
   if (r->uri_changes == 0) {
       ngx_log_error(NGX_LOG_ERR, r->connection->log, 0,
                     "rewrite or internal redirection cycle "
                     "while internal redirection to \"%V\"", uri);
       ngx_http_finalize_request(r, NGX_HTTP_INTERNAL_SERVER_ERROR);
       return NGX_DONE;
   }
   r->uri_changes--;
   ```
2. **Обновление переменных пути:**
   - Переменная `$uri` (и `$document_uri`) принимает новое нормализованное значение переданного пути.
   - Переменная `$args` обновляется переданными аргументами строки запроса.
   - Переменная `$request_uri` **остается неизменной** — она пожизненно хранит исходную строку URI, отправленную клиентом.
3. **Сброс контекстов модулей:** Очищаются структуры контекстов большинства модулей обработки контента (`r->ctx`), отменяется привязка предыдущего обработчика `r->content_handler`.
4. **Перезапуск конвейера фаз:** Запрос переводится на фазу `NGX_HTTP_SERVER_REWRITE_PHASE` либо `NGX_HTTP_FIND_CONFIG_PHASE` для поиска нового подходящего блока `location` по обновленному `$uri`.

### Различия механизмов маршрутизации

Понимание различий между внутренним редиректом, переходом в именованный `location` и подзапросом критично для проектирования надежных систем:

| Характеристика | Внутренний редирект (`ngx_http_internal_redirect`) | Именованный `location` (`@name`) | Подзапрос (`ngx_http_subrequest`) |
| :--- | :--- | :--- | :--- |
| **Инициаторы** | `rewrite ... last`, `try_files URI`, `error_page URI`, `X-Accel-Redirect` | `try_files ... @name`, `error_page ... @name`, `post_action @name` | `auth_request`, `mirror`, `ssi`, `addition` |
| **Изменение `$uri`** | Да (`$uri` меняется на новый путь) | **Нет** (`$uri` сохраняет исходный путь запроса) | Имеет собственный `$uri` внутри дочернего запроса |
| **Повторный выбор location** | Да (полный проход Trie префиксов и PCRE regex) | **Нет** (прямой переход по указателю на блок) | Да (поиск location для URI подзапроса) |
| **Лимит вызовов** | Лимит 10 (`NGX_HTTP_MAX_URI_CHANGES`) | Ограничен общим стеком вызовов директивы | Лимит 50 вложенных подзапросов (`NGX_HTTP_MAX_SUBREQUESTS`) |
| **Формирование ответа** | Замещает исходный ответ клиенту | Замещает исходный ответ клиенту | Вспомогательный (проверка статуса или дублирование тела) |

### Именованные location (`@name`)

Именованные блоки задаются синтаксисом `location @<name> { ... }`.

```nginx
location / {
    try_files $uri $uri/ @fallback;
}

location @fallback {
    proxy_pass http://app_upstream;
}
```

**Ключевые особенности и архитектурные правила:**
- **Изоляция:** Именованный `location` нельзя сопоставить ни с каким внешним HTTP-запросом, даже если клиент запросит `GET /@fallback` (символ `@` в начале пути URI сопоставляется как обычный символ в префиксном поиске `/@fallback`, а не с блоком `@fallback`).
- **Сохранение `$uri`:** Внутри `@fallback` переменная `$uri` сохраняет исходный путь входящего запроса. Например, при запросе `/api/v1/items` и переходе по `try_files` в `@fallback`, `$uri` будет равен `/api/v1/items`.
- **Запрет вложенности:** Именованный блок не может содержать вложенные блоки `location`, а также не может быть вложен в другие `location`.
- **Отсутствие повторного матчинга:** Переход в именованный `location` происходит мгновенно по прямому указателю конфигурации, минуя вычисления регулярных выражений и префиксных деревьев, что экономит циклы CPU.

### Директива `internal`

Директива `internal;` применяется внутри контекста `location`.

```nginx
location ^~ /protected-store/ {
    internal;
    alias /var/storage/private/;
    sendfile on;
    tcp_nopush on;
}
```

- **Принцип работы:** На фазе проверки доступа (`NGX_HTTP_ACCESS_PHASE`) Nginx проверяет битовый флаг `r->internal`. Если запрос пришел извне по сети (`r->internal == 0`), обработка прерывается.
- **Статус ответа:** Начиная с Nginx 1.25.x, возвращается статус `404 Not Found`. Это исключает утечку информации о топологии внутренних каталогов (в версиях до 1.25.x возвращался статус `403 Forbidden`).
- **Сфера применения:**
  - Корневые каталоги защищенных файлов, раздаваемых через `X-Accel-Redirect`.
  - Внутренние URI страниц ошибок (`error_page 500 /500.html`).
  - Эндпоинты проверки прав модуля `auth_request`.
  - Эндпоинты дублирования трафика модуля `mirror`.

### Архитектура подзапросов (`Subrequests`)

Подзапрос — это легковесная копия структуры запроса, создаваемая модулями Nginx без создания сетевого соединения.

```
[Основной запрос клиента] ─────────────┐
         │                             │
   (auth_request)               (mirror)
         │                             │
         ▼                             ▼
[Подзапрос авторизации]      [Подзапрос зеркалирования]
 (синхронное ожидание         (асинхронный фоновый запрос,
  кода 2xx/401/403)            ответ отбрасывается)
```

1. **Модуль `auth_request`:** Выполняет синхронный подзапрос к указанному URI до фазы генерации контента (`NGX_HTTP_ACCESS_PHASE`). Если авторизационный сервис возвращает HTTP `2xx`, основной запрос продолжается. Если возвращен `401` или `403`, клиенту немедленно возвращается соответствующий статус с передачей заголовка `WWW-Authenticate`.
2. **Модуль `mirror`:** Создает асинхронный подзапрос в фазе предварительного контента (`NGX_HTTP_PRECONTENT_PHASE`). Копия клиентского запроса отправляется на вспомогательный бэкенд (для аудита, теневого тестирования или сбора метрик). Ответ подзапроса полностью игнорируется Nginx и не влияет на задержку ответа клиенту.
3. **Очистка заголовков в подзапросах:** При порождении подзапроса к API-сервисам авторизации тело клиентского запроса по умолчанию может вызвать зависание апстрима. Рекомендуется отключать передачу тела: `proxy_pass_request_body off;` и сбрасывать `proxy_set_header Content-Length "";`.

### Управляющие заголовки семейства `X-Accel-*`

Когда Nginx работает как обратный прокси (`proxy_pass`, `fastcgi_pass`, `uwsgi_pass`), бэкенд может вернуть специальные заголовки для управления поведением Nginx:

| Заголовок ответа апстрима | Назначение | Поведение Nginx |
| :--- | :--- | :--- |
| `X-Accel-Redirect: /uri` | Инициация внутренней отдачи | Nginx перехватывает заголовок, удаляет его из ответа клиенту и выполняет `ngx_http_internal_redirect` на переданный `/uri`. |
| `X-Accel-Limit-Rate: <bytes_per_sec>` | Динамическое ограничение скорости | Устанавливает лимит скорости отдачи (`$limit_rate`) для текущего клиентского соединения (например, `1048576` = 1 МБ/с). |
| `X-Accel-Buffering: yes \| no` | Управление буферизацией | Переопределяет директиву `proxy_buffering` для текущего ответа (полезно для SSE/стриминга). |
| `X-Accel-Charset: <charset>` | Установка кодировки | Переопределяет кодировку `Content-Type` для ответа без модификации бэкенда. |
| `X-Accel-Expires: <seconds \| off \| @epoch>` | Управление кэшированием | Управляет временем жизни ответа в `proxy_cache` (аналог `Cache-Control`). |

> **Критический факт безопасности:** Заголовки `X-Accel-*` обрабатываются Nginx только при поступлении от доверенного бэкенда. Nginx **никогда не пересылает заголовок `X-Accel-Redirect` клиенту**. Если клиент видит `X-Accel-Redirect` в выводе `curl -I`, это свидетельствует о дефекте конфигурации (например, ошибочном использовании `proxy_ignore_headers X-Accel-Redirect;`).

---

## Практические сценарии

### Сценарий 1: Высокопроизводительная защищенная раздача файлов (`X-Accel-Redirect` + Zero-Copy)

**Задача:** Авторизация доступа к крупным файлам (архивы, образы, медиа) выполняется веб-приложением (Python/Node/Go/PHP), а непосредственная отдача данных выполняется Nginx через ядро Linux без нагрузки на приложение.

```nginx
# /etc/nginx/conf.d/secure_storage.conf

upstream backend_app {
    server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 80;
    server_name storage.internal;

    # Точка входа для клиента
    location /download/ {
        proxy_pass http://backend_app;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Внутренний защищенный каталог файлов (недоступен снаружи)
    location ^~ /internal_storage/ {
        internal;
        alias /var/data/private_storage/;

        # Системные оптимизации отдачи Linux
        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;

        # Асинхронный ввод-вывод для файлов более 8 МБ через thread pool
        aio threads=default;
        directio 8m;

        # Безопасность статики
        add_header X-Content-Type-Options "nosniff" always;
        add_header Content-Disposition "attachment" always;
    }
}
```

**Пошаговая логика обработки:**
1. Клиент выполняет запрос `GET /download/report_2026.iso`.
2. Запрос передается в `backend_app`. Приложение проверяет JWT-токен или сессию в СУБД.
3. Приложение определяет путь к файлу на диске и возвращает HTTP-ответ:
   ```http
   HTTP/1.1 200 OK
   X-Accel-Redirect: /internal_storage/iso/report_2026.iso
   X-Accel-Limit-Rate: 5242880
   Content-Type: application/octet-stream
   ```
4. Модуль `ngx_http_upstream` перехватывает `X-Accel-Redirect` и удаляет его из списка заголовков.
5. Nginx запускает `ngx_http_internal_redirect` на `/internal_storage/iso/report_2026.iso`.
6. Срабатывает блок `location ^~ /internal_storage/`. Флаг `internal;` пропускает запрос.
7. Nginx транслирует файл с диска `/var/data/private_storage/iso/report_2026.iso` напрямую через системный вызов `sendfile64(2)`, ограничивая скорость до 5 МБ/с.

### Сценарий 2: Централизованная аутентификация через `auth_request` с передачей контекста

**Задача:** Ограничить доступ к внутреннему веб-интерфейсу администрирования через внешний микросервис проверки прав с передачей идентификатора пользователя.

```nginx
# /etc/nginx/conf.d/admin_portal.conf

server {
    listen 80;
    server_name admin.internal;

    # Защищенная зона
    location / {
        auth_request /auth-verify;

        # Извлечение заголовков ответа auth-сервиса в переменные Nginx
        auth_request_set $user_id $upstream_http_x_user_id;
        auth_request_set $user_role $upstream_http_x_user_role;

        # Проброс контекста пользователя в приложение
        proxy_set_header X-User-Id $user_id;
        proxy_set_header X-User-Role $user_role;

        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    # Внутренний эндпоинт проверки прав
    location = /auth-verify {
        internal;
        proxy_pass http://127.0.0.1:8081/verify-token;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";

        # Передача данных оригинального запроса
        proxy_set_header X-Original-URI $request_uri;
        proxy_set_header X-Original-Method $request_method;
        proxy_set_header X-Real-IP $remote_addr;

        # Тайм-ауты сервиса авторизации (Fail-fast)
        proxy_connect_timeout 2s;
        proxy_read_timeout 2s;
    }

    # Перенаправление неавторизованных пользователей на страницу логина
    error_page 401 = @login_redirect;

    location @login_redirect {
        return 302 http://auth.internal/login?return_to=$scheme://$http_host$request_uri;
    }
}
```

### Сценарий 3: Унифицированная обработка ошибок и API JSON Fallback

**Задача:** Обеспечить возврат стандартизированных JSON-ответов при ошибках Nginx и апстримов (502/503/504) для REST API с сохранением HTTP-методов и исключением ошибки `405 Method Not Allowed`.

```nginx
# /etc/nginx/conf.d/api_gateway.conf

server {
    listen 80;
    server_name api.internal;

    # Перехват ошибок от апстримов
    proxy_intercept_errors on;
    fastcgi_intercept_errors on;

    # Назначение обработчиков через именованные location
    error_page 400 = @json_400;
    error_page 404 = @json_404;
    error_page 500 502 503 504 = @json_50x;

    location /v1/ {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }

    # Именованные обработчики гарантируют работу для любых HTTP-методов (GET/POST/PUT/DELETE)
    location @json_400 {
        internal;
        default_type application/json;
        return 400 '{"status": 400, "error": "Bad Request", "path": "$request_uri"}\n';
    }

    location @json_404 {
        internal;
        default_type application/json;
        return 404 '{"status": 404, "error": "Resource Not Found", "path": "$request_uri"}\n';
    }

    location @json_50x {
        internal;
        default_type application/json;
        add_header Retry-After 30 always;
        return 502 '{"status": 502, "error": "Bad Gateway / Service Unavailable", "timestamp": "$time_iso8601"}\n';
    }
}
```

### Сценарий 4: Теневое зеркалирование трафика через `mirror` (Traffic Shadowing)

**Задача:** Протестировать новую версию сервиса на реальном производственном трафике без риска для пользователей и без задержки основного ответа.

```nginx
# /etc/nginx/conf.d/traffic_shadow.conf

server {
    listen 80;
    server_name service.internal;

    location /api/ {
        proxy_pass http://production_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;

        # Зеркалирование запросов
        mirror /mirror_traffic;
        mirror_request_body on;
    }

    location = /mirror_traffic {
        internal;
        proxy_pass http://canary_backend$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Shadow-Traffic "true";

        # Жесткая изоляция: при сбое канарейки клиент не страдает
        proxy_connect_timeout 500ms;
        proxy_read_timeout 1s;
        proxy_send_timeout 1s;

        # Игнорирование клиентских разрывов для зеркала
        proxy_ignore_client_abort on;
    }
}
```

### Сценарий 5: Динамический Maintenance-режим без перезагрузки Nginx

**Задача:** Перевод сервиса в режим обслуживания по триггеру файла на диске с гарантией запрета прямого доступа к файлу обслуживания и запретом кэширования в браузерах.

```nginx
# /etc/nginx/conf.d/maintenance.conf

server {
    listen 80;
    server_name app.internal;
    root /var/www/app/public;

    # Проверка наличия триггер-файла на диске
    if (-f /var/run/maintenance.flag) {
        return 503;
    }

    error_page 503 @maintenance_view;

    location / {
        try_files $uri $uri/ @app_upstream;
    }

    location @app_upstream {
        proxy_pass http://127.0.0.1:8000;
    }

    # Изолированный обработчик 503
    location @maintenance_view {
        internal;
        root /var/www/maintenance;
        rewrite ^(.*)$ /maintenance.html break;

        # Запрет кэширования аварийной заглушки промежуточными прокси
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
        add_header Pragma "no-cache" always;
        add_header Retry-After "300" always;
    }
}
```

### Сценарий 6: Оптимизированный каскад `try_files` со статикой и SPA/API

**Задача:** Организовать производительную отдачу фронтенда Single Page Application с отдачей существующих файлов и перенаправлением динамики на бэкенд без зацикливания.

```nginx
# /etc/nginx/conf.d/spa_routing.conf

server {
    listen 80;
    server_name portal.internal;
    root /var/www/portal/dist;
    index index.html;

    # Статические ассеты с долгосрочным кэшем
    location ^~ /assets/ {
        sendfile on;
        tcp_nopush on;
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    # Маршрутизация страниц SPA: если файла нет на диске, отдаем index.html
    location / {
        try_files $uri $uri/ @spa_fallback;
    }

    # Именованный fallback не меняет $uri и исключает циклы
    location @spa_fallback {
        add_header Cache-Control "no-cache, must-revalidate";
        rewrite ^ /index.html break;
    }
}
```

---

## Операции и команды

### Валидация конфигурации и инспекция топологии

```bash
# Синтаксическая проверка конфигурационных файлов
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Дамп полной активной конфигурации с поиском внутренних и именованных локаций
nginx -T | grep -E "(location\s+@|internal;)"
# → location @fallback {
# → location @json_404 {
# →     internal;
# → location = /auth-verify {
# →     internal;

# Безопасное применение изменений без сброса активных клиентских соединений
nginx -s reload
# → signal processed
```

### Тестирование внутренних маршрутов через `curl`

```bash
# 1. Проверка защищенности internal-локации (прямой доступ снаружи ДОЛЖЕН возвращать 404)
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/internal_storage/secret.pdf
# → 404

# 2. Проверка работы X-Accel-Redirect через точку входа бэкенда
# Заголовок X-Accel-Redirect НЕ должен присутствовать в клиентском ответе
curl -sI http://127.0.0.1/download/report_2026.iso
# → HTTP/1.1 200 OK
# → Server: nginx/1.26.2
# → Content-Type: application/octet-stream
# → Content-Length: 104857600
# → Accept-Ranges: bytes

# 3. Тестирование auth_request: успешная аутентификация
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer valid_token" http://127.0.0.1/admin/
# → 200

# 4. Тестирование auth_request: отсутствие токена (перехват 401 и редирект 302)
curl -sI http://127.0.0.1/admin/
# → HTTP/1.1 302 Moved Temporarily
# → Location: http://auth.internal/login?return_to=http://admin.internal/admin/
```

### Отладка в Nginx Debug Log

Для отслеживания каждого шага внутренней маршрутизации собирается отладочный лог:

```nginx
# В контексте main или http:
error_log /var/log/nginx/debug.log debug;
```

Инспекция лога позволяет увидеть инкремент перенаправлений и смену `location`:

```bash
# Отслеживание переходов внутренних редиректов по конкретному соединению
tail -f /var/log/nginx/debug.log | grep -E "(internal redirect|using location|uri_changes)"
# → *1042 internal redirect: "/internal_storage/iso/report_2026.iso?"
# → *1042 test location: "download/"
# → *1042 using location: "^~ /internal_storage/"
# → *1042 http script var: "$uri" = "/internal_storage/iso/report_2026.iso"
```

### Мониторинг системных вызовов Linux (SRE/Sysadmin)

Проверка реального использования Zero-Copy (`sendfile`) процессом Nginx воркер:

```bash
# Поиск PID воркеров Nginx
pgrep -f "nginx: worker process"
# → 4120
# → 4121

# Трассировка системного вызова sendfile при скачивании файла через X-Accel-Redirect
strace -p 4120 -f -e trace=sendfile,sendfile64,openat,close
# → openat(AT_FDCWD, "/var/data/private_storage/iso/report_2026.iso", O_RDONLY|O_NONBLOCK) = 14
# → sendfile64(12, 14, [0], 1048576) = 1048576
```

### Аудит циклов редиректа в журнале ошибок

```bash
# Поиск ошибок зацикливания маршрутизации (HTTP 500)
grep "rewrite or internal redirection cycle" /var/log/nginx/error.log
# → 2026/10/16 10:15:30 [error] 4120#4120: *512 rewrite or internal redirection cycle while internal redirection to "/index.html", client: 192.168.1.50, server: portal.internal, request: "GET / HTTP/1.1"

# Выявление URI, вызывающих максимальное количество внутренних ошибок 500
awk '$9 == "500" {print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10
```

### Управление правами доступа и контекстами безопасности в ОС

Для корректной отдачи защищенных файлов через `X-Accel-Redirect` учетная запись Nginx (`nginx` на RHEL/Rocky или `www-data` на Debian/Ubuntu) должна иметь доступ на чтение файлов и выполнение для директорий:

```bash
# Назначение владельца и прав доступа на каталог хранилища
chown -R root:nginx /var/data/private_storage
find /var/data/private_storage -type d -exec chmod 750 {} \;
find /var/data/private_storage -type f -exec chmod 640 {} \;

# SELinux (RHEL, Rocky Linux, AlmaLinux): установка контекста веб-сервера
semanage fcontext -a -t httpd_sys_content_t "/var/data/private_storage(/.*)?"
restorecon -Rv /var/data/private_storage

# Проверка контекста SELinux
ls -dZ /var/data/private_storage
# → system_u:object_r:httpd_sys_content_t:s0 /var/data/private_storage

# AppArmor (Ubuntu/Debian): проверка профиля Nginx
aa-status | grep nginx
# → /usr/sbin/nginx (enforce)
```

---

## Диагностика и устранение неполадок

### Матрица типичных неисправностей

| Симптом | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **HTTP 500** `rewrite or internal redirection cycle` | Превышен лимит 10 перенаправлений (`NGX_HTTP_MAX_URI_CHANGES`). Циклическая переадресация в `try_files` или `error_page`. | Анализ `error.log`: строка с указанием конечного URI цикла. | Заменить финальный URI в `try_files` на именованный `@fallback` или использовать флаг `break`. |
| **HTTP 405** `Method Not Allowed` при обработке ошибок | `POST`/`PUT` запрос завершился ошибкой и был перенаправлен на статический `.html` файл через `error_page`. | `curl -X POST http://host/api/` возвращает 405 со стандартной HTML-страницей Nginx. | Перенаправлять `error_page` на именованный `location @error` с `return` или настроить `error_page 405 =200 /error.html;`. |
| **HTTP 404** при корректной отдаче через `X-Accel-Redirect` | Несоответствие путей в `alias`/`root` или отсутствие завершающего слэша в директиве `alias`. | Сравнение префикса в заголовке бэкенда и пути в `error_log` (`file not found`). | Убедиться, что URI в заголовке начинается с префикса `location`. При использовании `alias` завершающий слэш обязателен. |
| **Заголовок `X-Accel-Redirect` отображается клиенту** | Nginx не перехватил заголовок из-за директивы `proxy_ignore_headers` или некорректного апстрим-модуля. | `curl -sI` показывает заголовок `X-Accel-Redirect`. | Удалить `X-Accel-Redirect` из `proxy_ignore_headers`. Проверить, что ответ идет от `proxy_pass`/`fastcgi_pass`. |
| **Потеря Query String (`$args`) при перенаправлении** | Редирект в директиве `rewrite` без флага сохранения аргументов или неверная конструкция `proxy_pass`. | В логах апстрима отсутствуют параметры запроса (`?key=val`). | В `proxy_pass` передавать `$request_uri` либо явно указывать `$is_args$args`. |
| **Зависание `auth_request`** | Nginx пытается передать тело большого POST-запроса в сервис проверки аутентификации. | Зависание клиента на фазе отправки тела, тайм-аут `auth_request`. | Добавить в `location` авторизации: `proxy_pass_request_body off;` и `proxy_set_header Content-Length "";`. |
| **HTTP 403 вместо 404 для `internal`** | Эксплуатация устаревшей версии Nginx (< 1.25.x). | Проверка `nginx -v`. | Обновить Nginx до актуальной стабильной ветки (1.26.x/1.27.x). |

### Глубокий разбор ловушек конфигурации

#### 1. Цикл `try_files` на index.html
**Проблема:**
```nginx
# ОШИБКА: приводит к циклу 500
location / {
    try_files $uri $uri/ /index.html;
}
```
Если клиент запрашивает `/index.html`, а файла нет на диске, `try_files` пробует `$uri` (нет), `$uri/` (нет) и переходит к последнему элементу `/index.html`. Nginx выполняет внутренний редирект на `/index.html`, снова попадает в `location /`, и процесс повторяется 10 раз до возврата 500.

**Решение:**
Использовать именованный `location`:
```nginx
location / {
    try_files $uri $uri/ @fallback;
}

location @fallback {
    rewrite ^ /index.html break;
}
```

#### 2. Ошибка "Off-by-slash" в связке `internal` + `alias`
**Проблема:**
```nginx
# ОШИБКА: рассинхронизация слэшей
location /protected/ {
    internal;
    alias /var/data/files; # Нет слэша в конце!
}
```
При заголовке `X-Accel-Redirect: /protected/docs/spec.pdf` Nginx отрезает префикс `/protected/` и конкатенирует остаток `docs/spec.pdf` с путем `alias`. Результат: `/var/data/filesdocs/spec.pdf` вместо `/var/data/files/docs/spec.pdf`.

**Решение:**
Строго следить за соответствием слэшей:
```nginx
location ^~ /protected/ {
    internal;
    alias /var/data/files/; # Слэш на конце обязателен!
}
```

#### 3. Блокировка POST/PUT запросов при вызове `error_page`
**Проблема:**
Клиент отправляет `POST /api/items`. Апстрим недоступен (502). В Nginx настроено:
```nginx
error_page 502 /502.html;
```
Nginx выполняет внутренний редирект на `/502.html`. Статический модуль обработки файлов проверяет метод `$request_method`. Поскольку метод `POST`, а статический файл не может принимать тело, Nginx возвращает клиенту **405 Method Not Allowed** вместо понятной ошибки сервера 502.

**Решение:**
Использовать именованный блок:
```nginx
error_page 502 @handle_502;

location @handle_502 {
    internal;
    default_type application/json;
    return 502 '{"error": "Backend unavailable"}\n';
}
```

---

## Лучшие практики

### Безопасность (Hardening)

1. **Строгое закрытие директивой `internal;`:** Любые служебные блоки (обработчики ошибок, эндпоинты `auth_request`, пути `X-Accel-Redirect`, зеркала `mirror`) обязаны содержать директиву `internal;`. Это полностью предотвращает сканирование и прямой вызов внутренних ресурсов из интернета.
2. **Изоляция директорий отдачи:** Каталоги, указанные в `alias`/`root` для `X-Accel-Redirect`, должны располагаться вне общего `root` веб-сайта. Например: сайт в `/var/www/site/public`, защищенные файлы в `/var/data/secure_storage`.
3. **Нормализация путей от бэкенда:** При генерации заголовка `X-Accel-Redirect` бэкенд обязан валидировать и санировать путь к файлу, исключая последовательности directory traversal (`../`).
4. **Схлопывание слэшей:** Убедитесь, что директива `merge_slashes on;` активна (по умолчанию включена). Это предотвращает обход совпадений `location` при множественных слэшах (`//protected//file`).
5. **Сокрытие версии сервера:** Директива `server_tokens off;` в контексте `http` должна быть включена для предотвращения раскрытия версии Nginx в ответах с кодами ошибок.

### Производительность и Zero-Copy

1. **Связка `sendfile` + `tcp_nopush`:** Для статических файлов, отдаваемых через `X-Accel-Redirect`, обязательно включать `sendfile on;` и `tcp_nopush on;`. Это активирует режим полной упаковки сетевых пакетов TCP до отправки клиенту, снижая накладные расходы на прерывания ядра.
2. **Пул потоков (`aio threads`) для больших объемов:** Чтение файлов размером в сотни мегабайт с медленных дисков блокирует рабочий процесс воркера Nginx. Выносите ввод-вывод в пулы потоков:
   ```nginx
   # /etc/nginx/nginx.conf
   thread_pool default threads=32 max_queue=65536;
   
   # В блоке location:
   aio threads=default;
   directio 8m;
   ```
3. **Использование `@name` вместо URI для fallback:** Именованные `location` не требуют повторного прохода по дереву префиксов и таблице PCRE, экономя время обработки каждого входящего запроса.

### Эксплуатация и надёжность (SRE / Sysadmin)

1. **Тайм-ауты в подзапросах `auth_request`:** Задержки на сервисе авторизации напрямую транслируются в задержку для конечного пользователя. Устанавливайте жесткие лимиты: `proxy_connect_timeout 1s; proxy_read_timeout 2s;`.
2. **Мониторинг циклов маршрутизации:** Настройте в системе мониторинга (Prometheus + mtail / Vector / logstash) алерт на появление паттерна `rewrite or internal redirection cycle` в журнале `error.log`. Это критическая ошибка проектирования конфигурации.
3. **Логирование внутренних параметров:** Добавляйте переменные `$upstream_status`, `$request_time` и `$upstream_response_time` в формат `log_format` для разделения задержек Nginx и времени ответа бэкенда при внутренней маршрутизации.
4. **Применение принципа Fail-Safe:** Если сервис `auth_request` недоступен, Nginx по умолчанию вернет 500 (Fail-Closed). Если политика сервиса допускает деградацию, используйте `error_page 500 502 503 504 = @auth_fallback;`.

---

## Дополнительная информация

### См. также в базе знаний

- **[Директива location: основы и приоритеты](./basics.md)** — алгоритм поиска по префиксному дереву (Trie), регулярным выражениям PCRE и фазы обработки Nginx.
- **[Nginx location: примеры интеграции](./integration_examples.md)** — эталонные шаблоны сопряжения с PHP-FPM, UWSGI, ASGI, Node.js и сокетами Unix.
- **[Перенаправления и перезапись URI в Nginx](../nginx_rewrite_rules_and_try_files.md)** — детальный разбор директив `rewrite`, `return`, `try_files` и константы `NGX_HTTP_MAX_URI_CHANGES`.
- **[Maintenance-режим в Nginx](../../Scenarios/nginx_maintenance_mode.md)** — развертывание необслуживаемого режима с использованием `internal` и `error_page`.
- **[Диагностика и устранение неполадок Nginx](../../Operations/nginx_troubleshooting.md)** — методология анализа аварийных ситуаций, дампов памяти и системных логов.

### Официальная документация и исходный код

- [Nginx ngx_http_core_module: Directives internal, error_page, try_files](https://nginx.org/en/docs/http/ngx_http_core_module.html)
- [Nginx ngx_http_auth_request_module](https://nginx.org/en/docs/http/ngx_http_auth_request_module.html)
- [Nginx ngx_http_mirror_module](https://nginx.org/en/docs/http/ngx_http_mirror_module.html)
- [X-Accel headers specification](https://www.nginx.com/resources/wiki/start/topics/examples/x-accel/)
- Исходный код Nginx: `src/http/ngx_http_core_module.c` (`ngx_http_internal_redirect`), `src/http/ngx_http_request.c` (`ngx_http_subrequest`).
