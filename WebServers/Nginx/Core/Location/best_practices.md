# Nginx location: лучшие практики и отладка

**Актуально для:** Nginx 1.26.x (Stable) / 1.27.x (Mainline)

## Определения

**Лучшие практики (Best practices) для location** — набор проверенных архитектурных и конфигурационных рекомендаций по организации блоков `location`, направленных на оптимизацию производительности сопоставления URI, усиление безопасности веб-сервера и упрощение сопровождения в эксплуатации DevOps, SRE и системных администраторов.

**Плоская структура (Flat structure)** — архитектурный подход к проектированию конфигурации, при котором блоки `location` объявляются на одном верхнем уровне внутри блока `server` без глубокой вложенности, а повторяющиеся фрагменты выносятся в отдельные файлы через директиву `include`.

**Наследование директив (Directive inheritance)** — модель распространения настроек в иерархии Nginx (`http` → `server` → `location`). Директивы списочного типа (action/array directives, такие как `add_header` и `proxy_set_header`) при определении на текущем уровне полностью перезаписывают значения, унаследованные с родительских уровней.

**Именованный location (`@name`)** — конфигурационный блок, идентифицируемый префиксом `@`, который исключен из стандартного сопоставления входящих URI и вызывается исключительно внутренними механизмами сервера (`try_files`, `error_page`, `rewrite ... last`, `X-Accel-Redirect`). Подробнее — в **[Внутренняя маршрутизация](./internal_routing.md)**.

**Внутренний запрос (Internal request)** — вторичный цикл обработки запроса, инициируемый самим Nginx без возврата сетевого ответа клиенту и без изменения URL в адресной строке браузера.

**Zero-downtime reload** — процедура горячего применения новой конфигурации Nginx без потери и разрыва активных клиентских соединений, инициируемая сигналом `HUP` (`nginx -s reload` или `systemctl reload nginx`) после успешной валидации через `nginx -t`.

**Rate limiting per location** — ограничение частоты запросов и количества параллельных соединений на уровне конкретного блока `location` через модули `ngx_http_limit_req_module` и `ngx_http_limit_conn_module`.

**Режим симуляции (Dry run)** — диагностический режим директивы `limit_req_dry_run on;`, при котором превышение лимитов запросов фиксируется в логах и обновляет статусную переменную `$limit_req_status`, но клиентам не возвращается блокирующий HTTP-статус 429.

**Off-by-slash** — конфигурационная уязвимость маршрутизации при использовании директивы `alias`, возникающая из-за отсутствия замыкающего слэша в префиксе `location` при наличии слэша в целевом пути, что позволяет атакующему выполнять обход каталога (Directory Traversal).

**Заголовок трассировки (Tracing header)** — служебный HTTP-заголовок ответа (например, `X-Matched-Location`), добавляемый директивой `add_header ... always;` для точной идентификации блока `location`, обработавшего запрос.

**PCRE JIT (Just-In-Time)** — компилятор регулярных выражений библиотеки PCRE/PCRE2 в машинный код во время инициализации воркеров Nginx, минимизирующий процессорные задержки при сопоставлении regex-локаций.

---

## Базовые концепции

### Архитектура и организация location-блоков

#### Плоская vs вложенная структура

Nginx синтаксически поддерживает вложенные блоки `location`, однако в промышленной эксплуатации (production SRE) глубокая вложенность является распространенным антипаттерном. 

Причины отказа от вложенности:
1. **Неочевидное наследование директив:** Вложенный `location` полностью перетирает унаследованные директивы массивов (`proxy_set_header`, `add_header`), если объявляет хотя бы одну собственную.
2. **Усложнение алгоритма сопоставления:** При вложенности Nginx сначала ищет совпадение на внешнем уровне, затем спускается во внутренние блоки, где правила приоритетов префиксов и регулярных выражений начинают работать локально. Это резко увеличивает сложность отладки.
3. **Затруднение автоматического аудита:** Плоские конфигурации легко парсятся утилитами автоматизации, grep и линтерами.

**Эталонная организация файловой структуры:**

```
/etc/nginx/
├── nginx.conf                 # Глобальный контекст (worker_processes, events, http)
├── conf.d/
│   ├── logging.conf           # Форматы журналов (main, json, tracing)
│   ├── rate_limits.conf       # Зоны limit_req_zone и limit_conn_zone
│   └── upstreams.conf         # Пулы серверов upstream
├── sites-available/
│   ├── example.com.conf       # Конфигурация виртуального хоста
│   └── api.example.com.conf   # Конфигурация API хоста
├── sites-enabled/             # Символические ссылки на активные vhost
└── snippets/
    ├── ssl-params.conf        # Параметры TLS, шифры, сессии
    ├── security-headers.conf  # Заголовки безопасности (HSTS, CSP, X-Frame)
    └── proxy-params.conf      # Заголовки и таймауты проксирования
```

#### Централизация настроек через include и snippets

