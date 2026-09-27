# Nginx location: лучшие практики и отладка

> **Надежность: 10** (Подтверждено актуальной документацией Nginx на август 2026)

## Определения

**Лучшие практики (Best practices) для location** — набор проверенных рекомендаций по организации блоков `location`, направленных на повышение производительности, безопасности и удобства сопровождения конфигурации Nginx в эксплуатации SRE/sysadmin.

**Плоская структура (Flat structure)** — организация конфигурации, при которой блоки `location` не вложены друг в друга, а повторяющиеся настройки выносятся в отдельные файлы через `include`. Является эталоном для поддерживаемых конфигураций.

**Именованный location (`@name`)** — блок `location`, идентифицируемый именем после символа `@`, не участвующий в стандартном сопоставлении URI и вызываемый только явно через `try_files`, `error_page`, `rewrite ... last` или `X-Accel-Redirect`. Подробнее — в **[Внутренняя маршрутизация](./internal_routing.md)**.

**Внутренний запрос** — запрос, генерируемый самим Nginx (через `rewrite`, `try_files`, `error_page`, `X-Accel-Redirect`, `auth_request`, `mirror`), без участия внешнего клиента.

**Zero-downtime reload** — перезагрузка конфигурации Nginx без обрыва существующих соединений, выполняемая через `nginx -s reload`. Требует предварительной валидации конфигурации командой `nginx -t`.

**Rate limiting per location** — ограничение частоты запросов на уровне отдельного блока `location` через директивы `limit_req` и `limit_conn`. Позволяет защищать чувствительные эндпоинты без глобальных настроек.

---

## Базовые концепции

### Архитектура и организация location-блоков

#### Плоская vs вложенная структура

Nginx поддерживает вложенность блоков `location`, но это считается антипаттерном. Вложенность создает сложные цепочки наследования директив (`proxy_set_header`, `root`, `add_header`), которые трудно отлаживать и приводят к неочевидному поведению.

**Эталонная плоская структура:**

```
/etc/nginx/
├── nginx.conf                 # Глобальные параметры (worker_processes, events, http)
├── conf.d/
│   ├── headers.conf           # Общие заголовки безопасности
│   ├── logging.conf           # Форматы логов
│   └── rate_limits.conf       # Зоны limit_req/limit_conn
├── sites-available/
│   ├── example.com.conf       # Основной vhost
│   └── api.example.com.conf   # API vhost
└── snippets/
    ├── ssl.conf               # TLS-настройки
    └── proxy-params.conf      # Параметры проксирования
```

**Преимущества плоской структуры:**
- Каждый блок `location` явно объявлен в одном файле.
- Наследование директив предсказуемо.
- Изменения в одном файле не затрагивают неожиданные блоки.
- `nginx -T` выдает плоский список, удобный для grep.

#### Централизация через include

Для исключения дублирования настроек выносите их в отдельные файлы и подключайте через `include`:

```nginx
# /etc/nginx/conf.d/headers.conf
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;

# /etc/nginx/sites-available/example.com.conf
server {
    listen 443 ssl http2;
    server_name example.com;

    include conf.d/headers.conf;

    location /assets/ {
        root /var/www/html;
        expires 30d;
    }
}
```

> **Важно:** Файлы, подключаемые через `include`, обрабатываются в порядке их объявления. Если внутри `include` определен `location`, он участвует в общем алгоритме сопоставления. Порядок `include` внутри `server` влияет на приоритет regex-локаций.

### Производительность сопоставления

#### Приоритет префиксов над регулярными выражениями

Префиксные `location` (без модификатора и с `^~`) используют префиксное дерево (trie) для поиска за O(L), где L — длина URI. Регулярные выражения (`~` / `~*`) проверяются последовательно в порядке объявления в файле.

**Рекомендации:**
- Для статических директорий всегда используйте `^~`. Это прекращает поиск после нахождения самого длинного префикса и полностью исключает стадию проверки регулярных выражений.
- Регулярные выражения используйте только для сложных паттернов (проверка расширений файлов, скрытых файлов).
- Модификатор `~*` (регистронезависимый) предпочтительнее `~` для расширений файлов, чтобы корректно обрабатывать `.JPG` и `.jpg`.

#### PCRE JIT

Если использование регулярных выражений необходимо, включите JIT (Just-In-Time) для библиотеки PCRE:

