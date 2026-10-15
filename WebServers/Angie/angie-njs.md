# Скриптование на njs в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x (модуль njs 0.8.x – 0.9.x)

## Определения

**njs (Nginx/Angie JavaScript)** — специализированное легковесное подмножество языка ECMAScript, встроенное непосредственно в архитектуру рабочих процессов Angie. Реализует синхронное и асинхронное исполнение кода в виртуальной машине внутри воркера без подключения внешних тяжелых сред исполнения (таких как V8 или Node.js) и без блокировки основного событийного цикла epoll/kqueue.

**ngx_http_js_module** — динамический модуль Angie (поставляемый в пакетах `angie-module-njs` и `angie-pro-module-njs`), расширяющий HTTP-контекст директивами внедрения JavaScript-логики (`js_import`, `js_set`, `js_var`, `js_content`, `js_access`, `js_header_filter`, `js_body_filter`, `js_periodic`, `js_shared_dict_zone`).

**ngx_stream_js_module** — динамический модуль Angie для стека транспортного уровня (L4 TCP/UDP Stream), позволяющий перехватывать, анализировать и модифицировать сетевые сессии директивами `js_preread`, `js_filter`, `js_access`.

**js_content** — терминальный обработчик контента в блоке `location`, передающий управление JavaScript-функции для полной генерации HTTP-ответа (статус, заголовки, тело).

**js_set** — директива вычисления динамической переменной ядра Angie с отложенным расчетом (lazy evaluation) при первом обращении к переменной в рамках текущего запроса. Результат кэшируется на время жизни запроса.

**js_var** — директива объявления пользовательской переменной njs с поддержкой явной перезаписи значения внутри JavaScript-кода в ходе обработки запроса.

**js_access** — фазовый обработчик доступа (Access Phase), исполняемый перед передачей запроса к обработчику контента или проксированию. Позволяет подтвердить доступ (`r.return(204)`), заблокировать его (`r.return(403)`) или делегировать дальнейшим модулям (`r.pass()`).

**js_header_filter** — фильтр исходящих HTTP-заголовков, вызываемый после формирования ответа бэкендом или локальным обработчиком, предназначенный для модификации, добавления или удаления заголовков ответа на лету.

**js_body_filter** — потоковый фильтр тела HTTP-ответа, получающий чанки данных от бэкенда и способный трансформировать или маскировать полезную нагрузку до отправки клиенту.

**js_shared_dict_zone** — разделяемая зона памяти (Shared Memory Zone), доступная всем рабочим процессам Angie (worker processes) для потокобезопасного хранения пар ключ-значение со встроенным механизмом вытеснения по алгоритму LRU (Least Recently Used).

**js_periodic** — директива запуска регулярных фоновых задач внутри рабочего процесса Angie с заданным интервалом без использования внешних системных планировщиков (cron/systemd timers).

**Объект `r` (HTTP Request)** — контекстный объект HTTP-запроса в njs, предоставляющий доступ к метаданным (`r.uri`, `r.method`, `r.args`, `r.headersIn`, `r.headersOut`, `r.variables`), методам отправки ответов (`r.return()`, `r.sendHeader()`, `r.send()`, `r.finish()`), внутренним подзапросам (`r.subrequest()`) и системному логированию (`r.log()`, `r.warn()`, `r.error()`).

**Объект `s` (Stream Session)** — контекстный объект TCP/UDP-сессии в Stream-модуле njs (`s.remoteAddress`, `s.variables`, `s.on()`, `s.send()`, `s.done()`, `s.deny()`, `s.allow()`).

**Глобальный объект `ngx`** — корневое пространство имен среды исполнения njs, содержащее глобальные методы сетевого взаимодействия (`ngx.fetch()`), доступ к разделяемой памяти (`ngx.shared`), криптографическим примитивам (`crypto.subtle`) и расширенным системным операциям.

## Архитектура и базовые концепции

### Архитектура виртуальной машины njs: VM-on-demand

В отличие от традиционных сред исполнения JavaScript (Node.js, Deno, Bun на базе V8 или JavaScriptCore) и сред Lua (OpenResty на базе LuaJIT), модуль njs спроектирован специально под неблокирующую архитектуру веб-серверов семейств Angie/Nginx:

