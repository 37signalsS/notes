# Директива location: основы и приоритеты

**Актуально для:** Nginx 1.26.x (Stable) / 1.27.x (Mainline)

## Определения

**Директива `location`** — ключевая контекстная директива Nginx, определяющая конфигурационный блок для обработки входящего HTTP-запроса на основе сопоставления нормализованного URI с заданным префиксом или регулярным выражением внутри блока `server`.

**URI (Uniform Resource Identifier)** — строковый путь ресурса в HTTP-запросе без схемы, домена и параметров строки запроса (`query string`), используемый Nginx для маршрутизации.

**Нормализация URI** — процесс предварительной обработки URI сервером Nginx (декодирование percent-encoding, разрешение относительных сегментов `.` и `..`, схлопывание дублирующихся слэшей) перед выполнением поиска подходящего `location`.

**Префиксное дерево (Trie)** — компактная структура данных в оперативной памяти Nginx, в которую компилируются все префиксные `location`. Обеспечивает логарифмическую/линейную от длины URI скорость поиска `O(L)` независимо от общего количества префиксов.

**PCRE (Perl Compatible Regular Expressions)** — библиотека синтаксического анализа и сопоставления регулярных выражений, применяемая Nginx для обработки модификаторов `~` и `~*`.

**PCRE JIT (Just-In-Time)** — механизм компиляции шаблонов регулярных выражений PCRE в машинный код во время старта или перезагрузки Nginx, существенно снижающий нагрузку на CPU при сопоставлении regex-локейшенов.

**Именованный location (`@name`)** — конфигурационный блок, идентифицируемый префиксом `@`, который полностью исключен из стандартного сопоставления URI и вызывается исключительно внутренними механизмами сервера (`try_files`, `error_page`, `X-Accel-Redirect`).

**Внутренний запрос (Internal request)** — запрос, генерируемый самим сервером Nginx (перенаправление по `error_page`, `try_files`, заголовок `X-Accel-Redirect` от апстрима, модуль `auth_request` или `mirror`) без возврата ответа внешнему клиенту.

**Подзапрос (Subrequest)** — вторичный внутренний запрос Nginx к другому `location` (например, в директивах `auth_request`, `ssi` или `addition`), выполняемый параллельно или последовательно с основным запросом.

**Off-by-slash** — архитектурная уязвимость конфигурации при использовании директивы `alias`, возникающая из-за отсутствия завершающего слэша в префиксе `location`, что приводит к выходу за пределы целевой директории (Directory Traversal).

---

## Базовые концепции

### Архитектура сопоставления и фазы обработки

Маршрутизация запроса по блокам `location` выполняется на фазе `NGX_HTTP_FIND_CONFIG_PHASE` одиннадцатифазного жизненного цикла HTTP-запроса в Nginx (подробнее об архитектуре ядра — в **[Обзор архитектуры Nginx](../nginx_overview.md)**).

```
[Клиентский запрос из сетевого сокета]
         │
         ▼
 1. [NGX_HTTP_POST_READ_PHASE]      (Чтение заголовков, восстановление real_ip)
         │
         ▼
 2. [NGX_HTTP_SERVER_REWRITE_PHASE] (rewrite на уровне блока server до выбора location)
         │
         ▼
 3. [NGX_HTTP_FIND_CONFIG_PHASE]    ◄── ВЫБОР LOCATION (Нормализация URI -> Trie -> Regex)
         │
         ▼
 4. [NGX_HTTP_REWRITE_PHASE]        (rewrite, set, return внутри выбранного location)
         │
         ▼
 5. [NGX_HTTP_POST_REWRITE_PHASE]   (Проверка циклов редиректа: лимит до 10 переходов)
         │
         ▼
 6. [NGX_HTTP_PREACCESS_PHASE]      (Ограничения частоты и соединений: limit_req, limit_conn)
         │
         ▼
 7. [NGX_HTTP_ACCESS_PHASE]         (Авторизация: allow, deny, auth_basic, auth_request)
         │
         ▼
 8. [NGX_HTTP_POST_ACCESS_PHASE]    (Агрегация прав доступа: директива satisfy any|all)
         │
         ▼
 9. [NGX_HTTP_PRECONTENT_PHASE]     (Предварительные действия: mirror, try_files)
         │
         ▼
10. [NGX_HTTP_CONTENT_PHASE]        (Генерация ответа: ровно один content handler)
         │                           (proxy_pass, fastcgi_pass, root/static, autoindex)
         ▼
11. [NGX_HTTP_LOG_PHASE]            (Запись в access_log после отправки клиенту)
         │
         ▼
    [Фильтры вывода (Output Filters)] (add_header, gzip, sub_filter)
```

Если директивы `rewrite` в контексте `server` изменяют URI, поиск `location` на фазе `NGX_HTTP_FIND_CONFIG_PHASE` производится уже по новому, модифицированному значению пути.

#### Порядок директив внутри location: декларативность против процедурности

Ключевой вопрос на технических собеседованиях:
*«Имеет ли значение порядок строк внутри блока `location`? Что выполнится раньше, если написать `proxy_pass` на первой строке, а строкой ниже — `return 301`?»*

