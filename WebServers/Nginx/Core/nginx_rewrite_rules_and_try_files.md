# Перенаправления и перезапись URI в Nginx

**Актуально для:** Nginx 1.26.x (Stable) / 1.27.x (Mainline)

## Определения

Манипуляция URI — одна из центральных задач Nginx при обработке входящих HTTP-запросов. Для изменения пути запроса, перенаправления клиента или организации fallback-механизмов используются директивы `rewrite`, `return` и `try_files`, входящие в состав модулей `ngx_http_rewrite_module` и `ngx_http_core_module`.

- **Rewrite (перезапись)** — внутреннее изменение URI запроса сервером на основе регулярных выражений PCRE/PCRE2. Процесс прозрачен для клиента: браузер сохраняет исходный URL в адресной строке, но Nginx обрабатывает запрос по новому пути.
- **Redirect (редирект)** — внешнее перенаправление клиента. Сервер возвращает ответ со статусом `3xx` (например, `301`, `302`, `307`, `308`) и заголовком `Location`, указывая браузеру или HTTP-клиенту выполнить новый запрос по новому адресу.
- **Try_files (каскадная проверка)** — механизм модуля `ngx_http_core_module` для последовательной проверки существования файлов и директорий на диске с последующим выполнением внутреннего перенаправления или возвратом HTTP-статуса.
- **Internal redirect (внутренний редирект)** — повторный запуск цикла обработки запроса внутри Nginx без отправки сетевого ответа клиенту. Клиент не видит изменений URL, а сервер перевыбирает блок `location` по измененному URI.
- **Internal redirect cycle (цикл внутренних перенаправлений)** — ошибка `500 Internal Server Error`, возникающая при превышении системного лимита внутренних перенаправлений (жестко закодированная константа `NGX_HTTP_MAX_URI_CHANGES = 10` в `ngx_http_core_module.h`).
- **`ngx_http_rewrite_module`** — встроенный модуль Nginx, реализующий императивные инструкции манипуляции запросом (`rewrite`, `return`, `set`, `if`, `break`, `rewrite_log`, `uninitialized_variable_warn`).
- **`ngx_http_map_module`** — встроенный модуль Nginx, позволяющий декларативно создавать новые переменные на основе сопоставления значений других переменных. Вычисляется лениво (on-demand) и служит эффективной заменой директиве `if`.
- **`$uri` (синоним `$document_uri`)** — текущий нормализованный URI запроса без аргументов (без query string). Декодирует percent-encoded символы (`%20` → пробел), устраняет относительные сегменты (`/../`) и обновляется при выполнении `rewrite` или внутреннего редиректа.
- **`$request_uri`** — исходный, полный URI запроса, полученный непосредственно из HTTP-строки запроса клиента, включая query string и без нормализации. Неизменяем на протяжении всего жизненного цикла запроса.
- **`$args` (синоним `$query_string`)** — строка аргументов запроса после символа `?`.
- **`$is_args`** — переменная, принимающая значение `?`, если аргументы запроса присутствуют, и пустую строку, если аргументов нет. Используется для безопасной конкатенации URI и аргументов.
- **Именованный `location` (`@name`)** — специальный блок `location`, не участвующий в стандартном алгоритме сопоставления URI и вызываемый исключительно явно через `try_files`, `error_page`, `rewrite ... last` или `X-Accel-Redirect`.

---

## Базовые концепции

### Фазы обработки запроса и жизненный цикл rewrite

Nginx обрабатывает каждый HTTP-запрос через фиксированный конвейер из 11 фаз. Понимание того, на каких фазах работают директивы манипуляции URI, критично для предотвращения скрытых ошибок маршрутизации:

1. **`NGX_HTTP_POST_READ_PHASE`** — первичная обработка после чтения заголовков (здесь работают модули вроде `realip`).
2. **`NGX_HTTP_SERVER_REWRITE_PHASE`** — выполнение директив `rewrite`, `set` и `return`, определенных на уровне блока `server` (до выбора `location`). Если URI перезаписывается здесь, новый URI используется для первичного поиска `location`.
3. **`NGX_HTTP_FIND_CONFIG_PHASE`** — сопоставление нормализованного URI с конфигурационными блоками `location` (поиск по префиксному дереву и регулярным выражениям).
4. **`NGX_HTTP_REWRITE_PHASE`** — выполнение директив `rewrite`, `set`, `if`, `return` внутри выбранного блока `location`. Инструкции выполняются последовательно сверху вниз как императивный скрипт.
5. **`NGX_HTTP_POST_REWRITE_PHASE`** — оценка результатов фазы rewrite. Если URI был изменен правилом с флагом `last`, Nginx немедленно возвращает запрос на фазу `FIND_CONFIG` для повторного поиска `location`.
6. **`NGX_HTTP_PREACCESS_PHASE`** — проверка лимитов (модули `limit_req`, `limit_conn`).
7. **`NGX_HTTP_ACCESS_PHASE`** — авторизация и контроль доступа (`allow`, `deny`, `auth_basic`, `auth_request`).
8. **`NGX_HTTP_POST_ACCESS_PHASE`** — финальное подтверждение доступа.
9. **`NGX_HTTP_PRECONTENT_PHASE`** — предварительная подготовка контента. **Именно на этой фазе выполняется директива `try_files`!**
10. **`NGX_HTTP_CONTENT_PHASE`** — генерация ответа (отдача статики с диска через `root`/`alias`, проксирование через `proxy_pass`, передача в `fastcgi_pass`).
11. **`NGX_HTTP_LOG_PHASE`** — запись в `access_log`.

