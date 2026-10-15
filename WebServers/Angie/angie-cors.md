# CORS в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**CORS (Cross-Origin Resource Sharing)** — стандарт безопасности, реализованный на уровне веб-браузеров, разрешающий веб-странице одного происхождения (Origin) запрашивать ресурсы с сервера другого происхождения. Механизм защищает пользователей от чтения конфиденциальных данных сторонними сайтами через AJAX-запросы (`fetch`, `XMLHttpRequest`).

**Origin (Источник)** — комбинация протокола (схемы), доменного имени (хоста) и порта сетевого адреса (например, `https://app.example.com:443`). Два адреса считаются разными источниками, если различается хотя бы один из этих компонентов.

**Preflight Request (Предварительный запрос)** — предварительный HTTP-запрос методом `OPTIONS`, автоматически отправляемый браузером перед выполнением основного запроса. Отправляется для «непростых» (non-simple) запросов: при использовании методов `PUT`, `DELETE`, `PATCH`, кастомных HTTP-заголовков (например, `Authorization`, `X-Request-ID`) или типов содержимого, отличных от стандартных форм (`application/json`). Сервер должен вернуть статус `200` или `204` с набором разрешающих заголовков.

**Simple Request (Простой запрос)** — запрос браузера, не требующий preflight-проверки. Должен использовать методы `GET`, `HEAD` или `POST`, стандартные заголовки (`Accept`, `Accept-Language`, `Content-Language`) и безопасный `Content-Type` (`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`).

**Credentialed Request (Запрос с аутентификацией)** — запрос с включенной передачей учетных данных (`credentials: 'include'`), таких как Cookies, HTTP-аутентификация (Basic/Digest) или TLS-сертификаты клиента. В спецификации CORS для таких запросов категорически запрещено использование подстановочного символа `*` в ответе сервера.

## Архитектура и принцип работы

### Жизненный цикл CORS-запроса

Обработка CORS делится на два сценария взаимодействия между браузером, обратным прокси Angie и upstream-бэкендом:

1. **Простой запрос (Simple Request):**
   - Браузер отправляет запрос с заголовком `Origin: https://app.example.com`.
   - Angie сверяет переданный `Origin` со списком разрешенных доменов.
   - Если домен разрешен, Angie передает запрос в upstream и возвращает ответ клиенту с заголовком `Access-Control-Allow-Origin`.
   - Браузер проверяет наличие разрешающего заголовка; если заголовок отсутствует или не совпадает, браузер блокирует чтение ответа клиентским скриптом (сам HTTP-запрос при этом достигает сервера).

2. **Запрос с предварительной проверкой (Preflight OPTIONS):**
   - Браузер задерживает основной запрос и отправляет легковесный `OPTIONS` с заголовками:
     - `Origin: https://app.example.com`
     - `Access-Control-Request-Method: POST`
     - `Access-Control-Request-Headers: authorization, content-type`
   - Angie перехватывает `OPTIONS` на уровне обратного прокси, не нагружая upstream-сервер.
   - Angie возвращает статус `204 No Content` с заголовками допустимых методов, заголовков и времени кэширования решения (`Access-Control-Max-Age`).
   - Браузер сохраняет параметры в кэше и отправляет основной рабочий запрос.

```
+---------+                 +---------------+                 +-----------------+
| Browser |                 | Angie (Proxy) |                 | Upstream API    |
+---------+                 +---------------+                 +-----------------+
     |                              |                                  |
     | [Preflight] OPTIONS /api/    |                                  |
     | Origin: https://app...       |                                  |
     | Access-Control-Request-M...  |                                  |
     |----------------------------->| (Terminates preflight locally)   |
     |                              |                                  |
     | 204 No Content               |                                  |
     | Access-Control-Allow-Origin  |                                  |
     | Access-Control-Allow-Methods |                                  |
     | Access-Control-Max-Age: 86400|                                  |
     |<-----------------------------|                                  |
     |                              |                                  |
     | [Actual] POST /api/data      |                                  |
     | Origin: https://app...       |   POST /api/data                 |
     | Authorization: Bearer ...    |--------------------------------->|
     |----------------------------->|                                  |
     |                              |   200 OK (JSON payload)          |
     |                              |<---------------------------------|
     | 200 OK (JSON payload)        |                                  |
     | Access-Control-Allow-Origin  |                                  |
     | Vary: Origin                 |                                  |
     |<-----------------------------|                                  |
```

