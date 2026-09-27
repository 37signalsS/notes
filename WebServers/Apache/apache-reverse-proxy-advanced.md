# Apache: Обратное проксирование — продвинутые сценарии

---

## Определения

**ProxyPassMatch** — вариант `ProxyPass` с регулярным выражением: проксирует запросы, URL которых соответствует pattern, на backend.

**`ProxyPass ... !`** — специальная нотация «не проксировать»: исключение из проксирования для указанного пути (обычно статика/admin), обрабатывается локально.

**ProxyPassReverse** — перезапись заголовков `Location`/`Content-Location` из ответа backend, чтобы редиректы вели через Apache, а не «в обход».

**ProxyPassReverseCookieDomain / ProxyPassReverseCookiePath** — перезапись атрибутов `Domain`/`Path` в `Set-Cookie` при переходе между именами/путями.

**ProxyErrorOverride** — заставляет Apache отдавать собственные `ErrorDocument`-страницы (например кастомную 503) вместо страниц ошибок backend.

**ProxyPassInterpolateEnv** — разрешает подстановку переменных окружения (`${VAR}`) в значениях proxy-директив.

**gRPC** — фреймворк удалённого вызова поверх HTTP/2. Проксируется Apache через `mod_proxy_http2` на h2c-бэкенд.

---

## Основные концепции

### Порядок и специфичность правил ProxyPass

`ProxyPass` применяется в порядке появления в конфиге (первое совпадение). Более специфичный путь задаётся раньше общего; «не проксировать» (`!`) снимает правило для точного пути:

```apacheconf
ProxyPass /static/ !          # статику отдаёт Apache
ProxyPass /admin/ !           # админку отдаёт Apache/другой хендлер
ProxyPass / balancer://backend/
```

Обратные директивы `ProxyPassReverse`/`ProxyPassReverseCookie*` не зависят от правила доступа — они перезаписывают ответ backend.

### Когда нужен ProxyPassReverse

Если backend (например Java, PHP, Rails) отвечает `Location: http://backend:8080/foo`, клиент без `ProxyPassReverse` уйдёт на внутренний адрес. Правило:

```apacheconf
ProxyPassReverse / http://backend.internal:8080/
ProxyPassReverse / https://public.example.com/   # второй вариант для canonical-host
```

### Cookie-rewrite

При смене имени хоста (интерфейс на `www.example.com`, бэкенд на `app.example.com`) сессионная cookie должна иметь `Domain=www.example.com`; перезаписывается:

```apacheconf
ProxyPassReverseCookieDomain app.internal www.example.com
ProxyPassReverseCookiePath / /
```

### ErrorDocument за ProxyErrorOverride

Чтобы пользователи видели аккуратные страницы, а не текст backend-фреймворка, и чтобы алерты не смешивались с видами ошибок:

```apacheconf
ProxyErrorOverride On
ErrorDocument 500 /errors/500.html
ErrorDocument 502 /errors/502.html
ErrorDocument 503 /errors/503.html
```

При `Off` Apache отдаёт ответы backend «как есть». `On` — в т.ч. HTTP-статусы 5xx от внутренних серверов.

### Передача заголовков на backend