```nginx
# В контексте main (обычно в /etc/nginx/nginx.conf)
pcre_jit on;
```

JIT компилирует регулярные выражения в машинный код при запуске, ускоряя выполнение в десятки раз. Без JIT regex-локации обрабатываются значительно медленнее префиксных.

### Безопасность location-блоков

#### Директива internal

Директива `internal` ограничивает доступ к `location` только внутренними запросами Nginx. Прямой HTTP-запрос от клиента вернет `404 Not Found` (начиная с Nginx 1.25.x; в более старых версиях мог возвращаться `403`).

```nginx
location /internal_files/ {
    internal;
    alias /data/secure/;
}
```

**Случаи использования:**
- Защита статики, отдаваемой через `X-Accel-Redirect`.
- Защита страниц ошибок, которые не должны вызываться напрямую.
- Внутренние API-эндпоинты для `auth_request`.

#### Защита системных и скрытых файлов

Блокировка доступа к служебным данным (`.git`, `.env`, `.htaccess`, файлы конфигурации) должна быть приоритетной. Размещайте этот `location` в начале `server` блока:

```nginx
location ~ /\.(?!well-known) {
    deny all;
    access_log off;
    log_not_found off;
}
```

`access_log off` и `log_not_found off` предотвращают заполнение логов запросами к несуществующим скрытым файлам.

#### Ограничение методов через limit_except

Внутри `location` можно ограничить использование определенных HTTP-методов:

```nginx
location /api/ {
    limit_except GET POST {
        allow 192.168.1.0/24;
        deny  all;
    }
    proxy_pass http://backend_api;
}
```

В этом примере методы GET и POST будут разрешены всем (согласно другим правилам), а PUT, DELETE, PATCH — только из доверенной подсети.

#### Влияние merge_slashes

Директива `merge_slashes on;` (по умолчанию) объединяет несколько слэшей в один (`//path//` → `/path/`). Отключение (`off`) позволяет различать `//path` и `/path`, что используется для контроля обхода путей. При проектировании путей учитывайте это поведение, особенно если в конфигурации есть regex-локации, зависящие от точного совпадения.

#### Защита от Directory Traversal через disable_symlinks

Для каталогов, где пользователи могут загружать файлы, отключайте переход по символическим ссылкам:

```nginx
location /uploads/ {
    disable_symlinks on from=$document_root;
    root /var/www/html;
}
```

Это предотвращает атаки, когда злоумышленник загружает симлинк, указывающий на `/etc/passwd`.

### Управление конфигурацией

#### Верификация перед применением

Любые изменения в конфигурации должны проходить обязательную проверку:

```bash
# Проверка синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Просмотр объединенного конфига (отладка include)
nginx -T | grep -n "location"

# Graceful reload — без потери соединений
nginx -s reload
# → signal processed
```

`nginx -t` проверяет только синтаксис. Для проверки конфликтов `location` и валидации путей используйте `nginx -T`.

#### Стратегия rollback

Для production-серверов настройте быстрый откат:

```bash
# Сохранить текущую рабочую конфигурацию
cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak.$(date +%Y%m%d%H%M%S)

# При ошибке после reload — мгновенный откат
cp /etc/nginx/nginx.conf.bak.20260922153000 /etc/nginx/nginx.conf
nginx -s reload
```

В системах с `git` конфигурации Nginx рекомендуется хранить в репозитории и применять через CI/CD pipeline с автоматическим rollback при неудаче `nginx -t`.

---

## Практические сценарии

### Сценарий 1: Разделение статики и динамики

Приоритетная отдача статики без проверки регулярных выражений:

```nginx
# Приоритетный префикс для статики — пропускаем regex
location ^~ /assets/ {
    root /var/www/html;
    expires 30d;
    add_header Cache-Control "public, no-transform" always;
    access_log off;
}

# Приоритетный префикс для API — пропускаем regex
location ^~ /api/ {
    proxy_pass http://backend_api;
    proxy_set_header Host $host;
}

# Regex для PHP
location ~ \.php$ {
    include fastcgi_params;
    fastcgi_pass unix:/var/run/php/php-fpm.sock;
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
}

# Префикс по умолчанию
location / {
    root /var/www/html;
    try_files $uri $uri/ =404;
}
```

