# Редиректы в Nginx: proxy_redirect, absolute_redirect, server_name_in_redirect, port_in_redirect

**Актуально для:** Nginx 1.26+ (OSS/Plus) / 1.28+ (Mainline), Angie 1.6+ / 1.12.x

---

## Определения

**Редирект (HTTP Redirection)** — механизм протокола HTTP, при котором сервер сообщает клиенту (браузеру, API-клиенту, CLI-утилите) о необходимости выполнить повторный запрос по новому адресу. Редирект возвращает код статуса группы `3xx` и заголовок `Location` с целевым URI.
- `301 Moved Permanently` — постоянный редирект с кэшированием в клиенте; исторически многие клиенты принудительно преобразуют метод запроса в `GET` (RFC 7231).
- `302 Found` — временный редирект; аналогично 301, клиенты часто нелегитимно мутируют метод `POST` в `GET`.
- `303 See Other` — временный редирект, стандартизированный для реализации паттерна POST-Redirect-GET; клиент гарантированно выполняет повторный запрос методом `GET`.
- `307 Temporary Redirect` — временный редирект, строго предписывающий клиенту сохранить исходный HTTP-метод и тело запроса без изменений (RFC 7231 / RFC 9110).
- `308 Permanent Redirect` — постоянный редирект с кэшированием, строго сохраняющий HTTP-метод и тело запроса (RFC 7538 / RFC 9110).

**Заголовок Location** — HTTP-заголовок ответа сервера, указывающий целевой URI перенаправления. Согласно современным стандартам RFC 7231 (§7.1.2) и RFC 9110 (§10.2.2), заголовок `Location` может содержать как абсолютный URI (`https://example.com/login`), так и относительный путь (`/login` или `../auth`).

**Заголовок Refresh** — нестандартный, но широко поддерживаемый HTTP-заголовок ответа (аналог `<meta http-equiv="Refresh">`), задающий задержку в секундах и целевой URL (например, `Refresh: 0; url=http://internal-app:8080/auth`). Обрабатывается модулем `ngx_http_proxy_module` наряду с `Location`.

**proxy_redirect** — директива модуля `ngx_http_proxy_module`, предназначенная для инспекции и модификации (поиска и замены) текста в заголовках `Location` и `Refresh` ответов, полученных от **проксируемых серверов (апстримов)**. Предотвращает утечку внутренних IP-адресов, портов и закрытых доменных имен апстримов во внешнюю сеть. Синтаксис: `proxy_redirect default;`, `proxy_redirect off;`, `proxy_redirect redirect replacement;` или регулярные выражения `proxy_redirect ~regex replacement;`. Значение по умолчанию: `proxy_redirect default;`.

**absolute_redirect** — директива модуля `ngx_http_core_module` (появилась в Nginx 1.11.8), управляющая форматом редиректов, **издаваемых непосредственно самим Nginx** (директивы `return 3xx`, `error_page 3xx`, автогенерация редиректа со слэшем для каталогов). При значении `off` Nginx генерирует относительные заголовки `Location` (`Location: /path/`), устраняя проблемы подмены протокола HTTP/HTTPS при терминации TLS на внешнем шлюзе. Значение по умолчанию: `on`.

**server_name_in_redirect** — директива модуля `ngx_http_core_module`, определяющая имя хоста, подставляемое Nginx в абсолютные редиректы собственного производства. При `off` (по умолчанию) Nginx берет хост из клиентского заголовка запроса `Host`. При `on` Nginx всегда подставляет первое имя, объявленное в директиве `server_name` текущего виртуального хоста.

**port_in_redirect** — директива модуля `ngx_http_core_module`, управляющая включением номера сетевого порта в абсолютные редиректы, генерируемые Nginx. При `on` (по умолчанию) Nginx добавляет порт текущего соединения (если он отличается от стандартных 80/443). При `off` номер порта никогда не включается в заголовок `Location`.

**Редирект от апстрима (Upstream Redirect)** — редирект, сформированный логикой внутреннего приложения (FastCGI, WSGI, Node.js, Go, Java-бэкенд). Nginx лишь пропускает ответ через свой конвейер и может модифицировать его заголовки директивой `proxy_redirect`.

**Редирект Nginx (Core Redirect)** — редирект, сгенерированный самим веб-сервером Nginx до обращения к бэкенду или при локальной обработке (завершающий слэш директории, `return 301/302`, `rewrite ... redirect|permanent`). Контролируется исключительно директивами `absolute_redirect`, `server_name_in_redirect` и `port_in_redirect`.

**Цикл редиректов (Redirect Loop / ERR_TOO_MANY_REDIRECTS)** — критическая аномалия маршрутизации, при которой клиент бесконечно перенаправляется между двумя или более URL (например, внешний Nginx с принудительным HTTPS перенаправляет на защищенный порт, а бэкенд за ним не видит TLS-терминации и возвращает редирект обратно на HTTP).

