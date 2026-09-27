# Редиректы в Nginx: proxy_redirect, absolute_redirect, server_name_in_redirect, port_in_redirect

> Редирект (переадресация) — ответ HTTP 3xx (чаще всего `301`/`302`/`307`/`308`) с заголовком `Location`, указывающим клиенту, куда идти дальше. Когда Nginx работает прокси, `Location` может генерировать либо сам апстрим-сервис, либо сам Nginx — и это два РАЗНЫХ механизма, которые путают чаще всего:
> - **`proxy_redirect`** переписывает `Location`/`Refresh`, пришедший **от апстрима** (модуль `ngx_http_proxy_module`);
> - **`absolute_redirect`**, **`server_name_in_redirect`**, **`port_in_redirect`** управляют редиректами, которые **издаёт сам Nginx** (модуль `ngx_http_core_module`).

## Определения

**Редирект (HTTP Redirect)** — ответ статуса `301 Moved Permanently`, `302 Found`, `303 See Other`, `307 Temporary Redirect`, `308 Permanent Redirect` с заголовком `Location`. Клиент (браузер, `curl`, API-клиент) автоматически выполняет новый запрос по адресу из `Location`.

**Location** — заголовок ответа, задающий целевой URI редиректа. По RFC 7231 может быть как абсолютным URL (`https://example.com/path`), так и относительной ссылкой (`/new/path`).

**Refresh** — редко используемый заголовок (не-HTTP-стандарт), тоже попадает под действие `proxy_redirect`. Встречается в формах login/SSO (например, в связке с POST-Redirect-GET).

**proxy_redirect** — директива `ngx_http_proxy_module`, которая выполняет поиск и замену (replace) текста в заголовках `Location` и `Refresh` ответа, полученного от проксируемого сервера. Формат: `proxy_redirect redirect replacement;` или служебные `default`/`off`.

**absolute_redirect** — директива `ngx_http_core_module` (с версии 1.11.8), управляющая форматом редиректов, **издаваемых самим Nginx** (директивы `return`, `error_page` со статусом 3xx, автогенерируемый редирект на `/` для каталога). `absolute_redirect off` заставляет Nginx отдавать относительные `Location`.

**server_name_in_redirect** — директива `ngx_http_core_module` (по умолчанию `off`, с 1.3.4). Когда `off` (по умолчанию), в абсолютных редиректах, издаваемых Nginx, имя сервера берётся из заголовка запроса `Host`; когда `on` — из директивы `server_name`.

**port_in_redirect** — директива `ngx_http_core_module` (по умолчанию `on`). Управляет включением порта в абсолютные редиректы, издаваемые Nginx. Выключите, если Nginx слушает нестандартный порт, который не должен «протекать» в `Location`.

## Основные концепции

### Два слоя редиректов: апстрим ≠ Nginx

| Признак | Редирект от апстрима | Редирект, изданный Nginx |
| :--- | :--- | :--- |
| Кто пишет `Location` | приложение (Golang/PHP/Java API, Grafana, Keycloak) | сам Nginx (`return 301`, `error_page 302`, trailing-slash) |
| Действующая директива | `proxy_redirect` | `absolute_redirect`, `server_name_in_redirect`, `port_in_redirect` |
| Типичная проблема | внутри `Location` «протекает» внутренний IP/порт `http://10.0.0.5:8080/...` | `Location` содержит `http://` вместо `https://` потому, что TLS терминирует фронтовый балансировщик/ингресс |

Если проблемный редирект выдал апстрим — правьте **инструментами апстрима** (`proxy_redirect`), если сам Nginx — правьте **core-директивами**. Обратное не работает: `proxy_redirect` не трогает редиректы, сгенерированные самим Nginx, а `absolute_redirect` не трогает `Location` от апстрима.

### Формы `proxy_redirect`

| Форма | Описание |
| :--- | :--- |
| `proxy_redirect redirect replacement;` | Префиксная замена: если `Location` начинается с `redirect`, этот префикс заменяется на `replacement`. Не совпало — `Location` передаётся без изменений. |
| `proxy_redirect default;` | Эквивалент явного отображения, построенного из `location` и `proxy_pass`. Запрещено, если в `proxy_pass` используются переменные. |
| `proxy_redirect off;` | Отменяет унаследованные директивы (при наследовании из `http`/`server`) и передаёт `Location` без изменений. |
| `proxy_redirect ~regex replacement;` / `~*` | Полное совпадение URI по регулярному выражению (с 1.1.11). `~` — регистрозависимо, `~*` — нет. Допускаются захваты `$1`, `$2`. |

