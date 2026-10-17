# njs — скриптовый модуль Nginx (Nginx JavaScript)

**Актуально для:** Nginx 1.26.x / 1.28.x (модуль njs 0.8.x – 1.0.x)

## Определения

**njs (Nginx JavaScript)** — специализированная легковесная реализация среды исполнения JavaScript (подмножество стандартов ECMAScript), интегрированная непосредственно в архитектуру рабочих процессов Nginx. Предоставляет возможность динамической обработки запросов на уровне веб-сервера без накладных расходов внешних рантаймов (Node.js, Deno) и без компиляции сторонних C-модулей.

**ngx_http_js_module** — динамический модуль Nginx (`ngx_http_js_module.so`), расширяющий контекст `http` директивами внедрения JavaScript-логики на различных фазах обработки HTTP-запроса (`js_import`, `js_set`, `js_var`, `js_access`, `js_content`, `js_header_filter`, `js_body_filter`, `js_shared_dict_zone`, `js_periodic`).

**ngx_stream_js_module** — динамический модуль Nginx (`ngx_stream_js_module.so`) для транспортного уровня (L4 TCP/UDP Stream), позволяющий анализировать, маршрутизировать и модифицировать сырые сетевые потоки директивами `js_preread`, `js_filter`, `js_access`.

**js_set** — директива вычисления динамической переменной ядра Nginx с отложенным расчетом (lazy evaluation) при первом обращении к переменной в рамках текущего запроса. Результат вычисления кешируется на все время жизни запроса.

**js_var** — директива предварительного объявления пользовательской переменной njs, значение которой может явно перезаписываться внутри JavaScript-кода (`r.variables.var_name = ...`) в ходе обработки запроса.

**js_access** — фазовый обработчик доступа (Access Phase), исполняемый перед передачей запроса обработчику контента или проксированием. Позволяет разрешить обработку (`r.pass()`), прервать запрос с кодом ошибки (`r.return(401)`, `r.return(403)`) или выполнить внутреннее перенаправление.

**js_content** — терминальный обработчик контента в блоке `location`, полностью передающий управление JavaScript-функции для формирования HTTP-ответа (статус, заголовки, тело).

**js_header_filter** — фильтр исходящих HTTP-заголовков ответа, вызываемый после получения данных от бэкенда или локального генератора контента, позволяющий мутировать, добавлять или удалять заголовки на лету.

**js_body_filter** — потоковый фильтр тела HTTP-ответа, получающий чанки данных от бэкенда и способный трансформировать полезную нагрузку до отправки клиенту.

**js_shared_dict_zone** — разделяемая зона оперативной памяти (Shared Memory Zone), доступная всем рабочим процессам Nginx (worker processes) для потокобезопасного хранения пар ключ-значение со встроенным механизмом вытеснения по алгоритму LRU (Least Recently Used).

**js_periodic** — директива запуска периодических фоновых задач внутри воркера Nginx с заданным временным интервалом без привлечения внешних планировщиков (cron, systemd timers).

**js_engine** — директива выбора движка исполнения JavaScript: встроенный оптимизированный интерпретатор `njs` либо движок `qjs` (QuickJS, доступен с версии njs 0.9.1) для расширенной поддержки спецификаций ES2023.

**Объект `r` (HTTP Request)** — контекстный объект HTTP-запроса в njs, предоставляющий доступ к метаданным запроса (`r.uri`, `r.method`, `r.args`, `r.headersIn`, `r.headersOut`, `r.variables`), методам формирования ответа (`r.return()`, `r.sendHeader()`, `r.send()`, `r.finish()`), внутренним подзапросам (`r.subrequest()`) и системному журналу (`r.log()`, `r.warn()`, `r.error()`).

**Объект `s` (Stream Session)** — контекстный объект сессии в модуле `stream` (`s.remoteAddress`, `s.variables`, `s.on()`, `s.send()`, `s.done()`, `s.deny()`, `s.allow()`).

**Глобальный объект `ngx`** — глобальное пространство имен njs, предоставляющее функции асинхронного сетевого взаимодействия (`ngx.fetch()`), доступ к разделяемой памяти (`ngx.shared`), встроенной криптографии (`crypto.subtle`) и системным буферам (`Buffer`).