---

## Базовые концепции и архитектура

### Два независимых слоя редиректов в архитектуре Reverse Proxy

Главный источник конфигурационных ошибок системных администраторов и инженеров эксплуатации — смешение двух независимых слоев генерации редиректов. Nginx функционирует одновременно как HTTP-сервер (ядро `ngx_http_core_module`) и как обратный прокси-сервер (`ngx_http_proxy_module`). Каждому из этих состояний соответствует свой набор директив:

| Параметр | Редирект от апстрима (Upstream Layer) | Редирект от Nginx (Core Layer) |
| :--- | :--- | :--- |
| **Источник генерации** | Бэкенд-сервис (Go, Python, Java, PHP-FPM, Keycloak, Grafana) | Ядро веб-сервера Nginx (`ngx_http_core_module`, `ngx_http_rewrite_module`) |
| **Управляющие директивы** | `proxy_redirect` | `absolute_redirect`, `server_name_in_redirect`, `port_in_redirect` |
| **Триггеры возникновения** | Логика аутентификации приложения, сброс сессии, POST-Redirect-GET, маршрутизация микросервисов | Обращение к директории без слеша (`/docs` → `/docs/`), директивы `return 301/302`, `rewrite ... redirect` |
| **Типичные дефекты** | Утечка внутреннего адреса кластера (`Location: http://10.244.2.15:8080/auth`), поломка путей при strip-prefix | Принудительный даунгрейд схемы на HTTP при SSL-терминации, утечка нестандартного порта прокси (`:8443`) |
| **Изоляция директив** | Директивы ядра (`absolute_redirect`) не влияют на заголовки бэкенда | `proxy_redirect` полностью игнорирует редиректы, созданные директивами `return` или ядром Nginx |

### Схема прохождения трафика и обработка заголовка Location

```text
Сценарий 1: Редирект генерирует апстрим (обработка через proxy_redirect)
═════════════════════════════════════════════════════════════════════════
[Клиент]               [Nginx Edge Reverse Proxy]                 [Upstream Service]
   │                               │                                     │
   │ 1. GET https://site.ru/admin  │                                     │
   │──────────────────────────────>│ 2. GET http://10.0.0.12:8080/       │
   │                               │────────────────────────────────────>│
   │                               │                                     │
   │                               │ 3. HTTP/1.1 302 Found               │
   │                               │    Location: http://10.0.0.12:8080/login
   │                               │<────────────────────────────────────│
   │                               │                                     │
   │                               │ [ngx_http_proxy_module]             │
   │                               │ Применение: proxy_redirect          │
   │                               │ http://10.0.0.12:8080/ -> /admin/   │
   │                               │ (или https://site.ru/admin/)        │
   │ 4. HTTP/1.1 302 Found         │                                     │
   │    Location: /admin/login     │                                     │
   │<──────────────────────────────│                                     │

Сценарий 2: Редирект генерирует ядро Nginx (обработка через absolute_redirect)
═════════════════════════════════════════════════════════════════════════════
[Клиент]               [Nginx Edge Reverse Proxy]                 [Upstream / Файлы]
   │                               │                                     │
   │ 1. GET https://site.ru/static │                                     │
   │──────────────────────────────>│ [ngx_http_core_module]             │
   │                               │ Обнаружен каталог /static           │
   │                               │ Требуется trailing slash: /static/  │
   │                               │ Проверка absolute_redirect:         │
   │                               │  • on:  Location: $scheme://$host/static/
   │                               │  • off: Location: /static/          │
   │ 2. HTTP/1.1 301 Moved Perm    │                                     │
   │    Location: /static/         │ (Запрос к апстриму даже не уходил!) │
   │<──────────────────────────────│                                     │
```

---

### Детальная анатомия директивы proxy_redirect

Директива `proxy_redirect` перехватывает заголовки `Location` и `Refresh` в ответе апстрима на фазе получения ответа бэкенда (`NGX_HTTP_CONTENT_PHASE` в контексте апстрима) до отправки заголовков клиенту.

#### 1. Форма `proxy_redirect default;`
Форма `default` является поведением Nginx по умолчанию. Nginx автоматически вычисляет строку сопоставления (`redirect`) и строку подстановки (`replacement`) на основе текущего префикса `location` и значения `proxy_pass`:

```nginx
location /portal/ {
    proxy_pass http://backend-srv:8080/app/;
    proxy_redirect default;
}
```

Данная конфигурация абсолютно идентична явной записи:
```nginx
location /portal/ {
    proxy_pass http://backend-srv:8080/app/;
    proxy_redirect http://backend-srv:8080/app/ /portal/;
}
```