**Порядок обработки запросов:**
- `/assets/style.css` → `location ^~ /assets/` (префикс с `^~`, шаг 3 алгоритма)
- `/api/v1/users` → `location ^~ /api/` (префикс с `^~`, шаг 3)
- `/index.php` → `location ~ \.php$` (регулярное выражение, шаг 4)
- `/about.html` → `location /` (префикс по умолчанию, шаг 5)

### Сценарий 2: Canary-развертывание через location + map

Для постепенного развертывания новой версии часть трафика направляется на новую версию. Используется связка `map` + `location`:

```nginx
# В контексте http: распределение по заголовку X-Canary
map $http_x_canary $backend_target {
    default         "http://stable_backend:8080";
    "true"          "http://canary_backend:8080";
    "1"             "http://canary_backend:8080";
}

server {
    listen 80;
    server_name app.example.com;

    location / {
        proxy_pass $backend_target;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Для проверки: `curl -H "X-Canary: true" http://app.example.com/api/health` → маршрут на `canary_backend`.

#### Canary по доле трафика (`split_clients`)

Хедер/cookie-канарейка хороша для точечных проверок, но для честного *процентного* распределения без участия клиента используется `split_clients` (стохастический выбор по хэшу `$remote_addr`+`$request_uri`):

```nginx
# В контексте http: 10% трафика → canary, остальные → stable
split_clients "${remote_addr}${request_uri}" $backend_target {
    10%  "http://canary_backend:8080";
    *    "http://stable_backend:8080";
}

server {
    listen 80;
    server_name app.example.com;

    location / {
        proxy_pass $backend_target;
        proxy_set_header X-Canary-Version $backend_target;
    }
}
```

Тот же клиент стабильно попадает в одну группу (детерминизм по хэшу), при росте нагрузки достаточно менять проценты — распределение остаётся взвешенным. Полный разбор canary-стратегий для Nginx (включая `map`+cookie и грейдинг 1→5→10%) — в [Canary Deployment](../../../../CI-CD/Deployment_Strategies/canary_deployment.md). Синтаксис и продвинутые приёмы `map`/`set`/`split_clients` (хэш-функции, сложные ключи, fallback) — в [переменных, map и гео в Angie](../../../Angie/angie_variables.md).

### Сценарий 3: Отладка неверного сопоставления в production

Для определения, какой блок обработал запрос, используйте кастомные заголовки:

```nginx
location ^~ /api/v1/ {
    add_header X-Matched-Location "API-V1" always;
    proxy_pass http://api_upstream;
}

location ^~ /api/v2/ {
    add_header X-Matched-Location "API-V2" always;
    proxy_pass http://api_upstream_v2;
}

location / {
    add_header X-Matched-Location "ROOT" always;
    root /var/www/html;
}
```

Параметр `always` гарантирует отправку заголовка даже в ответах с ошибками (404, 500).

### Сценарий 4: Ограничение скорости по location

Защита чувствительных эндпоинтов от брутфорса и флуда:

```nginx
http {
    # Зона для ограничения скорости API
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_status 429;

    # Зона для ограничения соединений
    limit_conn_zone $binary_remote_addr zone=addr:10m;
}

server {
    location /login {
        limit_req zone=api_limit burst=5 nodelay;
        limit_conn addr 10;
        proxy_pass http://auth_backend;
    }

    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
        proxy_pass http://api_backend;
    }
}
```

`burst=5` позволяет короткий всплеск до 5 запросов сверх лимита. `nodelay` обрабатывает burst-запросы немедленно, без задержки.

### Сценарий 5: Graceful config change с include и rollback

Применение изменений без downtime:

```bash
# 1. Создать новую версию include-файла
cat > /etc/nginx/snippets/new-location.conf << 'EOF'
location ^~ /new-feature/ {
    proxy_pass http://new_backend;
    proxy_set_header Host $host;
}
EOF

# 2. Подключить в vhost
echo 'include snippets/new-location.conf;' >> /etc/nginx/sites-available/example.com.conf

# 3. Валидация
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 4. Применение
nginx -s reload
# → signal processed

# 5. При проблемах — откат
sed -i '/include snippets\/new-location.conf/d' /etc/nginx/sites-available/example.com.conf
nginx -s reload
```

---

## Операции и команды

### Валидация и применение конфигурации

```bash
# Проверка синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Graceful reload — без потери соединений
nginx -s reload
# → signal processed

# Принудительная остановка (разрывает активные соединения)
nginx -s stop

# Просмотр объединенного конфига с подстановкой include
nginx -T | grep -n "location"
# → 45: location ^~ /assets/ {
# → 52: location ~ \.php$ {
# → 58: location / {
```

