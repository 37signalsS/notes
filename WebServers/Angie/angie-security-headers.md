# Заголовки безопасности в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Заголовки безопасности (Security Headers)** — стандартизированные HTTP-заголовки ответа, передаваемые веб-сервером клиентскому браузеру для принудительного включения встроенных механизмов защиты: изоляции контекста выполнения, блокировки атак внедрения кода (XSS), предотвращения подмены интерфейса (Clickjacking), запрета несанкционированного MIME-сниффинга и принудительного шифрования сетевого канала.

**`add_header`** — базовая директива модуля `ngx_http_headers_filter_module` в веб-сервере Angie, добавляющая произвольные заголовки к формируемому HTTP-ответу. Поддерживает параметр `always`, гарантирующий отправку заголовка при любых статус-кодах ответа, включая ошибки (4xx и 5xx).

**HTTP Strict Transport Security (HSTS, RFC 6797)** — механизм принудительного перехода на защищенный протокол HTTPS. Инструктирует браузер автоматически преобразовывать все небезопасные HTTP-ссылки в HTTPS до выполнения сетевого запроса и запрещает пользователю игнорировать предупреждения о недействительных TLS-сертификатах.

**Content Security Policy (CSP, W3C CSP Level 3)** — декларативная политика безопасности, ограничивающая доверенные источники загрузки исполняемого кода, стилей, изображений, шрифтов, фреймов и сетевых соединений. Является фундаментальным средством защиты от межсайтового скриптинга (XSS), инъекций данных и вредоносных внедрений.

**Cross-Origin Isolation (COOP, COEP, CORP)** — группа современных спецификаций W3C (`Cross-Origin-Opener-Policy`, `Cross-Origin-Embedder-Policy`, `Cross-Origin-Resource-Policy`), изолирующая среду выполнения веб-страницы в отдельном адресном пространстве процесса ОС для нейтрализации атак по сторонним каналам утечки памяти (Spectre, Meltdown) и безопасного использования высокоточных API (`SharedArrayBuffer`, `performance.now()`).

**MIME-Sniffing (RFC 7231 / MIME Sniffing Standard)** — эвристический алгоритм браузера, пытающийся угадать реальный тип содержимого файла по его байтовому содержимому вопреки значению заголовка `Content-Type`. Блокируется директивой `X-Content-Type-Options: nosniff`.

**Clickjacking (UI Redressing)** — класс атак, при котором целевой сайт незаметно загружается внутри прозрачного элемента `<iframe>` стороннего ресурса, вынуждая пользователя совершать непреднамеренные действия. Предотвращается заголовком `X-Frame-Options` и директивой CSP `frame-ancestors`.

**Permissions-Policy** — спецификация W3C (пришедшая на смену `Feature-Policy`), предоставляющая сайту гранулярный контроль над доступом клиентского JavaScript к аппаратным и конфиденциальным интерфейсам браузера (камера, микрофон, геолокация, датчики движения, USB, платежные интерфейсы).

**Санитизация заголовков (`proxy_hide_header`, `fastcgi_hide_header`)** — механизм удаления специфических или конфликтующих HTTP-заголовков, сгенерированных upstream-серверами (Node.js, Go, Python, PHP-FPM), перед передачей ответа конечному клиенту для исключения дублирования политик безопасности.

---

## Архитектура и принцип работы

### 1. Жизненный цикл HTTP-ответа и модуль ngx_http_headers_filter_module

В архитектуре Angie добавление заголовков безопасности происходит на стадии исходящей фильтрации HTTP-ответов (`output filter chain`). За этот процесс отвечает встроенный модуль `ngx_http_headers_filter_module`.

```
[ Клиентский запрос ]
         │
         ▼
[ HTTP Core Engine / Location Match ]
         │
         ▼
[ Обработчик содержимого (Content Handler) ]
(Static file / proxy_pass / fastcgi_pass / return)
         │
         ▼
[ Формирование базовых заголовков ответа ]
         │
         ▼
[ ngx_http_headers_filter_module ] ◄─── add_header ... [always]
  • Проверка статус-кода ответа
  • Проверка директив add_header для текущего контекста
  • Вставка заголовков в цепочку буферов ответа
         │
         ▼
[ TLS Encryption & Network Output ]
```