1. **Компиляция на старте:** При запуске или перезагрузке (reload) Angie файлы скриптов компилируются один раз в мастер-процессе в промежуточное представление (байткод). Байткод распределяется по разделяемой памяти рабочих процессов. Синтаксические ошибки выявляются на этапе валидации конфигурации (`angie -t`).
2. **Изоляция и модель памяти (VM-on-demand):** Для каждого входящего запроса создается независимый легковесный экземпляр виртуальной машины njs. Память под переменные и объекты выделяется напрямую из внутреннего пула памяти запроса веб-сервера (`ngx_pool_t`).
3. **Отсутствие пауз сборщика мусора (No GC Pauses):** В njs отсутствует классический фоновый сборщик мусора (Tracing/Generational Garbage Collector). По завершении обработки HTTP-запроса весь пул памяти `ngx_pool_t` освобождается атомарно за одну системную операцию. Это исключает непредсказуемые задержки (latency spikes) и деградацию хвостовых перцентилей (p99/p99.9).
4. **Запрет динамической генерации кода:** В njs жестко заблокированы функции `eval()`, конструктор `new Function()` и модификация прототипов встроенных типов. Вся исполняемая логика полностью детерминирована на этапе старта сервера.

### Сравнение njs, Node.js и LuaJIT (OpenResty)

| Критерий | njs (Angie) | Node.js (V8) | OpenResty (LuaJIT) |
| :--- | :--- | :--- | :--- |
| **Интеграция** | Встроен в воркер веб-сервера | Отдельный сервис/процесс | Встроен в воркер веб-сервера |
| **Сборка мусора (GC)** | Отсутствует (очистка пула запроса) | Поколенческий GC (Mark-Sweep) | Инкрементальный GC LuaJIT |
| **Модель памяти** | Изолированная VM на запрос | Общая куча (Heap) на процесс | Единый контекст Lua на воркер |
| **Накладные расходы RAM** | Единицы килобайт на запрос | 30–100+ МБ на процесс | Сотни килобайт на инстанс |
| **Старт/Инициализация** | Мгновенно (< 1 мкс) | Секунды | Единицы миллисекунд |
| **JIT-компиляция** | Нет (чистый байткод-интерпретатор) | Да (Crankshaft/TurboFan) | Да (трассирующий JIT) |
| **Сетевой I/O** | `r.subrequest()`, `ngx.fetch()` | libuv (асинхронные сокеты) | Cosocket API |
| **Типовые сценарии** | Маршрутизация, auth, трансформация | Бизнес-логика, микросервисы | Сложные шлюзы, интеграции |

### Жизненный цикл HTTP-запроса и точки интеграции njs

Директивы модуля `ngx_http_js_module` встраиваются в стандартные фазы конвейера обработки HTTP-запросов Angie:

```
+-------------------------------------------------------------------------+
|                  Фаза Init (Парсинг конфига / reload)                   |
|  - Компиляция JS-файлов из директив js_import в байткод                 |
|  - Инициализация зон разделяемой памяти (js_shared_dict_zone)           |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                       Фаза Pre-Read / Rewrite                           |
|  - js_set: инициализация и расчет динамических переменных               |
|  - js_var: регистрация изменяемых переменных запроса                    |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                       Фаза Access (Проверка прав)                       |
|  - js_access: валидация токенов, HMAC, белых/черных списков             |
|  - Пропуск (204 / pass), отказ (401/403) или редирект                   |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Фаза Content (Генерация ответа)                    |
|  - js_content: формирование ответа целиком (API mock, healthcheck)     |
|  - ИЛИ передача в proxy_pass / fastcgi_pass / статику                   |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Фаза Header Filter (Заголовки)                     |
|  - js_header_filter: добавление/удаление/мутация заголовков ответа     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Фаза Body Filter (Тело ответа)                     |
|  - js_body_filter: потоковая фильтрация чанков, маскирование данных     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Фаза Log (Журналирование)                          |
|  - Использование вычисленных js_set переменных в директиве log_format   |
+-------------------------------------------------------------------------+
```

### Асинхронная неблокирующая модель ввода-вывода

Виртуальная машина njs исполняется внутри рабочего потока воркера Angie. Вызов любых долгих синхронных системных вызовов (например, синхронный расчет ресурсоемких криптографических хэшей в цикле, блокирующее чтение с диска или синхронные сетевые запросы) **блокирует обработку всех остальных соединений данного воркера**.

Для выполнения внешних сетевых операций njs предоставляет два механизма:
1. **`ngx.fetch(url, options)`** — встроенная реализация стандарта Fetch API на базе асинхронного сетевого стека Angie. Возвращает `Promise`. Не блокирует воркер: веб-сервер регистрирует сокет в epoll и переключается на обслуживание других клиентских подключений до момента прихода ответа от удаленного узла.
2. **`r.subrequest(uri, options, callback)`** — создание внутреннего неблокирующего подзапроса к другим `location` текущего веб-сервера Angie (например, к upstream-группе или локальному обработчику).

### Межворкерная разделяемая память (`js_shared_dict_zone`)