> [!IMPORTANT]
> **Ограничение формы `default`:** Если в значении директивы `proxy_pass` используются переменные Nginx (например, `proxy_pass http://$target_upstream;` или `proxy_pass http://backend$request_uri;`), Nginx не может статически вычислить параметры сопоставления при компиляции конфигурации. Применение `proxy_redirect default;` в таком блоке вызовет фатальную ошибку парсинга конфигурации: `nginx: [emerg] "proxy_redirect default" cannot be used with "proxy_pass" containing variables`. В этом случае допустимы только явные строки или регулярные выражения.

#### 2. Форма `proxy_redirect off;`
Отключает модификацию заголовков на текущем уровне конфигурации. Nginx передает заголовки `Location` и `Refresh` от апстрима клиенту в исходном («сыром») виде без каких-либо изменений.
Применяется в случаях, когда:
- Бэкенд сконфигурирован с пониманием своего публичного URL (через передачу заголовков `X-Forwarded-Proto`, `X-Forwarded-Host`, `X-Forwarded-Port`);
- Необходимо исключить двойную перезапись заголовков во внутренних слоях многоуровневой прокси-инфраструктуры;
- Приложение генерирует полностью относительные редиректы (`Location: /auth/login`), которые не требуют адаптации домена и схемы.

#### 3. Префиксная замена: `proxy_redirect redirect replacement;`
Выполняет сопоставление по точному префиксу строки:
- Если значение заголовка `Location` начинается с подстроки `redirect`, этот префикс заменяется на `replacement`.
- Если соответствие не найдено, заголовок передается клиенту без изменений.
- Если в параметре `replacement` опущено имя хоста (путь начинается с `/`), Nginx формирует либо относительный редирект, либо подставляет текущие имя сервера и порт в соответствии с директивами `server_name_in_redirect` и `port_in_redirect`:
  ```nginx
  # Вход от апстрима: Location: http://192.168.1.50:9000/v2/items
  proxy_redirect http://192.168.1.50:9000/v2/ /catalog/v2/;
  # Итог клиенту:     Location: /catalog/v2/items (или https://public-domain/catalog/v2/items)
  ```
- В параметре `replacement` разрешено использовать стандартные переменные Nginx: `$scheme`, `$host`, `$server_port`, `$http_host`:
  ```nginx
  proxy_redirect http://internal.local:8080/ $scheme://$host:$server_port/;
  ```

#### 4. Замена по регулярным выражениям: `proxy_redirect ~regex replacement;`
Начиная с версии Nginx 1.1.11, поддерживается сопоставление по регулярным выражениям PCRE:
- Символ `~` задает сопоставление с учетом регистра;
- Символ `~*` задает сопоставление без учета регистра;
- Регулярное выражение применяется ко **всей строке** заголовка `Location`;
- В `replacement` поддерживаются позиционные переменные захвата (`$1`, `$2` и т.д.):

```nginx
# Вырезание произвольного внутреннего порта из редиректа апстрима
proxy_redirect ~^(http|https)://backend-cluster:[0-9]+/(.*)$ $1://$host/$2;

# Нормализация динамических путей арендаторов (multi-tenant)
proxy_redirect ~*^http://tenant-([a-z0-9]+)\.internal:8080/(.*)$ https://$1.example.com/$2;
```

#### 5. Порядок вычисления и наследование директив
- На одном уровне конфигурации (`http`, `server` или `location`) разрешено указывать **несколько директив** `proxy_redirect`.
- Nginx сопоставляет заголовок последовательно сверху вниз до **первого совпадения**:
  ```nginx
  location / {
      proxy_pass http://upstream_pool;
      proxy_redirect http://upstream-node1:8080/ /;
      proxy_redirect http://upstream-node2:8080/ /;
      proxy_redirect default;
  }
  ```
- **Правило наследования Nginx:** Директивы `proxy_redirect`, объявленные на уровне `http` или `server`, наследуются дочерними блоками `location` **только при условии**, что в самом блоке `location` не определена ни одна директива `proxy_redirect`. Если в блоке `location` прописана хотя бы одна инструкция `proxy_redirect` (даже `proxy_redirect off;`), все унаследованные выше правила полностью аннулируются для этой локации.

---

### Архитектурные директивы ядра Nginx для генерации редиректов

Когда запрос завершается редиректом силами самого Nginx, заголовок `Location` генерируется функцией `ngx_http_send_header` на базе конфигурации `ngx_http_core_module`.

#### 1. absolute_redirect
```nginx
Syntax:  absolute_redirect on | off;
Default: absolute_redirect on;
Context: http, server, location
```
- `absolute_redirect on;` — Nginx формирует абсолютный URL вида:
  `Location: <схема>://<хост>[:<порт>]/<путь>`
  Схема определяется переменной `$scheme` (которая равна протоколу сокета на Nginx). Если перед Nginx стоит балансировщик с SSL-offloading, сокет на Nginx будет `http://`, и Nginx сформирует редирект на небезопасный протокол.
