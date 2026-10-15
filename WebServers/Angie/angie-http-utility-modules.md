# Вспомогательные HTTP-модули и внутренние директивы Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**sub_filter** (`ngx_http_sub_module`) — потоковый фильтр тела ответа (body filter), выполняющий замену одной или нескольких строковых подстрок в исходящем потоке данных на лету. Применяется для динамической модификации HTML/JS, подмены URL ассетов и CDN-доменов, вставки скриптов аналитики и мониторинга без пересборки бэкенда.

**slice** (`ngx_http_slice_module`) — фильтр обработки запросов, разбивающий тяжелые HTTP-ответы от проксируемого бэкенда на фрагменты (срезы/чанги) фиксированного размера с использованием байтовых диапазонов (`Range`). Обеспечивает независимое кэширование произвольных фрагментов больших файлов (ISO, видео, артефакты сборки) без необходимости полной загрузки файла в кэш.

**split_clients** (`ngx_http_split_clients_module`) — модуль детерминированного A/B-тестирования и канареечной раскатки (Canary) на базе 32-битного алгоритма MurmurHash2. Разделяет клиентский трафик по процентным долям на основе хеша переданной строки (например, IP-адреса, cookie или сессионного токена).

**referer** (`ngx_http_referer_module`) — модуль контроля доступа на фазе Access, валидирующий значение заголовка запроса `Referer`. Выставляет флаг `$invalid_referer` для защиты медиафайлов от хотлинкинга (direct linking), парсинга контента сторонними сайтами и паразитного расхода полосы пропускания.

**gunzip** (`ngx_http_gunzip_module`) — фильтр тела ответа, выполняющий динамическую распаковку ответов с `Content-Encoding: gzip` для клиентов, не поддерживающих сжатие (инструменты автоматизации, устаревшие HTTP-клиенты, сканеры), если бэкенд или локальный диск хранят только сжатые версии файлов.

**server_names_hash** — статические хэш-таблицы ядра Angie для ускоренной маршрутизации входящих запросов по заголовку `Host` к соответствующим блокам `server`. Конфигурируются директивами `server_names_hash_max_size` и `server_names_hash_bucket_size`.

**map_hash** / **types_hash** / **variables_hash** — хэш-таблицы Angie для быстрого поиска соответствий в директивах `map`, таблицы сопоставления MIME-типов (`mime.types`) и пользовательских переменных ядра.

**underscores_in_headers** — директива парсинга заголовков HTTP ядра Angie, определяющая, разрешено ли клиентам передавать имена заголовков с символом подчеркивания `_`. По умолчанию выключена для предотвращения конфликтов переменных окружения в FastCGI/WSGI интерфейсах и атак манипуляции заголовками (CGI HTTP header injection).

**ignore_invalid_headers** — директива ядра Angie, предписывающая отбрасывать некорректные или недопустимые заголовки запроса в соответствии с RFC 7230 / RFC 9112 для нейтрализации атак рассогласования запросов (HTTP Request Smuggling).

## Архитектура и базовые концепции

### Жизненный цикл обработки запроса вспомогательными модулями

Вспомогательные утилитные модули Angie встроены в ядро веб-сервера и исполняются на разных фазах HTTP-конвейера (request processing phases):

```
+-------------------------------------------------------------------------+
|                         Запуск Angie (Init Phase)                       |
|  - Расчет хэш-таблиц: server_names_hash, map_hash, types_hash           |
|  - Проверка кратности bucket_size размеру строки кэша CPU (L1 line)     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                  Фаза чтения и парсинга заголовков                      |
|  - underscores_in_headers (фильтрация заголовков с '_')                 |
|  - ignore_invalid_headers (отбрасывание невалидных символов заголовков) |
|  - merge_slashes (нормализация URI)                                     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                    Фаза Rewrite / Пре-аксесс                            |
|  - split_clients: вычисление MurmurHash2(ключ), установка $ab_variable  |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                    Фаза Access (Контроль доступа)                       |
|  - ngx_http_referer_module: сверка заголовка Referer, расчет           |
|    переменной $invalid_referer (0 - разрешено, 1 - запрещено)           |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                    Фаза Content / Proxy Generation                      |
|  - ngx_http_slice_module: генерация Range-подзапросов к бэкенду         |
|    через переменную $slice_range, сегментация кэша по чанкам            |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                    Фаза Body Filter (Исходящий поток)                   |
|  1. ngx_http_gunzip_module: распаковка gzip-потока (при необходимости)  |
|  2. ngx_http_sub_module: строковая замена текста в буфере тела ответа   |
|  3. Пересчет Content-Length / удаление ETag / Last-Modified             |
+-------------------------------------------------------------------------+
```