Для соблюдения принципа DRY (Don't Repeat Yourself) повторяющиеся директивы выносятся в каталоги `snippets/` или `conf.d/`.

```nginx
# /etc/nginx/snippets/security-headers.conf
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

# /etc/nginx/sites-available/example.com.conf
server {
    listen 443 ssl;
    http2 on;
    server_name example.com;

    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    # Подключение общих заголовков на уровне server
    include snippets/security-headers.conf;

    location / {
        root /var/www/html;
        try_files $uri $uri/ =404;
    }

    location ^~ /assets/ {
        root /var/www/html;
        expires 30d;
        # Если здесь объявляется локальный add_header, родительские заголовки пропадут!
        # Решение: повторный include snippets/security-headers.conf
        include snippets/security-headers.conf;
        add_header Cache-Control "public, no-transform, immutable" always;
    }
}
```

#### Логика и ловушки наследования директив

Ключевое правило Nginx для директив списочного типа (`add_header`, `proxy_set_header`, `fastcgi_param`):
> **Директивы наследуются с предыдущего уровня конфигурации тогда и только тогда, когда на текущем уровне не объявлено ни одной директивы этого же типа.**

Если на уровне `server` настроены заголовки безопасности через `add_header`, а внутри `location /download/` объявлен заголовок `add_header Content-Disposition "attachment";`, то браузер клиента **не получит** ни одного заголовка безопасности (`X-Frame-Options`, `HSTS` и т.д.) для запросов к `/download/`. 

Для предотвращения этой проблемы в эксплуатации применяются два подхода:
1. Вынос базового комплекта заголовков в snippet и его вызов во всех блоках `location`, содержащих специфические `add_header`.
2. Использование внешнего динамического модуля `ngx_headers_more` (`more_set_headers`), который заменяет логику перезаписи на безусловное добавление, если сборка Nginx поддерживает сторонние модули.

---

### Производительность сопоставления

#### Префиксное дерево (Trie) против последовательного перебора regex

Алгоритм поиска целевого `location` состоит из двух основных этапов:
1. **Поиск по префиксам:** Nginx выполняет поиск самого длинного совпадающего префикса в статическом префиксном дереве (Trie). Вычислительная сложность составляет $O(L)$, где $L$ — длина URI, и не зависит от общего числа блоков `location`.
2. **Проверка регулярных выражений:** Если самый длинный префикс не содержит модификатора `^~` или `=`, Nginx начинает последовательно проверять блоки с модификаторами `~` и `~*` в порядке их следования в конфигурационном файле. Вычислительная сложность составляет $O(N \cdot M)$, где $N$ — число regex-локаций, а $M$ — стоимость выполнения регулярного выражения.

```
Входящий URI
     │
     ▼
[Точное совпадение = ] ──(Да)──► Немедленный выбор (Stop)
     │
    (Нет)
     ▼
[Поиск в префиксном дереве] ──► Запоминаем самый длинный префикс
     │
     ├─ Префикс с ^~ ? ──(Да)──► Немедленный выбор (Stop, пропуск regex)
     │
    (Нет)
     ▼
[Последовательная проверка regex ~ / ~*]
     │
     ├─ Совпало regex-правило? ──(Да)──► Выбор первого совпавшего regex (Stop)
     │
    (Нет)
     ▼
[Возврат к сохраненному длинному префиксу]
```

**Рекомендации по оптимизации:**
- Для всех статических путей, медиа-каталогов и API-эндпоинтов используйте модификатор `^~`. Он прекращает маршрутизацию сразу после нахождения префикса и полностью исключает фазу перебора регулярных выражений, снижая latency на высоконагруженных шлюзах.
- Для критичных одиночных URI (например, `/healthz`, `/robots.txt`, `/favicon.ico`) используйте точный модификатор `=`. Поиск по точному равенству выполняется за $O(1)$ хэш-таблицы еще до обхода префиксного дерева.

#### PCRE JIT

Если использование регулярных выражений неизбежно (например, роутинг по сложным расширениям файлов или валидация токенов в URI), необходимо активировать JIT-компиляцию в глобальном контексте:

```nginx
# В контексте main (/etc/nginx/nginx.conf)
pcre_jit on;
```

Директива `pcre_jit on;` компилирует регулярные выражения в машинные инструкции процессора при старте сервера. Это ускоряет выполнение проверок в 3–10 раз по сравнению с классической интерпретацией байткода PCRE при каждом входящем запросе.

---

### Безопасность location-блоков

#### Директива internal

Директива `internal` запрещает прямой доступ к блоку `location` из внешней сети. При попытке внешнего клиента запросить такой URI сервер возвращает код `404 Not Found`, маскируя факт существования эндпоинта.

```nginx
location /internal_assets/ {
    internal;
    alias /var/www/protected_storage/;
}
```

Области применения:
- Отдача защищенных файлов, проверенных бэкендом, через заголовок `X-Accel-Redirect`.
- Эндпоинты страниц ошибок (`error_page 404 /custom_404.html;`).
- Обработчики модуля аутентификации `auth_request /auth_check;`.

#### Защита системных и скрытых файлов

Защита метаданных систем контроля версий (`.git`, `.svn`), переменных окружения (`.env`) и файлов конфигурации (`.htaccess`, `.yml`) должна реализовываться с высоким приоритетом:

```nginx
# Блокировка скрытых файлов с пропуском ACME-челленджей Let's Encrypt
location ~ /\.(?!well-known) {
    deny all;
    access_log off;
    log_not_found off;
}
```

*Sysadmin/SRE примечание:* Директива `deny all;` возвращает код `403 Forbidden`. Для предотвращения сканирования периметра автоматизированными утилитами разведки рекомендуется подменять код на 404 директивой `return 404;`:

```nginx
location ~ /\.(?!well-known) {
    return 404;
    access_log off;
    log_not_found off;
}
```

#### Предотвращение Directory Traversal (Уязвимость Off-by-slash в alias)

Классическая уязвимость маршрутизации Nginx возникает при несовпадении замыкающих слэшей в префиксном `location` и директиве `alias`:

```nginx
# УЯЗВИМАЯ КОНФИГУРАЦИЯ (Off-by-slash):
location /static {
    alias /var/www/app/static/;
}
```

**Механизм атаки:**
При запросе `GET /static../app.py HTTP/1.1` Nginx сопоставляет префикс `/static`, удаляет его из URI, а оставшуюся часть `../app.py` конкатенирует с путем в `alias`. В результате формируется путь `/var/www/app/static/../app.py`, что приводит к отдаче исходного кода приложения `/var/www/app/app.py`.

```nginx
# БЕЗОПАСНАЯ КОНФИГУРАЦИЯ:
location /static/ {
    alias /var/www/app/static/;
}
```

*Правило:* Если путь в директиве `location` завершается слэшем, путь в директиве `alias` также обязан завершаться слэшем. Там, где структура каталогов на диске совпадает со структурой URI, безопаснее использовать директиву `root`, которая не подвержена уязвимости off-by-slash.

#### Ограничение методов через limit_except

Директива `limit_except` ограничивает HTTP-методы внутри `location`. Важная особенность: ограничения, указанные внутри блока `limit_except`, применяются только к тем методам, которые **не перечислены** в заголовке директивы:

```nginx
location /api/data/ {
    # GET и HEAD разрешены всем согласно внешним правилам
    limit_except GET HEAD {
        allow 192.168.1.0/24;  # Доверительная подсеть для записи/удаления
        allow 10.10.0.5;       # IP сервера администрирования
        deny all;              # POST, PUT, DELETE, PATCH запрещены для всех остальных
    }
    proxy_pass http://backend_api;
}
```

#### Влияние merge_slashes

По умолчанию активна директива `merge_slashes on;`, которая схлопывает множественные слэши в один (`//api///v1` → `/api/v1`) на этапе нормализации URI перед поиском `location`.

Отключение директивы (`merge_slashes off;`) несет серьезные риски безопасности: запросы вида `//admin` не будут соответствовать префиксу `/admin`, что может привести к обходу правил ограничения доступа и WAF-фильтров, если бэкенд за Nginx самостоятельно нормализует путь.

#### Защита от симлинков (disable_symlinks)

Для каталогов загрузки пользовательского контента (uploads, temp) необходимо предотвращать обращение к файловой системе через символические ссылки:

```nginx
location /uploads/ {
    # Запрет перехода по симлинкам, если владелец ссылки не совпадает с владельцем целевого файла
    disable_symlinks if_not_owner from=$document_root;
    root /var/www/data;
}
```

---

### Управление конфигурацией

#### Верификация и Zero-Downtime Reload

Применение изменений в Nginx на серверах высокой доступности строится на трех этапах:
1. **Проверка синтаксиса:** `nginx -t` выполняет синтаксический анализ и проверяет доступность файлов конфигурации.
2. **Анализ полной структуры:** `nginx -T` выводит объединенную конфигурацию со всеми включенными `include`.
3. **Graceful Reload:** Сигнал `HUP` (`nginx -s reload` или `kill -HUP <master_pid>`) инициирует процедуру zero-downtime перезагрузки.

**Жизненный цикл Zero-Downtime Reload:**
1. Master-процесс перечитывает конфигурационные файлы.
2. При обнаружении ошибок master прерывает операцию и оставляет старые worker-процессы работать без сбоев.
3. При успешном парсинге master запускает новые worker-процессы с новой конфигурацией.
4. Master отправляет старым worker-процессам сигнал `QUIT` (graceful shutdown).
5. Старые воркеры закрывают слушающие сокеты, дорабатывают текущие клиентские соединения и завершают работу без обрыва трафика.

#### Стратегия Rollback через атомарные симлинки

Резервное копирование одного файла `nginx.conf` недостаточно при распределенной структуре с десятками файлов в `conf.d/` и `sites-available/`. В production SRE рекомендуется версионировать весь каталог конфигурации через Git и использовать атомарные симлинки:

```bash
# Структура каталогов релизов:
# /etc/nginx-releases/
# ├── 20261016_1000/
# └── 20261016_1030/
# /etc/nginx -> /etc/nginx-releases/20261016_1030

# Атомарный откат на предыдущую версию:
ln -sfn /etc/nginx-releases/20261016_1000 /etc/nginx.target
mv -Tf /etc/nginx.target /etc/nginx
nginx -t && nginx -s reload
```

---

## Практические сценарии

### Сценарий 1: Разделение статики, API и бэкенда с защитой от shadowing

**Контекст:** Веб-приложение с динамическим бэкендом, высоконагруженной статикой и REST API. Необходимо исключить накладные расходы на regex и гарантировать сохранение заголовков безопасности.

**Предварительные требования:**
- Nginx версии 1.26+ с поддержкой директивы `http2 on;`.
- Upstream-сервис API, доступный на локальном порту 8080.
- Сокет PHP-FPM `/run/php/php-fpm.sock`.

**Конфигурация `/etc/nginx/sites-available/app.example.com.conf`:**

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name app.example.com;

    ssl_certificate /etc/ssl/certs/app.example.com.crt;
    ssl_certificate_key /etc/ssl/private/app.example.com.key;

    # Базовые заголовки безопасности на уровне server
    include snippets/security-headers.conf;

    # 1. Приоритетный префикс для статики — полностью пропускает проверку regex
    location ^~ /static/ {
        alias /var/www/app/static/;
        expires 30d;
        include snippets/security-headers.conf;
        add_header Cache-Control "public, no-transform, immutable" always;
        access_log off;
    }

    # 2. Приоритетный префикс для API — исключает regex
    location ^~ /api/ {
        proxy_pass http://127.0.0.1:8080;
        include snippets/proxy-params.conf;
    }

    # 3. Регулярное выражение для legacy скриптов
    location ~ \.php$ {
        root /var/www/app/public;
        try_files $uri =404;
        include fastcgi_params;
        fastcgi_pass unix:/run/php/php-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    # 4. Префикс по умолчанию для SPA фронтенда
    location / {
        root /var/www/app/public;
        try_files $uri $uri/ /index.html;
    }
}
```

**Проверка и валидация:**

```bash
# 1. Валидация синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Применение конфигурации
nginx -s reload
# → 

# 3. Проверка статики и заголовков кэширования
curl -sI https://app.example.com/static/style.css
# → HTTP/2 200
# → cache-control: public, no-transform, immutable
# → x-content-type-options: nosniff
# → x-frame-options: SAMEORIGIN

# 4. Проверка изоляции API
curl -sI https://app.example.com/api/v1/health
# → HTTP/2 200
# → content-type: application/json
```

---

### Сценарий 2: Canary-развертывание через location (по заголовку и split_clients)

**Контекст:** Проведение канареечного релиза для микросервиса. Необходимо направить 10% общего пользовательского трафика на новую версию `canary`, а также обеспечить возможность принудительного переключения через HTTP-заголовок `X-Canary-Test` для внутреннего тестирования.

**Предварительные требования:**
- Два независимых пула upstream-серверов: `backend_stable` (порт 8081) и `backend_canary` (порт 8082).
- Включение логики в контексте `http`.

**Конфигурация:**

```nginx
# В контексте http (/etc/nginx/conf.d/canary_map.conf)

# Стохастическое распределение 10% трафика по хэшу от IP и URI
split_clients "${remote_addr}${request_uri}" $canary_percentage_pool {
    10%     http://backend_canary;
    *       http://backend_stable;
}

# Принудительный оверрайд через заголовок для инженеров QA/SRE
map $http_x_canary_test $target_upstream {
    default     $canary_percentage_pool;
    "always"    http://backend_canary;
    "never"     http://backend_stable;
}

# В контексте server (/etc/nginx/sites-available/service.example.com.conf)
server {
    listen 80;
    server_name service.example.com;

    location / {
        proxy_pass $target_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Индикация выбранного бэкенда в служебном заголовке ответа
        add_header X-Backend-Pool $target_upstream always;
    }
}
```

**Проверка и валидация:**

```bash
# Тест принудительного попадания в Canary пул
curl -sI http://service.example.com/ -H "X-Canary-Test: always" | grep -i "X-Backend-Pool"
# → x-backend-pool: http://backend_canary

# Тест принудительного попадания в Stable пул
curl -sI http://service.example.com/ -H "X-Canary-Test: never" | grep -i "X-Backend-Pool"
# → x-backend-pool: http://backend_stable

# Статистическая проверка распределения (100 запросов)
for i in {1..100}; do
    curl -sI http://service.example.com/ -H "X-Real-IP: 192.168.1.$i" | grep -i "X-Backend-Pool"
done | sort | uniq -c
# →    90 x-backend-pool: http://backend_stable
# →    10 x-backend-pool: http://backend_canary
```

Дополнительные архитектурные паттерны Canary приведены в **[Канареечное развертывание (Canary Deployment)](../../../../CI-CD/Deployment_Strategies/canary_deployment.md)**, а детальный синтаксис директивы `split_clients` — в **[Переменные в Angie](../../../Angie/angie_variables.md)**.

---

### Сценарий 3: Защищенный Healthcheck-эндпоинт для мониторинга (SRE)

**Контекст:** Мониторинг жизнеспособности (liveness probe) узла Nginx системами Prometheus/Zabbix. Эндпоинт должен быть легковесным, не писать в access-лог и быть изолированным от внешнего мира.

**Конфигурация `/etc/nginx/conf.d/healthcheck.conf`:**

```nginx
server {
    listen 80 default_server;
    server_name _;

    # Изолированный healthcheck с точным модификатором =
    location = /healthz {
        # Запрет логирования регулярных проб мониторинга для экономии I/O
        access_log off;

        # Ограничение доступа: только localhost и подсеть мониторинга
        allow 127.0.0.1;
        allow 10.100.0.0/16;
        deny all;

        default_type text/plain;
        return 200 "OK\n";
    }

    # Локация статуса Nginx (требует ngx_http_stub_status_module)
    location = /nginx_status {
        stub_status;
        access_log off;
        allow 127.0.0.1;
        allow 10.100.0.0/16;
        deny all;
    }
}
```

**Проверка и валидация:**

```bash
# Запрос с разрешенного интерфейса localhost
curl -i http://127.0.0.1/healthz
# → HTTP/1.1 200 OK
# → Content-Type: text/plain
# → Content-Length: 3
# → 
# → OK

# Запрос метрик stub_status
curl -s http://127.0.0.1/nginx_status
# → Active connections: 2 
# → server accepts handled requests
# →  104 104 250 
# → Reading: 0 Writing: 1 Waiting: 1

# Попытка запроса с внешнего адреса (симуляция внешней сети)
curl -sI -H "Host: forbidden" http://192.168.1.100/healthz
# → HTTP/1.1 403 Forbidden
```

---

### Сценарий 4: Ограничение скорости (Rate limiting) с режимом Dry Run

**Контекст:** Защита формы авторизации `/auth/login` от перебора паролей. Перед жестким включением блокировок (код 429) необходимо проанализировать реальный поток трафика в режиме dry run, чтобы исключить ложные срабатывания (false positives).

**Предварительные требования:**
- Nginx версии 1.23.4+ для директивы `limit_req_dry_run`.
- Наличие переменной `$limit_req_status` в формате логов.

**Конфигурация:**

```nginx
# В контексте http
log_format rate_debug '$remote_addr [$time_local] "$request" '
                      'status=$status limit_status=$limit_req_status';

# Выделение зоны 10MB (около 160 000 уникальных IP) с лимитом 5 запросов в секунду
limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/s;

server {
    listen 80;
    server_name api.example.com;

    access_log /var/log/nginx/rate_audit.log rate_debug;

    location /auth/login {
        limit_req zone=login_limit burst=10 nodelay;
        
        # РЕЖИМ DRY RUN: проверка лимита без блокировки клиентов
        limit_req_dry_run on;

        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Проверка и валидация:**

```bash
# Генерация всплеска из 15 параллельных запросов
seq 1 15 | xargs -n 1 -P 15 curl -s -o /dev/null -w "%{http_code}\n" http://api.example.com/auth/login
# → 200
# → 200
# ... (все запросы возвращают 200, ни один клиент не заблокирован)

# Анализ статусов в аудит-логе
tail -n 15 /var/log/nginx/rate_audit.log | grep "limit_status"
# → 127.0.0.1 [16/Oct/2026:10:15:00 +0300] "GET /auth/login HTTP/1.1" status=200 limit_status=PASSED
# → 127.0.0.1 [16/Oct/2026:10:15:00 +0300] "GET /auth/login HTTP/1.1" status=200 limit_status=DELAYED_DRY_RUN
# → 127.0.0.1 [16/Oct/2026:10:15:00 +0300] "GET /auth/login HTTP/1.1" status=200 limit_status=REJECTED_DRY_RUN
```

После подтверждения адекватности лимитов директива `limit_req_dry_run on;` отключается или удаляется, и клиенты сверх `burst` начинают получать стандартный HTTP-статус `429 Too Many Requests`.

---

### Сценарий 5: Безопасная отладка сопоставления в production (debug_connection)

**Контекст:** В production-среде запросы к определенному URL попадают не в тот блок `location`. Включение глобального `error_log ... debug;` недопустимо из-за генерации сотен мегабайт логов в секунду и падения производительности. Необходимо изолировать отладку исключительно на IP-адрес инженера SRE.

**Конфигурация `/etc/nginx/nginx.conf`:**

```nginx
events {
    worker_connections 1024;
    # Включение debug-лога ТОЛЬКО для рабочего IP инженера SRE
    debug_connection 192.168.1.55;
}

http {
    # Основной лог уровня notice или warn
    error_log /var/log/nginx/error.log notice;

    server {
        listen 80;
        server_name example.com;

        # Добавление диагностического заголовка трассировки
        location ^~ /catalog/items/ {
            add_header X-Matched-Location "Prefix-Catalog-Items" always;
            root /var/www/html;
        }

        location ~ \.(json|xml)$ {
            add_header X-Matched-Location "Regex-Data-Files" always;
            root /var/www/html;
        }

        location / {
            add_header X-Matched-Location "Default-Root" always;
            root /var/www/html;
        }
    }
}
```

**Проверка и валидация:**

```bash
# 1. Применение настройки
nginx -s reload
# → 

# 2. Выполнение запроса с отладочного IP (192.168.1.55)
curl -sI http://example.com/catalog/items/list.json | grep -i "X-Matched-Location"
# → x-matched-location: Prefix-Catalog-Items

# 3. Чтение журнала сопоставления location в error.log
grep -E "test location|using configuration" /var/log/nginx/error.log | tail -n 5
# → 2026/10/16 10:20:12 [debug] 31204#31204: *42 test location: "/"
# → 2026/10/16 10:20:12 [debug] 31204#31204: *42 test location: "catalog/items/"
# → 2026/10/16 10:20:12 [debug] 31204#31204: *42 using configuration "^~ /catalog/items/"
```

Инженер получает исчерпывающую пошаговую картину работы роутера Nginx для своего сеанса, тогда как для всех остальных клиентов Nginx продолжает работать на полной скорости с минимальным логированием.

---

### Сценарий 6: Graceful config rollout и откат через атомарный symlink

**Контекст:** Автоматизированный деплой новой версии конфигурации виртуального хоста через CI/CD-пайплайн с возможностью мгновенного автоматического отката без прерывания соединений.

**Пошаговое выполнение:**

```bash
# Шаг 1: Подготовка каталогов релизов
mkdir -p /etc/nginx/releases/rev_1
mkdir -p /etc/nginx/releases/rev_2

# Шаг 2: Создание новой версии конфигурации в rev_2
cat << 'EOF' > /etc/nginx/releases/rev_2/vhost.conf
server {
    listen 80;
    server_name deploy.example.com;

    location ^~ /v2/ {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
    }

    location / {
        root /var/www/html;
        try_files $uri $uri/ =404;
    }
}
EOF

# Шаг 3: Атомарное переключение символической ссылки на новую ревизию
ln -sfn /etc/nginx/releases/rev_2/vhost.conf /etc/nginx/conf.d/vhost.conf.next
mv -Tf /etc/nginx/conf.d/vhost.conf.next /etc/nginx/conf.d/vhost.conf

# Шаг 4: Валидация синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Шаг 5: Применение конфигурации (graceful reload)
nginx -s reload
# → 

# Шаг 6: Тестовый запрос
curl -s -o /dev/null -w "%{http_code}\n" http://deploy.example.com/
# → 200

# Шаг 7: Автоматический откат при обнаружении сбоя (rollback)
ln -sfn /etc/nginx/releases/rev_1/vhost.conf /etc/nginx/conf.d/vhost.conf.next
mv -Tf /etc/nginx/conf.d/vhost.conf.next /etc/nginx/conf.d/vhost.conf
nginx -s reload
# → 
```

---

## Операции и команды

### Валидация и применение конфигурации

```bash
# 1. Проверка синтаксиса без перезагрузки
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Вывод полной объединенной конфигурации с номерами строк (поиск директив location)
nginx -T | grep -n "location"
# → 45:    location = /healthz {
# → 62:    location ^~ /static/ {
# → 78:    location ~ \.php$ {
# → 94:    location / {

# 3. Мягкая перезагрузка конфигурации (Zero-Downtime Reload)
nginx -s reload
# → 

# 4. Альтернативная перезагрузка через systemd
systemctl reload nginx
# → 

# 5. Проверка состояния master и worker процессов после reload
ps aux | grep "[n]ginx"
# → root       12401  0.0  0.1  45120  8920 ?        Ss   10:00   0:00 nginx: master process /usr/sbin/nginx -g daemon on; master_process on;
# → www-data   12530  0.2  0.3  48240 14210 ?        S    10:25   0:01 nginx: worker process
# → www-data   12531  0.2  0.3  48240 14190 ?        S    10:25   0:01 nginx: worker process
```

### Отладка и трассировка сопоставления

```bash
# 1. Запрос заголовков ответа с проверкой кастомного трейсинг-маркера
curl -sI https://example.com/static/bundle.js | grep -E "HTTP|X-Matched-Location|Cache-Control"
# → HTTP/2 200 
# → cache-control: public, no-transform, immutable
# → x-matched-location: Prefix-Static

# 2. Инспекция нормализации URI через эндпоинт отладки (при временной настройке)
curl -s "http://localhost/debug_uri/some//path/../test?param=1"
# → URI: /debug_uri/some/test | ARGS: param=1

# 3. Фильтрация отладочного журнала для анализа выбора location
tail -f /var/log/nginx/error.log | grep -E "using configuration|test location"
# → 2026/10/16 10:28:40 [debug] 12530#12530: *12 test location: "/"
# → 2026/10/16 10:28:40 [debug] 12530#12530: *12 test location: "api/"
# → 2026/10/16 10:28:40 [debug] 12530#12530: *12 using configuration "^~ /api/"
```

### Системное администрирование и безопасность (Linux / Sysadmin)

```bash
# 1. Установка корректного владельца веб-директории
chown -R www-data:www-data /var/www/html
# → 

# 2. Разделение прав доступа: каталоги 755, файлы 644
find /var/www/html -type d -exec chmod 755 {} +
find /var/www/html -type f -exec chmod 644 {} +

# 3. Изоляция каталогов загрузки пользователей от исполнения скриптов
chmod 733 /var/www/html/uploads
# → 

# 4. Проверка контекстов безопасности SELinux
ls -dZ /var/www/html
# → system_u:object_r:httpd_sys_content_t:s0 /var/www/html

# 5. Восстановление стандартного контекста SELinux для веб-контента
restorecon -Rv /var/www/html
# → Relabeled /var/www/html from unconfined_u:object_r:default_t:s0 to system_u:object_r:httpd_sys_content_t:s0

# 6. Назначение контекста для каталогов с правом записи (uploads, кэш)
chcon -R -t httpd_sys_rw_content_t /var/www/html/uploads
# → 

# 7. Проверка статуса профиля AppArmor
aa-status | grep nginx
# → 2 profiles are in enforce mode.
# →    nginx
# → 0 processes are in complain mode.
```

### Ротация и аудит журналов

```bash
# 1. Проверка конфигурации утилиты logrotate для Nginx
cat /etc/logrotate.d/nginx
# → /var/log/nginx/*.log {
# →     daily
# →     missingok
# →     rotate 14
# →     compress
# →     delaycompress
# →     notifempty
# →     create 0640 www-data adm
# →     sharedscripts
# →     prerotate
# →         if [ -d /etc/logrotate.d/httpd-prerotate ]; then \
# →             run-parts /etc/logrotate.d/httpd-prerotate; \
# →         fi \
# →     endscript
# →     postrotate
# →         invoke-rc.d nginx rotate >/dev/null 2>&1
# →     endscript
# → }

# 2. Тестовый прогон ротации без реального изменения файлов (dry run)
logrotate -d /etc/logrotate.d/nginx
# → reading config file /etc/logrotate.d/nginx
# → handling log /var/log/nginx/*.log
# → ... log does not need rotating (dry-run completed)

# 3. Принудительная немедленная ротация логов
logrotate -f /etc/logrotate.d/nginx
# → 

# 4. Контроль дискового пространства журналов
du -sh /var/log/nginx/*
# → 14M    /var/log/nginx/access.log
# → 1.2M   /var/log/nginx/error.log
# → 120M   /var/log/nginx/access.log.1.gz
```

---

## Диагностика и устранение неполадок

### Таблица типичных неисправностей

| Симптом | Первопричина | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| Запрос попадает в неожиданный regex `location` вместо префиксного | Префиксный `location` объявлен без модификатора `^~`, из-за чего проверка продолжилась до regex | `error_log ... debug;` (строки `test location` и `using configuration`) | Добавить модификатор `^~` перед префиксом (например, `location ^~ /static/`) |
| Пропадают заголовки безопасности (`HSTS`, `X-Frame-Options`) на определенных путях | В блоке `location` объявлен локальный `add_header`, который перетер заголовки уровня `server` | `curl -sI https://host/path` — отсутствие ожидаемых заголовков | Вынести базовые заголовки в `snippets/security-headers.conf` и подключить через `include` внутри проблемного `location` |
| Ошибка `404 Not Found` при использовании директивы `alias` | Несовпадение замыкающих слэшей (off-by-slash) | Проверить значение переменной `$request_filename` через `return 200 "$request_filename\n";` | Синхронизировать слэши: если префикс `location /static/`, то путь `alias /dir/static/;` |
| Ошибка `500 Internal Server Error` (циклическая маршрутизация) | `try_files` перенаправляет на URI, который снова попадает в тот же `location`, превышая лимит 10 циклов | Журнал `error.log`: сообщение `rewrite or internal redirection cycle while internally redirecting to ...` | Перенаправлять fallback в именованный блок: `try_files $uri $uri/ @backend;` |
| Ошибка `403 Forbidden` на существующие статические файлы | Ограничения `disable_symlinks`, отсутствие прав `o+r` на файл или блокирующий контекст SELinux | `grep "denied" /var/log/nginx/error.log` и проверка SELinux `ausearch -m avc -ts recent` | Назначить права `chmod 644`, проверить владельцев или выполнить `restorecon -Rv` |
| При проксировании через fallback теряются параметры строки запроса (`query string`) | В директиве `proxy_pass` внутри fallback-локации указан URI без передачи аргументов | `tcpdump -nn -s 0 -A 'tcp port 8080'` или инспекция логов бэкенда | Использовать переменную `$request_uri` или `$is_args$args`: `proxy_pass http://backend$request_uri;` |
| Ошибка `429 Too Many Requests` у легитимных пользователей | Слишком низкий лимит `rate` или недостаточный буфер `burst` в директиве `limit_req` | Анализ поля `$limit_req_status` в журнале `access.log` | Увеличить `burst`, добавить параметр `nodelay` или перевести в `limit_req_dry_run on;` для калибровки |

---

### Детальные сценарии устранения проблем

#### 1. Устранение циклов внутренних перенаправлений (Redirection Cycle)

**Диагностика:** В `error.log` фиксируется критическая ошибка:
```
2026/10/16 10:35:14 [error] 14210#14210: *88 rewrite or internal redirection cycle while internally redirecting to "/index.html", client: 192.168.1.100, server: example.com, request: "GET /dashboard HTTP/1.1"
```

**Причина:** Директива `try_files $uri $uri/ /index.html;` внутри `location /` при отсутствии на диске `/dashboard` выполняет внутренний редирект на `/index.html`. Если сам файл `/index.html` отсутствует или перенаправляется другим правилом `rewrite`, запрос повторно проходит цикл сопоставления. После 10 итераций (`NGX_HTTP_MAX_URI_CHANGES = 10`) Nginx прерывает обработку ошибкой 500.

**Решение:** Разделение логики проверки файлов и обработки fallback через именованный `location`:

```nginx
location / {
    root /var/www/html;
    # Если файл или каталог не найдены — передаем управление в именованную локацию
    try_files $uri $uri/ @fallback;
}

location @fallback {
    root /var/www/html;
    # Точечная отдача index.html без повторного входа в общий цикл try_files
    rewrite ^ /index.html break;
}
```

#### 2. Сохранение Query String при проксировании из fallback

**Диагностика:** Клиент отправляет запрос `GET /items?category=books&sort=asc`, который перенаправляется на бэкенд, но бэкенд получает запрос `GET /items` без параметров.

**Причина:** При использовании именованного `location` директива `proxy_pass` с указанием URI заменяет исходный URI.

```nginx
# ОШИБОЧНО:
location @backend {
    proxy_pass http://api_server/api; # Замена URI отсекает $args!
}

# КОРРЕКТНО:
location @backend {
    # Явная передача query string через $is_args$args
    proxy_pass http://api_server/api$is_args$args;
}

# АЛЬТЕРНАТИВНО (без модификации URI):
location @backend {
    # Отсутствие URI в proxy_pass передает исходный $request_uri без изменений
    proxy_pass http://api_server;
}
```

---

## Лучшие практики

### Производительность

1. **Используйте `^~` для всех статических префиксов.** Это исключает фазу поиска по регулярным выражениям для статики и статических путей API, сокращая время обработки запроса.
2. **Включайте `pcre_jit on;` в глобальном контексте.** Компиляция регулярных выражений в машинный код разгружает процессор при сопоставлении сложных URL.
3. **Применяйте точный модификатор `=` для одиночных частых URI.** Для путей вроде `/healthz` или `/favicon.ico` поиск по хэш-таблице выполняется за $O(1)$.
4. **Отключайте access_log для часто запрашиваемых статических и служебных ресурсов.** Логирование иконок, стилей и регулярных проб healthcheck создает избыточную нагрузку на дисковую подсистему I/O.
5. **Используйте именованные `location` (`@name`) для fallback-сценариев.** Это защищает сервер от циклических редиректов и повторного прогона запроса по всему префиксному дереву.

### Безопасность

1. **Скрывайте служебные и скрытые файлы через `return 404;`.** Ответ 404 вместо 403 предотвращает идентификацию существующих файлов автоматическими сканерами уязвимостей.
2. **Всегда синхронизируйте замыкающие слэши в `location` и `alias`.** Несоответствие слэшей приводит к уязвимости Directory Traversal (off-by-slash).
3. **Контролируйте наследование `add_header`.** При добавлении кастомного заголовка в `location` обязательно переподключайте сниппет с базовыми заголовками безопасности (`HSTS`, `X-Frame-Options`, `CSP`).
4. **Не отключайте `merge_slashes`.** Значение по умолчанию `merge_slashes on;` нормализует пути и предотвращает обход правил безопасности с помощью дублирования слэшей.
5. **Ограничивайте доступ к системным ресурсам через `disable_symlinks`.** Для каталогов с загрузкой файлов пользователями используйте `disable_symlinks if_not_owner from=$document_root;`.
6. **Ограничивайте методы через `limit_except`.** Разрешайте только необходимые методы (GET, POST), блокируя небезопасные или неиспользуемые глаголы HTTP.

### Эксплуатация (DevOps / SRE)

1. **Придерживайтесь плоской структуры `location`.** Избегайте вложенных блоков; организуйте конфигурацию в виде независимых префиксов с централизацией общих параметров через `snippets/`.
2. **Используйте Zero-Downtime Reload (`nginx -s reload`).** Никогда не перезапускайте Nginx через `restart` в production без крайней необходимости (например, обновление бинарника без поддержки USR2).
3. **Автоматизируйте валидацию конфигурации.** Включайте шаг `nginx -t` во все CI/CD-пайплайны перед применением изменений на серверах.
4. **Обеспечивайте быстрый Rollback.** Храните версии конфигурации в версионированных каталогах и переключайте релизы через атомарную смену символических ссылок.
5. **Используйте режим `limit_req_dry_run on;` перед включением Rate Limiting.** Анализируйте лог `$limit_req_status` на реальном трафике для предотвращения ложных срабатываний.
6. **Выделяйте мониторинг в изолированный блок `/healthz`.** Ограничивайте healthcheck локальной сетью, отключайте логирование и возвращайте статичный ответ `200 "OK\n"`.

### Наблюдаемость (Observability)

1. **Используйте заголовки трассировки `X-Matched-Location`.** Добавление кастомного заголовка на этапе тестирования или в staging-среде позволяет однозначно определить, какой конфигурационный блок обработал запрос.
2. **Применяйте `debug_connection` для точечной отладки.** Включайте детальный лог `debug` только для IP-адреса инженера SRE в блоке `events`, исключая деградацию производительности для реальных пользователей.
3. **Разделяйте журналы по типам трафика.** Пишите запросы к API, статике и страницам авторизации в раздельные файлы журналов с кастомными форматами `log_format`.

---

## Дополнительная информация

### Связанные темы

- **[Директива location: основы и приоритеты](./basics.md)** — алгоритмы сопоставления префиксов, модификаторы и фазы обработки HTTP-запросов.
- **[Внутренняя маршрутизация](./internal_routing.md)** — детальный разбор директивы `internal`, заголовка `X-Accel-Redirect` и именованных локаций.
- **[Отдача статических файлов](./serving_files.md)** — архитектура `root` и `alias`, кэширование, буферизация и оптимизация передачи данных.
- **[Примеры интеграции](./integration_examples.md)** — интеграция блоков `location` с бэкендами FastCGI, uWSGI, gRPC и HTTP reverse proxy.
- **[Предикатные локейшены](./predicate_locations.md)** — продвинутая маршрутизация API на основе переменных, заголовков и модуля NJS.
- **[Перенаправления и перезапись URI в Nginx](../nginx_rewrite_rules_and_try_files.md)** — манипуляция путями запросов через `rewrite`, `return` и каскадную проверку `try_files`.
- **[Диагностика и устранение неисправностей Nginx](../../Operations/nginx_troubleshooting.md)** — методы анализа дампов процессов, системных ресурсов и общих сбоев сервера.
- **[Руководство по безопасности Nginx](../../Security/nginx_security_guide.md)** — комплексное руководство по харденингу веб-сервера, защите от атак и настройке TLS.
- **[Канареечное развертывание (Canary Deployment)](../../../../CI-CD/Deployment_Strategies/canary_deployment.md)** — теория, паттерны и методы постепенного развертывания версий в продакшене.
- **[Переменные в Angie](../../../Angie/angie_variables.md)** — расширенные возможности работы с директивами `map`, `split_clients` и переменными окружения.