Ключевые правила:

- **Директива работает по принципу префикса.** Пример (пары из документации):

```nginx
# Апстрим отдаёт Location: http://localhost:8000/two/some/uri/
proxy_redirect http://localhost:8000/two/ http://frontend/one/;
# → Location: http://frontend/one/some/uri/
```

- **`default` — то же самое, что явная пара** из `location` + `proxy_pass`:

```nginx
# Эквивалентные конфигурации:
location /one/ {
    proxy_pass http://upstream:port/two/;
    proxy_redirect default;
}

location /one/ {
    proxy_pass http://upstream:port/two/;
    proxy_redirect http://upstream:port/two/ /one/;
}
```

- **`replacement` может содержать переменные** ($host, $server_port, $scheme и т.д.): `proxy_redirect http://localhost:8000/ http://$host:$server_port/;`
- **Если в `replacement` опущено имя сервера**, будет подставлено имя primary server и порт (кроме стандартного 80): `proxy_redirect http://localhost:8000/two/ /;`
- **На одном уровне можно дать несколько директив**; отрабатывает **первое совпадение** сверху вниз.
- **`Refresh` обрабатывается так же** — это важно для POST-Redirect-GET и форм авторизации.

Регулярные выражения полезны, когда апстрим отдаёт динамический хост/порт:

```nginx
# Убрать порт из абсолютного Location (1.1.11+)
proxy_redirect ~^(http://[^:]+):\d+(/.+)$ $1$2;

# Подменить хост по подстроке
proxy_redirect ~*/user/([^/]+)/(.+)$ http://$1.example.com/$2;
```

### Редиректы, издаваемые самим Nginx

- `absolute_redirect on;` (по умолчанию) — Nginx отдаёт `Location` как абсолютный URL, собирая схему из `$scheme`, имя сервера — из `Host` (или `server_name`), порт — по `port_in_redirect`.
- `absolute_redirect off;` — Nginx отдаёт относительный `Location` (`/path?query`). Относительный `Location` полностью легален по RFC и поддерживается всеми браузерами и `curl` (`-L`). Это ключевой приём для схем, где TLS терминирует внешний балансировщик.
- В разогреваемых сценариях даже с `absolute_redirect on` полезно отключить лишнее: `port_in_redirect off` (не «протекать» порт `8080` наружу) и при необходимости `server_name_in_redirect on` (если хотите фиксированное имя из конфига, а не из `Host`).

## Практические сценарии

### Сценарий 1. Апстрим светит внутренний адрес за https-балансировщиком

Классика: TLS терминирует ингресс/load balancer, апстрим отвечает конфигурацией «я localhost:8080»:

```nginx
location /app/ {
    proxy_pass http://10.0.0.10:8080/;
    proxy_redirect http://10.0.0.10:8080/ /;   # Location → /... (относительный)
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Ответ: `Location: /login` вместо `Location: http://10.0.0.10:8080/login`.

### Сценарий 2. Навязывание публичного хоста

Приложение не знает внешний домен и отдаёт `Location: http://backend:8080/dashboard`:

```nginx
proxy_redirect http://backend:8080/ https://app.example.com/;
```

### Сценарий 3. Редирект, изданный самим Nginx, уходит в http

Nginx сам выдаёт `301` (например, на каталог без слэша: `/users → 301 Location /users/`). Снаружи TLS терминирует ингресс, и из-за этого Nginx видит `http` и формирует `Location: http://app.example.com/users/`:

```nginx
location /users/ {
    absolute_redirect off;   # → Location: /users/
}
```

### Сценарий 4. Убрать порт из Location

Nginx слушает `80` и `8080`: с `port_in_redirect off` в `Location` порт исчезнет, даже если запрос пришёл на `8080`:

```nginx
server {
    listen 80;
    listen 8080;
    server_name example.com;
    port_in_redirect off;
    return 301 https://example.com$request_uri;
}
```

### Сценарий 5. Приложение само знает свой внешний URL

Если приложение настроено с корректным внешним base URL (типично для Grafana, GitLab, Keycloak), любые перезаписи ломают его редиректы. Подключаем `off` и оставляем `Location` как есть:

```nginx
location /grafana/ {
    proxy_pass http://grafana:3000;
    proxy_redirect off;
}
```

### Сценарий 6. Формы и POST-Redirect-GET (Refresh)

Сервисы, возвращающие `<meta http-equiv="Refresh">` или заголовок `Refresh` (старые PHP-приложения, некоторые SSO), тоже затронуты `proxy_redirect`:

```nginx
proxy_redirect ~* ^http://internal[./] /;
```