---

## Архитектура и базовые концепции

### Модель виртуальной машины: VM-on-demand и управление памятью

В отличие от стандартных сред JavaScript (Node.js/V8) и Lua (OpenResty/LuaJIT), модуль njs спроектирован с учетом неблокирующей событийно-ориентированной архитектуры веб-сервера Nginx:

1. **Компиляция в байткод на этапе старта:** При запуске или перезагрузке конфигурации (`nginx -s reload`) мастер-процесс Nginx парсит все импортированные JS-модули (`js_import`) и компилирует исходный код в промежуточный байткод. Байткод размещается в памяти, доступной рабочим процессам. Синтаксические ошибки и ошибки разрешения зависимостей выявляются на этапе валидации конфигурации (`nginx -t`).
2. **Изоляция запросов (VM-on-demand):** Для каждого входящего HTTP-соединения или запроса создается независимый легковесный экземпляр виртуальной машины njs. Объекты и переменные скрипта размещаются в пуле памяти конкретного запроса (`ngx_pool_t`).
3. **Отсутствие пауз сборщика мусора (Zero GC Pauses):** В njs отсутствует фоновый сборщик мусора (Tracing/Generational Garbage Collector). После завершения обработки HTTP-запроса весь пул памяти `ngx_pool_t` освобождается ядром Nginx за одну системную операцию. Это предотвращает возникновение неконтролируемых задержек (latency spikes) и деградацию хвостовых перцентилей времени отклика (p99/p99.9).
4. **Безопасность и детерминированность:** В njs жестко заблокированы динамическая компиляция кода (`eval()`, конструктор `new Function()`) и изменение прототипов стандартных типов. Весь исполняемый код детерминирован на этапе запуска Nginx.

### Сравнение njs, LuaJIT (OpenResty) и Node.js

| Критерий | njs (Nginx) | OpenResty (LuaJIT) | Node.js (V8) |
| :--- | :--- | :--- | :--- |
| **Способ интеграции** | Динамический модуль Nginx | Форк Nginx с встроенным LuaJIT | Внешний сервис / upstream |
| **Язык** | ECMAScript (JS) | Lua 5.1 / LuaJIT | JavaScript (полный ES-стандарт) |
| **Сборка мусора (GC)** | Отсутствует (очистка пула запроса) | Инкрементальный GC LuaJIT | Поколенческий GC V8 (Stop-the-world) |
| **Модель памяти** | Изолированная VM на каждый запрос | Единый контекст Lua на воркер | Общая куча (Heap) процесса |
| **Потребление RAM** | Единицы килобайт на запрос | Сотни килобайт на инстанс | От 30–100+ МБ на процесс |
| **Инициализация VM** | Мгновенно (< 1 мкс) | Миллисекунды | Секунды |
| **JIT-компиляция** | Нет (байткод-интерпретатор) | Да (трассирующий JIT LuaJIT) | Да (TurboFan / Crankshaft) |
| **Ввод-вывод (I/O)** | `r.subrequest()`, `ngx.fetch()` | Cosocket API | libuv (асинхронный event loop) |
| **Целевая область** | Маршрутизация, auth, инспекция, WAF | Сложные шлюзы, тяжелые интеграции | Микросервисы, бизнес-логика |

### Фазы конвейера обработки HTTP-запроса в Nginx

Директивы модуля `ngx_http_js_module` интегрируются в стандартную фазовую модель обработки соединений Nginx:

```
+-------------------------------------------------------------------------+
|                  Фаза Init (Парсинг конфига / reload)                   |
|  - Компиляция JS-файлов из директив js_import в байткод                 |
|  - Инициализация зон разделяемой памяти (js_shared_dict_zone)           |
|  - Выбор движка исполнения через js_engine (njs / qjs)                  |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                       Фаза Pre-Read / Rewrite                           |
|  - js_set: инициализация и отложенный расчет переменных                 |
|  - js_var: объявление изменяемых переменных запроса                     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                       Фаза Access (Проверка доступа)                    |
|  - js_access: валидация токенов, HMAC, белых/черных списков             |
|  - Решение: пропуск (r.pass()), отказ (r.return(401/403))               |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Фаза Content (Генерация ответа)                    |
|  - js_content: формирование ответа в JS (healthcheck, mock, auth proxy) |
|  - ИЛИ передача в proxy_pass / fastcgi_pass / статичный файл            |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Фаза Header Filter (Заголовки)                     |
|  - js_header_filter: инспекция, удаление или добавление заголовков      |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Фаза Body Filter (Тело ответа)                     |
|  - js_body_filter: потоковая фильтрация, маскирование данных            |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Фаза Log (Журналирование)                          |
|  - Использование вычисленных js_set переменных в директиве log_format   |
+-------------------------------------------------------------------------+
```