**Ответ:** Nginx **декларативен**, а не процедурен. Инструкции внутри `location` не выполняются как скрипт сверху вниз, а привязываются к соответствующим фазам конвейера обработки запроса:
1. Директивы модуля rewrite (`set`, `rewrite`, `return`) регистрируются на фазе `REWRITE_PHASE` (Фаза 4).
2. Директивы контроля доступа (`allow`, `deny`) регистрируются на фазе `ACCESS_PHASE` (Фаза 7).
3. Обработчики контента (`proxy_pass`, `root`, `fastcgi_pass`) регистрируются на фазе `CONTENT_PHASE` (Фаза 10).
4. Заголовки `add_header` внедряются на этапе фильтрации заголовков (Output Header Filter).

Следовательно, директива `return` **всегда выполнится раньше**, чем `proxy_pass` или `root`, независимо от того, в какой строке блока `location` она физически записана. Запрос мгновенно завершится отправкой ответа клиенту, а фаза генерации контента даже не начнется.

*Исключение:* Директивы, принадлежащие одному и тому же модулю и фазе (например, последовательность инструкций `rewrite` или цепочка правил `allow` и `deny`), выполняются строго последовательно в порядке записи в файле.

#### Принцип единственного обработчика контента (Single Content Handler)

В структуре внутреннего запроса Nginx (`ngx_http_request_t`) поле `r->content_handler` представляет собой указатель ровно на одну функцию-генератор. На фазе `NGX_HTTP_CONTENT_PHASE` у блока `location` может быть **только один обработчик контента**:
- Либо обратный прокси (`proxy_pass`);
- Либо шлюз приложений (`fastcgi_pass`, `uwsgi_pass`, `scgi_pass`, `grpc_pass`);
- Либо статический файловый обработчик (`ngx_http_static_handler`, активируемый через `root` или `alias`);
- Либо служебный генератор (`stub_status`, `autoindex`).

Попытка указать в одном `location` одновременно `proxy_pass` и `fastcgi_pass` приведет к ошибке компиляции конфигурации (`nginx: [emerg] "fastcgi_pass" directive is duplicate`). При совмещении `root` и `proxy_pass` директива `proxy_pass` перехватывает управление, а `root` игнорируется (за исключением редких директив вроде `open_file_cache`).

---

### Нормализация URI

Перед сопоставлением URI с шаблонами `location` Nginx производит строгую нормализацию пути:

1. **Декодирование percent-encoding (`%XX`):** Значения вроде `%20` преобразуются в пробел, `%2F` преобразуется в `/`. Декодирование применяется ко всему пути, исключая обход защитных правил через двойное кодирование.
2. **Разрешение относительных сегментов пути:** Конструкции `.` (текущий каталог) и `..` (родительский каталог) схлопываются. Например, запрос `/static/css/../images/logo.png` нормализуется в `/static/images/logo.png`.
3. **Схлопывание дублирующихся слэшей:** Два и более идущих подряд слэша заменяются на один (`//api///v1//users` → `/api/v1/users`). Поведением управляет директива `merge_slashes` (по умолчанию `on`). При `merge_slashes off;` URI сохраняет множественные слэши, что нарушает стандартное префиксное совпадение.
4. **Отсечение аргументов запроса (Query String):** Строка параметров после знака `?` (доступная в переменной `$args`) **полностью исключается** из проверки `location`. Шаблон `location /search?q=test` является синтаксически неверным для сопоставления параметров — сопоставление выполняется исключительно по нормализованному пути (`$uri`).

---

### Полный алгоритм выбора location

При поступлении запроса Nginx выполняет детерминированный алгоритм сопоставления:

```
[Входящий нормализованный URI]
              │
              ▼
   [Шаг 1: Точное совпадение '=']
              │
        Совпало? ──Да──► [Использовать данный location] (Поиск остановлен)
              │ Нет
              ▼
   [Шаг 2: Поиск в префиксном дереве (Trie)]
   (Поиск самого длинного совпавшего префикса)
              │
              ▼
   [Шаг 3: Проверка модификатора '^~']
              │
 Самый длинный префикс ──Да──► [Использовать данный location] (Regex НЕ проверяются)
     содержит '^~'?
              │ Нет (сохраняем найденный префикс как запасной)
              ▼
   [Шаг 4: Проверка регулярных выражений '~' и '~*']
   (Последовательный перебор в порядке появления в конфиге)
              │
        Совпало? ──Да──► [Использовать первый совпавший regex] (Поиск остановлен)
              │ Нет
              ▼
   [Шаг 5: Использование сохраненного префикса]
   (Был найден префикс на Шаге 2? ──Да──► Использовать его; Нет ──► 404 Not Found)
```

#### Пошаговое описание алгоритма:

1. **Шаг 1 — Точные совпадения (`=`):** Nginx проверяет наличие точного совпадения URI с блоком `location = /path`. Если найдено, этот блок выбирается немедленно. Дальнейший поиск прекращается мгновенно (`O(1)`).
2. **Шаг 2 — Поиск префиксов:** Nginx просматривает префиксные блоки (как с модификатором `^~`, так и без него) по скомпилированному префиксному дереву (Trie). Фиксируется **наиболее длинный** совпавший префикс.
3. **Шаг 3 — Приоритетная остановка префикса (`^~`):** Если найденный на Шаге 2 самый длинный префикс объявлен с модификатором `^~`, Nginx **полностью отменяет** фазу регулярных выражений и немедленно выбирает этот префиксный блок.
4. **Шаг 4 — Проверка регулярных выражений (`~` и `~*`):** Если Шаг 3 не остановил алгоритм, Nginx по очереди тестирует регулярные выражения в том порядке, в котором они физически записаны в конфигурационных файлах. Первый совпавший блок regex берется для обработки, а поиск завершается.
5. **Шаг 5 — Применение лучшего префикса:** Если ни одно регулярное выражение не совпало (или regex-локейшены отсутствуют), используется блок с самым длинным префиксом, запомненным на Шаге 2. Если ни один блок не подошел (и нет блока `location /`), Nginx возвращает ошибку `404 Not Found`.