## Операции и команды

```bash
# Валидация конфигурации перед reload
sudo nginx -t
sudo systemctl reload nginx

# Посмотреть, что реально уходит клиенту (заголовки ответа)
curl -sI http://127.0.0.1/app/
curl -sI -H 'Host: app.example.com' http://127.0.0.1/users/
curl -skIL https://app.example.com/users/

# Только итоговый URL после всех редиректов
curl -s -o /dev/null -w '%{redirect_url}' http://127.0.0.1/app/login

# Найти, где настроены перезаписи
sudo grep -rn "proxy_redirect\|absolute_redirect\|port_in_redirect" /etc/nginx/
```

При проверке различайте слои: если `Location` совпадает со схемой/хостом апстрима — источник редиректа апстрим (чинится через `proxy_redirect`); если это «рукотворный» Nginx-редирект (trailing slash, `return 301`) — чинится через `absolute_redirect`/`port_in_redirect`.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Location: http://10.0.0.5:8080/...` (внутренний адрес) | Апстрим отдал абсолютный `Location` с внутренним адресом, перезаписи нет | `proxy_redirect http://10.0.0.5:8080/ /;` |
| `Location: http://example.com/...` вместо https | ТLS терминирует ингресс, Nginx видит `$scheme=http` | `absolute_redirect off` на уровне фронтового локации (или проксировать с `X-Forwarded-Proto` и переписать схему) |
| Двойной редирект (nginx → апстрим → nginx) | Перезапись добавляется и во фронтовом, и во внутреннем слое | Одиночная точка преобразования: переписать на самом внешнем слое, дальше — `proxy_redirect off` |
| Порт `:8080` протекает в `Location` | `port_in_redirect on` (по умолчанию) | `port_in_redirect off;` |
| `Location: /path` не переписался | Апстрим отдал относительный `Location` (префикс не совпал) | Перезапись не нужна; если нужно сделать абсолютный — добавьте `proxy_redirect / /;` |
| `proxy_redirect default` с ошибкой конфигурации | В `proxy_pass` используются переменные | Перезапишите на явную пару `proxy_redirect http://... /;` |
| Редиректы от апстрима не меняются | Ошибка слоя: применён `absolute_redirect`, а не `proxy_redirect` | Проверить источник редиректа и применить правильную директиву |

## Лучшие практики

1. **Разделяйте два слоя.** Директива `proxy_redirect` — только для `Location`/`Refresh` апстрима; `absolute_redirect`/`port_in_redirect`/`server_name_in_redirect` — только для редиректов, издаваемых самим Nginx.
2. **За фронтовым TLS-терминатором отдавайте относительные `Location`**: `absolute_redirect off;` — самый простой и надёжный способ не «протекать» схему и внутренние адреса.
3. **Никогда не публикуйте внутренние IP/имена** в `Location`; при необходимости навязывайте публичный хост явной парой `proxy_redirect ... /`.
4. **Используйте `proxy_redirect off`** только когда апстрим настроен на корректный внешний URL — иначе получите двойное преобразование.
5. **Перезапись держите на одном слое** (обычно на самом внешнем прокси) — у внутренних инстансов `proxy_redirect off`.
6. **Проверяйте полную цепочку** `curl -sIL` (с `-L`) и с явным `Host` — она видит то же, что браузер.
7. Способствуйте атрибуции схемы во фронте: передавайте `X-Forwarded-Proto`/`X-Forwarded-Host`, см. [HTTP-проксирование и заголовки](../../../Networking/Protocols/HTTP/http_servers_proxies.md).

## Дополнительная информация

- Полный справочник директив: `proxy_redirect` — [nginx.org docs: ngx_http_proxy_module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_redirect); `absolute_redirect`, `server_name_in_redirect`, `port_in_redirect` — [nginx.org docs: ngx_http_core_module](https://nginx.org/en/docs/http/ngx_http_core_module.html#absolute_redirect).

### См. также

- [Проксирование и заголовки (HTTP)](../../../Networking/Protocols/HTTP/http_servers_proxies.md) — X-Forwarded-*, Host, схемы за балансировщиком.
- [Buffering и стриминг движка](./nginx_buffering_and_streaming.md) — поведение `proxy_pass` при передаче тел ответов.
- [Практическая конфигурация проксирования](./Load_Balancing/practical_configuration.md) — базовые примеры `proxy_pass` и upstream.
- [Перенаправления и перезапись URI (Angie)](../../Angie/angie_redirects_and_rewrites.md) — `rewrite`/`return`/`try_files`; отличие внутренней перезаписи от внешнего редиректа.