Директива `js_shared_dict_zone` выделяет сегмент общей оперативной памяти (Shared Memory), доступный всем воркерам веб-сервера. Доступ к ключам синхронизируется через внутренние спинлоки ядра Angie:

* Чтение и запись значений производятся через объект `ngx.shared.<zone_name>`.
* Поддерживаются типы данных `string` и `number`.
* Атомарные операции: `.set()`, `.add()`, `.get()`, `.delete()`, `.incr()`, `.clear()`.
* При переполнении памяти старые ключи вытесняются по алгоритму LRU либо выдается ошибка при отключенном вытеснении.

## Практические сценарии и настройка

### Предварительные требования и установка модуля

Модуль njs поставляется в виде динамических разделяемых библиотек (`ngx_http_js_module.so` и `ngx_stream_js_module.so`).

#### Установка в Debian / Ubuntu

```bash
sudo apt update
sudo apt install -y angie-module-njs
# → Setting up angie-module-njs ...
```

Для коммерческой редакции Angie PRO:
```bash
sudo apt install -y angie-pro-module-njs
# → Setting up angie-pro-module-njs ...
```

#### Установка в RHEL / AlmaLinux / Rocky Linux / RedOS

```bash
sudo dnf install -y angie-module-njs
# → Installed: angie-module-njs.x86_64 ... Complete!
```

#### Установка в Astra Linux Special Edition 1.7

В дистрибутивах Astra Linux со включенным режимом Замкнутой программной среды (ЗПС / CSE) все динамические библиотеки проверяются на наличие цифровой подписи:

```bash
sudo apt-get install -y angie-module-njs
# Проверка наличия цифровой подписи библиотеки для ЗПС
bsign -c /usr/lib/angie/modules/ngx_http_js_module.so
# → /usr/lib/angie/modules/ngx_http_js_module.so: GOOD signature
```

### Подключение модулей и организация файловой структуры

Директивы `load_module` должны находиться на самом верхнем уровне конфигурации (контекст `main`, до блоков `http` и `stream`).

Файлы скриптов рекомендуется размещать в изолированном каталоге `/etc/angie/scripts/` с разграничением прав: владелец `root:root`, права `0755` на каталог и `0644` на файлы скриптов (запись веб-сервером запрещена).

Создание каталога и установка прав:
```bash
sudo mkdir -p /etc/angie/scripts
sudo chown -R root:root /etc/angie/scripts
sudo chmod 755 /etc/angie/scripts
```

Базовый каркас `/etc/angie/angie.conf`:
```nginx
# Контекст main
user angie;
worker_processes auto;
pid /run/angie.pid;

# Подключение динамических модулей njs
load_module modules/ngx_http_js_module.so;
load_module modules/ngx_stream_js_module.so;

events {
    worker_connections 1024;
}

http {
    include /etc/angie/mime.types;
    default_type application/octet-stream;

    # Импорт модулей скриптов в контексте http
    js_import router from /etc/angie/scripts/router.js;
    js_import security from /etc/angie/scripts/security.js;

    # Зона разделяемой памяти для межворкерных счетчиков и лимитов
    js_shared_dict_zone zone=rate_limit_zone:10m timeout=60s eviction=lru;

    include /etc/angie/conf.d/*.conf;
}
```

---

### Сценарий 1: Проверка HMAC / API-ключа на фазе Access (`js_access`)

Реализация высокопроизводительной валидации API-токенов или HMAC-подписей запроса прямо на входе в веб-сервер без обращения к внешнему сервису аутентификации.

**Файл скрипта `/etc/angie/scripts/security.js`:**
```javascript
// Проверка статического или вычисляемого токена в заголовках
function validateApiKey(r) {
    const key = r.headersIn['X-API-Key'];

    if (!key) {
        r.error('Authentication failed: Missing X-API-Key header');
        r.return(401, JSON.stringify({ error: 'Unauthorized', message: 'X-API-Key header required' }));
        return;
    }

    // Проверка формата ключа (hex-строка из 32 символов)
    if (!/^[a-f0-9]{32}$/i.test(key)) {
        r.warn(`Authentication failed: Invalid key format from ${r.remoteAddress}`);
        r.return(400, JSON.stringify({ error: 'Bad Request', message: 'Malformed API Key' }));
        return;
    }

    // Пример сверки с доверенным пулом токенов
    const validKeys = new Set([
        'c8b394d18e8749a9b6c4358a9840d512',
        'e1d2c3b4a59687786950413223140516'
    ]);

    if (validKeys.has(key)) {
        // Успешная авторизация - пропуск запроса дальше по конвейеру
        r.headersOut['X-Auth-Status'] = 'Verified';
        r.pass();
    } else {
        r.warn(`Access denied for IP ${r.remoteAddress}: Token mismatch`);
        r.return(403, JSON.stringify({ error: 'Forbidden', message: 'Invalid API Key' }));
    }
}

export default { validateApiKey };
```