**Итоговый приоритет:**
`=` (точное) **>** `^~` (длиннейший префикс с блокировкой regex) **>** `~` / `~*` (первый совпавший regex по порядку в файле) **>** префикс без модификатора (длиннейший префикс как fallback).

---

### Детальный разбор модификаторов location

| Модификатор | Тип сопоставления | Алгоритм поиска | Влияние порядка в файле | Назначение и контекст |
| :--- | :--- | :--- | :--- | :--- |
| `=` | Точное совпадение | Хэш-таблица / дерево | Не имеет значения | Высокочастотные эндпоинты (`/`, `/favicon.ico`, `/healthz`) |
| `^~` | Приоритетный префикс | Префиксное дерево (Trie) | Не имеет значения | Изоляция каталогов статики и API от перехвата регулярными выражениями |
| `~` | Регулярное выражение (регистрозависимое) | Линейный перебор (PCRE) | **Критически важен** (первое совпадение) | Обработка динамических сценариев, PHP/FastCGI, валидация расширений |
| `~*` | Регулярное выражение (регистронезависимое) | Линейный перебор (PCRE) | **Критически важен** (первое совпадение) | Статические ассеты со смешанным регистром расширений (`.jpg`, `.JPG`, `.png`) |
| *(пусто)* | Стандартный префикс | Префиксное дерево (Trie) | Не имеет значения | Базовая маршрутизация сервисов, fallback-правила (`location /`) |
| `@` | Именованный location | Прямой вызов | Не участвует в URI | Обработчики fallback для `try_files`, `error_page`, внутренних редиректов |

#### Нюанс длины префикса `^~` vs стандартный префикс
Модификатор `^~` отменяет проверку регулярных выражений только в том случае, если он оказался **наиболее длинным** совпавшим префиксом.

Рассмотрим пример:
```nginx
location ^~ /app/ {
    # Приоритетный префикс длиной 5 символов
}

location /app/data/ {
    # Стандартный префикс длиной 10 символов (без ^~)
}

location ~* \.json$ {
    # Регулярное выражение
}
```

- При запросе `/app/info.html` самый длинный совпавший префикс — `/app/` (`^~`). Проверка регулярных выражений **блокируется**, запрос обрабатывается в `location ^~ /app/`.
- При запросе `/app/data/schema.json` самый длинный совпавший префикс — `/app/data/` (10 символов против 5). Так как префикс `/app/data/` не имеет модификатора `^~`, Nginx **переходит к проверке регулярных выражений** (Шаг 4). Шаблон `~* \.json$` совпадает, и запрос уходит в regex-локейшен, а не в `/app/data/`!

#### Ловушка нестрогого префикса (Substring Match Trap)

Распространенная ошибка проектирования — объявление префикса без завершающего слэша (`location /api` вместо `location /api/`).

**Механизм работы:**
Префиксное сопоставление в Nginx работает как **строковое сравнение с начала строки**, а не как покомпонентный разбор дерева каталогов:
- Блок `location /api` совпадет со следующими запросами:
  - `/api` — совпадает;
  - `/api/` — совпадает;
  - `/api/v1/users` — совпадает;
  - `/api-docs` — **совпадает!** (начинается с `/api`);
  - `/application` — **совпадает!**;
  - `/api_secret_key` — **совпадает!**.

**Продакшен-инцидент (Access Control Bypass / Routing Collision):**
Если администратор закрывает закрытый раздел правилом:
```nginx
location /admin {
    allow 10.0.0.0/8;
    deny all;
}
```
А публичная страница справочника называется `/admin-help` или `/admin_public`, доступ к ней будет неожиданно заблокирован для всех клиентов. В обратной ситуации, если защищен только `location /admin/`, злоумышленник может обойти ограничение через обращение к `/admin`.

**Правило:** Всегда завершайте префиксные блоки слэшем (`location /api/`), если цель — накрыть каталог или группу эндпоинтов. Если требуется совпадение ровно с одним эндпоинтом, используйте точный модификатор `location = /api`.

---

### Семантика `proxy_pass` и трансформация URI

Поведение директивы `proxy_pass` принципиально зависит от наличия URI в адресе проксирования и типа `location`.

#### 1. Префиксный location: `proxy_pass` БЕЗ URI

Если в строке `proxy_pass` указан только хост/сокет без пути (нет даже завершающего слэша), Nginx передает апстриму оригинальный нормализованный URI клиента целиком:

```nginx
location /api/ {
    proxy_pass http://backend_pool;
    # GET /api/v1/users → backend получает GET /api/v1/users
}
```

#### 2. Префиксный location: `proxy_pass` С URI

Если в строке `proxy_pass` указан URI (хотя бы одиночный завершающий слэш `/`), Nginx **заменяет** часть URI, совпавшую с префиксом `location`, на URI из директивы `proxy_pass`:

```nginx
location /api/ {
    proxy_pass http://backend_pool/;
    # GET /api/v1/users → совпадение "/api/" вырезается и заменяется на "/"
    # backend получает GET /v1/users
}

location /legacy-service/ {
    proxy_pass http://backend_pool/v2/;
    # GET /legacy-service/items → совпадение "/legacy-service/" заменяется на "/v2/"
    # backend получает GET /v2/items
}
```

#### 3. Регулярные выражения и именованные location: запрет URI в `proxy_pass`

Внутри `location`, заданных регулярным выражением (`~`, `~*`), или именованных `location` (`@name`), Nginx **не может** вычислить часть пути для замены. 

Попытка указать URI в `proxy_pass` внутри regex-локейшена вызовет фатальную ошибку парсинга конфигурации при проверке `nginx -t`:
`nginx: [emerg] "proxy_pass" cannot have URI part in location given by regular expression, or inside named location, or inside the "if" statement, or inside "limit_except" block`

**Корректное решение для подмены URI в regex-локейшенах:** использование директивы `rewrite ... break`:
```nginx
location ~ ^/service-[a-z]+/(.*)$ {
    rewrite ^/service-[a-z]+/(.*)$ /$1 break;
    proxy_pass http://backend_pool; # Без URI!
}
```

#### 4. Динамическое проксирование через переменные

Если в строке `proxy_pass` используются переменные, автоматическая подмена пути Nginx отключается, а для разрешения имен хостов в рантайме требуется директива `resolver`:

```nginx
location /forward/ {
    resolver 127.0.0.1 valid=30s;
    set $target_backend "app.internal.domain:8080";
    # ВНИМАНИЕ: $uri передает нормализованный путь БЕЗ query string ($args)!
    proxy_pass http://$target_backend$request_uri;
}
```

#### 5. Подводный камень нормализации и декодирования `%2F` в `proxy_pass`

Один из самых коварных инцидентов в REST API за Nginx:
- При директиве с URI `proxy_pass http://backend/;` Nginx отправляет бэкенду нормализованный `$uri`. На этапе нормализации код `%2F` преобразуется в реальный слэш `/`, а `%20` — в пробел.
- Если клиент запрашивает ресурс с закодированным путем (например, в GitLab/Artifactory/S3: `GET /api/v1/repos/group%2Fproject`), бэкенд получает `GET /v1/repos/group/project` — структура пути ломается, и сервер возвращает `404 Not Found`.

**Решение:**
1. Если подмена пути не требуется: использовать `proxy_pass http://backend;` (строго **без** завершающего слэша). В этом режиме Nginx передает оригинальный сырой `RAW URI` клиента из сокета без декодирования.
2. При динамическом роутинге: всегда передавать переменную `$request_uri` (`proxy_pass http://$upstream$request_uri;`), которая хранит точный исходный URI вместе с аргументами и закодированными символами.

---

### Обработка завершающего слэша (Trailing Slash)

Если префиксный `location` заканчивается слэшем (`location /docs/`), а входящий запрос поступил без слэша (`/docs`), Nginx проверяет обработчик контента:
1. Если запрос обслуживается файловым модулем (`root`), и `/docs` является существующим каталогом на диске, модуль `ngx_http_index_module` автоматически возвращает клиенту редирект `301 Moved Permanently` с заголовком `Location: /docs/`.
2. Если используется стандартный `proxy_pass http://backend/;`, Nginx аналогично генерирует внутренний или внешний 301-редирект на URI со слэшем для предотвращения поломки относительных путей в веб-интерфейсе.

При использовании `try_files` автоматический 301-редирект не инициируется, если в явном виде не указан маркер `$uri/`.

#### Взаимодействие с `proxy_redirect` и статус-кодами 301 vs 308 в REST API

1. **Модификация заголовка `Location` (`proxy_redirect`):**
   Когда бэкенд возвращает редирект на свой внутренний сокет (`Location: http://10.0.0.5:8080/auth`), Nginx по умолчанию (`proxy_redirect default;`) переписывает заголовок, подставляя внешний префикс текущего `location`. Подробнее о предотвращении утечек портов и циклов редиректа — в **[Редиректы и proxy_redirect](../../Proxy/nginx_proxy_redirects.md)**.

2. **Проблема потери тела запроса (301/302 vs 307/308):**
   Исторически браузеры и HTTP-клиенты при получении редиректов `301 Moved Permanently` и `302 Found` **изменяют HTTP-метод запроса на `GET` и отбрасывают тело запроса** (`POST`/`PUT` payload).
   - В REST API при перенаправлениях (на HTTPS или завершающий слэш) необходимо использовать коды `307 Temporary Redirect` или `308 Permanent Redirect` (RFC 9110), которые строго предписывают клиенту повторить запрос с тем же методом и телом:
   ```nginx
   # Для API обязательно использовать 308 вместо 301:
   location = /api/v1/orders {
       return 308 /api/v1/orders/;
   }
   ```

---

### Ограничение методов через `limit_except`

Директива `limit_except` задает исключения для списка HTTP-методов. Все методы, **не перечисленные** в заголовке директивы, подпадают под действие вложенных правил контроля доступа (`allow`, `deny`):

```nginx
location /api/write/ {
    # Методы GET и HEAD разрешены всем
    limit_except GET {
        allow 192.168.10.0/24; # Подсеть администраторов
        allow 127.0.0.1;
        deny  all;             # POST, PUT, DELETE, PATCH запрещены для остальных
    }
    proxy_pass http://api_backend;
}
```

#### Архитектурное ограничение `limit_except` и возврат HTTP 405