### Спецификация заголовков ответа CORS

| Заголовок | Описание и назначение |
|:---|:---|
| `Access-Control-Allow-Origin` | Указывает один конкретный разрешенный источник (`https://app.example.com`) либо подстановочный символ `*` (только для открытых данных без учетных данных). |
| `Access-Control-Allow-Methods` | Список разрешенных HTTP-методов для кросс-доменных запросов (`GET, POST, PUT, DELETE, PATCH, OPTIONS`). |
| `Access-Control-Allow-Headers` | Список заголовков, которые клиентскому приложению разрешено отправлять в preflight-запросе (`Authorization, Content-Type, X-Request-ID`). |
| `Access-Control-Allow-Credentials` | Флаг (`true`), разрешающий браузеру передавать Cookies и заголовки авторизации. Несовместим со значением `*` в `Access-Control-Allow-Origin`. |
| `Access-Control-Max-Age` | Время в секундах, в течение которого браузеру разрешено кэшировать результат preflight-запроса, не повторяя `OPTIONS` при каждом вызове (например, `86400` — 24 часа). |
| `Access-Control-Expose-Headers` | Список заголовков ответа сервера, к которым клиентский JavaScript имеет доступ (`Content-Length, X-Request-ID, Content-Disposition`). По умолчанию браузер предоставляет доступ только к базовым заголовкам (`Cache-Control`, `Content-Language`, `Content-Type`, `Expires`, `Last-Modified`, `Pragma`). |

### Особенности поведения Angie в роли обратного прокси

1. **Ловушка наследования директивы `add_header`:**
   В архитектуре Angie директивы `add_header` наследуются с предыдущего уровня конфигурации (`http` -> `server` -> `location`) **только в том случае, если на текущем уровне не задано ни одной директивы `add_header`**. Если внутри блока `location` объявляется хотя бы один локальный заголовок (например, `add_header X-Debug 1;`), абсолютно все заголовки CORS, объявленные на уровне `server` или `http`, перестают добавляться в ответ. В производственной среде это решается изоляцией CORS-конфигурации в отдельные включаемые файлы (`include`).

2. **Флаг `always`:**
   По умолчанию директива `add_header` добавляет заголовки только для успешных ответов со статусами `200`, `201`, `204`, `206`, `301`, `302`, `303`, `304`, `307` или `308`. Если бэкенд возвращает ошибку (`401 Unauthorized`, `403 Forbidden`, `404 Not Found`, `500 Internal Server Error`, `502 Bad Gateway`), заголовки без флага `always` будут отброшены. В результате браузер перехватывает ответ как «ошибку CORS» и скрывает реальный код ошибки и тело ответа от разработчика. Использование флага `always` обязательно для всех CORS-заголовков.

3. **Защита кэша и CDN (`Vary: Origin`):**
   Если перед Angie или внутри него используется HTTP-кэширование (`proxy_cache`), сервер обязан отдавать заголовок `Vary: Origin`. Без этого заголовок ответа, сформированный для первого запросившего пользователя (`Access-Control-Allow-Origin: https://app.example.com`), сохранится в кэше и будет отдан другому клиенту, пришедшему с `https://admin.example.com`, что приведет к блокировке запроса браузером второго клиента.

4. **Дублирование заголовков upstream-бэкендом:**
   Если бэкенд-приложение (Node.js, Go, Python, Java) уже генерирует собственные заголовки CORS, а Angie добавляет свои через `add_header`, браузер получит дублирующиеся заголовки (например, `Access-Control-Allow-Origin: https://app.example.com, https://app.example.com` или `*, https://app.example.com`) и заблокирует запрос. В конфигурации Angie необходимо либо подавлять заголовки бэкенда директивой `proxy_hide_header`, либо централизованно управлять CORS исключительно на уровне прокси.

## Практические сценарии и конфигурация

### Предварительные требования

- Установленный веб-сервер Angie 1.12.x или Angie PRO 1.12.x в операционной системе Linux (Debian, Ubuntu, Rocky Linux, AlmaLinux, RHEL).
- Наличие прав суперпользователя `root` или `sudo` для редактирования файлов конфигурации (`/etc/angie/angie.conf`, `/etc/angie/http.d/`).
- Базовый upstream-сервис (например, REST API на `http://127.0.0.1:8080`).