**Фрагмент конфигурации `/etc/angie/conf.d/api.conf`:**
```nginx
server {
    listen 8080;
    server_name api.internal.local;

    # Импорт модуля безопасности
    js_import security from /etc/angie/scripts/security.js;

    location /api/v1/ {
        # Подключение функции на фазе access
        js_access security.validateApiKey;

        proxy_pass http://backend_pool;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Проверка валидации:
```bash
# 1. Запрос без ключа -> 401 Unauthorized
curl -i http://127.0.0.1:8080/api/v1/data
# → HTTP/1.1 401 Unauthorized
# → {"error":"Unauthorized","message":"X-API-Key header required"}

# 2. Запрос с некорректным ключом -> 403 Forbidden
curl -i -H "X-API-Key: 00000000000000000000000000000000" http://127.0.0.1:8080/api/v1/data
# → HTTP/1.1 403 Forbidden
# → {"error":"Forbidden","message":"Invalid API Key"}

# 3. Запрос с валидным ключом -> 200 OK
curl -i -H "X-API-Key: c8b394d18e8749a9b6c4358a9840d512" http://127.0.0.1:8080/api/v1/data
# → HTTP/1.1 200 OK
```

---

### Сценарий 2: Канареечная маршрутизация (Canary) и динамический upstream через `js_set`

Обеспечивает интеллектуальное распределение запросов между стабильной версией сервиса (`stable`) и канареечным релизом (`canary`) на базе cookie, заголовка или процентного распределения по хэшу клиентского IP.

**Файл скрипта `/etc/angie/scripts/router.js`:**
```javascript
function selectUpstream(r) {
    // 1. Приоритет: явный заголовок для внутреннего тестирования QA-инженерами
    const debugHeader = r.headersIn['X-Target-Release'];
    if (debugHeader === 'canary') {
        return 'upstream_canary';
    }

    // 2. Проверка сессионной cookie beta_tester=true
    const cookies = r.headersIn['Cookie'] || '';
    if (cookies.includes('beta_tester=true')) {
        return 'upstream_canary';
    }

    // 3. Детерминированное распределение 10% аудитории по хэшу клиентского IP
    const ip = r.remoteAddress || '127.0.0.1';
    let hash = 0;
    for (let i = 0; i < ip.length; i++) {
        hash = (hash * 31 + ip.charCodeAt(i)) >>> 0;
    }

    // Если остаток от деления меньше 10 — направляем на canary (10% трафика)
    if (hash % 100 < 10) {
        return 'upstream_canary';
    }

    return 'upstream_stable';
}

export default { selectUpstream };
```

**Фрагмент конфигурации `/etc/angie/conf.d/canary.conf`:**
```nginx
upstream upstream_stable {
    zone upstream_stable 64k;
    server 10.10.1.11:8000 max_fails=2 fail_timeout=10s;
    server 10.10.1.12:8000 max_fails=2 fail_timeout=10s;
    keepalive 32;
}

upstream upstream_canary {
    zone upstream_canary 64k;
    server 10.10.2.11:8000 max_fails=2 fail_timeout=10s;
    keepalive 16;
}

# Расчет имени upstream-группы для каждого запроса
js_import router from /etc/angie/scripts/router.js;
js_set $target_backend router.selectUpstream;

server {
    listen 80;
    server_name service.example.internal;

    location / {
        proxy_pass http://$target_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;

        # Проброс метки целевого апстрима в заголовке ответа для диагностики
        add_header X-Routed-Backend $target_backend always;
    }
}
```

Проверка маршрутизации:
```bash
# Принудительный запрос на canary через заголовок
curl -s -I -H "X-Target-Release: canary" http://127.0.0.1/
# → HTTP/1.1 200 OK
# → X-Routed-Backend: upstream_canary

# Стандартный запрос
curl -s -I http://127.0.0.1/
# → HTTP/1.1 200 OK
# → X-Routed-Backend: upstream_stable
```

---

### Сценарий 3: Потоковая маскировка конфиденциальных данных (`js_header_filter` и `js_body_filter`)

Маскирование персональных данных (PII), номеров кредитных карт или секретных токенов в теле ответов бэкенда на уровне обратного прокси перед отдачей клиенту или системам сбора логов.

**Файл скрипта `/etc/angie/scripts/filter.js`:**
```javascript
function headerFilter(r) {
    // Удаляем заголовок Content-Length, так как длина тела изменится при замене строк
    delete r.headersOut['Content-Length'];
    // Запрещаем сжатие бэкендом, чтобы body_filter получал открытый текст
    r.headersOut['X-Filter-Applied'] = 'Data-Masking-v1';
}