```
[Запрос от клиента]
        │
        ▼
[SERVER_REWRITE] ──(rewrite/return в server {})
        │
        ▼
[FIND_CONFIG]    ◄────────────────────────────────────────┐
        │                                                 │
        ▼                                                 │
[REWRITE]        ──(rewrite/return/if в location {})      │
        │                                                 │
        ▼                                                 │
[POST_REWRITE]   ──(флаг last / изменение URI?) ──────────┤
        │  (нет)                                          │
        ▼                                                 │
[PREACCESS / ACCESS]                                      │
        │                                                 │
        ▼                                                 │
[PRECONTENT]     ──(try_files: fallback на URI?) ─────────┘
        │  (файл найден или fallback на @name / =code)
        ▼
[CONTENT]        ──(отдача статики / proxy_pass / fastcgi_pass)
        │
        ▼
[LOG] ──────────► [Ответ клиенту]
```

> **Критический вывод:** Директивы `rewrite` и `return` выполняются на фазе `REWRITE`, а `try_files` — на фазе `PRECONTENT`. Поэтому правила `rewrite` внутри `location` всегда отрабатывают **раньше**, чем `try_files`, независимо от того, в каком порядке они записаны в файле конфигурации.

### Лимит внутренних перенаправлений

Nginx жестко ограничивает количество внутренних перенаправлений до **10** на один запрос (константа `NGX_HTTP_MAX_URI_CHANGES = 10`).

Причины циклов:
- Правило `rewrite ^(.*)$ /prefix$1 last;`, повторно сопоставляющееся с тем же или родительским `location`.
- Директива `try_files $uri $uri/ /index.html;` внутри `location /`, где `/index.html` снова попадает в `location /` при отсутствии самого файла `index.html` на диске.
- Взаимные перенаправления между `error_page` и `try_files`.

При превышении счетчика Nginx немедленно прерывает обработку, возвращает клиенту ответ `500 Internal Server Error` и фиксирует в `error.log` запись:
`rewrite or internal redirection cycle while internally redirecting to "/..."`.

---

### Директива `rewrite`

Директива использует регулярные выражения PCRE (или PCRE2, поддерживаемый по умолчанию с Nginx 1.21.5) для сопоставления и изменения URI.

**Синтаксис:** `rewrite regex replacement [flag];`  
**Контекст:** `server`, `location`, `if`.

Правила `rewrite` в одном блоке выполняются строго последовательно в порядке их объявления.

#### Флаги управления

| Флаг | Контекст | Поведение |
| :--- | :--- | :--- |
| **`last`** | `server`, `location` | Останавливает выполнение текущего набора директив `rewrite`. Nginx переходит на фазу `FIND_CONFIG` и запускает **новый цикл поиска location** по измененному URI. |
| **`break`** | `server`, `location` | Останавливает выполнение директив `rewrite`. Nginx **не ищет новый location**, а продолжает обработку запроса в текущем блоке на последующих фазах (`ACCESS`, `PRECONTENT`, `CONTENT`). |
| **`redirect`** | `server`, `location`, `if` | Возвращает клиенту временный внешний редирект со статусом `302 Found` и заголовком `Location`. |
| **`permanent`** | `server`, `location`, `if` | Возвращает клиенту постоянный внешний редирект со статусом `301 Moved Permanently` и заголовком `Location`. |

**Поведение без флага:**
- Если строка `replacement` начинается с `http://`, `https://` или `$scheme`, Nginx автоматически возвращает внешний редирект `302 Found`.
- Если строка `replacement` задает локальный URI, Nginx перезаписывает `$uri` и продолжает выполнять следующие директивы `rewrite` в этом же блоке. Это поведение часто приводит к непреднамеренным циклам и сложно уловимым багам. Всегда указывайте флаг явно.

#### Разница между `last` и `break`

Различие между `last` и `break` — один из ключевых вопросов архитектуры Nginx:

```nginx
location /download/ {
    # last: перезаписывает URI и отправляет запрос на НОВЫЙ поиск location
    rewrite ^/download/(.*)$ /files/$1 last;
}

location /files/ {
    internal;
    root /var/storage;
}
```
В данном случае запрос `/download/manual.pdf` превращается в `/files/manual.pdf`, выходит из `location /download/`, находит `location /files/` и безопасно отдается из директории `/var/storage/files/manual.pdf`.

Если применить `break`:
```nginx
location /download/ {
    root /var/storage;
    # break: перезаписывает URI, но ОСТАЕТСЯ внутри location /download/
    rewrite ^/download/(.*)$ /files/$1 break;
}
```
В этом случае Nginx не будет искать `location /files/`. Он останется в `location /download/` и будет искать файл на диске по пути `/var/storage/files/manual.pdf`. При проксировании (`proxy_pass`) флаг `break` позволяет переписать путь перед передачей на бэкенд без повторного прогона через конфигурацию локаций.

#### Управление строкой аргументов (Query String)

По умолчанию Nginx автоматически присоединяет исходную строку аргументов (`$args`) к целевому `replacement`:

```nginx
# Запрос: /old-catalog?category=books&page=2
rewrite ^/old-catalog$ /new-catalog permanent;
# → Клиент получает редирект на: /new-catalog?category=books&page=2
```

Для управления аргументами используется символ `?` в конце строки замены:

```nginx
# 1. Полное удаление query string (завершающий знак вопроса):
rewrite ^/users/(.*)$ /profile/$1? permanent;
# /users/42?tracker=email -> /profile/42

# 2. Добавление собственных аргументов с очисткой исходных:
rewrite ^/item/([0-9]+)$ /catalog?id=$1? permanent;
# /item/42?old_param=1 -> /catalog?id=42

# 3. Добавление новых аргументов с сохранением исходных (без ? в конце):
rewrite ^/item/([0-9]+)$ /catalog?id=$1 permanent;
# /item/42?sort=desc -> /catalog?id=42&sort=desc (Nginx объединяет аргументы через &)
```

---

### Директива `return`

Директива `return` немедленно прекращает обработку запроса на фазе rewrite и возвращает ответ клиенту.

**Синтаксис:**
- `return code [text];`
- `return code URL;`
- `return URL;`

**Контекст:** `server`, `location`, `if`.

**Преимущества перед `rewrite`:**
1. **Производительность:** `return` не использует движок регулярных выражений PCRE и не тратит циклы CPU на компиляцию и сопоставление шаблонов.
2. **Предсказуемость:** Выполнение прекращается немедленно, исключая каскадные ошибки и скрытые сайд-эффекты последующих правил.

```nginx
# 1. Канонический редирект HTTP -> HTTPS (постоянный 301)
return 301 https://$host$request_uri;

# 2. Редирект с сохранением метода запроса (POST/PUT/PATCH)
return 308 https://$host$request_uri;

# 3. Временный редирект (302 Found)
return 302 /temporary-target;

# 4. Немедленный возврат ошибки с телом в формате JSON или текста
return 403 "Forbidden: Access restricted by policy\n";

# 5. Сброс TCP-соединения без отправки ответа (Nginx non-standard code 444)
return 444;
```

#### Выбор кода статуса перенаправления

| Код | Стандарт | Семантика | Поведение HTTP-методов |
| :--- | :--- | :--- | :--- |
| **`301 Moved Permanently`** | RFC 7231 | Ресурс окончательно перенесен. Кэшируется браузерами на длительный срок. | Клиенты исторически могут менять `POST` на `GET`. |
| **`308 Permanent Redirect`** | RFC 7538 | Постоянный редирект с жестким сохранением HTTP-метода. | Клиент **обязан** повторить запрос тем же методом (`POST` остается `POST`). |
| **`302 Found`** | RFC 7231 | Временный редирект. По умолчанию не кэшируется. | Клиенты исторически могут менять `POST` на `GET`. |
| **`307 Temporary Redirect`** | RFC 7231 | Временный редирект с сохранением метода запроса. | Клиент **обязан** повторить запрос тем же методом (`POST` остается `POST`). |

> **SRE-рекомендация:** Для современных REST/gRPC API при перенаправлении эндпоинтов используйте `307` или `308`, чтобы исключить потерю тела запроса и несанкционированную конвертацию мутирующих запросов (`POST`/`PUT`) в `GET`.

---

### Директива `try_files`

Директива последовательно проверяет наличие файлов и директорий в файловой системе. Проверка осуществляется относительно текущего корня, заданного директивами `root` или `alias`.

**Синтаксис:**
- `try_files file ... uri;`
- `try_files file ... =code;`

**Контекст:** `server`, `location`.

**Параметры:**
1. **Проверяемые файлы (`file`):** Список путей, проверяемых слева направо.
   - `$uri` — проверка точного файла (например, `/css/style.css`).
   - `$uri/` — проверка существования директории (Nginx проверяет наличие директории и пытается вызвать индексный файл, заданный директивой `index`).
   - `file.html` или произвольные статические пути.