- `absolute_redirect off;` — Nginx выдает относительный URI:
  `Location: /docs/`
  Браузер клиента разрешает относительный URI, сохраняя текущую безопасную схему `https://` и исходный домен.

#### 2. server_name_in_redirect
```nginx
Syntax:  server_name_in_redirect on | off;
Default: server_name_in_redirect off;
Context: http, server, location
```
- `server_name_in_redirect off;` — Nginx извлекает имя хоста из клиентского заголовка `Host`. Если клиент не прислал заголовок `Host` (HTTP/1.0) или он пуст, берется IP-адрес сетевого интерфейса, принявшего соединение.
- `server_name_in_redirect on;` — Nginx принудительно подставляет первое имя из директивы `server_name`. Полезно для канонизации доменов, когда запросы на алиасы должны явно переадресовываться на primary domain.

#### 3. port_in_redirect
```nginx
Syntax:  port_in_redirect on | off;
Default: port_in_redirect on;
Context: http, server, location
```
- `port_in_redirect on;` — если Nginx слушает нестандартный порт (например, `8080` за NAT/PAT или внутри контейнера), он дописывает `:8080` к значению `Location`. Для внешнего клиента этот порт недоступен, что приводит к таймаутам соединения (`ERR_CONNECTION_TIMED_OUT`).
- `port_in_redirect off;` — порт никогда не добавляется в заголовок `Location`.

---

## Практические сценарии и конфигурация

### Сценарий 1: Апстрим светит внутренний адрес за Reverse Proxy с TLS-терминацией

**Контекст:** Внутренний сервис запущен на локальном хосте или во внутренней сети (`10.0.0.15:8080`). На внешнем сервере Nginx терминирует TLS-трафик для домена `https://service.internal.company.com`. При попытке входа сервис выдает редирект `Location: http://10.0.0.15:8080/login`.

**Задача:** Переписать заголовок `Location`, исключив утечку внутренней топологии сети и сохранив схему HTTPS.

```nginx
# /etc/nginx/conf.d/service.conf

upstream backend_auth {
    server 10.0.0.15:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name service.internal.company.com;

    ssl_certificate     /etc/ssl/certs/service.crt;
    ssl_certificate_key /etc/ssl/private/service.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://backend_auth;

        # Переписываем внутренний IP и порт в относительный редирект
        proxy_redirect http://10.0.0.15:8080/ /;

        # Передача метаданных исходного клиентского соединения
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port $server_port;

        # Поддержка постоянных соединений с апстримом
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

---

### Сценарий 2: Маршрутизация с изменением префикса пути (Strip Prefix / API Gateway)

**Контекст:** Nginx работает шлюзом для нескольких внутренних API-сервисов. Внешние клиенты обращаются по пути `/api/v1/billing/`. Внутренний сервис биллинга не знает о префиксе `/api/v1/billing/` и ожидает запросы в корень `/`. При ошибке авторизации сервис возвращает `Location: http://billing-backend:5000/auth`.

**Задача:** Перенаправить клиента на публичный путь `/api/v1/billing/auth`.

```nginx
# /etc/nginx/conf.d/gateway.conf

upstream billing_upstream {
    server 192.168.10.20:5000;
}

server {
    listen 443 ssl;
    server_name api.company.com;

    ssl_certificate     /etc/ssl/certs/api.crt;
    ssl_certificate_key /etc/ssl/private/api.key;

    location /api/v1/billing/ {
        # Слэш в конце proxy_pass срезает URI префикс /api/v1/billing/
        proxy_pass http://billing_upstream/;

        # Восстановление публичного префикса в ответе апстрима
        proxy_redirect http://billing_upstream/ /api/v1/billing/;
        # Fallback для относительного редиректа от сервиса
        proxy_redirect / /api/v1/billing/;

        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

### Сценарий 3: Регулярные выражения для динамических апстримов и микросервисов

**Контекст:** Nginx балансирует трафик на пул микросервисов, запущенных на разных портах, либо использует динамическую маршрутизацию. Апстрим может вернуть редирект вида `Location: http://srv-node-03.infra:9100/checkout/step2`.

**Задача:** Нормализовать любой порт и имя узла в единый публичный домен компании.

```nginx
# /etc/nginx/conf.d/microservices.conf

server {
    listen 443 ssl;
    server_name app.company.com;

    ssl_certificate     /etc/ssl/certs/app.crt;
    ssl_certificate_key /etc/ssl/private/app.key;

    location / {
        proxy_pass http://internal_nodes;

        # PCRE замена: перехват схемы, хоста узла и порта, замена на публичный URL
        proxy_redirect ~*^https?://srv-node-[0-9]+\.infra:[0-9]+/(.*)$ https://app.company.com/$1;

        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

---

### Сценарий 4: Терминация SSL на Edge и предотвращение утечки HTTP через absolute_redirect

**Контекст:** Nginx принимает запросы за внешним L4/L7-балансировщиком нагрузки (HAProxy, Keepalived LVS) по протоколу HTTP (порт 8080), в то время как клиент обращается к балансировщику по HTTPS. При запросе каталога без завершающего слэша (`https://app.company.com/static`) Nginx генерирует редирект на `/static/`. Поскольку Nginx видит `$scheme = http`, он возвращает клиенту `Location: http://app.company.com:8080/static/`, вызывая сбой безопасности браузера (Mixed Content / SSL Drop).