function maskPiiData(r, data, flags) {
    if (!data) {
        return;
    }

    // Регулярное выражение для поиска номеров банковских карт (16 цифр)
    // Заменяем средние 8 цифр на звездочки: 4111********1111
    const masked = data.replace(/\b(\d{4})\d{8}(\d{4})\b/g, '$1********$2');

    // Передаем модифицированный чанк данных следующему фильтру
    r.sendBuffer(masked, flags);
}

export default { headerFilter, maskPiiData };
```

**Фрагмент конфигурации `/etc/angie/conf.d/masking.conf`:**
```nginx
js_import filter from /etc/angie/scripts/filter.js;

server {
    listen 8080;
    server_name pii-proxy.local;

    location /payments/ {
        proxy_pass http://payment_backend;

        # Отключение gzip со стороны бэкенда для возможности анализа текста
        proxy_set_header Accept-Encoding "";

        # Подключение фильтров заголовков и тела ответа
        js_header_filter filter.headerFilter;
        js_body_filter filter.maskPiiData;
    }
}
```

---

### Сценарий 4: Межворкерный Rate Limiting через `js_shared_dict_zone`

Реализация скользящего счетчика запросов или блокировки подозрительных IP-адресов с хранением состояния в разделяемой памяти, доступной всем воркерам веб-сервера.

**Файл скрипта `/etc/angie/scripts/rate_limiter.js`:**
```javascript
function limitRequests(r) {
    const zone = ngx.shared.rate_limit_zone;
    if (!zone) {
        r.error('Rate limit shared zone not found');
        r.pass();
        return;
    }

    const clientIp = r.remoteAddress;
    const maxRequests = 100; // Максимум запросов в минуту
    const windowSeconds = 60;

    // Считываем текущее значение счетчика
    let current = zone.get(clientIp);

    if (current === undefined) {
        // Первый запрос в текущем окне: инициализируем значение 1 с TTL 60 сек
        zone.set(clientIp, 1, windowSeconds);
        r.headersOut['X-RateLimit-Remaining'] = String(maxRequests - 1);
        r.pass();
    } else if (Number(current) >= maxRequests) {
        // Превышение лимита
        r.warn(`Rate limit exceeded for IP: ${clientIp}`);
        r.headersOut['Retry-After'] = '60';
        r.return(429, JSON.stringify({
            error: 'Too Many Requests',
            message: 'Rate limit of 100 req/min exceeded. Please try again later.'
        }));
    } else {
        // Инкремент существующего ключа
        zone.incr(clientIp, 1);
        r.headersOut['X-RateLimit-Remaining'] = String(maxRequests - Number(current) - 1);
        r.pass();
    }
}

export default { limitRequests };
```

**Фрагмент конфигурации `/etc/angie/conf.d/rate_limit.conf`:**
```nginx
# В контексте http:
# js_shared_dict_zone zone=rate_limit_zone:10m timeout=60s eviction=lru;

server {
    listen 80;
    server_name api.service.internal;

    js_import rate_limiter from /etc/angie/scripts/rate_limiter.js;

    location /api/highload/ {
        js_access rate_limiter.limitRequests;

        proxy_pass http://api_backend;
    }
}
```

---

### Сценарий 5: Фоновые периодические задачи (`js_periodic`)

Директива `js_periodic` позволяет запускать JavaScript-функции с заданным интервалом непосредственно в воркере Angie. Это применяется для регулярного сброса локальных метрик, прогрева DNS/кэша или фонового опроса контроллеров состояния.

**Файл скрипта `/etc/angie/scripts/periodic.js`:**
```javascript
async function healthcheckCollector() {
    try {
        // Асинхронный опрос внутреннего сервиса метрик без блокировки воркера
        const res = await ngx.fetch('http://127.0.0.1:8080/internal/ping', {
            method: 'GET',
            headers: { 'User-Agent': 'Angie-Periodic-Collector' }
        });

        if (res.status === 200) {
            ngx.log(ngx.INFO, `Periodic healthcheck passed, status: ${res.status}`);
        } else {
            ngx.log(ngx.WARN, `Periodic healthcheck returned degraded status: ${res.status}`);
        }
    } catch (e) {
        ngx.log(ngx.ERR, `Periodic healthcheck network error: ${e.message}`);
    }
}

export default { healthcheckCollector };
```

**Фрагмент конфигурации `/etc/angie/conf.d/periodic.conf`:**
```nginx
js_import periodic from /etc/angie/scripts/periodic.js;