Частая ошибка на собеседованиях и в конфигурации — попытка вернуть клиенту `405 Method Not Allowed` через `limit_except`:
```nginx
# ОШИБКА: Синтаксический сбой при nginx -t
limit_except GET POST {
    return 405; # Запрещено! Директива return недопустима внутри limit_except
}
```

Директива `limit_except` поддерживает внутри своего контекста **только директивы модулей доступа** (`allow`, `deny`, `auth_basic`). При попытке поместить туда `return`, `rewrite` или `proxy_pass` Nginx завершится с ошибкой `nginx: [emerg] "return" directive is not allowed here`.

**Продакшен-паттерн возврата HTTP 405 через `map`:**
Для корректного отклонения неразрешенных методов с отдачей стандарта HTTP 405 используется декларативная таблица `map` на уровне `http`:

```nginx
# В контексте http:
map $request_method $is_disallowed_api_method {
    default         1;
    GET             0;
    POST            0;
    HEAD            0;
    OPTIONS         0;
}

# В контексте server / location:
location /api/v1/payments/ {
    if ($is_disallowed_api_method) {
        return 405 "Method Not Allowed\n";
    }
    proxy_pass http://payment_backend;
}
```

---

### Директива `internal`

Директива `internal` запрещает прямое обращение клиентов к `location` через внешние HTTP-запросы.

```nginx
location /protected_assets/ {
    internal;
    root /var/www/private;
}
```

- Любой прямой HTTP-запрос снаружи немедленно получает ответ `404 Not Found` (начиная с Nginx 1.25.x; в старых версиях мог возвращаться `403`).
- Блок доступен только при внутренних вызовах:
  * Заголовок `X-Accel-Redirect`, выставленный авторизованным бэкендом.
  * Результат проверки `try_files $uri /protected_assets/fallback.pdf;`.
  * Перенаправление через директиву `error_page 404 = /protected_assets/error.html;`.
  * Вызов модуля проверки подлинности `auth_request /internal_auth;`.

---

## Практические сценарии

### Сценарий 1: Высоконагруженная статика с изоляцией от regex

**Задача:** Обеспечить отдачу статических файлов (`/static/`, `/assets/`) с максимальной производительностью, кэшированием дескрипторов, без накладных расходов на перебор общих регулярных выражений для PHP/Python.

```nginx
# Контекст http: оптимизация работы ядра
sendfile on;
tcp_nopush on;
tcp_nodelay on;

server {
    listen 80;
    server_name example.com;
    root /var/www/example.com;

    # 1. Приоритетный префикс: регулярные выражения полностью игнорируются
    location ^~ /static/ {
        open_file_cache max=10000 inactive=120s;
        open_file_cache_valid 60s;
        open_file_cache_min_uses 2;
        open_file_cache_errors on;

        expires 30d;
        add_header Cache-Control "public, no-transform, immutable";
        access_log off;
        try_files $uri =404;
    }

    # 2. Динамический бэкенд на regex
    location ~ \.php$ {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    }

    # 3. Базовый префикс
    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }
}
```

**Верификация:**
```bash
# Проверка отдачи статики и наличия заголовков кэширования
curl -sI http://example.com/static/bundle.css
# → HTTP/1.1 200 OK
# → Cache-Control: public, no-transform, immutable

# Запрос к статическому файлу с расширением .php внутри /static/ отдается как статика, а не исполняется
curl -sI http://example.com/static/test.php
# → HTTP/1.1 200 OK
# → Content-Type: application/octet-stream (или text/plain, скрипт не передан в FastCGI)
```

---

### Сценарий 2: Микросервисный шлюз (API Gateway) с разделением путей

**Задача:** Смаршрутизировать трафик сервисов: `/api/v1/` требует удаления префикса перед отправкой на upstream, а `/api/v2/` должен передаваться с сохранением оригинального пути.

```nginx
upstream backend_v1 {
    server 127.0.0.1:8001;
    keepalive 32;
}

upstream backend_v2 {
    server 127.0.0.1:8002;
    keepalive 32;
}

server {
    listen 80;
    server_name api.company.internal;

    # Стриппинг префикса: завершающий слэш в proxy_pass подменяет "/api/v1/" на "/"
    location ^~ /api/v1/ {
        proxy_pass http://backend_v1/;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Сохранение полного пути: proxy_pass БЕЗ завершающего слэша
    location ^~ /api/v2/ {
        proxy_pass http://backend_v2;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

**Верификация:**
```bash
# Запрос v1: апстрим 8001 видит GET /users
curl -s http://api.company.internal/api/v1/users
# → {"status":"ok","source":"backend_v1","handled_path":"/users"}

# Запрос v2: апстрим 8002 видит GET /api/v2/orders
curl -s http://api.company.internal/api/v2/orders
# → {"status":"ok","source":"backend_v2","handled_path":"/api/v2/orders"}
```

---

### Сценарий 3: Защита административной зоны и блокировка скрытых файлов

**Задача:** Ограничить доступ к `/admin/` по белым IP-адресам, защитить системные конфигурационные файлы (`.git`, `.env`) и скрыть метрики.

```nginx
server {
    listen 80;
    server_name admin.internal;
    root /var/www/app;

    # Блокировка скрытых файлов (.git, .env, .htaccess) во всех URI
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    # Закрытый административный интерфейс
    location ^~ /admin/ {
        # Разрешен доступ только инженерам эксплуатации
        allow 192.168.1.0/24;
        allow 10.50.0.10;
        allow 127.0.0.1;
        deny  all;

        auth_basic "Restricted Operations";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
    }
}
```

**Верификация:**
```bash
# Попытка чтения .env файла извне
curl -sI http://admin.internal/.env
# → HTTP/1.1 403 Forbidden