### Сводная таблица утилитных модулей

| Модуль | Директивы и переменные | Фаза / Уровень | Потребление ресурсов |
| :--- | :--- | :--- | :--- |
| `ngx_http_sub_module` | `sub_filter`, `sub_filter_types`, `sub_filter_once`, `sub_filter_last_modified` | Output body filter | Память под буферы (`sub_filter_buffers`), умеренная нагрузка на CPU при сканировании строк |
| `ngx_http_slice_module` | `slice`, переменная `$slice_range` | Upstream / Cache handler | Увеличение количества L7-подзапросов к бэкенду, существенная экономия дискового пространства кэша |
| `ngx_http_split_clients_module` | `split_clients` | Pre-rewrite / Variable calculation | Минимальное: детерминированное вычисление хэша MurmurHash2 в оперативной памяти |
| `ngx_http_referer_module` | `valid_referers`, переменная `$invalid_referer` | Access filter | Минимальное: парсинг строки Referer и сопоставление по маске или регулярному выражению |
| `ngx_http_gunzip_module` | `gunzip`, `gunzip_buffers` | Output body filter | Нагрузка на CPU при распаковке потока `zlib`, выделение буферов памяти |

### Устройство и тюнинг хэш-таблиц ядра

Angie использует специализированные статические хэш-таблицы с открытой адресацией для минимизации задержек на этапе сопоставления доменов и переменных.

1. **Размер корзины (`bucket_size`):**
   - Параметры `server_names_hash_bucket_size`, `map_hash_bucket_size`, `types_hash_bucket_size` задают размер одной корзины хэш-таблицы в байтах.
   - Размер корзины должен быть строго кратен размеру кэш-линии процессора (CPU L1 cache line size, обычно **64 байта** на архитектурах x86_64 и AArch64). Это гарантирует, что поиск ключа в пределах одной корзины выполняется за одно обращение к кэшу памяти L1 без Cache Miss.
   - Если самое длинное доменное имя в блоках `server_name` превышает размер корзины, Angie завершает запуск с фатальной ошибкой: `could not build the server_names_hash, you should increase server_names_hash_bucket_size`.
2. **Максимальный размер хэша (`max_size`):**
   - Параметр `server_names_hash_max_size` задает суммарный предельный размер хэш-таблицы. При превышении этого лимита Angie пытается увеличить размер таблицы; если лимит исчерпан, запуск блокируется.

### Безопасность разбора HTTP-заголовков (RFC 7230 / CGI Collision)

1. **Проблема коллизии подчеркиваний:**
   - В спецификации CGI/WSGI/FastCGI все HTTP-заголовки запроса трансформируются в переменные окружения путем перевода в верхний регистр, добавления префикса `HTTP_` и замены дефисов на подчеркивания:
     - Заголовок `X-Forwarded-User` превращается в `HTTP_X_FORWARDED_USER`.
     - Злоумышленник может передать заголовок `X_Forwarded_User`. В среде бэкенда он также превратится в `HTTP_X_FORWARDED_USER`.
   - Если `underscores_in_headers on;` включено глобально, бэкенд не сможет отличить легитимный прокси-заголовок от инъекции злоумышленника. Поэтому директива по умолчанию выключена (`off`).
2. **Защита от рассогласования запросов (HTTP Request Smuggling):**
   - Директива `ignore_invalid_headers on;` (по умолчанию включена) запрещает прием заголовков с пробелами перед двоеточием, недопустимыми ASCII-символами и спецсимволами, предотвращая рассинхронизацию между фронтенд-прокси и бэкенд-серверами.

## Практические сценарии