Фильтр заголовков вызывается непосредственно перед отправкой заголовков в сетевой сокет:
1. Заголовки ответа формируются базовым обработчиком (чтение статического файла, генерация ответа приложением upstream или встроенная директива `return`).
2. Модуль заголовков проверяет статус-код сформированного ответа и флаг `always`.
3. Модуль определяет список применимых директив `add_header` в соответствии с жесткими правилами иерархического наследования Angie.
4. Вычисленные заголовки добавляются в память структуры HTTP-заголовков ответа (`ngx_http_headers_out_t`).

---

### 2. Механика наследования add_header и конфигурационная ловушка

Ключевая архитектурная особенность директивы `add_header` в Angie (унаследованная из ядра Nginx) заключается в правиле наследования блоков конфигурации:

> **Правило наследования:** Директивы `add_header` наследуются с предыдущего уровня конфигурации (например, с уровня `http` на уровень `server`, или с `server` на `location`) **только и исключительно в том случае, если на текущем уровне не объявлено ни одной директивы `add_header`**.

Если внутри дочернего блока `location` объявляется хотя бы один локальный заголовок (например, отладочный маркер или заголовок кэширования), **абсолютно все заголовки безопасности с уровней `http` и `server` аннулируются для этого `location`**:

```
+-----------------------------------------------------------------------+
| http {                                                                |
|     add_header X-Frame-Options "DENY" always;                         |
|     add_header X-Content-Type-Options "nosniff" always;               |
|                                                                       |
|     server {                                                          |
|         # [location /] не имеет своих add_header                      |
|         location / {                                                  |
|             # -> НАСЛЕДУЮТСЯ: X-Frame-Options, X-Content-Type-Options |
|         }                                                             |
|                                                                       |
|         # [location /api/] определяет локальный заголовок             |
|         location /api/ {                                              |
|             add_header X-Custom-Trace $request_id;                    |
|             # -> КАТАСТРОФА: X-Frame-Options и X-Content-Type-Options |
|             #    ПОЛНОСТЬЮ СБРОШЕНЫ И НЕ ОТПРАВЛЯЮТСЯ!               |
|         }                                                             |
|     }                                                                 |
| }                                                                     |
+-----------------------------------------------------------------------+
```

#### Архитектурные шаблоны решения проблемы наследования:

1. **Паттерн модульных сниппетов (Snippets Include — промышленный стандарт):**
   Базовый набор заголовков выносится в отдельный файл (например, `/etc/angie/snippets/security-headers.conf`). Этот файл принудительно подключается через директиву `include` в контекст каждого `server`, а также во все `location`, где требуется добавить специфические локальные заголовки.
2. **Паттерн условных переменных через `map`:**
   Значения динамических заголовков формируются на уровне `http` через директиву `map` в переменные. На уровне `http` или `server` объявляется единый набор `add_header`, ссылающийся на эти переменные. Если переменная вычисляется в пустую строку `""`, Angie автоматически опускает отправку данного заголовка без сброса наследования.

---

### 3. Детальная семантика флага always

Поведение директивы `add_header` жестко зависит от наличия или отсутствия завершающего параметра `always`:

| Режим директивы | Статусы ответа, для которых заголовок ОТПРАВЛЯЕТСЯ | Статусы ответа, для которых заголовок ТЕРЯЕТСЯ |
| :--- | :--- | :--- |
| **`add_header Name Value;`** *(по умолчанию)* | `200`, `201`, `204`, `206`, `301`, `302`, `303`, `304`, `307`, `308` | `400`, `401`, `403`, `404`, `405`, `429`, `500`, `502`, `503`, `504` |
| **`add_header Name Value always;`** | **Все без исключения:** 2xx, 3xx, 4xx, 5xx | *Нет (отправляется всегда)* |

#### Почему флаг `always` обязателен для безопасности:
- **Уязвимости на страницах ошибок 4xx/5xx:** Если злоумышленник обращается к несуществующему ресурсу (`404 Not Found`) или вызывает ошибку сервера (`500 Internal Server Error`), веб-сервер без флага `always` отдаст тело ошибки без заголовков `X-Frame-Options` и `Content-Security-Policy`. В результате страница ошибки может быть встроена во фрейм на вредоносном ресурсе для проведения Clickjacking-атаки или фишинга.
- **HSTS на ошибках авторизации 401/403:** Клиенты, получающие ошибку доступа по незащищенному соединению или в процессе отладки, обязаны сохранять флаг принудительного HTTPS для домена, что невозможно без отправки `Strict-Transport-Security` на кодах `401` и `403`.

---

### 4. Взаимодействие с upstream и FastCGI: дедупликация заголовков