# Запрос из неавторизованной подсети
curl -sI http://admin.internal/admin/dashboard
# → HTTP/1.1 403 Forbidden
```

---

### Сценарий 4: Endpoint мониторинга (Health Check и Metrics)

**Задача:** Настроить надежный эндпоинт для сбора базовых метрик Nginx (`stub_status`) и health-проверок балансировщиков без загрязнения access-логов и утечки внутренней информации.

```nginx
server {
    listen 80 default_server;
    server_name _;

    # Моментальное точное совпадение: наивысший приоритет
    location = /nginx_status {
        stub_status;
        access_log off;

        # Доступ строго для мониторинга
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        deny all;
    }

    # Легковесный health check для внешней проверки доступности ноды
    location = /healthz {
        access_log off;
        add_header Content-Type text/plain;
        return 200 "healthy\n";
    }
}
```

**Верификация:**
```bash
# Опрос метрик локальным сборщиком (Prometheus Nginx Exporter)
curl -s http://127.0.0.1/nginx_status
# → Active connections: 2
# → server accepts handled requests
# →  1042 1042 2084
# → Reading: 0 Writing: 1 Waiting: 1

# Проверка healthz-зонда
curl -s http://127.0.0.1/healthz
# → healthy
```

---

### Сценарий 5: Проксирование WebSocket-соединений

**Задача:** Обеспечить прозрачный прокси-туннель для протокола WebSocket (`ws://` / `wss://`) с корректной трансляцией заголовков `Upgrade` и увеличенными таймаутами неактивности.

```nginx
# В контексте http определяем корректное значение заголовка Connection
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name socket.example.com;

    location /ws/ {
        proxy_pass http://127.0.0.1:4000;
        proxy_http_version 1.1;

        # Проброс заголовков рукопожатия WebSocket
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;

        # Таймауты для длительных двусторонних сессий (по умолчанию 60s)
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

**Верификация:**
```bash
# Проверка ответа сервера на запрос с Upgrade-заголовками
curl -sI -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==" \
     -H "Sec-WebSocket-Version: 13" \
     http://socket.example.com/ws/
# → HTTP/1.1 101 Switching Protocols
# → Upgrade: websocket
# → Connection: upgrade
```

---

### Сценарий 6: Single Page Application (SPA) с fallback на `@fallback`

**Задача:** Обеспечить корректную работу роутинга в HTML5 History Mode для SPA без зацикливания внутренних перенаправлений.

```nginx
server {
    listen 80;
    server_name app.example.com;
    root /var/www/spa/dist;
    index index.html;

    # Статические файлы фронтенда
    location ^~ /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    # Маршрутизация приложения
    location / {
        try_files $uri $uri/ @spa_router;
    }

    # Именованный fallback: передача управления на входной index.html
    location @spa_router {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        rewrite ^ /index.html break;
    }
}
```

**Верификация:**
```bash
# Существующий ассет отдается напрямую
curl -sI http://app.example.com/assets/app.12345.js
# → HTTP/1.1 200 OK
# → Cache-Control: public, immutable

# Виртуальный SPA-маршрут возвращает index.html без 404 ошибки
curl -s http://app.example.com/profile/settings | head -n 3
# → <!DOCTYPE html>
# → <html lang="en">
# → <head><title>SPA Application</title>
```

---

### Сценарий 7: Защищенный `alias` без уязвимости Off-by-slash

**Задача:** Настроить отдачу файлов из внешней директории через `alias`, предотвратив Directory Traversal.

```nginx
server {
    listen 80;
    server_name files.example.com;

    # БЕЗОПАСНАЯ КОНФИГУРАЦИЯ: оба пути заканчиваются слэшем
    location /user-data/ {
        alias /var/storage/user_files/;
        try_files $uri =404;
    }
}
```

> **Критическое предупреждение (Off-by-slash):** Если объявить `location /user-data` (без завершающего слэша), а в `alias` указать `/var/storage/user_files/`, Nginx выполняет конкатенацию остатка строки. Запрос `GET /user-data../secret.txt` преобразуется сервером в чтение файла `/var/storage/user_files/../secret.txt`, что открывает злоумышленнику доступ к родительскому каталогу `/var/storage/`. Всегда синхронизируйте наличие завершающего слэша в `location` и `alias`!

---

## Операции и команды

### Валидация и проверка конфигурации

Перед применением любых правок в `location` обязательна проверка синтаксиса:

```bash
# 1. Проверка синтаксиса и целостности всех конфигурационных файлов
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Дамп полной развернутой конфигурации со всеми include для инспекции блоков location
nginx -T | grep -n "location "
# → 45:    location = / {
# → 52:    location ^~ /static/ {
# → 68:    location ~ \.php$ {
# → 85:    location / {

# 3. Применение изменений без разрыва активных соединений (Graceful reload)
nginx -s reload
# → signal processed
```

---

### Трассировка сопоставления location через Debug Log

Если Nginx направляет запрос не в тот `location`, стандартного access-лога недостаточно. Для точной диагностики активируется режим отладки:

```nginx
# В контексте events или http:
error_log /var/log/nginx/error.log debug;
```

После перезагрузки Nginx (`nginx -s reload`) и отправки тестового запроса лог фильтруется по этапам сопоставления:

```bash
# Отправка тестового запроса
curl -s http://localhost/static/css/main.css > /dev/null