### Сценарий 1: Динамическая подмена строк в HTML через sub_filter

Модуль `sub_filter` работает исключительно с распакованным потоком. Если бэкенд отдает сжатый контент (`Content-Encoding: gzip`), `sub_filter` не сможет выполнить замену. Для надежной работы необходимо принудительно отключать сжатие на стороне апстрима через сброс заголовка `Accept-Encoding`.

```nginx
# /etc/angie/http.d/sub_filter_demo.conf
server {
    listen 80;
    server_name portal.example.com;

    location / {
        proxy_pass http://internal_portal_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Критично: запрещаем бэкенду сжимать ответ, иначе sub_filter пропустит тело без изменений
        proxy_set_header Accept-Encoding "";

        # Включение множественных правил замены
        sub_filter 'https://legacy-static.internal' 'https://cdn.example.com/assets';
        sub_filter '</head>' '<link rel="preload" href="/static/fonts/inter.woff2" as="font" type="font/woff2" crossorigin></head>';
        sub_filter '<!-- ENVIRONMENT -->' '<meta name="app-env" content="production">';

        # Заменять все вхождения подстрок (off), а не только первое (on)
        sub_filter_once off;

        # Разрешенные MIME-типы для сканирования и замены
        sub_filter_types text/html text/xml text/javascript application/javascript;

        # Сброс или сохранение Last-Modified. При off заголовок Last-Modified удаляется,
        # так как контент был изменен на лету
        sub_filter_last_modified off;

        # Буферизация для непрерывного потокового сканирования
        sub_filter_buffers 8 16k;
    }
}
```

### Сценарий 2: Сегментированное кэширование тяжелых файлов через slice

При кэшировании видеофайлов (MP4, MKV), образов операционных систем (ISO) или пакетов репозиториев клиенты скачивают файлы параллельно или используют докачку (`Range: bytes=...`). Модуль `ngx_http_slice_module` запрашивает у бэкенда контент строго фиксированными чанками (например, по 2 МБ).

> [!IMPORTANT]
> Для корректной работы `slice` директива `proxy_cache_key` **обязана** включать переменную `$slice_range`, а директива `proxy_cache_valid` должна кэшировать статус **206**, так как бэкенд возвращает `206 Partial Content`.

```nginx
# /etc/angie/http.d/slice_caching.conf
proxy_cache_path /var/cache/angie/media_slice
                 levels=1:2
                 keys_zone=slice_cache:64m
                 max_size=50g
                 inactive=7d
                 use_temp_path=off;

server {
    listen 80;
    server_name storage.example.com;

    location ~* \.(mp4|iso|zip|tar\.gz|qcow2)$ {
        # Размер одного чанка среза
        slice 2m;

        proxy_cache slice_cache;

        # Уникальный ключ кэша ОБЯЗАН содержать $slice_range
        proxy_cache_key $uri$is_args$args$slice_range;

        # Передача диапазона среза бэкенду
        proxy_set_header Range $slice_range;

        # Обязательно кэшировать ответы 200 и 206 (Partial Content)
        proxy_cache_valid 200 206 72h;
        proxy_cache_valid 404 1m;

        # HTTP/1.1 требуется для устойчивой поддержки Range-запросов и Keepalive
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_pass http://backend_storage;

        # Заголовки для отладки состояния кэша в SRE-мониторинге
        add_header X-Cache-Status $upstream_cache_status always;
        add_header X-Slice-Range $slice_range always;
    }
}
```

### Сценарий 3: Детерминированная Canary-раскатка через split_clients

Модуль `split_clients` вычисляет 32-битный хэш MurmurHash2 от входного ключа и проецирует его на шкалу от 0 до 100%. Для отказоустойчивой маршрутизации избегайте использования директивы `if` в location — используйте переменную upstream-группы.