### Асинхронная неблокирующая модель ввода-вывода

Код виртуальной машины njs выполняется синхронно в рамках однопоточного цикла обработки событий рабочего процесса Nginx (`epoll` в Linux). Вызов тяжелых синхронных операций (например, блокирующий цикл обработки миллионов итераций или синхронный разбор гигантского JSON) замораживает воркер и блокирует обслуживание всех параллельных соединений.

Для работы с внешними сервисами njs предоставляет неблокирующие механизмы:

1. **`ngx.fetch(url, [options])`** — реализация стандарта Fetch API на базе неблокирующих сокетов Nginx. Возвращает `Promise`. Воркер инициирует TCP/TLS-соединение, регистрирует сокет в системном селекторе `epoll` и продолжает обработку других клиентских запросов. При получении пакета от удаленного узла воркер возобновляет выполнение функции.
2. **`r.subrequest(uri, [options], callback)`** — создание внутреннего подзапроса к другому `location` того же веб-сервера (например, к upstream-группе балансировки). Выполняется полностью асинхронно без порождения дополнительных сетевых сокетов на уровне ОС.

### Межворкерная разделяемая память (`js_shared_dict_zone`)

Директива `js_shared_dict_zone` выделяет именованный сегмент разделяемой памяти (Shared Memory), доступный всем процессам-воркерам Nginx:

- Хранилище пар «ключ-значение» управляется потокобезопасно через внутренние спинлоки ядра Nginx.
- Доступ из кода осуществляется через глобальный объект `ngx.shared.<имя_зоны>`.
- Поддерживаются методы `.get(key)`, `.set(key, value, [timeout])`, `.add(key, value, [timeout])`, `.replace(key, value, [timeout])`, `.delete(key)`, `.incr(key, delta, [init])`, `.clear()`.
- Ключи — строки, значения — строки или числа.
- При исчерпании памяти зона автоматически вытесняет наименее востребованные записи (алгоритм LRU), если указан параметр `evict`.

---

## Практические сценарии и настройка

### Предварительные требования и установка модуля

Для работы njs требуются установленный веб-сервер Nginx (версии 1.26.x или 1.28.x) и пакет динамических библиотек `nginx-module-njs`.

#### Установка в Debian / Ubuntu

При использовании официального репозитория `nginx.org`:

```bash
sudo apt update
sudo apt install -y nginx-module-njs
# → Setting up nginx-module-njs ...
```

*Примечание:* В стандартных репозиториях дистрибутивов Debian/Ubuntu пакет может называться `libnginx-mod-http-js` и `libnginx-mod-stream-js`.

#### Установка в RHEL / AlmaLinux / Rocky Linux

```bash
sudo dnf install -y nginx-module-njs
# → Installed: nginx-module-njs ...
```

#### Проверка установленных библиотек

```bash
ls -l /usr/lib/nginx/modules/ngx_*js_module.so
# → -rwxr-xr-x 1 root root ngx_http_js_module.so
# → -rwxr-xr-x 1 root root ngx_stream_js_module.so
```

#### Подключение модулей в `nginx.conf`

Директивы `load_module` должны располагаться **в самом начале главного конфигурационного файла** вне блоков `http`, `events` или `stream`:

```nginx
# /etc/nginx/nginx.conf
load_module modules/ngx_http_js_module.so;
load_module modules/ngx_stream_js_module.so;

user nginx;
worker_processes auto;
pid /var/run/nginx.pid;

events {
    worker_connections 2048;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # Каталог хранения JS-библиотек
    js_path /etc/nginx/njs/;
    
    include /etc/nginx/conf.d/*.conf;
}
```