# Поиск шагов алгоритма выбора location в логе
grep -E "using configuration|test location" /var/log/nginx/error.log
# → 2026/10/16 09:35:10 [debug] 14201#14201: *1 test location: "/"
# → 2026/10/16 09:35:10 [debug] 14201#14201: *1 test location: "static/"
# → 2026/10/16 09:35:10 [debug] 14201#14201: *1 using configuration "^~ /static/"
```

> **SRE Best Practice:** Debug log генерирует сотни мегабайт данных в секунду при активном трафике. Включайте `debug` только на staging-серверах либо для изолированного IP-адреса через директиву `events { debug_connection 192.168.1.50; }`.

---

### Отладка маршрутизации через кастомные HTTP-заголовки

На этапе тестирования инфраструктуры рекомендуется добавлять в каждый блок диагностический заголовок:

```nginx
location ^~ /api/v1/ {
    add_header X-Debug-Matched-Location "/api/v1/" always;
    proxy_pass http://backend_v1;
}

location ~ \.(jpg|png)$ {
    add_header X-Debug-Matched-Location "regex_images" always;
    root /var/www/media;
}
```

```bash
# Инспекция выбранного блока через заголовки ответа
curl -sI http://localhost/api/v1/users | grep -i "X-Debug-Matched"
# → X-Debug-Matched-Location: /api/v1/
```

---

### Тестирование граничных случаев (Edge Cases)

```bash
# 1. Проверка обработки двойных слэшей (merge_slashes)
curl -sI "http://localhost//api///users"
# → HTTP/1.1 200 OK (Nginx нормализовал URI до /api/users)

# 2. Проверка игнорирования параметров запроса при сопоставлении
curl -sI "http://localhost/static/style.css?version=2.4.1"
# → HTTP/1.1 200 OK (успешно выбран /static/, параметры не повлияли на Trie)

# 3. Проверка автоматического редиректа на каталог со слэшем
curl -sI "http://localhost/docs"
# → HTTP/1.1 301 Moved Permanently
# → Location: http://localhost/docs/
```

---

## Устранение неполадок

### Диагностическая матрица типовых инцидентов

| Симптом | Корневая причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Статический файл (CSS/JS) в директории `/static/` возвращает ошибку 502 или уходит в бэкенд | Запрос перехвачен регулярным выражением (`location ~ \.(css\|js)$` или PHP) | `nginx -T`, поиск regex с `~` | Добавить модификатор `^~` в префикс статики: `location ^~ /static/` |
| Ошибка `[emerg] "proxy_pass" cannot have URI part in location given by regular expression` | Указан путь в `proxy_pass` внутри regex-локейшена или `@name` | `nginx -t` | Удалить путь из `proxy_pass` и использовать `rewrite ... break` |
| Утечка файлов родительского каталога (Directory Traversal) через `alias` | Несогласованный слэш (Off-by-slash: `location /files` и `alias /data/files/`) | Аудит `nginx -T`, `curl http://host/files../` | Добавить завершающий слэш в `location`: `location /files/` |
| Префикс `location /api` перехватывает запросы к сторонним сервисам (`/api-docs`, `/application`) | Префиксное сопоставление в Nginx выполняется по строковому совпадению подстроки с начала пути | Анализ access-логов и трассировка сопоставления | Добавить завершающий слэш `location /api/` либо использовать точный модификатор `location = /api` |
| Запросы REST API с закодированными слэшами (`%2F`) падают с 404 на бэкенде | В `proxy_pass` указан URI (`proxy_pass http://b/;`), что форсирует декодирование `%2F` в `/` через `$uri` | Инспекция логов бэкенда: приход пути с реальным слэшем вместо `%2F` | Убрать URI из `proxy_pass http://backend;` или передавать сырой `$request_uri` |
| Ошибка `[emerg] "return" directive is not allowed here` | Попытка вернуть HTTP 405 внутри директивы `limit_except` | `nginx -t` при валидации конфигурации | `limit_except` работает только с модулями доступа; отдачу 405 реализовывать через `map` |
| `location /search?q=1` никогда не срабатывает | Query string исключается из `$uri` до сопоставления с `location` | Проверка URI в access-логе | Использовать `location /search` и проверять параметры через `if ($arg_q)` или директиву `map` |
| Ошибка `500 Internal Server Error`, сообщение `rewrite or internal redirection cycle` | Бесконечный цикл в `try_files` или `error_page` (более 10 переходов) | Просмотр `/var/log/nginx/error.log` | Использовать именованный location `@fallback` в конце цепочки `try_files` |
| Ошибка `403 Forbidden` при обращении к каталогу без файла индекса | Отсутствует файл из директивы `index` и выключен `autoindex` | Просмотр `/var/log/nginx/error.log`: `directory index of "/path/" is forbidden` | Создать `index.html` или включить `autoindex on;` |

---

### Подробный разбор инцидентов