### Сценарий 1: Публичный API без авторизации (Wildcard)

Подходит для публичных шрифтов, статических файлов, открытых API каталогов или документации, где не используются cookies и авторизационные токены.

```nginx
# /etc/angie/http.d/public_api.conf
server {
    listen 443 ssl;
    server_name static-api.example.com;

    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    location /v1/public/ {
        # Preflight запросы
        if ($request_method = OPTIONS) {
            add_header Access-Control-Allow-Origin "*" always;
            add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
            add_header Access-Control-Allow-Headers "Accept, Authorization, Content-Type, Origin" always;
            add_header Access-Control-Max-Age 86400 always;
            add_header Content-Type "text/plain; charset=utf-8";
            add_header Content-Length 0;
            return 204;
        }

        # Основные запросы
        add_header Access-Control-Allow-Origin "*" always;
        add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
        add_header Access-Control-Expose-Headers "Content-Length, Content-Range" always;

        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Сценарий 2: Производственный API с белым списком доменов и учетными данными (Credentials)

Рекомендуемый подход для защищенных микросервисов и API, использующих Cookie, сессии или Bearer-токены. Список разрешенных Origin валидируется через `map` в контексте `http`.

```nginx
# /etc/angie/http.d/cors_map.conf
# Блок map объявляется в контексте http (на уровне http.d/)
map $http_origin $cors_allowed_origin {
    default "";
    "https://app.example.com"             "https://app.example.com";
    "https://admin.example.com"           "https://admin.example.com";
    "https://partner.example.org"         "https://partner.example.org";
    # Допустимо использование регулярных выражений для dev/stage стендов:
    "~^https://[a-z0-9-]+--stage\.example\.com$" "$http_origin";
}