По умолчанию `mod_proxy_http` добавляет стандартный набор (`X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `Via`). Управление:

| Директива | Действие |
|---|---|
| `ProxyAddHeaders Off` | Отключить добавление X-Forwarded-* |
| `RequestHeader set X-Forwarded-Proto https` | Принудительно выставить протокол |
| `<Proxy *><Require ...></Proxy>` | Ограничение доступа к прокси-функции |
| `ProxyPreserveHost On` | Передавать оригинальный Host |

### gRPC через Apache

gRPC работает только по HTTP/2. Apache проксирует через `mod_proxy_http2` на h2c-бэкенд (Go gRPC-сервер обычно слушает h2c):

```apacheconf
LoadModule proxy_http2_module modules/mod_proxy_http2.so

<VirtualHost *:443>
    SSLEngine on
    ...
    Protocols h2 http/1.1
    ProxyPass /grpc/ http://127.0.0.1:50051/ upgrade=http2
    ProxyPassReverse /grpc/ http://127.0.0.1:50051/
</VirtualHost>
```

Для h2c без TLS на фротенде требуется `Protocols h2c http/1.1` на соответствующем `<VirtualHost>`.

---

## Практические сценарии

### 1. Статика локально + прокси остального (классика)

```apacheconf
<VirtualHost *:80>
    ServerName app.example.com

    Alias /static/ /opt/app/web/static/
    <Directory "/opt/app/web/static">
        Require all granted
    </Directory>
    ProxyPass /static/ !

    # Все остальные пути — на backend
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/
    ProxyPassReverseCookieDomain example.com www.example.com
    ProxyPassReverseCookiePath / /
</VirtualHost>
```

### 2. Regexp-проксирование (ProxyPassMatch)

```apacheconf
# API-версии — на отдельный backend
ProxyPassMatch "^/api/v2/(.*)$" "http://api-v2.internal:9000/$1"
ProxyPassMatch "^/media/(.*\.(png|jpg|webp))$" "http://images.internal:9001/$1"
```

Важно: pattern применяется к URL-path, `$1` — содержание группы.

### 3. Backend за TLS (HTTPS)

```apacheconf
SSLProxyEngine on
SSLProxyCACertificateFile /etc/pki/tls/certs/internal-ca.pem
ProxyPass / https://backend.internal:8443/
ProxySSLVerify require
```

### 4. Интерполяция переменных окружения

```apacheconf
SetEnv BACKEND_HOST 10.0.0.11
ProxyPassInterpolateEnv On
ProxyPass / http://${BACKEND_HOST}:8080/ interpolate=On
```

### 5. WebSocket и SSE поверх прокси

`mod_proxy_wstunnel` (см. [Обзор Apache](./apache_overview.md)) перехватывает `Upgrade: websocket`. Для SSE — обычный `ProxyPass` с `ProxyTimeout`, без Upgrade:

```apacheconf
ProxyPass /sse/ http://127.0.0.1:8080/sse/
ProxyTimeout 300
```

### 6. Продвинутая диагностика через заголовки

```apacheconf
# Добавить в лог X-Forwarded-For backend'у
RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
# Прокси-цепочка в ответе нежелательна:
ProxyVia Off
```

---

## Операции и команды

| Команда/проверка | Назначение | Пример вывода |
|---|---|---|
| `curl -sI http://localhost/static/app.css` | Проверка, что статика не проксируется | `200 OK`, `Server: Apache` |
| `curl -sI http://localhost/x` | Проверка проксирования метода | `200 OK`, заголовки backend |
| `curl -sIL` | Проход Location-цепочек | `Location: ...` |
| `apache2ctl -M \| grep -E "proxy_http|proxy_http2"` | Модули протокола | `proxy_http_module (shared)` |
| `tail access_log \| grep X-Forwarded` | Реальность IP клиента на backend | заголовок |

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| Редирект уводит на `backend.internal:8080` | Нет `ProxyPassReverse` | Добавить `ProxyPassReverse / http://backend.internal:8080/` |
| Cookie сессии с внутренним Domain | Нет `ProxyPassReverseCookieDomain` | Указать правильное доменное правило |
| 404 для `/static/` при работающем app | `ProxyPass /` перекрывает статику до правила `!` | Переместить `ProxyPass /static/ !` выше общего правила |
| Пользователь видит стек-трейс backend | `ProxyErrorOverride Off` + кастомные страницы | `ProxyErrorOverride On` + `ErrorDocument` |
| gRPC-запрос падает `400/415` | Бэкенд не принимает h2c или не настроен `upgrade=http2` | `mod_proxy_http2`, `upgrade=http2`, проверка h2c |
| Backend не видит реальный IP | `mod_remoteip`/`RemoteIPHeader` не настроен | См. [mod_remoteip](./apache_overview.md) |

---

## Лучшие практики

1. Правила `ProxyPass` упорядочивать: исключения (`!`) и специфичные пути — раньше общих.
2. Всегда использовать `ProxyPassReverse` и, при смене хоста/пути, `ProxyPassReverseCookieDomain`/`CookiePath`.
3. Статику обслуживать Apache (или `.htaccess`-независимо) — не гонять через backend.
4. `ProxyErrorOverride On` в связке с едиными страницами ошибок, чтобы фронт не «светил» стек-трейсы внутренних сервисов.
5. Для гRPC-проксирования использовать h2c-бэкенды; h2 на фронте обязателен.
6. Заголовки `X-Forwarded-*` доверять только после `mod_remoteip`-фильтрации — иначе клиенты могут подделывать IP в логах и правилах.

---

## Дополнительная информация

### См. также

*   [Обзор Apache: основы reverse proxy, WebSocket](./apache_overview.md) — базовые `ProxyPass`/`mod_proxy_wstunnel`.
*   [Балансировка нагрузки](./apache_load_balancing.md) — balancer, sticky, health-проверки.
*   [Определение реального IP (mod_remoteip)](./apache_overview.md) — корректные логи и `Require` за прокси.