**Задача:** Запретить генерацию абсолютных редиректов ядром Nginx и отключить добавление внутреннего порта.

```nginx
# /etc/nginx/conf.d/app_internal.conf

server {
    listen 8080;
    server_name app.company.com;

    # Отключаем генерацию абсолютных URL ядром Nginx
    absolute_redirect off;

    # Запрещаем передавать порт 8080 в заголовок Location
    port_in_redirect off;

    root /var/www/app_data;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }

    location /media/ {
        # Запрос к /media завершится относительным редиректом:
        # Location: /media/
        # Клиентский браузер сохранит HTTPS и правильный порт!
        alias /var/storage/media/;
    }
}
```

---

### Сценарий 5: Интеграция с сервисами, знающими свой Base URL (Keycloak, Grafana)

**Контекст:** Современные инфраструктурные веб-приложения (Keycloak, Grafana, GitLab, Vault, HashiCorp Consul) умеют корректно формировать исходящие редиректы и callback URL, если им переданы стандартизированные заголовки обратного прокси. Попытка применить `proxy_redirect default` или ручные подстановки может повредить аргументы запроса (например, `?redirect_uri=https%3A%2F%2F...`).

**Задача:** Полностью отключить вмешательство Nginx в заголовки `Location`, корректно настроив атрибуцию схемы и хоста.

```nginx
# /etc/nginx/conf.d/grafana.conf

upstream grafana_backend {
    server 127.0.0.1:3000;
    keepalive 16;
}

server {
    listen 443 ssl;
    server_name monitoring.company.com;

    ssl_certificate     /etc/ssl/certs/monitoring.crt;
    ssl_certificate_key /etc/ssl/private/monitoring.key;

    location / {
        proxy_pass http://grafana_backend;

        # Отключаем перезапись Location — Grafana сама формирует верный URL
        proxy_redirect off;

        # Атрибуция схемы и хоста для бэкенда
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Поддержка веб-сокетов Grafana Live
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

### Сценарий 6: Нестандартные порты и канонизация через server_name_in_redirect

**Контекст:** Компания использует сервер перенаправления устаревших или вспомогательных доменов (`example.org`, `example.net`, `old.example.com`) на основной портал `example.com`. Nginx размещен в демилитаризованной зоне (DMZ) и слушает порт 8443 за пограничным маршрутизатором с пробросом портов (DNAT: 443 → 8443).

**Задача:** Гарантировать, что клиент всегда будет перенаправлен на канонический домен `example.com` без указания технического порта 8443.

```nginx
# /etc/nginx/conf.d/canonical_redirects.conf

server {
    listen 8443 ssl;
    server_name example.com example.org example.net old.example.com;

    ssl_certificate     /etc/ssl/certs/bundle.crt;
    ssl_certificate_key /etc/ssl/private/bundle.key;

    # Принудительно используем первое имя из server_name (example.com)
    server_name_in_redirect on;

    # Исключаем порт 8443 из редиректов
    port_in_redirect off;

    # Относительные редиректы не нужны, так как цель — смена домена
    absolute_redirect on;

    if ($host != "example.com") {
        return 301 https://example.com$request_uri;
    }

    location / {
        root /var/www/html;
        index index.html;
    }
}
```

---

### Сценарий 7: Обработка заголовка Refresh и формы аутентификации

**Контекст:** Устаревшие веб-приложения и некоторые системы Enterprise SSO (Active Directory Federation Services / старые Java-сервлеты) возвращают заголовки `Refresh: 0; url=http://internal-sso:8080/idp/profile` вместо стандартного `Location: ...`.

**Задача:** Переписать заголовок `Refresh` на публичный шлюз аутентификации.

```nginx
# /etc/nginx/conf.d/legacy_sso.conf

location /sso/ {
    proxy_pass http://10.10.5.50:8080/idp/;

    # Перезапись действует одновременно на Location и Refresh!
    proxy_redirect http://10.10.5.50:8080/idp/ /sso/;
    proxy_redirect http://internal-sso:8080/idp/ /sso/;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
}
```

---

### Сценарий 8: Каскадная многоуровневая прокси-инфраструктура (DMZ Edge → Internal Ingress → Pod/VM)