### Отладка сопоставления location

```bash
# Включение debug-лога в конфигурации:
# error_log /var/log/nginx/error.log debug;

# После reload в логе появляются записи:
# → *12345 using location "/api/v1/" for "/api/v1/users"
# → *12345 http script var: "$uri" = "/api/v1/users"

# Проверка через кастомный заголовок
curl -sI http://nginx-host/assets/style.css
# → X-Matched-Location: /assets/

# Проверка переменной $document_root
curl -s http://nginx-host/test/ \
  -H "Host: example.com"
# → (если настроен location /test/ с return 200 "$document_root")
```

### Мониторинг и статистика

```bash
# Проверка stub_status
curl -s http://localhost/nginx_status
# → Active connections: 1
#   server accepts handled requests
#   10 10 20
#   Reading: 0 Writing: 1 Waiting: 0

# Топ IP по количеству запросов
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10
# →   15234 192.168.1.100
#     8923 10.0.0.50
#     4521 172.16.0.1

# Поиск URL с наибольшим количеством ошибок 4xx/5xx
awk '$9 ~ /^[45]/ {print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10
```

### Управление правами и контекстом безопасности (sysadmin)

```bash
# Установка владельца для корневого каталога сайта
chown -R www-data:www-data /var/www/html

# Установка прав: директории 755, файлы 644
find /var/www/html -type d -exec chmod 755 {} \;
find /var/www/html -type f -exec chmod 644 {} \;

# Удаление прав на запись для группы и остальных
chmod -R go-w /var/www/html

# Для каталогов с загрузкой пользователей (upload)
chmod 733 /var/www/uploads

# Проверка контекста SELinux
ls -Z /var/www/html/

# Установка контекста для веб-контента (SELinux)
chcon -R -t httpd_sys_content_t /var/www/html/
chcon -R -t httpd_sys_rw_content_t /var/www/uploads/

# AppArmor: проверка профиля Nginx
aa-status | grep nginx
```

### Ротация логов

```bash
# Проверка конфигурации logrotate
cat /etc/logrotate.d/nginx

# Принудительная ротация
logrotate -f /etc/logrotate.d/nginx

# Проверка размера логов
du -sh /var/log/nginx/*
# → 12K    /var/log/nginx/access.log
# → 4.0K   /var/log/nginx/error.log
```

---

## Диагностика и устранение неполадок

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Запрос попадает в неожиданный location | `location /` без `^~` перехвачен regex-локацией | Добавить `^~` для префиксного location |
| `403 Forbidden` на статический файл | Нет прав на чтение или `disable_symlinks` | `chmod o+r`, проверка `disable_symlinks` |
| `404 Not Found` при существующем файле | Неверный `root`/`alias` или off-by-slash | Проверить `$document_root` через `return` |
| `403 Forbidden` при отключенном `autoindex` | Запрошен каталог без индексного файла | Добавить `index` или включить `autoindex` |
| `404` после включения `alias` | В `alias` нет завершающего слэша | Добавить слэш, если `location` им заканчивается |
| Циклический внутренний редирект | `try_files` вызывает URI, который снова попадает в тот же `location` | Использовать именованный `location @fallback` |
| Старый контент отдается после деплоя | Клиентский кэш без `Cache-Control: no-cache` | Использовать cache busting (хэши в именах) |
| `429 Too Many Requests` | Сработал `limit_req` | Увеличить `rate` или `burst`, или настроить исключения |

### Диагностические команды

```bash
# Определить фактический порядок location после include
nginx -T | grep -n "location"

# Включить debug-лог для отслеживания выбора location
# В секции events или http:
error_log /var/log/nginx/error.log debug;

# После этого в логе:
# → *12345 using location "/api/v1/" for "/api/v1/users"

# Проверить переменную document_root для отладки
# В конфигурации добавьте:
# location /test/ {
#     default_type text/plain;
#     return 200 "document_root: $document_root\nuri: $uri\n";
# }

# Просмотр логов доступа для статики
tail -f /var/log/nginx/access.log | grep "\.\(css\|js\|png\|jpg\)"

# Анализ ошибок доступа
grep "denied" /var/log/nginx/error.log
```

### Распространённые проблемы с `try_files`