2. **Финальный параметр (Fallback):** Вызывается только в том случае, если ни один из предшествующих файлов не был найден на диске.
   - `uri` — вызывает **внутренний редирект** на указанный URI (например, `/index.php` или `/index.html`). Перезапускает цикл поиска `location` на фазе `FIND_CONFIG`.
   - `=code` — немедленно возвращает указанный код HTTP-ошибки без внутреннего редиректа (например, `=404`, `=503`).
   - `@name` — передает управление в именованный `location` без изменения `$uri` и без повторного сопоставления префиксов.

```nginx
# Классический паттерн фронтенд/бэкенд:
location / {
    root /var/www/site;
    # 1. Проверить файл -> 2. Проверить каталог -> 3. Уйти в именованный fallback
    try_files $uri $uri/ @fallback;
}

location @fallback {
    proxy_pass http://backend_upstream;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
}
```

> **Важно (Query String в fallback):** Если финальный параметр задан как URI (например, `try_files $uri $uri/ /index.php;`), Nginx выполняет внутренний редирект, где query string сохраняется в переменной `$args`, но не передается автоматически в параметрах пути fallback. Для гарантированной передачи параметров в скрипты всегда используйте конструкцию:  
> `try_files $uri $uri/ /index.php?$query_string;` (или `$is_args$args`).

---

### Переменные `$uri`, `$request_uri` и `$document_uri`

Правильный выбор переменной предотвращает уязвимости инъекций в заголовок `Location`, утерю параметров запроса и некорректное экранирование.

| Переменная | Пример значения | Содержит `$args`? | Декодирует `%XX`? | Изменяется при `rewrite`? |
| :--- | :--- | :--- | :--- | :--- |
| **`$request_uri`** | `/search?q=nginx%20rules` | **Да** (сырая строка) | **Нет** (сохраняет `%20`) | **Нет** (константа запроса) |
| **`$uri`** | `/search` | **Нет** | **Да** (`%20` → пробел) | **Да** (отражает текущий URI) |
| **`$document_uri`** | `/search` | **Нет** | **Да** | **Да** (полный синоним `$uri`) |
| **`$args`** | `q=nginx%20rules` | — | **Нет** | Может перезаписываться через `set $args` |

**Правила выбора для редиректов:**
- В директивах `return 301/302` на внешние URL **всегда используйте `$request_uri`**:  
  `return 301 https://$host$request_uri;`  
  Использование `$uri` в таких конструкциях приведет к потере всех GET-параметров клиента!
- В директивах внутреннего сопоставления используйте `$uri`, так как она нормализована и безопасна от directory traversal (`../`).

---

### Проблема «If is Evil» и альтернатива через `map`

Директива `if` входит в состав `ngx_http_rewrite_module` и выполняется на фазе `REWRITE`. Когда `if` помещается внутрь блока `location`, Nginx создает **скрытый вложенный location**. Если условие выполняется, запрос переносится в этот вложенный блок.

**В чем опасность:**
Вложенный location директивы `if` наследует директивы родительского блока избирательно. Если внутри блока присутствуют директивы фазы `CONTENT` (такие как `proxy_pass`, `fastcgi_pass`, `try_files`, `alias`), Nginx может повести себя непредсказуемо: проигнорировать директиву, выдать `404` или аварийно завершить рабочий процесс (segmentation fault).

**Правило безопасного использования `if`:**
Внутри блока `location` в блоке `if` **разрешено использовать только две директивы**:
1. `return ...;`
2. `rewrite ... last;` или `rewrite ... break;`

Любые другие комбинации (например, `if` совместно с `proxy_pass`, `add_header` или `try_files`) являются задокументированным антипаттерном.

#### Декларативная альтернатива: `map`

Для реализации сложной условной логики следует использовать директиву `map` модуля `ngx_http_map_module` на уровне `http`.

**Преимущества `map`:**
- **Декларативность:** Описывает соответствие входных и выходных данных, а не логику ветвления.
- **Ленивое вычисление (Lazy Evaluation):** Переменная, создаваемая через `map`, вычисляется ровно один раз за запрос и **только в том случае, если к ней фактически обратились**. Если запрос не использует переменную, вычисление не производится вовсе.
- **Производительность:** Сопоставление строк выполняется через быстрые хеш-таблицы в оперативной памяти.

```nginx
http {
    # Декларативное сопоставление старых разделов сайта с новыми
    map $request_uri $new_redirect_uri {
        default                 "";
        "/about-company"        "/about";
        "/price-list.pdf"       "/prices";
        "~^/blog/2021/(.*)$"    "/articles/$1";
    }

    server {
        listen 80;
        server_name example.com;

        # Если значение найдено в map, выполняем мгновенный редирект
        if ($new_redirect_uri != "") {
            return 301 $new_redirect_uri;
        }

        location / {
            try_files $uri $uri/ =404;
        }
    }
}
```