Проверка конфигурации и загрузки модуля:

```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

---

### Сценарий 1: Генерация Request-ID и обогащение заголовков трассировки через `js_set`

В распределенных инфраструктурах каждый запрос должен иметь сквозной идентификатор корреляции (`X-Request-Id`). Если клиент не передал заголовок, njs формирует уникальный идентификатор с меткой времени воркера.

Файл логики `/etc/nginx/njs/tracing.js`:

```javascript
function get_or_create_request_id(r) {
    let req_id = r.headersIn['X-Request-Id'];
    if (req_id && req_id.length > 0) {
        return req_id;
    }
    
    // Формирование уникального идентификатора: время + случайный hex
    const ts = Date.now().toString(16);
    const rand = Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, '0');
    return `${ts}-${rand}`;
}

export default { get_or_create_request_id };
```

Конфигурация `/etc/nginx/conf.d/tracing.conf`:

```nginx
js_import tracing from /etc/nginx/njs/tracing.js;

# Ленивое вычисление переменной: вычисляется один раз за запрос и кешируется
js_set $correlation_id tracing.get_or_create_request_id;

log_format traced '$remote_addr - [$time_local] "$request" '
                  'status=$status bytes=$body_bytes_sent '
                  'req_id="$correlation_id" rt=$request_time';

server {
    listen 80;
    server_name api.local;
    access_log /var/log/nginx/api_access.log traced;

    location / {
        proxy_pass http://backend_nodes;
        proxy_set_header X-Request-Id $correlation_id;
        add_header X-Request-Id $correlation_id always;
    }
}

upstream backend_nodes {
    server 127.0.0.1:8080;
}
```

Тестирование генерации и проброса заголовка:

```bash
curl -I http://127.0.0.1/
# → HTTP/1.1 200 OK
# → X-Request-Id: 19280b2a1c4-004a2f8c
# → ...
```

---

### Сценарий 2: Контроль доступа и валидация токена через `js_access`

Вместо проксирования неавторизованных запросов на бэкенд Nginx проверяет валидность токена на фазе доступа. Директива `js_access` выполняется до вызова upstream.

Файл логики `/etc/nginx/njs/auth.js`:

```javascript
function authorize(r) {
    const authHeader = r.headersIn['Authorization'];
    
    if (!authHeader) {
        r.error('Auth failure: missing Authorization header');
        r.return(401, JSON.stringify({ error: 'unauthorized', code: 401 }));
        return;
    }

    const parts = authHeader.split(' ');
    if (parts.length !== 2 || parts[0] !== 'Bearer') {
        r.return(400, JSON.stringify({ error: 'invalid_token_format' }));
        return;
    }

    const token = parts[1];
    
    // Проверка префикса или контрольного значения без похода во внешнюю сеть
    if (token.startsWith('prod-sec-') && token.length === 32) {
        // Доступ разрешен: передаем управление конвейеру Nginx дальше
        r.pass();
    } else {
        r.warn(`Access denied for client: ${r.remoteAddress}`);
        r.return(403, JSON.stringify({ error: 'forbidden', code: 403 }));
    }
}

export default { authorize };
```

Конфигурация `/etc/nginx/conf.d/auth.conf`:

```nginx
js_import auth from /etc/nginx/njs/auth.js;