server {
    listen 127.0.0.1:8080;

    location = /internal/ping {
        return 200 "pong\n";
    }

    # Запуск периодической функции раз в 10 секунд с разбросом 1 секунда (jitter)
    # worker_affinity привязывает задачу к первому рабочему процессу, чтобы избежать дублирования
    location @background_task {
        js_periodic periodic.healthcheckCollector interval=10s jitter=1s worker_affinity=0001;
    }
}
```

---

### Сценарий 6: Маршрутизация на транспортном уровне L4 (`ngx_stream_js_module`)

Инспекция начальных байт сырого TCP-потока данных (например, валидация заголовка протокола или выбор целевого сервера без расшифровки TLS) с использованием директивы `js_preread`.

**Файл скрипта `/etc/angie/scripts/stream_router.js`:**
```javascript
function inspectProtocol(s) {
    s.on('upload', function (data, flags) {
        // Проверяем наличие полезной нагрузки в первом пакете соединения
        if (data.length >= 3) {
            // Проверка TLS Handshake (0x16 0x03)
            if (data.charCodeAt(0) === 0x16 && data.charCodeAt(1) === 0x03) {
                s.variables.target_backend = 'tls_cluster';
                s.done();
                return;
            }
            // Проверка сигнатуры SSH (SSH-)
            if (data.startsWith('SSH-')) {
                s.variables.target_backend = 'ssh_jump_host';
                s.done();
                return;
            }
        }

        // Если пакет слишком короткий, продолжаем ожидание данных
        if (flags.last) {
            s.variables.target_backend = 'default_drop';
            s.done();
        }
    });
}

export default { inspectProtocol };
```

**Фрагмент конфигурации `/etc/angie/conf.d/stream.conf`:**
```nginx
stream {
    js_import stream_router from /etc/angie/scripts/stream_router.js;

    upstream tls_cluster {
        server 10.20.1.10:443;
    }

    upstream ssh_jump_host {
        server 10.20.1.20:22;
    }

    server {
        listen 2222;
        js_preread stream_router.inspectProtocol;

        proxy_pass $target_backend;
        proxy_timeout 1h;
        proxy_connect_timeout 5s;
    }
}
```

## Операции и команды

### Сводная таблица директив njs

| Директива | Контекст | Назначение |
| :--- | :--- | :--- |
| `load_module` | `main` | Загрузка `.so`-модуля (`ngx_http_js_module.so`, `ngx_stream_js_module.so`) |
| `js_import <module> from <path>;` | `http`, `stream`, `server`, `location` | Импорт JS-файла и привязка к имени модуля |
| `js_set $var <module>.<func>;` | `http`, `stream`, `server`, `location` | Вычисление переменной с кэшированием в рамках запроса |
| `js_var $var [value];` | `http`, `stream`, `server`, `location` | Объявление перезаписываемой переменной njs |
| `js_content <module>.<func>;` | `location`, `limit_except` | Терминальный обработчик контента (генерация ответа) |
| `js_access <module>.<func>;` | `http`, `server`, `location` | Фазовый контроль доступа до передачи запроса |
| `js_header_filter <module>.<func>;` | `location`, `if in location` | Потоковый фильтр HTTP-заголовков ответа |
| `js_body_filter <module>.<func> [buffer_type=string\|buffer];` | `location`, `if in location` | Потоковый фильтр чанков тела ответа |
| `js_shared_dict_zone zone=name:size [timeout=time] [type=string\|number] [eviction=lru];` | `http`, `stream` | Создание межворкерной разделяемой зоны памяти |
| `js_periodic <module>.<func> [interval=time] [jitter=time] [worker_affinity=mask];` | `location` | Запуск регулярной фоновой задачи по таймеру |
| `js_preread <module>.<func>;` | `stream`, `server` | Анализ сырых данных TCP/UDP до начала проксирования |
| `js_fetch_timeout <time>;` | `http`, `server`, `location` | Таймаут сетевых запросов функции `ngx.fetch` |
| `js_fetch_trusted_certificate <file>;` | `http`, `server`, `location` | Путь к CA-сертификатам для валидации HTTPS в `ngx.fetch` |

### Регламентные команды проверки и сопровождения

#### Проверка наличия установленных библиотек

```bash
# Проверка размещения разделяемых объектов Angie
ls -la /usr/lib/angie/modules/ngx_*js_module.so
# → -rwxr-xr-x 1 root root 872160 Mar 12 10:00 /usr/lib/angie/modules/ngx_http_js_module.so
# → -rwxr-xr-x 1 root root 425980 Mar 12 10:00 /usr/lib/angie/modules/ngx_stream_js_module.so