---

## Практические сценарии

### Сценарий 1: Канонический редирект HTTP → HTTPS с поддержкой Let's Encrypt

В production-окружениях редирект на HTTPS должен корректно работать для IPv4 и IPv6, сохранять URI и query-параметры, а также не блокировать проверку ACME challenge (Let's Encrypt / Certbot).

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # Исключение для валидации сертификатов Let's Encrypt через веб-корень
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        default_type "text/plain";
        try_files $uri =404;
    }

    # Постоянный редирект всего остального трафика на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    http2 on;
    server_name example.com www.example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # HSTS заголовок для защиты от атак понижения протокола (Downgrade)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        root /var/www/html;
        try_files $uri $uri/ =404;
    }
}
```

**Проверка:**

```bash
# Проверка редиректа обычной страницы
curl -I http://example.com/catalog?page=2
# → HTTP/1.1 301 Moved Permanently
# → Location: https://example.com/catalog?page=2

# Проверка доступности ACME challenge без редиректа
curl -I http://example.com/.well-known/acme-challenge/test-token
# → HTTP/1.1 404 Not Found (или 200, если файл существует; редирект не произошел)
```

---

### Сценарий 2: Канонизация домена (склейка www и non-www)

Для предотвращения дублирования поискового веса (SEO) и единообразия сертификатов используется отдельный блок `server` вместо проверки `$host` через `if`.

```nginx
# Редирект с www на канонический домен без www
server {
    listen 80;
    listen [::]:80;
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name www.example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    return 301 https://example.com$request_uri;
}

# Основной рабочий сервер
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    root /var/www/app/public;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

**Проверка:**

```bash
curl -I https://www.example.com/products/item-123
# → HTTP/2 301
# → location: https://example.com/products/item-123
```

---

### Сценарий 3: Маршрутизация SPA (React, Vue, Angular) с защитой от циклов

Для приложений со Single Page Application маршрутизация внутри клиентского приложения выполняется JavaScript-роутером. Nginx обязан отдавать существующие статические файлы (JS, CSS, изображения), а для всех остальных запросов отдавать файл `index.html`.

```nginx
server {
    listen 443 ssl;
    server_name spa.example.com;

    ssl_certificate /etc/ssl/certs/spa.example.com.crt;
    ssl_certificate_key /etc/ssl/private/spa.example.com.key;

    root /var/www/spa/dist;
    index index.html;

    # 1. Хэшированные ассеты (JS/CSS/картинки со сборщика) кэшируются агрессивно
    location ~* \.(?:css|js|woff2?|png|jpg|jpeg|gif|svg|ico)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
        try_files $uri =404;
    }

    # 2. Основной вход для приложения
    location / {
        try_files $uri $uri/ @spa_entry;
    }

    # 3. Именованный fallback для index.html с запретом кэширования
    location @spa_entry {
        # Запрет кэширования HTML-оболочки для мгновенного обновления версий бандлов
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        add_header Expires "0";
        rewrite ^ /index.html break;
    }
}
```

**Проверка:**

```bash
# Запрос к существующему скрипту
curl -I https://spa.example.com/assets/app.a1b2c3.js
# → HTTP/2 200
# → cache-control: public, immutable

# Запрос к виртуальному SPA-маршруту
curl -I https://spa.example.com/dashboard/settings
# → HTTP/2 200
# → cache-control: no-cache, no-store, must-revalidate
```

---

### Сценарий 4: Маршрутизация PHP-FPM (Laravel, Symfony, WordPress)

Стандартный стек для PHP-приложений требует безопасной передачи запросов на сокет FastCGI без выполнения произвольных `.php` файлов, загруженных пользователями.

```nginx
server {
    listen 443 ssl;
    server_name app.example.com;

    root /var/www/app/public;
    index index.php index.html;

    # Запрет доступа к скрытым системным файлам (.env, .git)
    location ~ /\.(?!well-known).* {
        deny all;
        access_log off;
        log_not_found off;
    }

    location / {
        # Поиск статики -> поиск каталога -> передача в роутер фреймворка
        try_files $uri $uri/ /index.php?$query_string;
    }

    location ~ \.php$ {
        # Защита от исполнения сторонних файлов через PATH_INFO
        try_files $uri =404;
        fastcgi_split_path_info ^(.+\.php)(/.+)$;

        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_index index.php;

        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param PATH_INFO $fastcgi_path_info;
    }
}
```

**Проверка:**

```bash
# Проверка передачи аргументов в контроллер
curl -I "https://app.example.com/api/v1/orders?status=active"
# → HTTP/2 200
```

---

### Сценарий 5: Версионирование и миграция API

При выпуске новой версии API необходимо перенаправить клиентов старых версий без изменения клиентских URL и без потери передаваемых параметров.