**Контекст:** Трафик проходит через два слоя проксирования:
1. Внешний пограничный прокси (DMZ Edge Nginx) — терминирует публичный TLS, защищает от DDoS.
2. Внутренний сервисный прокси (Internal Reverse Proxy) — маршрутизирует трафик в изолированные виртуальные машины / контейнеры.

**Задача:** Исключить повторную перезапись заголовков и конфликты преобразования путей.

```text
[Клиент] ──(HTTPS)──► [Edge Nginx (DMZ)] ──(HTTP)──► [Internal Nginx] ──(HTTP)──► [App]
```

**Конфигурация Edge Nginx (DMZ):**
```nginx
# /etc/nginx/conf.d/edge.conf
server {
    listen 443 ssl;
    server_name portal.company.com;

    ssl_certificate     /etc/ssl/certs/portal.crt;
    ssl_certificate_key /etc/ssl/private/portal.key;

    location / {
        proxy_pass http://internal-proxy.local:80;

        # Точка преобразования: преобразуем внутренний хост в публичный HTTPS
        proxy_redirect http://internal-proxy.local/ https://portal.company.com/;

        # Передаем оригинальные метаданные клиента
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Port 443;
    }
}
```

**Конфигурация Internal Nginx:**
```nginx
# /etc/nginx/conf.d/internal.conf
server {
    listen 80;
    server_name internal-proxy.local;

    location / {
        proxy_pass http://127.0.0.1:8080;

        # Во внутреннем слое отключаем перезапись!
        # Перезапись выполнит пограничный Edge Nginx.
        proxy_redirect off;

        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-For $http_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    }
}
```

---

## Операции и команды

Все команды тестирования и валидации выполняются в командной строке Linux под учетной записью администратора с выводом ожидаемого результата.

### 1. Валидация синтаксиса и дамп активных директив

```bash
# Проверка конфигурации Nginx на наличие синтаксических ошибок
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Дамп полной конфигурации и поиск всех активных правил редиректов
sudo nginx -T | grep -E "proxy_redirect|absolute_redirect|server_name_in_redirect|port_in_redirect"
# → absolute_redirect off;
# → port_in_redirect off;
# → proxy_redirect http://10.0.0.15:8080/ /;

# Безопасная перезагрузка рабочего процесса без разрыва текущих TCP-сессий
sudo systemctl reload nginx
# → (код возврата 0, служба перезагружена)
```

### 2. Тестирование заголовков ответов и поведения Location

```bash
# Проверка HTTP-заголовков без загрузки тела ответа
curl -sI -H "Host: service.internal.company.com" https://127.0.0.1/admin
# → HTTP/1.1 302 Found
# → Server: nginx
# → Date: Fri, 17 Oct 2026 13:15:00 GMT
# → Connection: keep-alive
# → Location: /admin/login

# Детальная трассировка с выводом рукопожатия TLS и заголовков запроса/ответа
curl -v -k -H "Host: service.internal.company.com" https://127.0.0.1/api/v1/billing
# → > GET /api/v1/billing HTTP/1.1
# → > Host: service.internal.company.com
# → > User-Agent: curl/8.5.0
# → < HTTP/1.1 301 Moved Permanently
# → < Server: nginx
# → < Location: /api/v1/billing/
# → < Content-Length: 0
```

### 3. Проверка цепочки редиректов и финального URL

```bash
# Автоматическое следование по всем редиректам с выводом каждого шага (флаг -L)
curl -sIL -k https://service.internal.company.com/portal
# → HTTP/1.1 302 Found
# → Location: /portal/auth
# → 
# → HTTP/1.1 200 OK
# → Content-Type: text/html; charset=utf-8

# Вывод исключительно итогового редиректа без вывода контента
curl -s -k -o /dev/null -w "%{redirect_url}\n" https://service.internal.company.com/app
# → /app/dashboard/

# Защита от бесконечных циклов: ограничение максимального числа редиректов
curl --max-redirs 5 -sIL https://service.internal.company.com/test-loop
# → curl: (47) Maximum (5) redirects followed
```

### 4. Проверка сохранения метода запроса (POST → POST vs POST → GET)

```bash
# Тест временного редиректа 307 (метод POST сохраняется)
curl -X POST -d "param=value" -sIL https://service.internal.company.com/api/save
# → HTTP/1.1 307 Temporary Redirect
# → Location: /api/v2/save
# → 
# → HTTP/1.1 200 OK (Сервер принял тело POST-запроса)

# Тест редиректа 302/301 с флагом --post302 (сохранение POST при старых кодах)
curl --post302 -X POST -d "param=value" -sIL https://service.internal.company.com/api/old
# → HTTP/1.1 302 Found
# → Location: /api/new
# → 
# → HTTP/1.1 200 OK
```

### 5. Аудит редиректов в логах Nginx