```nginx
# /etc/angie/http.d/canary_split.conf
# 5% трафика направляется на канареечный бэкенд, 95% — на стабильный
split_clients "${remote_addr}${http_user_agent}" $canary_target {
    5%     backend_canary;
    *      backend_stable;
}

upstream backend_stable {
    zone backend_stable_zone 64k;
    server 192.168.10.11:8080 max_fails=3 fail_timeout=10s;
    server 192.168.10.12:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

upstream backend_canary {
    zone backend_canary_zone 64k;
    server 192.168.10.13:8080 max_fails=2 fail_timeout=10s;
    keepalive 8;
}

server {
    listen 80;
    server_name api.example.com;

    # Логирование выбранной ветки трафика для сквозной аналитики
    access_log /var/log/angie/api_access.log combined;

    location / {
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Canary-Release $canary_target;

        # Динамическая передача в целевой upstream без директивы 'if'
        proxy_pass http://$canary_target;

        add_header X-Upstream-Selected $canary_target always;
    }
}
```

### Сценарий 4: Защита статических ресурсов от хотлинкинга (referer)

Модуль `ngx_http_referer_module` блокирует прямую вставку изображений и медиаконтента на сторонних сайтах.

```nginx
# /etc/angie/http.d/hotlink_protection.conf
server {
    listen 80;
    server_name cdn.example.com;

    location ~* \.(jpg|jpeg|png|webp|avif|svg|gif)$ {
        root /var/www/static;

        # Разрешенные источники:
        # none - запрос без Referer (прямой ввод URL в браузере, curl, мобильные приложения)
        # blocked - заголовок Referer удален корпоративным файрволом или прокси (начинается не с http/https)
        # server_names - собственные домены текущего блока server
        # *.example.com - все поддомены доверенного домена
        # ~partner.*\.org - регулярное выражение для доверенных сайтов-партнеров
        valid_referers none blocked server_names *.example.com ~partner.*\.org;

        if ($invalid_referer) {
            # Вариант 1: Жесткий сброс с 403 Forbidden
            return 403;

            # Вариант 2: Отдача специального баннера-заглушки вместо исходной картинки
            # rewrite ^ /images/hotlink-warning.png break;
        }

        expires 30d;
        add_header Cache-Control "public, no-transform";
    }
}
```

### Сценарий 5: Распаковка gzip-ответов для легаси-клиентов через gunzip

Если веб-сервер хранит предварительно сжатые статические файлы (`gzip_static on;`) или бэкенд возвращает исключительно сжатые ответы, модуль `gunzip` на лету распаковывает тело ответа для клиентов, не передающих `Accept-Encoding: gzip`.