```nginx
location /api/v1/ {
    # Внутренняя перезапись префикса с v1 на v2 с повторным поиском location
    # Флаг last перезапускает сопоставление в новом location /api/v2/
    rewrite ^/api/v1/(.*)$ /api/v2/$1 last;
}

location /api/v2/ {
    proxy_pass http://backend_v2_upstream;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

---

### Сценарий 6: Массовые редиректы через `map` при миграции сайта

При миграциях крупных порталов или интернет-магазинов часто требуется перенаправить тысячи старых URL на новые. Использование сотен строк `rewrite` замедляет обработку каждого запроса из-за линейного перебора регулярных выражений. Использование `map` гарантирует доступ за время $O(1)$ по хеш-таблице.

Файл `/etc/nginx/conf.d/redirects_map.conf`:
```nginx
map $request_uri $redirect_target {
    hostnames; # Поддержка масок доменов при необходимости
    default "";

    # Точные соответствия
    "/old-about-us"             "/company/about";
    "/catalog/old-category"     "/catalog/new-category";
    "/contacts.html"            "/support/contact";

    # Регулярные выражения (начинаются с ~)
    "~^/item/([0-9]+)/?$"       "/products/$1";
}
```

В блоке `server`:
```nginx
server {
    listen 443 ssl;
    server_name example.com;

    if ($redirect_target != "") {
        return 301 $redirect_target;
    }

    location / {
        root /var/www/html;
        try_files $uri $uri/ =404;
    }
}
```

---

### Сценарий 7: Защита от хотлинкинга (Hotlink Protection)

Запрет загрузки медиа-контента сторонними сайтами для предотвращения паразитного расхода серверной полосы пропускания (bandwidth stealing).

```nginx
location ~* \.(?:jpg|jpeg|png|gif|webp|svg|mp4)$ {
    root /var/www/media;

    # Разрешенные источники: отсутствие Referer, свои домены
    valid_referers none blocked server_names *.example.com example.com;

    if ($invalid_referer) {
        # Вариант 1: Жесткая блокировка
        return 403;

        # Вариант 2: Отдача специальной картинки-заглушки:
        # rewrite ^ /images/hotlink-placeholder.png break;
    }

    expires 30d;
    add_header Cache-Control "public, no-transform";
}
```

---

## Операции и команды

### Валидация и безопасное применение конфигурации

```bash
# 1. Проверка синтаксиса всех конфигурационных файлов
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Проверка синтаксиса с полным выводом всей собранной конфигурации
nginx -T | grep -E "rewrite|return|try_files"

# 3. Грациозная перезагрузка конфигурации (zero-downtime reload)
systemctl reload nginx
# или напрямую через сигнал master-процессу:
nginx -s reload
# → signal reload started

# 4. Проверка статуса службы в systemd
systemctl status nginx --no-pager
```

### Отладка правил rewrite через логи

Директива `rewrite_log` отправляет подробные сведения об обработке правил в системный журнал на уровне `notice`.

В конфигурации `nginx.conf`:
```nginx
http {
    # rewrite_log разрешен в контекстах: http, server, location, if
    rewrite_log on;

    # error_log ОБЯЗАТЕЛЬНО должен быть настроен на уровень notice или debug
    error_log /var/log/nginx/rewrite_debug.log notice;
}
```

Пример вывода записей в `/var/log/nginx/rewrite_debug.log`:
```
# → 2026/10/16 09:20:11 [notice] 14201#14201: *1 "^/api/v1/(.*)$" matches "/api/v1/users", client: 192.168.1.100, server: example.com, request: "GET /api/v1/users HTTP/1.1", host: "example.com"
# → 2026/10/16 09:20:11 [notice] 14201#14201: *1 rewritten data: "/api/v2/users", args: "", client: 192.168.1.100, server: example.com, request: "GET /api/v1/users HTTP/1.1", host: "example.com"
```

> **Эксплуатационное предупреждение:** Не оставляйте `rewrite_log on;` в production-окружениях с высоким трафиком (high load). Каждая проверка регулярного выражения производит системный вызов `write()` в файл лога, что приводит к деградации I/O и блокировкам воркеров.

### Диагностика с помощью `curl`

```bash
# 1. Проверка редиректа с выводом заголовков (без следования редиректу)
curl -I https://example.com/old-url
# → HTTP/2 301
# → location: https://example.com/new-url

# 2. Проверка цепочки перенаправлений с ограничением глубины
curl -IL --max-redirs 5 https://example.com/deep-redirect

# 3. Тестирование с указанием произвольного заголовка Host (проверка виртуальных хостов)
curl -Iv -H "Host: www.example.com" http://127.0.0.1/

# 4. Проверка сохранения POST-метода при редиректе 307/308
curl -IL -X POST -d '{"param":"value"}' -H "Content-Type: application/json" https://example.com/api/v1/submit