```bash
# Форматирование access.log с регистрацией $status и отправленного $sent_http_location:
# log_format redirects '$remote_addr [$time_local] "$request" $status to "$sent_http_location"';

# Мониторинг всех исходящих редиректов в реальном времени
sudo tail -f /var/log/nginx/access.log | grep -E 'HTTP/[0-9.]+" 30[12378]'
# → 192.168.1.100 [17/Oct/2026:13:20:01 +0000] "GET /docs HTTP/1.1" 301 to "/docs/"
# → 192.168.1.105 [17/Oct/2026:13:20:05 +0000] "POST /login HTTP/1.1" 302 to "https://service.internal.company.com/dashboard"
```

---

## Диагностика и устранение неисправностей

| Симптом | Корневая причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`ERR_TOO_MANY_REDIRECTS` (Redirect Loop)** | Edge Nginx перенаправляет HTTP → HTTPS, а бэкенд не видит заголовка `X-Forwarded-Proto` и возвращает редирект на HTTP | `curl -sI http://site/` и `curl -sI https://site/` оба возвращают `301/302` | 1. Добавить `proxy_set_header X-Forwarded-Proto https;`<br>2. Настроить бэкенд доверять Reverse Proxy |
| **Утечка внутреннего IP или порта** (`http://10.0.0.5:8080/path`) | Апстрим сформировал абсолютный редирект со своим локальным IP/портом, а `proxy_redirect` выключен или не совпал | `curl -sI https://public-domain/path` показывает внутренний IP в `Location` | Настроить префиксное правило:<br>`proxy_redirect http://10.0.0.5:8080/ /;` |
| **Утечка технического порта Nginx** (`https://site:8443/dir/`) | Nginx слушает порт 8443 за NAT/балансировщиком, включена опция `port_in_redirect on` | Проверить заголовки при обращении к папке без слэша: `curl -sI https://site/dir` | Добавить в блок `server`:<br>`port_in_redirect off;` |
| **Даунгрейд HTTPS на HTTP при редиректе на слэш** | Запрос к папке без слэша обрабатывается ядром Nginx с `absolute_redirect on;`, схема сокета `http` | Запрос `https://site/app` дает `Location: http://site/app/` | Задать `absolute_redirect off;` (Nginx выдаст относительный `Location: /app/`) |
| **Ошибка старта: `"proxy_redirect default" cannot be used...`** | В директиве `proxy_pass` используются переменные Nginx (`$upstream_host`), что запрещает вычисление `default` | `sudo nginx -t` завершается с кодом ошибки `emerg` | Заменить `proxy_redirect default;` на явное сопоставление путей или регулярное выражение |
| **Потеря тела POST-запроса при редиректе** | Бэкенд или Nginx вернул статус `301` или `302`. Клиент по стандарту RFC 7231 сменил метод на `GET` и сбросил payload | В логах бэкенда фиксируется `GET` вместо `POST` | Настроить генерацию статусов `307 Temporary Redirect` или `308 Permanent Redirect` |
| **404 Not Found после редиректа при strip-prefix** | Несоответствие путей: `proxy_pass` отрезал префикс, но в `proxy_redirect` префикс не был возвращен обратно | В `Location` возвращается `/dashboard` вместо `/api/v1/dashboard` | Добавить `proxy_redirect / /api/v1/;` |
| **Кэширование неверного редиректа в браузере** | Ошибочный редирект был отдан со статусом `301`, который кэшируется браузером на длительный срок | Браузер перенаправляет даже после изменения конфигурации Nginx | Очистить кэш браузера или временно тестировать в режиме инкогнито / через `curl` |

### Алгоритм пошаговой локализации проблем с редиректами

```text
Шаг 1: Определите слой-источник редиректа
       Выполните: curl -sI https://domain.com/problem-path
       │
       ├─► Запрос возвращается МГНОВЕННО, апстрим не фиксирует логов?
       │   └── Источник: Ядро Nginx (Core Layer).
       │       Решение: Проверьте trailing slash, try_files, return 301.
       │       Примените absolute_redirect off; port_in_redirect off;
       │
       └─► Запрос регистрируется в логах бэкенда?
           └── Источник: Апстрим (Upstream Layer).
               Решение: Проверьте proxy_redirect, proxy_set_header X-Forwarded-Proto,
               или настройте proxy_redirect off, если бэкенд управляет схемой сам.
```

---

## Рекомендации и Best Practices

1. **Принцип единой границы ответственности (Single Point of Redirection Rewrite):**
   - Выполняйте перезапись редиректов исключительно на пограничном шлюзе (Edge Reverse Proxy).
   - На всех внутренних промежуточных прокси-серверах и балансировщиках устанавливайте `proxy_redirect off;`, чтобы предотвратить искажения адресов и наложение правил.