# Проверка динамических зависимостей модуля через ldd
ldd /usr/lib/angie/modules/ngx_http_js_module.so | grep -E "libc|libm|libcrypto"
# → libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f90...)
# → libcrypto.so.3 => /usr/lib/x86_64-linux-gnu/libcrypto.so.3 (0x00007f8f...)
```

#### Валидация синтаксиса конфигурации и JS-файлов

При выполнении команды `angie -t` веб-сервер не только парсит директивы, но и производит пробную компиляцию всех подключенных через `js_import` файлов:

```bash
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
```

Если в JavaScript допущена синтаксическая ошибка:
```bash
sudo angie -t
# → angie: [emerg] SyntaxError: Unexpected token "}" in /etc/angie/scripts/security.js:45
# → angie: configuration file /etc/angie/angie.conf test failed
```

#### Автономное тестирование скрипта через CLI-утилиту njs

Утилита командной строки `njs` (поставляется в составе пакета или компилируется отдельно) позволяет протестировать работу чистых функций локально без запуска сервера:

```bash
# Проверка исполнения однострочника
njs -c "console.log(JSON.stringify({ status: 'ok', ts: Date.now() }))"
# → {"status":"ok","ts":1773489600000}

# Валидация синтаксиса файла скрипта
njs -c "import mod from '/etc/angie/scripts/router.js'; console.log('Syntax valid');"
# → Syntax valid
```

#### Применение изменений (Graceful Reload)

```bash
# Плавная перезагрузка рабочих процессов без обрыва клиентских соединений
sudo systemctl reload angie

# Проверка статуса службы systemd
systemctl is-active angie
# → active
```

## Устранение неисправностей

| Симптом / Ошибка | Вероятная причина | Диагностика | Метод устранения |
| :--- | :--- | :--- | :--- |
| **`HTTP 500 Internal Server Error`** при обращении к `js_content` / `js_access` | Необработанное исключение (uncaught exception) в JS-коде (обращение к `undefined`, ошибка в `JSON.parse`) | `grep -E "js\|njs" /var/log/angie/error.log \| tail -n 20` | Обернуть подозрительные участки кода в `try { ... } catch (e) { r.error(e.message); r.return(500); }` |
| **`unknown directive "js_import"`** или `unknown directive "js_set"` | Модуль `ngx_http_js_module.so` не загружен или директива `load_module` размещена внутри блока `http` | Проверить начало `/etc/angie/angie.conf` | Перенести директивы `load_module` на самый верхний уровень (`main` контекст), до блоков `events`, `http` и `stream` |
| **Зависание воркера / 100% CPU на один процесс** | Синхронный бесконечный цикл (`while(true)`), катастрофический возврат в регулярном выражении (ReDoS) | `top -b -n 1 -H -p $(pgrep -f "angie: worker")`<br>`gdb -p <worker_pid> -batch -ex "bt"` | Исключить ресурсоемкие регулярные выражения со сложными квантификаторами `(a+)+`; вынести тяжелые вычисления за пределы воркера |
| **`js exception: no memory`** | Переполнение пула памяти запроса или исчерпание лимита зоны `js_shared_dict_zone` | `grep "no memory" /var/log/angie/error.log` | Увеличить размер зоны `js_shared_dict_zone zone=name:<size>` или включить флаг вытеснения `eviction=lru` |
| **`subrequest() failed: 504 Gateway Timeout`** | Рекурсивный подзапрос сам к себе или зависание бэкенда во внутреннем `r.subrequest` | Проверить пути подзапросов в `r.subrequest` и директиву `subrequest_output_buffer_size` | Убедиться, что целевой `location` подзапроса помечен как `internal;` и не инициирует повторный вызов njs |
| **`Permission denied` при чтении JS-скриптов** | Рабочий процесс `angie` не имеет прав на чтение каталога `/etc/angie/scripts/` | `namei -l /etc/angie/scripts/router.js` | Выставить владельца `root:root` и права `0755` на каталоги и `0644` на файлы `.js` |
| **Блокировка `.so` библиотеки в Astra Linux** | Отсутствие валидной цифровой подписи библиотеки в режиме ЗПС (CSE) | `bsign -c /usr/lib/angie/modules/ngx_http_js_module.so` | Подписать библиотеку ключом организации через утилиту `bsign` или обновить официальный репозиторий Astra Linux |

### Детальная диагностика ошибок времени выполнения

При возникновении исключений njs записывает подробный стек вызовов в стандартный журнал ошибок веб-сервера.

Пример сообщения об ошибке в `/var/log/angie/error.log`:
```text
2026/10/14 18:22:10 [error] 41235#41235: *1482 js exception: TypeError: cannot convert undefined to object
    at validateApiKey (/etc/angie/scripts/security.js:8)
    at main (native)