Веб-сервер Angie функционирует как обратный прокси (`reverse proxy`) или шлюз перед приложениями (Go, Node.js, Python, Java, PHP-FPM). Приложения часто пытаются самостоятельно генерировать заголовки безопасности.

**Механика сложения заголовков:**
Директива `add_header` не заменяет заголовки upstream-бэкенда, а **добавляет** новую строку в HTTP-пакет. Если бэкенд отдал заголовок `X-Frame-Options: SAMEORIGIN`, а Angie выполнил `add_header X-Frame-Options "DENY" always;`, клиент получит ответ с двумя противоречивыми заголовками:

```http
HTTP/1.1 200 OK
Server: Angie
X-Frame-Options: SAMEORIGIN
X-Frame-Options: DENY
```

#### Последствия дублирования:
- **Для `X-Frame-Options`:** RFC 7034 запрещает несколько значений; большинство браузеров переходят в режим сбоя и либо полностью блокируют ресурс, либо игнорируют защиту.
- **Для `Content-Security-Policy`:** Браузер применяет пересечение политик (обе политики должны быть удовлетворены одновременно), что приводит к внезапной блокировке легитимных компонентов сайта.
- **Для `Access-Control-Allow-Origin` (CORS):** Браузер аннулирует ответ со статусом `CORS error`.

#### Решение на уровне архитектуры:
В архитектуре SRE/DevOps веб-сервер Angie выступает как Единый источник правды (SSoT) для периметра безопасности. Для исключения конфликтов заголовки бэкенда принудительно вырезаются директивами санитизации:

```nginx
# Очистка заголовков безопасности от проксируемого HTTP-бэкенда
proxy_hide_header X-Frame-Options;
proxy_hide_header X-Content-Type-Options;
proxy_hide_header Content-Security-Policy;
proxy_hide_header X-Permitted-Cross-Domain-Policies;

# Очистка заголовков от FastCGI/PHP-FPM
fastcgi_hide_header X-Frame-Options;
fastcgi_hide_header X-Content-Type-Options;
fastcgi_hide_header Content-Security-Policy;
```

---

### 5. Матрица современных заголовков безопасности

| Заголовок безопасности | Рекомендуемое эталонное значение | Назначение и предотвращаемые угрозы | Статус (2026) |
| :--- | :--- | :--- | :--- |
| **`Strict-Transport-Security`** | `max-age=31536000; includeSubDomains; preload` | Принудительный HTTPS, предотвращение SSL-Stripping и MITM. | Обязательный (RFC 6797) |
| **`X-Content-Type-Options`** | `nosniff` | Блокировка MIME-сниффинга браузером. | Обязательный |
| **`X-Frame-Options`** | `DENY` или `SAMEORIGIN` | Защита от Clickjacking (для устаревших браузеров без поддержки CSP). | Сохраняется для совместимости (RFC 7034) |
| **`Content-Security-Policy`** | `default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none';` | Полная изоляция источников загрузки контента, защита от XSS и инъекций. | Критический стандарт (W3C Level 3) |
| **`Referrer-Policy`** | `strict-origin-when-cross-origin` | Контроль утечки чувствительных URI-параметров в заголовке `Referer`. | Обязательный стандарт |
| **`Permissions-Policy`** | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` | Отключение неиспользуемых аппаратных API устройства пользователя. | Рекомендуемый (W3C) |
| **`Cross-Origin-Opener-Policy`** | `same-origin` | Изоляция контекста браузера (защита от Spectre и доступа через `window.opener`). | Высокий уровень защиты |
| **`Cross-Origin-Embedder-Policy`** | `require-corp` | Требование явного согласия сторонних ресурсов на встраивание. | Высокий уровень защиты |
| **`Cross-Origin-Resource-Policy`** | `same-origin` | Запрет сторонним сайтам считывать данные через теги `<script>`, `<img>`. | Высокий уровень защиты |
| **`X-Permitted-Cross-Domain-Policies`** | `none` | Запрет загрузки кросс-доменных политик клиентами Adobe Flash / PDF. | Харденинг периметра |
| **`Server`** | *(Удаляется или маскируется)* | Сокрытие типа и точной версии веб-сервера через `server_tokens off;`. | SRE-стандарт |

#### Устаревшие и опасные заголовки (не использовать):
- **`X-XSS-Protection`**: Устаревший заголовок. Значение `1; mode=block` признано небезопасным во всех современных движках (Chromium, Gecko, WebKit), так как сам эвристический XSS-фильтр создавал уязвимости утечки данных и отказ в обслуживании (Side-Channel Leaks). В современных конфигурациях либо не выставляется вообще, либо принудительно отключается: `add_header X-XSS-Protection "0" always;`.
- **`Public-Key-Pins` (HPKP)**: Полностью упразднен (Deprecated). Использование создавало высокий риск безвозвратного отказа в обслуживании (самоблокировки сайтов при утере приватных ключей резервных сертификатов).
- **`Expect-CT`**: Упразднен в связи с повсеместным внедрением обязательного Certificate Transparency в TLS-сертификатах на уровне браузеров.

---

## Практические сценарии

### Сценарий 1: Эталонный модульный сниппет заголовков безопасности

Создание эталонного подключаемого конфигурационного файла для исключения дублирования и предотвращения сброса наследования `add_header`.

#### 1. Создание каталога и эталонного файла конфигурации

Создайте файл `/etc/angie/snippets/security-headers.conf`:

```nginx
# ==============================================================================
# /etc/angie/snippets/security-headers.conf
# Эталонный набор заголовков безопасности для промышленного веб-сервера Angie
# ==============================================================================