#### 1. Regex перехватывает запросы префиксного каталога
**Проблема:** В конфигурации определен префикс `/uploads/` для загруженных пользовательских файлов и общее регулярное выражение для PHP. Злоумышленник загружает файл `avatar.php.png` или `script.php`.
```nginx
# ОШИБКА
location /uploads/ {
    root /var/www/app;
}

location ~ \.php$ {
    fastcgi_pass unix:/run/php-fpm.sock;
}
```
**Следствие:** При запросе `/uploads/script.php` префикс `/uploads/` проигрывает регулярному выражению на Шаге 4. Сервер передает файл на исполнение в FastCGI.
**Исправление:** Использовать приоритетный префикс `^~`:
```nginx
location ^~ /uploads/ {
    root /var/www/app;
}
```

#### 2. Зацикливание `try_files` в корне
**Проблема:**
```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```
Если файл `/index.html` физически отсутствует в `root`, Nginx совершает внутреннее перенаправление на `/index.html`, снова попадает в `location /`, проверяет `$uri`, не находит его и снова перенаправляет на `/index.html`. Достигается лимит в 10 внутренних редиректов, клиент получает HTTP 500.
**Исправление:** Выносить терминальный fallback в именованный блок:
```nginx
location / {
    try_files $uri $uri/ @fallback;
}

location @fallback {
    return 404; # Либо явный rewrite без повторного try_files
}
```

---

## Лучшие практики

### Архитектура и организация конфигурации

1. **Плоская иерархия блоков:** Избегайте вложенных блоков `location` (nesting). Вложенные блоки создают непредсказуемое наследование директив (`proxy_set_header`, `add_header`, `root`), которое сложно поддерживать и тестировать.
2. **Точные совпадения для ключевых путей:** Для корневого пути `/`, фавиконов и эндпоинтов проверок жизнеспособности используйте точный модификатор `=`:
   ```nginx
   location = / { ... }
   location = /favicon.ico { access_log off; log_not_found off; }
   location = /robots.txt  { access_log off; log_not_found off; }
   location = /healthz     { access_log off; return 200 "OK\n"; }
   ```
   Это полностью исключает проход по префиксному дереву и регулярным выражениям для наиболее частотных запросов.

---

### Производительность и оптимизация ресурсов

1. **Приоритетные префиксы (`^~`) для всех деревьев статики:** Любой префиксный путь к статическим ассетам (`/static/`, `/assets/`, `/media/`, `/images/`) объявляйте с модификатором `^~`. Это полностью отключает CPU-затратный перебор регулярных выражений.
2. **Включение PCRE JIT:** Обязательно активируйте JIT-компиляцию для регулярных выражений на уровне `main` контекста в `/etc/nginx/nginx.conf`:
   ```nginx
   pcre_jit on;
   ```
   Это ускоряет сопоставление сложных регулярных выражений в 2–5 раз при высоких RPS.
3. **Минимизация числа регулярных выражений:** Объединяйте родственные расширения статики в единые regex-паттерны (`\.(jpg|jpeg|png|gif|ico|webp)$`), не создавая отдельный `location` под каждый тип файла.

---

### Безопасность и эксплуатация (SRE)

1. **Аудит слэшей при использовании `alias`:** Каждая директива `alias` должна проходить проверку на Off-by-slash: если префикс `location` завершается на слэш, аргумент `alias` обязан завершаться на слэш.
2. **Изоляция служебных файлов:** Всегда добавляйте глобальное правило блокировки скрытых каталогов и файлов системы контроля версий:
   ```nginx
   location ~ /\. {
       deny all;
       access_log off;
       log_not_found off;
   }
   ```
3. **Очистка журналов для Health Checks:** Всегда отключайте `access_log off;` для эндпоинтов мониторинга (`/healthz`, `/nginx_status`). Это снижает нагрузку на дисковую подсистему (Disk I/O) и предотвращает раздувание журналов миллионами одинаковых записей.
4. **Контроль методов через `limit_except`:** Защищайте критические API-эндпоинты, разрешая модифицирующие методы (POST, PUT, DELETE) только авторизованным подсетям.

---

## Дополнительная информация

### См. также

- **[Nginx location: лучшие практики и отладка](./best_practices.md)** — архитектурные шаблоны плоских конфигураций, наследование директив и профилирование.
- **[Nginx: внутренняя маршрутизация](./internal_routing.md)** — глубокий разбор `try_files`, именованных локейшенов (`@name`), `error_page` и заголовка `X-Accel-Redirect`.
- **[Nginx: отдача статических файлов](./serving_files.md)** — директивы `root`, `alias`, кэширование дескрипторов `open_file_cache`, `sendfile` и `gzip_static`.
- **[Предикатные локейшены и продвинутая маршрутизация API-трафика](./predicate_locations.md)** — маршрутизация по переменным, заголовкам и телу запроса в Nginx 1.31.5+.
- **[Nginx location: примеры интеграции](./integration_examples.md)** — сопряжение Nginx с PHP-FPM, uWSGI, gRPC и Node.js.
- **[Перенаправления и перезапись URI в Nginx](../nginx_rewrite_rules_and_try_files.md)** — директивы `rewrite`, `return`, флаги `last` / `break` и взаимодействие с фазой поиска `location`.
- **[Редиректы и proxy_redirect в Nginx](../../Proxy/nginx_proxy_redirects.md)** — управление редиректами бэкендов, коды 301/302 vs 307/308 и абсолютные/относительные перенаправления.
- **[CORS в Nginx](../../Security/nginx_cors_guide.md)** — архитектура настройки Cross-Origin Resource Sharing, Preflight OPTIONS и белый список Origin.