# 5. Проверка сохранения query string
curl -I "https://example.com/old-search?category=devops&order=asc"
# → HTTP/2 301
# → location: https://example.com/new-search?category=devops&order=asc
```

### Автоматизированное тестирование правил в CI/CD Pipeline

Для исключения регрессий в сложных правилах маршрутизации применяется smoke-тестирование в рамках пайплайна:

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="http://127.0.0.1:8080"

test_redirect() {
    local src="$1"
    local expected_code="$2"
    local expected_target="$3"

    local response
    response=$(curl -s -o /dev/null -w "%{http_code} %{redirect_url}" -H "Host: example.com" "${TARGET_HOST}${src}")

    local actual_code
    local actual_target
    actual_code=$(echo "$response" | awk '{print $1}')
    actual_target=$(echo "$response" | awk '{print $2}')

    if [[ "$actual_code" == "$expected_code" && "$actual_target" == "$expected_target" ]]; then
        echo "[PASS] ${src} -> ${expected_code} to ${expected_target}"
    else
        echo "[FAIL] ${src} -> Expected: ${expected_code} ${expected_target}, Got: ${actual_code} ${actual_target}"
        exit 1
    fi
}

# Набор тестов
test_redirect "/old-catalog" "301" "https://example.com/new-catalog"
test_redirect "/legacy-api/status" "301" "https://example.com/api/v2/status"
```

---

## Диагностика и устранение неполадок

### Сводная таблица типовых неисправностей

| Симптом | Первопричина | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| `500 Internal Server Error` | Цикл внутренних редиректов (превышен лимит 10 итераций) | `grep "redirection cycle" /var/log/nginx/error.log` | Проверить флаги `last`; перевести fallback в `try_files` на именованный `location @name` или вернуть `=404` |
| `404 Not Found` при существующем файле | Несовместимость `try_files` с директивой `alias` в префиксном `location` | Запрос тестового URI через `curl -I` и проверка `$document_root` | Заменить `alias` на `root` с коррекцией файловой структуры, либо использовать regex с захватом пути |
| Утеря GET-аргументов после редиректа | Использование переменной `$uri` вместо `$request_uri` в `return 301/302` | Анализ заголовка `Location` в выводе `curl -I` | Заменить `return 301 https://$host$uri;` на `return 301 https://$host$request_uri;` |
| Браузер бесконечно перенаправляет на старый адрес | Агрессивное кэширование браузером редиректа `301 Moved Permanently` | `curl -I` показывает правильный ответ, но браузер отдает ответ из disk cache | Очистить кэш браузера или проверять через `curl` / режим инкогнито; на этапе разработки использовать `302` |
| Потеря тела `POST`-запроса при редиректе | Клиент преобразует `POST` в `GET` из-за использования кода `301` или `302` | `tcpdump -A -s 0 'port 80'` или инспекция curl с `-X POST` | Заменить статус редиректа на `307 Temporary Redirect` или `308 Permanent Redirect` |
| Циклическая петля редиректов HTTP ↔ HTTPS | TLS терминируется на внешнем балансировщике/L4-прокси, а Nginx проверяет только локальный `$scheme` | Запрос уходит по кругу: внешний прокси (HTTPS) → Nginx (HTTP) → 301 на HTTPS | Использовать проверку заголовка протокола: `if ($http_x_forwarded_proto = "http") { return 301 https://$host$request_uri; }` |
| Неожиданное поведение `try_files` с query string | Fallback в `try_files` не пробрасывает аргументы в бэкенд | Проверка аргументов в логе бэкенда (`$_GET` в PHP или query в Node.js) | Явно добавить `$is_args$args` или `$query_string` к целевому URI в `try_files` |

### Разбор проблемы `try_files` + `alias`

Один из наиболее частых архитектурных дефектов — попытка совместить `alias` и `try_files` в префиксном блоке:

```nginx
# ОШИБОЧНАЯ КОНФИГУРАЦИЯ:
location /static/ {
    alias /data/www/assets/;
    try_files $uri $uri/ =404; # ОШИБКА!
}
```

**Механизм возникновения ошибки:**  
Переменная `$uri` содержит полный путь запроса, включая префикс `/static/` (например, `/static/app.js`). При выполнении `try_files` Nginx берет путь `alias` (`/data/www/assets/`) и конкатенирует его с `$uri`, пытаясь открыть `/data/www/assets/static/app.js`. Файл не находится, и сервер отдает `404 Not Found`.

**Корректное решение 1 (через выделенный `root`):**
```nginx
location /static/ {
    root /data/www; # Ищет /data/www/static/app.js
    try_files $uri $uri/ =404;
}
```

**Корректное решение 2 (через регулярное выражение и захват):**
```nginx
location ~ ^/static/(?<static_file>.*)$ {
    alias /data/www/assets/$static_file;
    try_files "" =404;
}
```