1. **Бесконечный редирект:** `try_files $uri $uri/ /index.html` внутри `location /` вызывает `/index.html`, который снова попадает в тот же `location` и снова вызывает `try_files`.
   - **Решение:** Добавьте `index index.html;` или используйте именованный `location @fallback`.

2. **Потеря параметров запроса:** `try_files` передаёт только URI, query string отбрасывается.
   - **Решение:** Используйте `$is_args$args` в fallback: `try_files $uri $uri/ @backend;` и в `location @backend { proxy_pass http://backend$request_uri; }`.

---

## Лучшие практики

### Производительность

1. **Используйте `^~` для статических директорий.** Это прекращает поиск после нахождения самого длинного префикса и исключает проверку регулярных выражений, что критично для latency.
2. **Включайте `pcre_jit on;`** в контексте `main` для ускорения обработки регулярных выражений.
3. **Разделяйте статику и динамику:** горячая статика (CSS/JS) — на SSD, холодная (видео/архивы) — на HDD или отдельный сервер.
4. **Используйте именованные locations** для fallback-механизмов вместо дублирования конфигурации.
5. **Настраивайте `limit_req` и `limit_conn`** на уровне `location` для защиты чувствительных эндпоинтов.
6. **Включайте `access_log off`** для локаций с высокой частотой запросов к несуществующим ресурсам (например, regex для скрытых файлов).

### Безопасность

1. **Никогда не используйте `autoindex on`** в публичных зонах без контроля доступа.
2. **Блокируйте скрытые файлы и системные пути** на уровне `server`:

    ```nginx
    location ~ /\.(?!well-known) {
        deny all;
        access_log off;
        log_not_found off;
    }
    ```

3. **Отключайте симлинки** для каталогов, где пользователи могут загружать файлы:

    ```nginx
    disable_symlinks on from=$document_root;
    ```

4. **Используйте `internal`** для защищённых путей, доступных только через `X-Accel-Redirect`.
5. **Устанавливайте `merge_slashes on;`** (по умолчанию) для предотвращения атак обхода ограничений через двойные слэши.
6. **Используйте `limit_except`** для запрета нежелательных HTTP-методов на API-эндпоинтах.
7. **Применяйте `server_tokens off;`** для сокрытия версии Nginx.

### Эксплуатация (SRE)

1. **Ведение логов:** Настройте раздельные логи для статики и динамики, чтобы быстро диагностировать проблемы:

    ```nginx
    log_format static '$remote_addr - $remote_user [$time_local] '
                      '"$request" $status $body_bytes_sent '
                      '"$http_referer" "$http_user_agent"';

    location ~* \.(css|js|png|jpg|gif|ico|svg|woff2?)$ {
        access_log /var/log/nginx/static.access.log static;
    }
    ```

2. **Мониторинг:** Используйте `stub_status` или **[Мониторинг состояния Nginx](../../Operations/nginx_troubleshooting.md)** для отслеживания активных соединений.
3. **Версионирование конфигурации:** Храните конфиги в `git`, применяйте через CI/CD с автоматическим `nginx -t` и rollback.
4. **Валидация перед reload:** Всегда выполняйте `nginx -t` перед `nginx -s reload`. Ошибка в синтаксисе не затрагивает уже работающий Nginx — он продолжит работать со старой конфигурацией.
5. **Разделение ответственности:** Отдачу статики с TLS-терминацией лучше оставить на Nginx, а загрузку пользовательских файлов — вынести в отдельный виртуальный хост или поддомен для изоляции политик безопасности.

### Наблюдаемость

1. **Кастомные заголовки для отладки:** Используйте `add_header X-Matched-Location "..." always;` для быстрой идентификации обрабатывающего блока в production.
2. **Раздельные логи по типам:** Отдельные `log_format` для статики, API и ошибок.
3. **Метрики:** Подключите `stub_status` или `vts` для сбора метрик по location-блокам.

---

## Дополнительная информация

### Связанные темы

- **[Директива location: основы и приоритеты](./basics.md)** — алгоритмы выбора, модификаторы и приоритеты.
- **[Внутренняя маршрутизация](./internal_routing.md)** — `internal`, `X-Accel-Redirect`, именованные локации.
- **[Диагностика Nginx](../../Operations/nginx_troubleshooting.md)** — общие методы устранения ошибок.

### Тестирование конфигурации

```bash
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
nginx -s reload
# → graceful reload executed
```