server {
    listen 80;
    server_name secure.local;

    location /api/v1/ {
        default_type application/json;
        
        # Фаза доступа: перехватывает запрос до передачи в proxy_pass
        js_access auth.authorize;

        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

Валидация запроса без токена:

```bash
curl -i http://127.0.0.1/api/v1/data
# → HTTP/1.1 401 Unauthorized
# → Content-Type: application/json
# → {"error":"unauthorized","code":401}
```

Валидация запроса с корректным токеном:

```bash
curl -i -H "Authorization: Bearer prod-sec-0123456789abcdef012345" http://127.0.0.1/api/v1/data
# → HTTP/1.1 200 OK
# → ...
```

---

### Сценарий 3: Кастомный JSON Healthcheck и статус сервера через `js_content`

Для мониторинга жизнеспособности узла (healthcheck) балансировщиком нагрузки формируется легковесный эндпоинт со статусом воркера, временем работы и заголовками.

Файл логики `/etc/nginx/njs/health.js`:

```javascript
function check(r) {
    const payload = {
        status: 'UP',
        server: 'nginx',
        timestamp: Date.now(),
        http_version: r.httpVersion,
        client_ip: r.remoteAddress,
        request_uri: r.uri
    };

    r.headersOut['Content-Type'] = 'application/json; charset=utf-8';
    r.headersOut['Cache-Control'] = 'no-cache, no-store, must-revalidate';
    r.return(200, JSON.stringify(payload));
}

export default { check };
```

Конфигурация `/etc/nginx/conf.d/health.conf`:

```nginx
js_import health from /etc/nginx/njs/health.js;

server {
    listen 80;
    server_name localhost;

    location = /healthz {
        # Терминальный обработчик контента
        js_content health.check;
    }
}
```

Проверка работоспособности:

```bash
curl -s http://127.0.0.1/healthz
# → {"status":"UP","server":"nginx","timestamp":1730000000000,"http_version":"1.1","client_ip":"127.0.0.1","request_uri":"/healthz"}
```

---

### Сценарий 4: Асинхронное взаимодействие через `ngx.fetch` и `r.subrequest`

В njs сетевые вызовы выполняются асинхронно без блокировки основного цикла событий воркера.

Файл логики `/etc/nginx/njs/external_audit.js`:

```javascript
async function handle_with_audit(r) {
    try {
        // Асинхронный вызов локального сервиса телеметрии/аудита
        const auditData = {
            client: r.remoteAddress,
            uri: r.uri,
            ts: Date.now()
        };

        // Неблокирующий fetch-запрос во внутренний сервис
        const response = await ngx.fetch('http://127.0.0.1:9099/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(auditData),
            timeout: 500 // тайм-аут 500 мс
        });

        if (response.status >= 400) {
            r.warn(`Audit service returned warning code: ${response.status}`);
        }
    } catch (e) {
        // Ошибка сервиса аудита не должна ломать клиентский ответ
        r.error(`Audit service unavailable: ${e.message}`);
    }

    // Возврат ответа клиенту
    r.return(200, JSON.stringify({ status: 'processed', node: 'edge-01' }));
}

export default { handle_with_audit };
```

Конфигурация:

```nginx
js_import audit from /etc/nginx/njs/external_audit.js;

server {
    listen 80;
    server_name service.local;

    # Настройки таймаутов и буферов для ngx.fetch
    js_fetch_timeout 2s;
    js_fetch_buffer_size 16k;

    location /process {
        default_type application/json;
        js_content audit.handle_with_audit;
    }
}
```

---

### Сценарий 5: Модификация заголовков ответа через `js_header_filter` и скрытие серверных данных

Файл логики `/etc/nginx/njs/headers_filter.js`:

```javascript
function filter_response_headers(r) {
    // Удаление служебных заголовков бэкенда, раскрывающих стек
    delete r.headersOut['X-Powered-By'];
    delete r.headersOut['Server'];

    // Внедрение заголовков защиты
    r.headersOut['X-Content-Type-Options'] = 'nosniff';
    r.headersOut['X-Frame-Options'] = 'SAMEORIGIN';

    // Добавление динамического маркера обработки узлом
    r.headersOut['X-Edge-Node'] = r.variables.server_name || 'nginx-edge';
}

export default { filter_response_headers };
```

Конфигурация:

```nginx
js_import hfilter from /etc/nginx/njs/headers_filter.js;

server {
    listen 80;
    server_name app.local;

    location / {
        proxy_pass http://backend_cluster;
        
        # Вызов фильтра после формирования ответа бэкендом
        js_header_filter hfilter.filter_response_headers;
    }
}

upstream backend_cluster {
    server 127.0.0.1:8080;
}
```

---

### Сценарий 6: Межворкерный лимитер запросов через `js_shared_dict_zone`

Использование разделяемой памяти для подсчета скользящего количества запросов с IP-адреса без развертывания Redis.

Файл логики `/etc/nginx/njs/ratelimit.js`:

```javascript
function limit_by_ip(r) {
    const zone = ngx.shared.ip_limits;
    if (!zone) {
        r.error('Shared zone "ip_limits" not configured');
        r.pass();
        return;
    }

    const ip = r.remoteAddress;
    const maxRequestsPerWindow = 100;
    const windowSec = 60;

    let current = zone.get(ip);

    if (current === undefined) {
        // Первый запрос: создаем ключ с TTL 60 секунд
        zone.set(ip, 1, windowSec);
        r.pass();
    } else if (Number(current) >= maxRequestsPerWindow) {
        r.warn(`Rate limit exceeded for IP ${ip}: ${current} requests`);
        r.headersOut['Retry-After'] = '60';
        r.return(429, JSON.stringify({ error: 'too_many_requests', limit: maxRequestsPerWindow }));
    } else {
        // Атомарный инкремент счетчика
        zone.incr(ip, 1);
        r.pass();
    }
}

export default { limit_by_ip };
```

Конфигурация:

```nginx
# Выделение 10 МБ разделяемой памяти с вытеснением старых ключей по LRU
js_shared_dict_zone zone=ip_limits:10m timeout=60s evict;

js_import ratelimit from /etc/nginx/njs/ratelimit.js;

server {
    listen 80;
    server_name protected.local;

    location / {
        js_access ratelimit.limit_by_ip;
        proxy_pass http://127.0.0.1:8080;
    }
}
```

---

### Валидация и тестирование JavaScript-скриптов

#### Проверка синтаксиса на этапе конфигурации

При выполнении команды `nginx -t` Nginx загружает указанные модули и компилирует все файлы, объявленные в `js_import`. При наличии синтаксической ошибки в `.js` файле валидация прерывается:

```bash
nginx -t
# → nginx: [emerg] js_import error: SyntaxError: Unexpected token "{" in /etc/nginx/njs/auth.js:14
# → nginx: configuration file /etc/nginx/nginx.conf test failed
```

#### Использование автономной утилиты командной строки `njs`

Пакет `nginx-module-njs` поставляет CLI-утилиту `njs` (`/usr/bin/njs`), позволяющую проверять работу функций в изолированном окружении:

```bash
# Проверка версии рантайма
njs -v
# → 0.8.8

# Выполнение однострочного выражения
njs -c 'console.log(JSON.stringify({ status: "ok", code: 200 }));'
# → {"status":"ok","code":200}

# Интерактивная консоль REPL
njs
# >> const a = [1, 2, 3];
# >> a.map(x => x * 2);
# [2, 4, 6]
```

Для изолированного unit-тестирования функций рекомендуется создавать тестовый скрипт с заглушкой (mock) объекта `r`:

```javascript
// test_auth.js
import auth from './auth.js';

const mockRequest = {
    headersIn: { 'Authorization': 'Bearer prod-sec-0123456789abcdef012345' },
    remoteAddress: '127.0.0.1',
    pass: () => console.log('PASS: Access granted'),
    return: (code, msg) => console.log(`RETURN: ${code} - ${msg}`),
    error: (msg) => console.error(`ERROR: ${msg}`),
    warn: (msg) => console.warn(`WARN: ${msg}`)
};

auth.authorize(mockRequest);
```

Запуск проверки:

```bash
njs test_auth.js
# → PASS: Access granted
```

---

## Операции и команды

| Директива / Команда | Контекст | Назначение |
| :--- | :--- | :--- |
| `load_module <path>;` | `main` | Загрузка динамического модуля `ngx_http_js_module.so` или `ngx_stream_js_module.so`. |
| `js_import <module> from <file>;` | `http`, `stream` | Импорт JavaScript-файла и привязка экспортированных функций к пространству имен `<module>`. |
| `js_path <dir>;` | `http`, `stream` | Указание директории для поиска импортируемых модулей. |
| `js_set $var <module>.<fn>;` | `http`, `stream` | Вычисление строковой переменной Nginx с кешированием результата на время запроса. |
| `js_var $var [default];` | `http`, `stream` | Объявление изменяемой из JS переменной запроса (`r.variables.$var = val`). |
| `js_access <module>.<fn>;` | `http`, `server`, `location` | Фазовый обработчик доступа. Принимает решение о пропуске (`r.pass()`) или блокировке. |
| `js_content <module>.<fn>;` | `location` | Терминальный обработчик контента. Полностью формирует ответ клиенту. |
| `js_header_filter <module>.<fn>;` | `http`, `server`, `location` | Фильтр модификации заголовков ответа бэкенда (`r.headersOut`). |
| `js_body_filter <module>.<fn>;` | `http`, `server`, `location` | Потоковый фильтр инспекции и модификации тела ответа. |
| `js_shared_dict_zone zone=<name>:<size>;` | `http`, `stream` | Выделение сегмента разделяемой памяти для межворкерного хранилища ключ-значение. |
| `js_periodic <module>.<fn> interval=<time>;` | `location` | Запуск периодической функции внутри рабочего процесса Nginx. |
| `js_engine njs \| qjs;` | `http`, `stream` | Выбор движка виртуальной машины: нативный `njs` либо `qjs` (QuickJS). |
| `js_fetch_timeout <time>;` | `http`, `server`, `location` | Установка таймаута на сетевые операции вызова `ngx.fetch()`. |
| `js_fetch_buffer_size <size>;` | `http`, `server`, `location` | Размер буфера чтения ответа для вызовов `ngx.fetch()`. |
| `nginx -t` | CLI | Компиляция конфигурации и всех подключенных через `js_import` JS-скриптов. |
| `nginx -s reload` | CLI | Бесшовное обновление конфигурации и горячая замена байткода njs без простоя сервиса. |
| `njs -c "<expr>"` | CLI | Выполнение JavaScript-выражения в окружении njs CLI. |

---

## Устранение неполадок

### 1. Ошибка `unknown directive "js_set"` или `"js_import"`

**Причина:** Динамический модуль `ngx_http_js_module.so` не установлен либо директива `load_module` размещена не в глобальном контексте.
**Диагностика:**
```bash
nginx -t
# → nginx: [emerg] unknown directive "js_set" in /etc/nginx/conf.d/test.conf:5
```
**Решение:**
1. Проверьте установку пакета `nginx-module-njs` через пакетный менеджер системы (`dpkg -l | grep njs` или `rpm -qa | grep njs`).
2. Убедитесь, что строка `load_module modules/ngx_http_js_module.so;` расположена в самом начале файла `/etc/nginx/nginx.conf` до открытия блоков `http` и `events`.

### 2. Синтаксические ошибки и ошибки импорта при старте

**Причина:** Ошибка синтаксиса в JS-коде, использование неподдерживаемых конструкций (например, `eval`, `with`, `async` функций в неподдерживаемом контексте) или некорректный относительный путь в `js_import`.
**Диагностика:**
```bash
nginx -t
# → nginx: [emerg] js_import error: Cannot find module "/etc/nginx/njs/missing.js"
```
**Решение:**
1. Проверьте пути к файлам скриптов: используйте абсолютные пути либо задайте директиву `js_path /etc/nginx/njs/;`.
2. Запустите скрипт через `njs <file>.js` для локализации синтаксических ошибок.

### 3. Ошибка 500 Internal Server Error при выполнении `js_content` или `js_set`

**Причина:** Необработанное исключение во время исполнения скрипта (обращение к свойствам `undefined`, деление на ноль, неверный формат вызова API).
**Диагностика:** Изучите системный журнал ошибок Nginx:
```bash
tail -n 20 /var/log/nginx/error.log
# → [error] 14210#14210: *1 js exception: TypeError: cannot get property 'foo' of undefined in /etc/nginx/njs/api.js:8
```
**Решение:**
1. Оберните потенциально нестабильные блоки кода в конструкцию `try { ... } catch (e) { r.error(e.message); ... }`.
2. Перед обращением к вложенным свойствам проверяйте их существование: `r.headersIn && r.headersIn['X-Custom-Header']`.
3. В `js_set` возвращайте безопасное значение по умолчанию (пустую строку `''`), так как генерация исключения в `js_set` приводит к прерыванию обработки запроса.

### 4. Деградация производительности и зависание воркеров (Worker Starvation)

**Причина:** Использование синхронных тяжелых операций (глубокая рекурсия, синхронная обработка многомегабайтных строк/JSON) или блокирующий цикл ожидания.
**Диагностика:** Резкий рост утилизации CPU рабочими процессами Nginx (`top` / `htop`), увеличение latency на соседних независимых эндпоинтах.
```bash
top -p $(pgrep -d',' -f "nginx: worker")
```
**Решение:**
1. Исключите тяжелые CPU-bound алгоритмы из njs. njs предназначен для быстрой диспетчеризации и инспекции запросов; сложные вычисления должны производиться на бэкенде.
2. Для внешних сетевых вызовов используйте строго асинхронный `ngx.fetch()` с обязательной установкой тайм-аута `js_fetch_timeout`.

### 5. Ошибка `no memory in js shared dict zone`

**Причина:** Зона разделяемой памяти `js_shared_dict_zone` заполнена данными, а механизм вытеснения отключен (не указан параметр `evict`).
**Диагностика:**
```bash
grep -i "shared dict" /var/log/nginx/error.log
# → [error] 14210#14210: *1 js: no memory in js shared dict zone "ip_limits"
```
**Решение:**
1. Добавьте флаг `evict` в определение зоны: `js_shared_dict_zone zone=ip_limits:20m timeout=60s evict;`.
2. Увеличьте размер зоны с учетом пиковой нагрузки и установите TTL для временных ключей (`zone.set(key, val, ttl)`).

---

## Лучшие практики

1. **Структура хранения кода:** Размещайте все файлы `.js` в выделенном каталоге (например, `/etc/nginx/njs/`), версионируйте их в Git вместе с конфигурацией Nginx и настраивайте единый путь поиска через `js_path`.
2. **Изоляция и обработка ошибок:** Каждая экспортируемая функция обязана содержать защитный блок `try ... catch`. При сбое сетевого взаимодействия в `ngx.fetch` предусматривайте graceful degradation (резервный ответ или переход на дефолтную маршрутизацию).
3. **Кеширование переменных `js_set`:** Помните, что переменная, объявленная через `js_set`, вычисляется ровно один раз при первом обращении к ней в рамках текущего запроса, после чего значение фиксируется. Не используйте `js_set` для логики с побочными эффектами (side effects).
4. **Контроль фаз обработки:** Не используйте `js_content` там, где требуется лишь проверка прав — для валидации доступа применяйте `js_access`, чтобы запрос мог штатно уйти в стандартный `proxy_pass` без ручной реализации проксирования в JS.
5. **Безопасность входных данных:** Никогда не подставляйте значения из `r.args` или `r.headersIn` напрямую в команды перенаправления без валидации для защиты от Open Redirect и Header Injection атак.
6. **CI/CD пайплайн валидации:** Включайте валидацию синтаксиса скриптов `nginx -t` и автоматизированные тесты через `njs test_script.js` в конвейеры сборки и тестирования перед деплоем на продуктовые серверы.

---

## Дополнительная информация

### Взаимосвязи в базе знаний

- **[Обзор Nginx](./nginx_overview.md)** — архитектура мастер- и воркер-процессов Nginx, обработка событий epoll.
- **[Установка и базовая настройка Nginx](./nginx_setup.md)** — развертывание Nginx, конфигурация виртуальных хостов и CLI-управление.
- **[Предикатные location в Nginx](./Location/predicate_locations.md)** — динамическая маршрутизация запросов на основе njs-переменных и `js_set`.
- **[Сборка Nginx из исходников и модули](./nginx_build_from_source.md)** — компиляция динамических модулей и директива `load_module`.
- **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)** — общая методология анализа системных ошибок и журналов Nginx.
- **[Скриптование на njs в Angie](../../Angie/angie-njs.md)** — особенности реализации njs в веб-сервере Angie и переносимость скриптов.
- **[Контроль доступа в Angie](../../Angie/angie_access_control.md)** — альтернативные модули авторизации и аутентификации.

### Официальная документация

- [Официальная документация модуля ngx_http_js_module](https://nginx.org/en/docs/http/ngx_http_js_module.html) — спецификация директив, аргументов и конфигурации.
- [Справочник API njs (Reference)](https://nginx.org/en/docs/njs/reference.html) — полный перечень методов объектов `r`, `s`, `ngx`, `Buffer`, `crypto`.
- [Журнал изменений njs (Changelog)](https://nginx.org/en/docs/njs/changes.html) — история версий, новые директивы и исправления безопасности.