```nginx
# /etc/angie/http.d/gunzip_service.conf
server {
    listen 80;
    server_name archive.example.com;

    root /var/www/archive;

    # Включение отдачи pre-compressed файлов .gz при их наличии на диске
    gzip_static on;

    # Включение автоматической распаковки на лету, если клиент не поддерживает gzip
    gunzip on;

    # Выделение буферов для распаковщика zlib (количество размер)
    gunzip_buffers 32 8k;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

### Сценарий 6: Тюнинг хэш-таблиц для высоконагруженных инсталляций

При размещении сотен виртуальных хостов, масштабных гео-баз или таблиц перенаправлений `map` Angie требует расширения корзин и пределов хэширования в блоке `http`.

```nginx
# /etc/angie/http.d/hash_tuning.conf
http {
    # Размер корзины server_names (кратно 64 байтам - строке кэша L1)
    # 64 байта достаточно для большинства доменов длиной до 48-52 символов
    # 128 байт необходимо для сверхдлинных FQDN-имен
    server_names_hash_bucket_size 128;
    server_names_hash_max_size    4096;

    # Хэш-таблица для директив map
    map_hash_bucket_size          128;
    map_hash_max_size             8192;

    # Хэш-таблица для MIME-типов
    types_hash_bucket_size        64;
    types_hash_max_size           2048;

    # Хэш-таблица для переменных Angie
    variables_hash_bucket_size    128;
    variables_hash_max_size       4096;
}
```

### Сценарий 7: Безопасный прием кастомных заголовков с подчеркиванием

По умолчанию Angie игнорирует входящие заголовки с `_` (`underscores_in_headers off;`). Если внутренняя интеграция строго требует такие заголовки, разрешайте их точечно на уровне `server` или отдельного приватного порта, изолированного от публичного интернета.

```nginx
# /etc/angie/http.d/internal_api.conf
server {
    listen 10.0.50.15:8443 ssl;
    server_name internal-gateway.local;

    ssl_certificate /etc/angie/tls/internal.crt;
    ssl_certificate_key /etc/angie/tls/internal.key;

    # Разрешено ТОЛЬКО в закрытом доверенном периметре
    underscores_in_headers on;

    # Жесткий отброс некорректных символов заголовков по RFC 7230
    ignore_invalid_headers on;

    # Нормализация сдвоенных слешей во избежание обхода правил безопасности
    merge_slashes on;

    location /api/v1/ {
        # Заголовок X_SERVICE_TOKEN будет успешно прочитан в $http_x_service_token
        proxy_set_header X-Validated-Token $http_x_service_token;
        proxy_pass http://backend_internal_api;
    }
}
```

## Операции и команды

### 1. Верификация доступности встроенных утилитных модулей

Проверка наличия модулей в скомпилированном бинарном файле Angie:

```bash
angie -V 2>&1 | tr ' ' '\n' | grep -E "with-http_(sub|slice|split_clients|referer|gunzip)_module"
```
```text
# → --with-http_sub_module
# → --with-http_slice_module
# → --with-http_gunzip_module
```
*(Модули `split_clients` и `referer` являются стандартными базовыми HTTP-модулями и присутствуют по умолчанию без отдельных флагов `--with`)*.

### 2. Валидация синтаксиса конфигурации

```bash
sudo angie -t
```
```text
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
```

Плавное применение изменений без прерывания активных клиентских сессий:

```bash
sudo systemctl reload angie
```
```text
# → (код возврата 0, статус active (running) в systemctl status angie)
```

### 3. Диагностика сегментированного кэша slice

Тестирование запроса первого чанка (0–1 МБ) с проверкой заголовков Range и статуса кэша:

```bash
curl -s -I -H "Range: bytes=0-1048575" http://storage.example.com/data.iso
```
```text
# → HTTP/1.1 206 Partial Content
# → Server: Angie/1.12.0
# → Content-Type: application/x-iso9660-image
# → Content-Length: 1048576
# → Content-Range: bytes 0-1048575/524288000
# → X-Cache-Status: MISS
# → X-Slice-Range: bytes=0-2097151
```

Повторный запрос для подтверждения попадания в кэш (HIT):

```bash
curl -s -I -H "Range: bytes=0-1048575" http://storage.example.com/data.iso | grep -E "HTTP|Content-Range|X-Cache-Status"
```
```text
# → HTTP/1.1 206 Partial Content
# → Content-Range: bytes 0-1048575/524288000
# → X-Cache-Status: HIT
```

### 4. Статистическое тестирование процентного распределения split_clients

Запуск 1000 запросов с уникальными синтетическими IP-адресами клиентов для валидации точности распределения канарейки:

```bash
for i in $(seq 1 1000); do
    curl -s -H "Host: api.example.com" -H "X-Real-IP: 10.100.$((i/255)).$((i%255))" http://127.0.0.1/ \
    -o /dev/null -w "%{header_json}\n" 2>/dev/null | grep -oP '(?<="x-upstream-selected":\[")[^"]+' || true