# Определение разрешенных методов для preflight
map $request_method $cors_preflight_method {
    default 0;
    OPTIONS 1;
}
```

Конфигурация виртуального хоста API:

```nginx
# /etc/angie/http.d/api.conf
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate /etc/ssl/certs/api.example.com.crt;
    ssl_certificate_key /etc/ssl/private/api.example.com.key;

    location /api/ {
        # Терминация Preflight на уровне прокси без передачи на бэкенд
        if ($cors_preflight_method) {
            add_header Access-Control-Allow-Origin $cors_allowed_origin always;
            add_header Access-Control-Allow-Credentials "true" always;
            add_header Access-Control-Allow-Methods "GET, POST, PUT, PATCH, DELETE, OPTIONS" always;
            add_header Access-Control-Allow-Headers "Accept, Authorization, Content-Type, Origin, X-Request-ID, X-Requested-With" always;
            add_header Access-Control-Max-Age 86400 always;
            add_header Vary "Origin" always;
            add_header Content-Type "text/plain; charset=utf-8";
            add_header Content-Length 0;
            return 204;
        }

        # Заголовки для фактических рабочих запросов (GET, POST и т.д.)
        if ($cors_allowed_origin) {
            add_header Access-Control-Allow-Origin $cors_allowed_origin always;
            add_header Access-Control-Allow-Credentials "true" always;
            add_header Access-Control-Expose-Headers "Content-Length, X-Request-ID" always;
            add_header Vary "Origin" always;
        }

        # Изоляция от дублирования CORS-заголовков бэкендом
        proxy_hide_header Access-Control-Allow-Origin;
        proxy_hide_header Access-Control-Allow-Credentials;
        proxy_hide_header Access-Control-Allow-Methods;
        proxy_hide_header Access-Control-Allow-Headers;

        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Сценарий 3: Модульная организация через Snippets (DRY для кластеров и множества сервисов)

Для исключения дублирования десятков строк `add_header` в каждом блоке `location` параметры CORS выносятся во включаемый фрагмент конфигурации.

1. Создание каталога и файла фрагмента:

```bash
sudo mkdir -p /etc/angie/snippets
```

```nginx
# /etc/angie/snippets/cors_headers.conf
# Проверка наличия совпадения в карте $cors_allowed_origin
if ($request_method = OPTIONS) {
    add_header Access-Control-Allow-Origin $cors_allowed_origin always;
    add_header Access-Control-Allow-Credentials "true" always;
    add_header Access-Control-Allow-Methods "GET, POST, PUT, PATCH, DELETE, OPTIONS" always;
    add_header Access-Control-Allow-Headers "Accept, Authorization, Content-Type, Origin, X-Request-ID, X-Requested-With" always;
    add_header Access-Control-Max-Age 86400 always;
    add_header Vary "Origin" always;
    add_header Content-Type "text/plain; charset=utf-8";
    add_header Content-Length 0;
    return 204;
}

if ($cors_allowed_origin) {
    add_header Access-Control-Allow-Origin $cors_allowed_origin always;
    add_header Access-Control-Allow-Credentials "true" always;
    add_header Access-Control-Expose-Headers "Content-Length, X-Request-ID" always;
    add_header Vary "Origin" always;
}

proxy_hide_header Access-Control-Allow-Origin;
proxy_hide_header Access-Control-Allow-Credentials;
proxy_hide_header Access-Control-Allow-Methods;
proxy_hide_header Access-Control-Allow-Headers;
```

2. Подключение фрагмента в целевых локациях:

```nginx
# /etc/angie/http.d/microservices.conf
server {
    listen 443 ssl;
    server_name gateway.example.com;

    ssl_certificate /etc/ssl/certs/gateway.example.com.crt;
    ssl_certificate_key /etc/ssl/private/gateway.example.com.key;

    location /services/users/ {
        include /etc/angie/snippets/cors_headers.conf;
        proxy_pass http://127.0.0.1:8081;
    }

    location /services/billing/ {
        include /etc/angie/snippets/cors_headers.conf;
        proxy_pass http://127.0.0.1:8082;
    }

    location /services/orders/ {
        include /etc/angie/snippets/cors_headers.conf;
        proxy_pass http://127.0.0.1:8083;
    }
}
```

### Сценарий 4: Аудит и мониторинг CORS через access_log

Системному администратору и инженеру SRE важно отслеживать несанкционированные попытки запросов с чужих сайтов, а также фиксировать распределение клиентов по Origin.

Определение формата журнала в контексте `http`:

```nginx
# /etc/angie/http.d/logging_cors.conf
log_format cors_detailed '$remote_addr - $remote_user [$time_local] '
                         '"$request" $status $body_bytes_sent '
                         'origin="$http_origin" cors_status="$cors_allowed_origin" '
                         'ua="$http_user_agent" rt=$request_time';

server {
    listen 443 ssl;
    server_name api.example.com;

    access_log /var/log/angie/cors_access.log cors_detailed;

    # ... остальная конфигурация ...
}
```

Анализ журнала с помощью утилит командной строки Linux:

```bash
# Подсчет уникальных Origin и количества запросов
awk -F'origin=' '{print $2}' /var/log/angie/cors_access.log | awk '{print $1}' | sort | uniq -c | sort -rn
# → 14250 "https://app.example.com"
# →  3100 "https://admin.example.com"
# →    45 "https://unauthorized-site.com"
# →    12 "-"

# Поиск нелегитимных Origin, для которых заголовок CORS не был выдан ($cors_allowed_origin="")
grep 'cors_status=""' /var/log/angie/cors_access.log | head -n 5
# → 198.51.100.24 - - [14/Oct/2026:14:22:10 +0300] "GET /api/v1/user HTTP/1.1" 200 512 origin="https://malicious-web.ru" cors_status="" ua="Mozilla/5.0..." rt=0.012
```

## Операции и валидация

### Проверка конфигурации и применение изменений

Перед применением новой конфигурации необходимо выполнить синтаксическую валидацию и плавную перезагрузку рабочего процесса:

```bash
# 1. Проверка синтаксиса конфигурационных файлов
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Применение изменений без остановки обслуживания клиентов (graceful reload)
sudo systemctl reload angie
# → (процесс завершается без вывода ошибок, статус active)

# 3. Контроль статуса службы
systemctl is-active angie
# → active
```

### Комплексный прогон проверок (Validation Suite)

Для тестирования используется утилита `curl` с эмуляцией заголовков веб-браузера:

1. **Проверка разрешенного Origin (Simple Request):**

```bash
curl -sI -H "Origin: https://app.example.com" https://api.example.com/api/status | grep -iE 'access-control|vary'
# → access-control-allow-origin: https://app.example.com
# → access-control-allow-credentials: true
# → access-control-expose-headers: Content-Length, X-Request-ID
# → vary: Origin
```

2. **Проверка запрещенного / стороннего Origin:**

```bash
curl -sI -H "Origin: https://attacker.example.org" https://api.example.com/api/status | grep -i access-control
# → (вывод пуст, заголовки Access-Control-* не передаются)
```

3. **Проверка Preflight OPTIONS запроса:**

```bash
curl -si -X OPTIONS https://api.example.com/api/users \
  -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Authorization, Content-Type, X-Request-ID" \
  | head -n 12
# → HTTP/1.1 204 No Content
# → Server: Angie
# → Access-Control-Allow-Origin: https://app.example.com
# → Access-Control-Allow-Credentials: true
# → Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS
# → Access-Control-Allow-Headers: Accept, Authorization, Content-Type, Origin, X-Request-ID, X-Requested-With
# → Access-Control-Max-Age: 86400
# → Vary: Origin
# → Content-Type: text/plain; charset=utf-8
# → Content-Length: 0
```

4. **Проверка сохранения CORS-заголовков на ошибках (флаг `always`):**

```bash
curl -sI -H "Origin: https://app.example.com" https://api.example.com/api/non-existent-endpoint | grep -iE 'http/|access-control-allow-origin'
# → HTTP/1.1 404 Not Found
# → access-control-allow-origin: https://app.example.com
```

5. **Проверка отсутствия дублирования заголовков от upstream:**

```bash
curl -sI -H "Origin: https://app.example.com" https://api.example.com/api/data | grep -c -i 'access-control-allow-origin'
# → 1
```

## Диагностика и устранение неполадок

| Симптом / Ошибка в консоли браузера | Вероятная причина | Метод диагностики | Способ устранения |
|:---|:---|:---|:---|
| `No 'Access-Control-Allow-Origin' header is present on the requested resource` | 1. `Origin` запроса отсутствует в белом списке `map`.<br>2. Запрос завершился ошибкой (4xx/5xx), а в директивах `add_header` не указан параметр `always`. | Выполнить `curl -sI -H "Origin: <domain>" <URL>`. Проверить журнал `/var/log/angie/cors_access.log`. | Добавить домен в карту `map $http_origin $cors_allowed_origin` либо добавить флаг `always` ко всем директивам `add_header`. |
| `The 'Access-Control-Allow-Origin' header contains multiple values '*, https://app...'` | Заголовок `Access-Control-Allow-Origin` выставляется одновременно и веб-сервером Angie, и бэкенд-приложением. | Выполнить `curl -sI -H "Origin: ..." <URL>` и посчитать количество строк `Access-Control-Allow-Origin`. | Добавить в `location` директиву `proxy_hide_header Access-Control-Allow-Origin;` либо отключить генерацию заголовков в коде бэкенда. |
| `The value of the 'Access-Control-Allow-Origin' header in the response must not be the wildcard '*' when the request's credentials mode is 'include'` | В конфигурации указано значение `*` совместно с `Access-Control-Allow-Credentials: true`. | Поиск по конфигурации: `grep -rn 'Access-Control-Allow-Origin "\*"' /etc/angie/`. | Заменить wildcard `*` на динамическое сопоставление через `map $http_origin`, возвращающее точный Origin клиента. |
| `Method Not Allowed (HTTP 405)` или `Forbidden (HTTP 403)` на запрос `OPTIONS` | 1. Запрос `OPTIONS` передается в upstream-сервер, который не поддерживает данный метод.<br>2. Директива `limit_except` блокирует `OPTIONS`. | Проверить ответ: `curl -si -X OPTIONS <URL>`. Изучить блок `limit_except` в `angie.conf`. | Реализовать перехват метода: `if ($request_method = OPTIONS) { return 204; }` и разрешить `OPTIONS` в `limit_except`. |
| `Request header field X-Custom-Header is not allowed by Access-Control-Allow-Headers in preflight response` | Клиентское приложение передает заголовок, отсутствующий в разрешающем перечне `Access-Control-Allow-Headers`. | Проверить заголовок `Access-Control-Request-Headers` в консоли браузера Network -> Headers. | Добавить недостающий заголовок в список `Access-Control-Allow-Headers` в preflight-блоке Angie. |
| Исчезновение CORS-заголовков в подлокации (например, при отдаче статики или скачивании файлов) | Сработала специфика наследования `add_header`: в дочернем `location` объявлен локальный `add_header`, отключивший родительские. | Проверить наличие `add_header` во вложенных директивах `location`. | Вынести блок CORS-заголовков в snippet `/etc/angie/snippets/cors.conf` и подключить через `include` внутри каждой локации. |
| Клиент на домене `B` внезапно получает заголовок `Access-Control-Allow-Origin: domain_A` | Кэширующий прокси (`proxy_cache`) или промежуточный кэш отдал закэшированный ответ другого пользователя. | Проверить наличие заголовка: `curl -sI <URL> | grep -i vary`. | Добавить директиву `add_header Vary "Origin" always;` во все блоки выдачи CORS-заголовков. |
| Ошибка CORS при падении бэкенда (`502 Bad Gateway` / `504 Gateway Timeout`) | Ошибки генерируются самим Angie, но директивы `add_header` не снабжены параметром `always`. | Проверить заголовки при выключенном upstream: `curl -sI -H "Origin: ..." <URL>`. | Добавить параметр `always` к директивам `add_header`. |

## Лучшие практики

1. **Никогда не возвращайте произвольный Origin вслепую:**
   Антипаттерн `add_header Access-Control-Allow-Origin $http_origin always;` без валидации через `map` полностью нивелирует защиту браузера: любой вредоносный сайт сможет выполнять запросы от имени авторизованного пользователя. Применяйте строго ограниченный белый список доменов.
2. **Обязательно используйте `Vary: Origin` при наличии кэширования:**
   Любой ответ с динамическим значением `Access-Control-Allow-Origin` обязан сопровождаться заголовком `Vary: Origin`, предотвращающим отравление кэша (Cache Poisoning) и коллизии между клиентами.
3. **Оптимизируйте `Access-Control-Max-Age`:**
   Значение по умолчанию для preflight в браузерах составляет всего 5 секунд. Установка значения `Access-Control-Max-Age 86400` (24 часа) радикально снижает нагрузку на обратный прокси и сеть, исключая лишние `OPTIONS`-запросы при повторных AJAX-вызовах. Браузеры на базе Chromium ограничивают максимальное время 7200 секундами (2 часа), а Firefox поддерживает до 86400 секунд.
4. **Централизуйте CORS на пограничном прокси Angie:**
   Обработка preflight на уровне прокси снимает нагрузку с бэкенд-приложений, избавляет от необходимости дублировать логику CORS в микросервисах на разных языках программирования и гарантирует корректную отдачу заголовков даже при авариях бэкенда (`502/504`).
5. **Изолируйте слои проксирования через `proxy_hide_header`:**
   Всегда подавляйте дублирующиеся заголовки `Access-Control-*` от бэкенда директивами `proxy_hide_header`, чтобы исключить сбои парсинга в строгих браузерных движках.
6. **Выносите повторяющиеся конфигурации в Snippets:**
   Использование директивы `include /etc/angie/snippets/cors.conf` в блоках `location` защищает конфигурацию от ошибок, связанных с прекращением наследования `add_header`.

## Дополнительная информация

- **Спецификация:** [W3C Cross-Origin Resource Sharing (W3C Recommendation)](https://www.w3.org/TR/cors/) и [WHATWG Fetch Living Standard](https://fetch.spec.whatwg.org/#http-cors-protocol).

## См. также

- **[Заголовки безопасности в Angie](./angie-security-headers.md)** — управление заголовками безопасности (CSP, HSTS, X-Content-Type-Options) и специфика директивы `add_header`.
- **[Настройка TLS в Angie](./angie_tls_setup.md)** — развертывание защищенного протокола HTTPS для продуктовых API.
- **[Конфигурирование обратного прокси в Angie](./angie_reverse_proxy.md)** — настройка upstream-серверов, буферизации и параметров `proxy_pass`.
- **[Настройка логирования в Angie](./angie_logging.md)** — форматы журналов, ротация и сбор телеметрии.
- **[Директивы location в Angie](./angie_location_directives.md)** — правила маршрутизации, наследование контекстов и приоритеты обработки URL.
- **[Укрепление безопасности Nginx/Angie](../Nginx/Security/nginx_security_guide.md)** — комплексная защита веб-сервера от атак, ограничения методов и hardening.