# 1. HSTS (Принудительный HTTPS на 1 год с поддоменами)
# ВНИМАНИЕ: директива активна только для HTTPS соединений
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

# 2. Запрет MIME-sniffing
add_header X-Content-Type-Options "nosniff" always;

# 3. Защита от Clickjacking для устаревших клиентов (дублирует frame-ancestors)
add_header X-Frame-Options "SAMEORIGIN" always;

# 4. Контроль утечки путей в Referer
add_header Referrer-Policy "strict-origin-when-cross-origin" always;

# 5. Ограничение доступа к аппаратным API браузера
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()" always;

# 6. Изоляция контекста браузера (Cross-Origin Protection)
add_header Cross-Origin-Opener-Policy "same-origin" always;
add_header Cross-Origin-Resource-Policy "same-origin" always;

# 7. Запрет кросс-доменных политик документов
add_header X-Permitted-Cross-Domain-Policies "none" always;

# 8. Отключение устаревшего уязвимого аудитора XSS
add_header X-XSS-Protection "0" always;
```

#### 2. Подключение сниппета в конфигурацию виртуального сервера

Отредактируйте `/etc/angie/conf.d/example.com.conf`:

```nginx
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name example.com www.example.com;

    # Скрытие версии веб-сервера
    server_tokens off;

    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    # Базовые заголовки на уровне виртуального хоста
    include /etc/angie/snippets/security-headers.conf;

    # Базовая политика CSP для веб-приложения
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self';" always;

    root /var/www/example.com/public;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # В location с локальным add_header ОБЯЗАТЕЛЬНО повторно подключаем сниппет!
    location /download/ {
        # Локальный заголовок для принудительного скачивания
        add_header Content-Disposition "attachment" always;

        # Защита от сброса заголовков безопасности:
        include /etc/angie/snippets/security-headers.conf;

        alias /var/storage/downloads/;
    }
}
```

---

### Сценарий 2: Конфигурация для строгого API Gateway (JSON / gRPC)

Для REST/JSON API и микросервисных шлюзов веб-страницы не отдаются, поэтому требования к заголовкам безопасности отличаются: полное подавление фрейминга, блокировка выполнения любых клиентских скриптов и строгая изоляция данных.

Файл конфигурации `/etc/angie/conf.d/api.example.com.conf`:

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name api.example.com;

    server_tokens off;

    ssl_certificate /etc/ssl/certs/api.example.com.crt;
    ssl_certificate_key /etc/ssl/private/api.example.com.key;

    # Очистка заголовков upstream-микросервисов перед добавлением эталонных
    proxy_hide_header X-Frame-Options;
    proxy_hide_header X-Content-Type-Options;
    proxy_hide_header Content-Security-Policy;
    proxy_hide_header Strict-Transport-Security;

    # Строгие заголовки безопасности для API
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "no-referrer" always;

    # Максимально жесткий CSP: запрет загрузки любых ресурсов и выполнения скриптов
    add_header Content-Security-Policy "default-src 'none'; frame-ancestors 'none'; sandbox;" always;

    # Полная изоляция от сторонних источников
    add_header Cross-Origin-Resource-Policy "same-origin" always;
    add_header Cross-Origin-Opener-Policy "same-origin" always;

    # Кэширование API-ответов по умолчанию запрещено
    add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate" always;
    add_header Pragma "no-cache" always;

    location / {
        proxy_pass http://api_backend_pool;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

### Сценарий 3: Динамический CSP Nonce в SPA на базе встроенной переменной $request_id

Для веб-приложений (React, Vue, Angular, SSR), требующих выполнения встроенных скриптов без небезопасной директивы `'unsafe-inline'`, применяется механизм криптографических одноразовых чисел (**Nonce**). Angie генерирует уникальный 32-значный шестнадцатеричный идентификатор в переменной `$request_id`, который подставляется в CSP и передается бэкенду.

```nginx
server {
    listen 443 ssl;
    server_name portal.example.com;

    server_tokens off;

    ssl_certificate /etc/ssl/certs/portal.crt;
    ssl_certificate_key /etc/ssl/private/portal.key;

    # Передача сгенерированного nonce приложению через HTTP-заголовок
    proxy_set_header X-Request-ID $request_id;

    # Очистка CSP от upstream
    proxy_hide_header Content-Security-Policy;

    # Базовые заголовки
    include /etc/angie/snippets/security-headers.conf;

    # CSP с динамическим Nonce для скриптов и стилей
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'nonce-$request_id'; style-src 'self' 'nonce-$request_id'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self';" always;

    location / {
        proxy_pass http://portal_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Статические ассеты (JS/CSS бандлы, картинки) не требуют генерации dynamic CSP
    location /static/ {
        alias /var/www/portal/static/;
        expires 30d;
        add_header Cache-Control "public, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Access-Control-Allow-Origin "*" always;
    }
}
```

---

### Сценарий 4: Поэтапное внедрение CSP (Report-Only) со встроенным коллектором отчетов

Внедрение строгой политики CSP в работающем сервисе несет риск нарушения функциональности сайта. Для безопасного внедрения используется режим отчетов `Content-Security-Policy-Report-Only` в связке с локальным эндпоинтом Angie для сбора JSON-отчетов о нарушениях без использования внешних облачных сервисов.

#### 1. Настройка формата логов и внутреннего эндпоинта сбора отчетов

В файле `/etc/angie/conf.d/csp-reporting.conf`:

```nginx
# Формат журнала для регистрации нарушений CSP в формате JSON
log_format csp_reports escape=json '{'
    '"time_local":"$time_local",'
    '"remote_addr":"$remote_addr",'
    '"http_user_agent":"$http_user_agent",'
    '"request_body":"$request_body"'
'}';

server {
    listen 443 ssl;
    server_name app.example.com;

    server_tokens off;

    ssl_certificate /etc/ssl/certs/app.crt;
    ssl_certificate_key /etc/ssl/private/app.key;

    include /etc/angie/snippets/security-headers.conf;

    # Включение CSP в режиме ТЕСТИРОВАНИЯ (браузер выполняет код, но рапортует об ошибках)
    add_header Content-Security-Policy-Report-Only "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; report-uri /api/csp-report-endpoint;" always;

    location / {
        proxy_pass http://app_upstream;
    }

    # Локальный коллектор отчетов о нарушениях (без отправки в облачные сервисы)
    location = /api/csp-report-endpoint {
        # Прием только метода POST от браузеров
        limit_except POST {
            deny all;
        }

        # Буферизация и сброс тела отчета в системный лог
        client_body_buffer_size 128k;
        client_max_body_size 256k;
        
        access_log /var/log/angie/csp_violations.log csp_reports;

        # Возврат немедленного ответа браузеру без передачи бэкенду
        return 204;
    }
}
```

#### 2. Мониторинг поступающих отчетов администратором

```bash
# Мониторинг нарушений CSP в реальном времени через jq
tail -f /var/log/angie/csp_violations.log | jq .
```

---

### Сценарий 5: Санитизация бэкендов в режиме Reverse Proxy

В инфраструктурах с разнородными upstream-приложениями бэкенды могут отправлять собственные небезопасные заголовки или раскрывать детали стека (`X-Powered-By: Express`, `Server: Werkzeug/3.0`).

Конфигурация санитизации и переопределения в `/etc/angie/conf.d/secure-proxy.conf`:

```nginx
server {
    listen 443 ssl;
    server_name secure.example.com;

    server_tokens off;

    ssl_certificate /etc/ssl/certs/secure.crt;
    ssl_certificate_key /etc/ssl/private/secure.key;

    # 1. Подавление идентификационных и устаревших заголовков бэкенда
    proxy_hide_header Server;
    proxy_hide_header X-Powered-By;
    proxy_hide_header X-AspNet-Version;
    proxy_hide_header X-Runtime;

    # 2. Подавление заголовков безопасности upstream для устранения коллизий
    proxy_hide_header X-Frame-Options;
    proxy_hide_header X-Content-Type-Options;
    proxy_hide_header Content-Security-Policy;
    proxy_hide_header Strict-Transport-Security;
    proxy_hide_header Referrer-Policy;
    proxy_hide_header Permissions-Policy;

    # 3. Принудительное наложение эталонных заголовков безопасности шлюза Angie
    include /etc/angie/snippets/security-headers.conf;

    location / {
        proxy_pass http://internal_app_node;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

### Сценарий 6: Проверка, валидация и CI/CD автоматизация аудита заголовков

#### 1. Инспекция заголовков через curl

Проверка ответа сервера на успешном запросе:

```bash
curl -sI https://example.com/
```
```http
# → HTTP/2 200 
# → server: Angie
# → date: Wed, 14 Oct 2026 17:40:00 GMT
# → content-type: text/html; charset=UTF-8
# → strict-transport-security: max-age=31536000; includeSubDomains
# → x-content-type-options: nosniff
# → x-frame-options: SAMEORIGIN
# → referrer-policy: strict-origin-when-cross-origin
# → permissions-policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()
# → cross-origin-opener-policy: same-origin
# → cross-origin-resource-policy: same-origin
# → x-permitted-cross-domain-policies: none
# → x-xss-protection: 0
```

Проверка отправки заголовков на ошибке 404 (валидация директивы `always`):

```bash
curl -sI https://example.com/nonexistent-test-path-404 | grep -Ei "HTTP/|strict-transport|x-content-type|x-frame"
```
```http
# → HTTP/2 404 
# → strict-transport-security: max-age=31536000; includeSubDomains
# → x-content-type-options: nosniff
# → x-frame-options: SAMEORIGIN
```

Проверка отсутствия версионного баннера в заголовке `Server`:

```bash
curl -sI https://example.com/ | grep -i "^server:"
```
```http
# → server: Angie
```

#### 2. Bash-скрипт для пайплайна автоматического тестирования в CI/CD

Скрипт проверки заголовков безопасности для включения в сборочные линии (GitLab CI / Jenkins / локальный запуск SRE):

```bash
#!/usr/bin/env bash
# ==============================================================================
# verify-security-headers.sh — Валидация заголовков безопасности веб-сервера
# ==============================================================================
set -euo pipefail

TARGET_URL="${1:-https://127.0.0.1}"
FAILED=0

echo "[*] Тестирование целевого хоста: ${TARGET_URL}"

# Получение заголовков ответа
HEADERS=$(curl -k -sI "${TARGET_URL}")

# Функция валидации наличия заголовка
check_header() {
    local header_name="$1"
    local expected_regex="$2"
    
    if echo "${HEADERS}" | grep -Ei "^${header_name}:" | grep -Eqi "${expected_regex}"; then
        echo "  [OK] ${header_name} присутствует и корректен."
    else
        echo "  [FAIL] ${header_name} отсутствует или не соответствует шаблону: ${expected_regex}"
        FAILED=1
    fi
}

check_header "Strict-Transport-Security" "max-age=[0-9]+"
check_header "X-Content-Type-Options" "nosniff"
check_header "X-Frame-Options" "(DENY|SAMEORIGIN)"
check_header "Referrer-Policy" "strict-origin"
check_header "Permissions-Policy" "camera="

# Проверка сокрытия версии в заголовке Server
if echo "${HEADERS}" | grep -Ei "^Server:" | grep -Eqi "[0-9]+\.[0-9]+"; then
    echo "  [FAIL] Заголовок Server раскрывает номер версии веб-сервера!"
    FAILED=1
else
    echo "  [OK] Заголовок Server не содержит номера версии."
fi

if [ ${FAILED} -ne 0 ]; then
    echo "[ERROR] Проверка заголовков безопасности завершилась с ошибками!"
    exit 1
fi

echo "[SUCCESS] Все обязательные заголовки безопасности подтверждены."
exit 0
```

---

## Диагностика и устранение неполадок

### Сводная таблица типовых неисправностей

| Симптом / Ошибка | Первопричина проблемы | Диагностика | Метод исправления |
| :--- | :--- | :--- | :--- |
| **Заголовки безопасности отсутствуют в одном конкретном `location`** (например, `/api/` или `/downloads/`). | **Ловушка наследования `add_header`:** внутри данного `location` объявлен локальный `add_header`, аннулировавший заголовки родительского уровня `server`/`http`. | `curl -sI https://example.com/api/test`<br>Сравнить вывод с `https://example.com/`. | Добавить `include /etc/angie/snippets/security-headers.conf;` непосредственно внутрь дочернего блока `location`. |
| **Браузер выводит ошибку: `Multiple values for X-Frame-Options` или дублирующийся CSP.** | Заголовок генерируется одновременно и приложением бэкенда (Node.js/Django), и веб-сервером Angie. | `curl -sI https://example.com/ \| grep -i x-frame`<br>Обнаружено две строки заголовка. | В блоке `location` обратного прокси добавить `proxy_hide_header X-Frame-Options;` (или CSP). |
| **Заголовки безопасности пропадают на страницах ошибок 404, 500, 502.** | В директивах `add_header` пропущен обязательный параметр `always`. | `curl -sI https://example.com/nonexistent_path`<br>Проверить заголовки ответа 404. | Дописать ключевое слово `always` в конец каждой директивы `add_header`: `add_header X-Frame-Options "DENY" always;`. |
| **Браузер блокирует скрипты: `Refused to execute inline script because it violates CSP`.** | Политика CSP запрещает выполнение inline-скриптов (`<script>...</script>`) без указания хэша или nonce. | Консоль разработчика браузера (F12 -> Console) фиксирует блокировку ресурса. | Перевести CSP в режим `Content-Security-Policy-Report-Only`, выявить все inline-скрипты, внедрить Nonce (`'nonce-$request_id'`) или вынести код во внешние `.js` файлы. |
| **Внутренний портал не может встроить сервис в `<iframe>` (`Refused to display in a frame`).** | Выставлен заголовок `X-Frame-Options: DENY` или `SAMEORIGIN`, запрещающий фрейминг со сторонних доверенных доменов. | Ошибка в консоли браузера: `Refused to display ... because it set 'X-Frame-Options' to 'SAMEORIGIN'`. | Использовать директиву CSP: `frame-ancestors 'self' https://portal.corp.internal;`. Обратите внимание: `X-Frame-Options` не поддерживает список нескольких доменов. |
| **Сайт или поддомены стали недоступны после включения HSTS с `includeSubDomains`.** | В `Strict-Transport-Security` была добавлена директива `includeSubDomains`, но один из внутренних поддоменов не имеет валидного TLS-сертификата. | Браузер отказывается открывать поддомен с ошибкой `NET::ERR_CERT_COMMON_NAME_INVALID` без кнопки пропуска. | Для временного исправления: на основном домене временно отдать `Strict-Transport-Security "max-age=0" always;` и зайти на него пользователем. Для продакшена: выпустить валидный Wildcard-сертификат перед добавлением `includeSubDomains`. |
| **Шрифты или картинки не загружаются со сторонних доменов (`Blocked by CORS / CORP`).** | Заголовок `Cross-Origin-Resource-Policy: same-origin` или строгий CSP блокирует загрузку статики. | Консоль браузера: `Cross-Origin Read Blocking (CORB)` или `CORP violation`. | Для CDN-локаций со статическими ресурсами выставить `Cross-Origin-Resource-Policy "cross-origin" always;` и скорректировать директивы CSP `img-src` / `font-src`. |
| **Сканеры безопасности видят версию сервера (`Server: Angie/1.12.0`).** | Не отключен вывод версии в глобальном контексте. | `curl -sI https://example.com/ \| grep -i server` показывает версию. | В блоке `http` файла `/etc/angie/angie.conf` прописать `server_tokens off;` и выполнить `angie -s reload`. |

---

### Пошаговая диагностика сбоев заголовков в CLI

#### Шаг 1: Проверка синтаксиса и активной конфигурации сервера

Перед применением любых изменений обязательна валидация конфигурации Angie:

```bash
sudo angie -t
```
```
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
```

Вывод полной развернутой конфигурации для выявления скрытых конфликтов и забытых директив `add_header`:

```bash
sudo angie -T | grep -En "add_header|proxy_hide_header"
```

#### Шаг 2: Проверка передачи сырых HTTP-заголовков через сокет

Диагностика ответа без искажения браузером и локальными кэшами:

```bash
curl -vk --resolve example.com:443:127.0.0.1 https://example.com/ -o /dev/null
```

#### Шаг 3: Проверка коллизий upstream-бэкенда

Выполните прямой запрос к бэкенду в обход прокси, чтобы увидеть, какие заголовки генерирует само приложение:

```bash
curl -sI http://127.0.0.1:8080/ | grep -Ei "x-frame|content-security|strict-transport"
```

Если бэкенд возвращает свои заголовки, убедитесь, что в соответствующем блоке `location` веб-сервера Angie присутствуют директивы `proxy_hide_header` для каждого из них.

---

## Лучшие практики

### 1. Архитектурный чек-лист для SRE и системных администраторов

- [ ] **Всегда использовать флаг `always`:** Каждая директива `add_header`, задающая параметры безопасности, должна заканчиваться параметром `always`. Исключений нет.
- [ ] **Модульность через сниппеты:** Выносите базовые заголовки в единый файл `/etc/angie/snippets/security-headers.conf`. Никогда не копируйте строки `add_header` вручную по десяткам файлов `server.conf`.
- [ ] **Защита дочерних `location`:** Если в `location` требуется задать хотя бы один кастомный заголовок (`add_header`), первой строкой внутри этого `location` обязательно включайте `include /etc/angie/snippets/security-headers.conf;`.
- [ ] **Централизованная санитизация прокси:** Всегда отключайте заголовки безопасности upstream-приложений директивой `proxy_hide_header`, гарантируя роль Angie как единой точки применения политик безопасности (SSoT).
- [ ] **Скрытие версий ПО:** Держите директиву `server_tokens off;` включенной на уровне контекста `http`.
- [ ] **Поэтапный ввод HSTS (Staged Rollout):**
  - *Этап 1 (Тестирование):* `max-age=300` (5 минут) без `includeSubDomains`.
  - *Этап 2 (Стабилизация):* `max-age=86400` (1 день).
  - *Этап 3 (Продакшен):* `max-age=31536000` (1 год) с добавлением `includeSubDomains` (только после аудита всех поддоменов!).
  - *Этап 4 (Preload):* Включение директивы `preload` и подача заявки в список Chrome HSTS Preload только при 100% готовности поддерживать постоянный HTTPS без возможности отката.
- [ ] **Поэтапный ввод CSP:** Никогда не включайте строгий блокирующий CSP в продакшене без предварительного тестирования через `Content-Security-Policy-Report-Only` и анализа логов нарушений минимум в течение 2–4 недель.
- [ ] **Запрет `X-XSS-Protection: 1; mode=block`:** Не используйте этот заголовок в современных конфигурациях. Задавайте `add_header X-XSS-Protection "0" always;` во избежание эксплуатации XSS-аудитора браузера.
- [ ] **Автоматизация проверок в CI/CD:** Интегрируйте вызов проверочного скрипта с `curl` в пайплайны развертывания инфраструктуры после перезагрузки конфигурации (`angie -s reload`).

---

## Дополнительная информация

### Официальные спецификации и стандарты
*   **RFC 6797** — HTTP Strict Transport Security (HSTS).
*   **RFC 7034** — HTTP Header Field X-Frame-Options.
*   **RFC 7231** — Hypertext Transfer Protocol (HTTP/1.1): Semantics and Content.
*   **W3C Content Security Policy Level 3** — Спецификация декларативных политик CSP.
*   **W3C Referrer Policy** — Спецификация управления заголовком Referer.

### См. также в базе знаний
*   **[Минимальная продакшен-конфигурация Angie](./angie-baseline-config.md)** — базовый каркас веб-сервера, контексты конфигурации и процессная модель.
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — криптографические протоколы TLS 1.2/1.3, HTTP/3 (QUIC), kTLS, OCSP Stapling и защита handshake.
*   **[CORS в Angie](./angie-cors.md)** — реализация Cross-Origin Resource Sharing, обработка preflight-запросов и защита API.
*   **[Обратный прокси в Angie](./angie_reverse_proxy.md)** — проксирование трафика, буферизация, настройка заголовков upstream и таймауты.
*   **[Укрепление безопасности HTTP (Test Hardening)](../../Networking/Protocols/HTTP/http_security_hardening.md)** — комплексная защита веб-протоколов, защита от Request Smuggling и атак замедленного типа (Slowloris).
*   **[Заголовки безопасности фронтенда (CI/CD)](../../CI-CD/Frontend_CI_CD/frontend_security_headers.md)** — практики аудита и валидации клиентских заголовков в автоматизированных сборочных линиях.