```

Анализ и устранение:
1. Ошибка указывает на обращение к свойству переменной, имеющей значение `undefined` на строке 8 файла `/etc/angie/scripts/security.js`.
2. Перед чтением вложенных свойств необходимо проверять их существование через оператор опциональной последовательности (optional chaining `r.headersIn?.['x-api-key']`) или логическое И `r.headersIn && r.headersIn['x-api-key']`.
3. Для отладочного вывода значений в лог используйте методы `r.log('Debug value: ' + val)` или `r.warn()`, которые попадают в журнал без остановки конвейера обработки.

## Лучшие практики

1. **Принцип нулевого доверия к окружению (Least Privilege):** Каталоги со скриптами `/etc/angie/scripts/` должны принадлежать суперпользователю `root:root` с правами `0755`. Рабочий процесс `angie` должен иметь права исключительно на чтение (`0644`). Любая возможность записи в `.js`-файлы из веб-окружения представляет собой критическую уязвимость удаленного исполнения кода (RCE).
2. **Исключение блокирующих синхронных операций:** Время исполнения JavaScript-функции в `js_content` или `js_set` не должно превышать единиц миллисекунд. Для взаимодействия с сетевыми сервисами используйте только асинхронные методы `ngx.fetch()` с обязательным ограничением таймаутов (`js_fetch_timeout 3s;`).
3. **Безопасность регулярных выражений (ReDoS):** Никогда не применяйте непроверенные регулярные выражения с пересекающимися группировками на пользовательском вводе (например, `r.args` или заголовках). Движок njs не использует JIT для регулярных выражений, что делает его уязвимым к катастрофическому возврату (catastrophic backtracking).
4. **Оптимизация директивы `js_set`:** Функция, привязанная через `js_set`, вызывается при первом чтении переменной. Не помещайте в `js_set` тяжелые вычисления, если переменная используется только для условного логирования в `log_format`. Для многократно модифицируемых значений применяйте `js_var`.
5. **Тестирование в пайплайнах CI/CD:** Включайте валидацию синтаксиса скриптов в шаг проверки пайплайна развертывания (`angie -t` внутри контейнера или `njs -c`). Не допускайте попадания файлов с ошибками синтаксиса на рабочие серверы.
6. **Грамотная настройка зон памяти:** При использовании `js_shared_dict_zone` всегда задавайте лимит `timeout` и параметр `eviction=lru`. Без флага `eviction=lru` при исчерпании выделенного размера зоны сервер вернет ошибку `no memory`, что приведет к сбою авторизации или лимитирования запросов.
7. **Мониторинг исключений:** Настройте в SIEM / Prometheus-экспортере мониторинг логов `/var/log/angie/error.log` по маске `js exception:`. Всплеск таких сообщений свидетельствует о нарушении формата данных со стороны клиентов или багах в скриптах.

## Дополнительная информация

### Взаимосвязи в базе знаний

- [Установка Angie](./angie_installation.md) — базовые принципы управления пакетами, репозиториями и архитектура каталогов Angie.
- [Контроль доступа в Angie](./angie_access_control.md) — реализация авторизации через встроенные модули (`auth_request`, `allow`/`deny`, `satisfy`) и сравнение с подходом на njs.
- [Аутентификация через OIDC в Angie](./angie-oidc.md) — построение шлюзов Single Sign-On с валидацией токенов и перенаправлением на Identity Provider.
- [Переменные в Angie](./angie_variables.md) — системные переменные ядра, правила их интерполяции и оптимизация через хэш-таблицы.
- [Журналирование в Angie](./angie_logging.md) — интеграция динамических переменных njs в структуру `log_format` и передача в SIEM.
- [Балансировка и проксирование L4 Stream](./l4_balancing_and_proxying.md) — управление TCP/UDP потоками и расширенное использование `ngx_stream_js_module`.
- [Скриптовый модуль njs в Nginx](../Nginx/Core/nginx_njs_module.md) — концептуальные отличия и переносимость скриптов между Angie и Nginx.

### Официальные источники

- Официальная документация Angie: [Внешние модули: ngx_http_js_module](https://angie.software/ru/configuration/modules/external-modules/http_js/)
- Официальная документация Angie: [Внешние модули: ngx_stream_js_module](https://angie.software/ru/configuration/modules/external-modules/stream_js/)
- Официальное руководство по языку njs: [NJS Reference Manual](https://nginx.org/en/docs/njs/reference.html)
- Изменения и релизы модуля njs: [NJS Changes Log](https://nginx.org/en/docs/njs/changes.html)

## См. также

- [Контроль доступа в Angie](./angie_access_control.md)
- [Аутентификация через OIDC в Angie](./angie-oidc.md)
- [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)
- [Балансировка и проксирование L4 Stream](./l4_balancing_and_proxying.md)
- [Переменные в Angie](./angie_variables.md)
- [Журналирование в Angie](./angie_logging.md)