---

## Лучшие практики

### Архитектура и производительность

1. **Предпочитайте `return` директиве `rewrite`:**  
   Для безусловных редиректов (HTTP → HTTPS, склейка доменов, переход на новый URL) всегда используйте `return 301/308`. Это полностью исключает обращение к библиотеке PCRE.
2. **Включайте PCRE JIT на уровне `main`:**  
   Директива `pcre_jit on;` в глобальном контексте конфигурации ускоряет выполнение регулярных выражений до 2–3 раз за счет их предварительной компиляции в машинный код.
3. **Используйте флаг `break` внутри целевого `location`:**  
   Если URI перезаписан и должен отдаваться текущим блоком (например, проксироваться через `proxy_pass`), используйте `break`, чтобы исключить накладные расходы на повторную фазу `FIND_CONFIG`.
4. **Заменяйте каскады `if` на таблицы `map`:**  
   Таблицы `map` вычисляются один раз за запрос по требованию, не вызывают фрагментации конфигурации и масштабируются до сотен тысяч записей без деградации CPU.

### Безопасность

1. **Защита от открытых редиректов (Open Redirect Vulnerability):**  
   Никогда не используйте заголовок клиента `$http_host` в директивах перенаправления:  
   ```nginx
   # НЕБЕЗОПАСНО: Атакующий передает заголовок Host: evil.com и уводит пользователя
   return 301 https://$http_host$request_uri;

   # БЕЗОПАСНО: Переменная $host валидируется по блокам server_name
   return 301 https://$host$request_uri;
   ```
2. **Предотвращение инъекций заголовков (CRLF Injection):**  
   Не используйте неэкранированные аргументы клиента в формировании заголовка `Location`. При передаче аргументов доверяйте только нормализованным переменным.
3. **Изоляция внутренних ресурсов директивой `internal`:**  
   Любые служебные location (обработчики ошибок, fallback-маршруты, эндпоинты `X-Accel-Redirect`) должны помечаться директивой `internal;`, запрещая прямой вызов клиентами извне.

### Эксплуатация (SRE)

1. **Идемпотентность и тестирование изменений:**  
   Ни одно изменение правил rewrite не должно выкатываться на production без проверки `nginx -t` и прогона автоматических тестов с `curl`.
2. **Алертинг на внутренние циклы:**  
   Настройте в системе сбора логов (Elasticsearch / OpenSearch / Graylog / Vector) мониторинг и алерты на строковый паттерн:  
   `"rewrite or internal redirection cycle"`.  
   Появление таких записей свидетельствует о критической ошибке в логике маршрутизации.
3. **Ограничение глубины цепочек редиректов:**  
   Стремитесь к тому, чтобы клиент никогда не получал более одного HTTP-редиректа за переход (например: HTTP/www → HTTPS/non-www должен выполняться строго за 1 шаг со статусом `301`, а не через промежуточный редирект на HTTP/non-www).

---

## Дополнительная информация

### Связанные документы базы знаний

- **[Директива location: основы и приоритеты](./Location/basics.md)** — алгоритмы сопоставления URI, префиксные деревья и модификаторы `^~`, `~*`.
- **[Внутренняя маршрутизация в Nginx](./Location/internal_routing.md)** — архитектура `internal`, `X-Accel-Redirect`, субзапросы и каскадные `error_page`.
- **[Nginx: отдача статических файлов](./Location/serving_files.md)** — глубокая настройка отдачи файлов, `open_file_cache`, `sendfile` и `tcp_nopush`.
- **[Редиректы в Nginx: proxy_redirect и core-директивы](../Proxy/nginx_proxy_redirects.md)** — обработка заголовков `Location` от апстрим-серверов и взаимодействие с `absolute_redirect`.
- **[Диагностика и устранение неполадок в Nginx](../Operations/nginx_troubleshooting.md)** — системный анализ ошибок Nginx, профилирование соединений и разбор логов.
- **[Maintenance-режим в Nginx](../Scenarios/nginx_maintenance_mode.md)** — паттерны бесшовного перевода сайта на обслуживание с использованием `map`, файлов-флагов и кодов 503.
- **[Обзор архитектуры Nginx](./nginx_overview.md)** — модель рабочих процессов (master/worker), фазы обработки запроса и архитектура событийного цикла.

### Официальная документация Nginx

- [Модуль ngx_http_rewrite_module](https://nginx.org/ru/docs/http/ngx_http_rewrite_module.html) — директивы `rewrite`, `return`, `set`, `if`, `break`, `rewrite_log`.
- [Модуль ngx_http_core_module (try_files)](https://nginx.org/ru/docs/http/ngx_http_core_module.html#try_files) — спецификация директивы `try_files`.
- [Модуль ngx_http_map_module](https://nginx.org/ru/docs/http/ngx_http_map_module.html) — спецификация директивы `map`.