done | sort | uniq -c
```
```text
# → 51 backend_canary
# → 949 backend_stable
```
*(Результат 51 / 949 идеально соответствует заданной пропорции 5% / 95% с погрешностью менее 0.2%)*.

### 5. Проверка блокировки хотлинкинга (referer)

Запрос с запрещенного стороннего реферера:

```bash
curl -s -o /dev/null -w "HTTP: %{http_code}\n" -H "Referer: https://malicious-tracker.ru/catalog" http://cdn.example.com/logo.png
```
```text
# → HTTP: 403
```

Запрос с доверенного реферера:

```bash
curl -s -o /dev/null -w "HTTP: %{http_code}\n" -H "Referer: https://app.example.com/dashboard" http://cdn.example.com/logo.png
```
```text
# → HTTP: 200
```

Запрос без заголовка Referer (валидируется ключевым словом `none`):

```bash
curl -s -o /dev/null -w "HTTP: %{http_code}\n" http://cdn.example.com/logo.png
```
```text
# → HTTP: 200
```

### 6. Мониторинг предупреждений хэш-таблиц ядра

Поиск сообщений о переполнении корзин хэшей или необходимости увеличения bucket size:

```bash
grep -iE "could not build|hash_bucket_size|hash_max_size" /var/log/angie/error.log | tail -n 10
```
```text
# → (при корректной конфигурации вывод пустой)
```

## Устранение неисправностей

| Симптом / Ошибка | Вероятная причина | Диагностика | Способ устранения |
| :--- | :--- | :--- | :--- |
| `could not build the server_names_hash, you should increase server_names_hash_bucket_size` | Доменное имя превышает текущую корзину (по умолчанию 32 или 64 байта) либо корзины переполнены коллизиями. | `angie -t` возвращает ошибку сборки хэша при запуске. | Увеличить в `http {}`: `server_names_hash_bucket_size 128;` и при необходимости `server_names_hash_max_size 4096;`. |
| `sub_filter` не заменяет подстроки в ответе | 1. Бэкенд сжал тело (`gzip`).<br>2. `Content-Type` не указан в `sub_filter_types`.<br>3. `sub_filter_once on` заменил только первое вхождение. | `curl -sI -H "Accept-Encoding: gzip" <URL>` возвращает `Content-Encoding: gzip`. | 1. Добавить `proxy_set_header Accept-Encoding "";`.<br>2. Добавить нужный тип в `sub_filter_types`.<br>3. Выставить `sub_filter_once off;`. |
| При использовании `slice` отдаются поврежденные файлы или дублирующиеся куски | Ключ кэша не содержит `$slice_range`, либо кэш не настроен на сохранение ответов с кодом `206`. | Проверить ключ кэша и ответ `curl -I -r 0-100 <URL>`. В логах кэша статус `MISS` сменяется неверным `HIT`. | 1. Указать `proxy_cache_key $uri$is_args$args$slice_range;`.<br>2. Задать `proxy_cache_valid 200 206 24h;`. |
| `split_clients` направляет всех клиентов на один и тот же бэкенд | Ключ распределения не уникален (например, все клиенты за корпоративным NAT приходят с одинаковым `$remote_addr`). | `awk '{print $1}' /var/log/angie/access.log \| sort \| uniq -c` показывает один IP. | Использовать комбинированный ключ: `split_clients "${remote_addr}$http_user_agent$cookie_session_id"`. При работе за балансировщиком включить модуль `real_ip`. |
| Пользовательский заголовок вида `X_Auth_Token` не доходит до бэкенда | Включена политика безопасности `underscores_in_headers off;` (по умолчанию). | В дампе трафика на бэкенде заголовок отсутствует, хотя клиент его отправляет. | Включить `underscores_in_headers on;` в блоке `server` либо изменить формат имени заголовка на стандартный `X-Auth-Token`. |
| `gunzip` возвращает ошибку буферизации или 500 Internal Server Error | Недостаточный размер или количество буферов `gunzip_buffers` для тяжелого распаковываемого файла. | В `error.log`: `gunzip: buffer error while decompressing`. | Увеличить буферы в конфигурации: `gunzip_buffers 32 16k;` или `64 8k;`. |

## Лучшие практики

1. **Кратность корзин хэшей кэш-линии процессора:** Всегда задавайте значения `server_names_hash_bucket_size`, `map_hash_bucket_size`, `types_hash_bucket_size` степенями двойки: **64** или **128**. Это обеспечивает размещение корзины точно в границах линий кэша L1/L2 процессора, предотвращая лишние циклы шины памяти.
2. **Безопасность заголовков в production:** Оставляйте директивы `underscores_in_headers off;` и `ignore_invalid_headers on;` включенными по умолчанию в глобальной конфигурации. Это предотвращает атаки рассогласования запросов (Request Smuggling) и исключает риск перезаписи переменных окружения через FastCGI/WSGI.
3. **Строгая сегментация больших файлов с slice:**
   - Выбирайте размер среза (`slice 1m;` .. `slice 4m;`) в зависимости от скорости дисковой подсистемы и структуры трафика. Чрезмерно маленький срез (например, 64k) перегружает процессор и планировщик L7-подзапросов, а слишком большой (32m) нивелирует выгоду от Range-кэширования при коротких сессиях просмотра.
   - Обязательно защищайте бэкенд директивой `proxy_cache_lock on;`, чтобы параллельные запросы на один и тот же непрогретый срез не создавали шквал одновременных запросов к дисковому хранилищу (Thundering Herd).
4. **Сброс Accept-Encoding при использовании sub_filter:** Если в цепочке проксирования задействован `sub_filter`, всегда сбрасывайте входящий заголовок сжатия `proxy_set_header Accept-Encoding "";`, либо организуйте связку с модулем `gunzip`. В противном случае сжатые бэкендом ответы будут отданы клиенту без модификации.
5. **Детерминизм канареечной раскатки (split_clients):**
   - Для сохранения непрерывности пользовательских сессий (Sticky Canary) формируйте ключ хэширования из стабильных идентификаторов: клиентского IP (с учетом `real_ip` за L4/L7 балансировщиками) в комбинации с сессионной cookie или `User-Agent`.
   - Не используйте псевдослучайные переменные (`$request_id`, `$msec`) в качестве ключа `split_clients`, если требуется стабильность отображения версии для одного и того же пользователя.
6. **Ограниченное применение referer:** Помните, что заголовок `Referer` легко подделывается любым HTTP-клиентом и отсекается современными браузерами при строгой политике `Referrer-Policy: no-referrer`. Используйте `ngx_http_referer_module` как фильтр паразитного браузерного трафика, а не как авторизационный механизм защиты приватных данных.
7. **Очистка заголовков кэширования при модификации ответов:** При использовании `sub_filter` устанавливайте `sub_filter_last_modified off;`. Если этого не сделать, браузеры и промежуточные кэширующие прокси могут закэшировать модифицированную версию под старым `ETag` / `Last-Modified`, что приведет к неконсистентности данных у пользователей.

## Дополнительная информация

### Связанные материалы в базе знаний

- [Базовая конфигурация Angie](./angie-baseline-config.md) — системная оптимизация буферов, worker-процессов и сетевого стека.
- [Директивы location в Angie](./angie_location_directives.md) — алгоритмы сопоставления префиксных и регулярных location.
- [Переменные, map и geo в Angie](./angie_variables.md) — глубокое погружение в синтаксис директив `map`, `geo` и хэширование переменных.
- [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md) — управление апстримами, health check и алгоритмы распределения запросов.
- [Потоковое видео в Angie](./angie_video_streaming.md) — практическая реализация MP4/HLS псевдостриминга и связка с `ngx_http_slice_module`.
- [Оптимизация сжатия в Nginx](../Nginx/Performance/nginx_compression.md) — параметры модулей `gzip`, `gzip_static` и Brotli.
- [Отдача файлов (serving_files)](../Nginx/Core/Location/serving_files.md) — организация статических хранилищ и оптимизация `sendfile`/`tcp_nopush`.

### Официальные источники

- Документация Angie: [https://angie.software/ru/configuration/](https://angie.software/ru/configuration/)
- Документация модуля `ngx_http_sub_module`: [https://nginx.org/ru/docs/http/ngx_http_sub_module.html](https://nginx.org/ru/docs/http/ngx_http_sub_module.html)
- Документация модуля `ngx_http_slice_module`: [https://nginx.org/ru/docs/http/ngx_http_slice_module.html](https://nginx.org/ru/docs/http/ngx_http_slice_module.html)
- Документация модуля `ngx_http_split_clients_module`: [https://nginx.org/ru/docs/http/ngx_http_split_clients_module.html](https://nginx.org/ru/docs/http/ngx_http_split_clients_module.html)
- Документация модуля `ngx_http_referer_module`: [https://nginx.org/ru/docs/http/ngx_http_referer_module.html](https://nginx.org/ru/docs/http/ngx_http_referer_module.html)
- Документация модуля `ngx_http_gunzip_module`: [https://nginx.org/ru/docs/http/ngx_http_gunzip_module.html](https://nginx.org/ru/docs/http/ngx_http_gunzip_module.html)