2. **Используйте относительные редиректы (`absolute_redirect off;`):**
   - При работе Nginx за пограничными балансировщиками с терминацией TLS отключение абсолютных редиректов (`absolute_redirect off;`) является индустриальным стандартом. Относительный заголовок `Location: /path/` валиден по RFC 9110 и гарантирует сохранение протокола HTTPS и исходного доменного имени.

3. **Скрывайте внутренние порты (`port_in_redirect off;`):**
   - Если сервер Nginx принимает трафик на портах, отличных от 80 и 443 (внутри контейнеров, за трансляцией адресов NAT/PAT или балансировщиками L4), директива `port_in_redirect off;` обязательна во всех блоках `server`.

4. **Аккуратность при выборе статусов 301 vs 302 vs 307/308:**
   - На этапе отладки и ввода сервисов в эксплуатацию используйте временные коды `302 Found` или `307 Temporary Redirect`.
   - Редирект `301 Moved Permanently` агрессивно кэшируется браузерами (включая постоянное дисковое кэширование). Ошибка в правиле 301 останется у пользователей даже после отката конфигурации Nginx.
   - Для REST API и микросервисов, передающих `POST`, `PUT`, `DELETE`, всегда применяйте `307` или `308`, чтобы исключить потерю тела запроса и несанкционированную мутацию в `GET`.

5. **Обязательная передача заголовков контекста клиенту:**
   - Для всех проксируемых запросов передавайте полный набор заголовков семейства Forwarded:
     ```nginx
     proxy_set_header Host $http_host;
     proxy_set_header X-Real-IP $remote_addr;
     proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
     proxy_set_header X-Forwarded-Proto $scheme;
     proxy_set_header X-Forwarded-Port $server_port;
     ```

6. **Включение `$sent_http_location` в access-логи:**
   - При расследовании инцидентов со штормами редиректов standard-лог Nginx не отображает целевой адрес перенаправления. Добавьте переменную `$sent_http_location` в пользовательский формат журнала:
     ```nginx
     log_format custom_trace '$remote_addr - $remote_user [$time_local] '
                             '"$request" $status $body_bytes_sent '
                             '"$http_referer" "$http_user_agent" '
                             'redir="$sent_http_location" upstream="$upstream_addr"';
     ```

7. **Защита от Open Redirect уязвимостей:**
   - При использовании регулярных выражений в `proxy_redirect ~...` строго валидируйте маску подстановки. Никогда не подставляйте непроверенные параметры пользовательского запроса напрямую в заголовок `Location`.

---

## Дополнительная информация

### Официальная документация и спецификации

- [Nginx ngx_http_proxy_module: proxy_redirect](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_redirect) — официальное руководство по синтаксису и поведению директивы `proxy_redirect`.
- [Nginx ngx_http_core_module: absolute_redirect](https://nginx.org/en/docs/http/ngx_http_core_module.html#absolute_redirect) — управление абсолютными и относительными редиректами ядра.
- [Nginx ngx_http_core_module: server_name_in_redirect](https://nginx.org/en/docs/http/ngx_http_core_module.html#server_name_in_redirect) — определение доменного имени в генерируемых ответах.
- [Nginx ngx_http_core_module: port_in_redirect](https://nginx.org/en/docs/http/ngx_http_core_module.html#port_in_redirect) — контроль вывода сетевых портов в ответах.
- [RFC 9110: HTTP Semantics §10.2.2 (Location)](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.2) — спецификация формата заголовка Location и относительных ссылок.
- [RFC 7538: The Hypertext Transfer Protocol Status Code 308 (Permanent Redirect)](https://www.rfc-editor.org/rfc/rfc7538.html) — спецификация постоянного редиректа с сохранением метода.

### См. также

- [HTTP-серверы и прокси: Конфигурация и эксплуатация](../../../Networking/Protocols/HTTP/http_servers_proxies.md) — базовые концепции обратного проксирования, работа с заголовками `X-Forwarded-*`.
- [Буферизация и стриминг в Nginx](./nginx_buffering_and_streaming.md) — поведение конвейера Nginx при обработке ответов апстримов.
- [Практическая конфигурация балансировки нагрузки](./Load_Balancing/practical_configuration.md) — шаблоны распределения трафика и директивы `proxy_pass`.
- [Перенаправления и перезапись URI в Nginx](../Core/nginx_rewrite_rules_and_try_files.md) — детальный разбор директив `rewrite`, `return`, `try_files` и фаз обработки запроса.
- [Перенаправления и перезапись URI в Angie](../../Angie/angie_redirects_and_rewrites.md) — архитектурные отличия, директивы `auto_redirect`, `goto` и оптимизации маршрутизации в Angie.
- [Обратный прокси-сервер в Angie](../../Angie/angie_reverse_proxy.md) — практическое использование `proxy_redirect` и заголовков в экосистеме Angie.
- [Устранение неполадок Nginx](../Operations/nginx_troubleshooting.md) — общая методология диагностики сбоев веб-сервера.