# Типовые уязвимости и ошибки конфигурации веб-серверов

**Актуально для:** Nginx 1.26+ / Angie 1.8+ / Apache 2.4.60+ / HAProxy 3.0+ / Traefik 3.x / Linux Kernel 5.15+ / 6.x

## Определения

**Path Traversal (Обход каталога / Directory Traversal)** — класс уязвимостей, позволяющий злоумышленнику получить несанкционированный доступ к файлам и каталогам файловой системы за пределами корневой директории веб-сервера (`root` / `DocumentRoot`) путем манипуляции последовательностями `../` или их закодированными эквивалентами (`%2e%2e%2f`).

**Off-by-slash (Alias Traversal)** — специфическая конфигурационная ошибка веб-серверов Nginx и Angie при использовании директивы `alias`, возникающая из-за несовпадения завершающих слешей в префиксе `location` и целевом пути файловой системы. Позволяет читать файлы родительского каталога через сцепку путей.

**HTTP Request Smuggling (Десинхронизация HTTP-запросов / HTTP Desync)** — атака на цепочку «обратный прокси → бэкенд», эксплуатирующая расхождения в интерпретации границ HTTP/1.1-запросов (заголовки `Content-Length` и `Transfer-Encoding: chunked`). Позволяет контрабандой внедрять вредоносный префикс в следующий запрос другого пользователя, вызывая кражу сессионных cookie, обход аутентификации и отравление кэша.

**CRLF Injection (HTTP Response Splitting)** — уязвимость, возникающая при некорректной подстановке несанитизированных пользовательских данных (или декодированной переменной `$uri`) в HTTP-заголовки ответа или директивы перенаправления. Символы возврата каретки и перевода строки (`\r\n` / `%0d%0a`) разделяют заголовок, позволяя злоумышленнику внедрять произвольные заголовки (например, `Set-Cookie`) или фальшивое тело ответа.

**Host Header Injection** — атака, эксплуатирующая неявную обработку заголовка `Host` сервером по умолчанию при отсутствии строгой привязки к виртуальным хостам (`default_server`), что приводит к отравлению ссылок сброса паролей, кэша и обходу межсетевых экранов.

**Default Server Drop (Отсечение мусорного трафика)** — паттерн конфигурации, при котором виртуальный хост по умолчанию явно настроен на немедленный сброс TCP-соединений (`return 444;` в Nginx/Angie или `http-request deny` в HAProxy) для любых запросов с неизвестными, отсутствующими или невалидными заголовками `Host` и IP-сканеров.

**Ловушка наследования заголовков (add_header Inheritance Trap)** — архитектурная особенность модуля заголовков Nginx/Angie: объявление хотя бы одной директивы `add_header` в дочернем контексте `location` полностью отменяет наследование всех директив `add_header`, определенных на родительских уровнях `server` и `http`.

---

## Основные концепции и архитектура

### 1. Механика Off-by-slash / Alias Traversal

Директива `alias` в Nginx выполняет строгую строковую замену префикса `location` на указанный файловый путь:

```text
[ Запрос клиента: GET /images../secret.txt ]
                      │
                      ▼
 Конфигурация с ошибкой:
 location /images {
     alias /var/www/static/;
 }
                      │
                      ▼
 Логика замены Nginx:
 1. Префикс "/images" совпадает с началом URI "/images../secret.txt"
 2. Nginx вырезает префикс "/images" -> остается "../secret.txt"
 3. Склеивает с базой alias: "/var/www/static/" + "../secret.txt"
 4. Результат: "/var/www/static/../secret.txt" -> "/var/www/secret.txt" (УТЕЧКА ФАЙЛА!)
```

Если же префикс объявлен как `location /images/` (с завершающим слешем), запрос `/images..` не совпадает с локацией и возвращает `404 Not Found`.

### 2. Архитектура HTTP Request Smuggling (CL.TE и TE.CL)

Уязвимость возникает, когда пограничный обратный прокси (Frontend) и внутренний сервер приложений (Backend) по-разному обрабатывают запросы, содержащие одновременно заголовки `Content-Length` (CL) и `Transfer-Encoding: chunked` (TE):

```text
               [ Вредоносный HTTP/1.1 запрос клиента ]
               Content-Length: 13
               Transfer-Encoding: chunked
               
               0\r\n\r\n
               GPOST / HTTP/1.1 (Контрабандный префикс)
                      │
                      ▼
       ┌──────────────────────────────┐
       │   Frontend Proxy (CL.TE)     │
       │   Ориентируется на CL = 13   │
       │   Передает весь пакет дальше │
       └──────────────┬───────────────┘
                      │
                      ▼ [ Пакет в сокете Keepalive ]
       ┌──────────────────────────────┐
       │   Backend Server (CL.TE)     │
       │   Ориентируется на TE        │
       │   Видит чанк размера 0       │
       │   (Запрос 1 завершен!)       │
       └──────────────┬───────────────┘
                      │
                      ▼ В буфере сокета остается:
               "GPOST / HTTP/1.1\r\n..."
                      │
                      ▼ Приходит легитимный Запрос 2 от другого пользователя:
               "GET /account HTTP/1.1\r\nHost: example.com\r\nCookie: session=ABC..."
                      │
                      ▼ Бэкенд склеивает остаток буфера с Запросом 2:
               "GPOST / HTTP/1.1GET /account HTTP/1.1\r\nHost: ...\r\nCookie: session=ABC..."
               (Запрос пользователя 2 искажен, его сессионные куки перехвачены!)
```

#### Классификация векторов десинхронизации:
1. **CL.TE:** Фронтенд использует заголовок `Content-Length`, а бэкенд отдает приоритет `Transfer-Encoding: chunked`.
2. **TE.CL:** Фронтенд использует `Transfer-Encoding`, а бэкенд — `Content-Length`.
3. **TE.TE (Обфускация заголовка):** Оба сервера поддерживают `Transfer-Encoding`, но один из них удается обмануть модификацией заголовка (`Transfer-Encoding: xchunked`, `Transfer-encoding: [space]chunked`), вынуждая его откатиться к `Content-Length`.

### 3. CRLF-инъекции через несанкционированное декодирование `$uri`

В Nginx существуют две системные переменные, отражающие запрашиваемый путь:
* `$request_uri`: Сырой, исходный URI в том виде, в котором он поступил из TCP-сокета от клиента (включая query string и процентное кодирование `%0d%0a`, `%20`).
* `$uri` (или `$document_uri`): Нормализованный, декодированный путь (символы `%0d%0a` раскодируются в реальные байты `\r\n`).

Если в конфигурации используется редирект вида:
```nginx
# ОШИБКА: $uri декодирован, что позволяет вставить переводы строк
return 301 https://$host$uri;
```
Злоумышленник передает запрос:
`GET /%0d%0aSet-Cookie:%20session=evil;%20Domain=.example.com HTTP/1.1`
Веб-сервер раскодирует последовательность и отправит клиенту заголовок:
```http
HTTP/1.1 301 Moved Permanently
Location: https://example.com/
Set-Cookie: session=evil; Domain=.example.com
```
Это позволяет злоумышленнику устанавливать сессионные cookies (Session Fixation) или внедрять тело ответа (XSS / Response Splitting).

---

## Практические сценарии и конфигурация

### Сценарий 1: Исправление уязвимости Off-by-slash в Nginx / Angie

**Небезопасная конфигурация:**
```nginx
# УЯЗВИМО: обращение к /static../app/config.py вернет приватный файл!
location /static {
    alias /var/www/app/static/;
}
```

**Безопасная конфигурация:**
```nginx
# БЕЗОПАСНО: обязательный завершающий слеш в обоих параметрах
location /static/ {
    alias /var/www/app/static/;
    autoindex off;
}

# Альтернативный промышленный стандарт (директива root вместо alias):
location /static/ {
    root /var/www/app;
    autoindex off;
}
```

---

### Сценарий 2: Защита от HTTP Request Smuggling на обратном прокси

Для предотвращения десинхронизации парсеров между обратным прокси и бэкендами применяются следующие правила:

**Конфигурация Nginx / Angie:**
```nginx
http {
    # 1. Отключение устаревшей поддержки HTTP/0.9
    # (Nginx по умолчанию не поддерживает HTTP/0.9 при proxy_pass)

    # 2. Принудительная буферизация тела запроса:
    # Nginx полностью вычитывает тело от клиента, пересчитывает Content-Length
    # и гарантирует отсутствие дублирующихся или противоречивых заголовков
    proxy_request_buffering on;

    # 3. Использование постоянных соединений HTTP/1.1 к бэкенду
    # со строгой санитизацией заголовка Connection
    upstream app_backend {
        zone app_backend_zone 64k;
        server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
        keepalive 32;
    }

    server {
        listen 443 ssl default_server;
        server_name example.com;

        # Защита от нестандартных и обфусцированных заголовков
        ignore_invalid_headers on;

        location / {
            proxy_pass http://app_backend;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;

            # Удаление потенциально опасных заголовков десинхронизации от клиента
            proxy_set_header Transfer-Encoding $http_transfer_encoding;
        }
    }
}
```

---

### Сценарий 3: Защита от CRLF Injection в редиректах

**Небезопасная конфигурация:**
```nginx
# УЯЗВИМО: раскодированный $uri допускает инъекцию \r\n
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$uri;
}
```

**Безопасная конфигурация:**
```nginx
# БЕЗОПАСНО: $request_uri сохраняет исходное URL-кодирование и query string
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 301 https://$host$request_uri;
}
```

---

### Сценарий 4: Защита от Host Header Injection и Default Server Drop

Запросы от интернет-сканеров и ботнетов часто приходят с IP-адресом вместо домена или произвольными заголовками `Host: evil.com`. Без хоста по умолчанию они попадут в первый попавшийся виртуальный хост.

**Конфигурация заглушки (Drop Dummy Host):**
```nginx
# 1. Заглушка для HTTP: немедленный сброс соединения без отдачи данных
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Код 444 в Nginx/Angie немедленно закрывает TCP-сокет без ответа
    return 444;
}

# 2. Заглушка для HTTPS: отсечение запросов с неизвестным SNI
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    # Самоподписанный фиктивный сертификат для отклонения рукопожатия
    ssl_certificate /etc/nginx/ssl/dummy.crt;
    ssl_certificate_key /etc/nginx/ssl/dummy.key;

    # Немедленный сброс
    return 444;
}
```

---

### Сценарий 5: Блокировка утечки служебных файлов (.git, .env, .bak)

**Конфигурация блокировки:**
```nginx
# 1. Запрет доступа к скрытым файлам и каталогам (начинающимся с точки: .git, .env, .ds_store)
# Исключение делается только для служебных каталогов ACME-валидации Let's Encrypt
location ~ /\.(?!well-known).* {
    deny all;
    access_log off;
    log_not_found off;
    return 404;
}

# 2. Запрет доступа к резервным копиям и временным файлам редакторов
location ~* (?:\.(?:bak|conf|dist|fla|in[ci]|log|psd|sh|sql|sw[op])|~)$ {
    deny all;
    access_log off;
    log_not_found off;
    return 404;
}
```

---

### Сценарий 6: Обход ловушки наследования `add_header`

**Проблема:**
```nginx
http {
    # Заголовки объявлены на уровне http
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    server {
        listen 443 ssl;
        server_name example.com;

        location /api/ {
            # ВНИМАНИЕ: добавление этого заголовка ПОЛНОСТЬЮ УДАЛЯЕТ
            # X-Frame-Options и X-Content-Type-Options для всех ответов /api/!
            add_header X-API-Version "1.0" always;
            proxy_pass http://backend;
        }
    }
}
```

**Решение через модульные сниппеты (Include Pattern):**
Создайте файл `/etc/nginx/snippets/security-headers.conf`:
```nginx
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
```

Подключайте его во все контексты:
```nginx
server {
    listen 443 ssl;
    server_name example.com;
    include /etc/nginx/snippets/security-headers.conf;

    location /api/ {
        # Подключаем сниппет повторно в location с локальными заголовками
        include /etc/nginx/snippets/security-headers.conf;
        add_header X-API-Version "1.0" always;
        proxy_pass http://backend;
    }
}
```

---

## Операции и команды валидации

### 1. Тестирование уязвимости Off-by-slash
```bash
# Попытка выхода в родительский каталог
curl -sI "http://127.0.0.1/static../"
# Ожидаемый безопасный вывод:
# → HTTP/1.1 404 Not Found (или 400 Bad Request)
# Опасный вывод:
# → HTTP/1.1 200 OK / 301 Moved Permanently
```

### 2. Тестирование CRLF-инъекции в редиректах
```bash
# Передача закодированных переводов строк в URI
curl -v "http://127.0.0.1/%0d%0aInjected-Header:%20Test" 2>&1 | grep -i "Injected-Header"
# Ожидаемый безопасный результат: заголовок отсутствует в ответе сервера:
# → (Пустой вывод)
# В строке Location символы должны оставаться закодированными:
# → Location: https://127.0.0.1/%0d%0aInjected-Header:%20Test
```

### 3. Проверка отсечения неизвестного Host (Default Server)
```bash
# Запрос с фиктивным заголовком Host
curl -v -H "Host: attacker.evil.com" http://127.0.0.1/
# Ожидаемый результат для return 444:
# → Empty reply from server (TCP RST / FIN)

# Запрос без заголовка Host (HTTP/1.0)
curl -v -0 http://127.0.0.1/
# → Empty reply from server
```

### 4. Проверка сохранения заголовков безопасности в дочерних location
```bash
# Запрос к эндпоинту, содержащему специфический add_header
curl -sI https://example.com/api/v1/health | grep -iE 'x-frame-options|x-content-type-options|x-api-version'
# Ожидаемый вывод: присутствуют ВСЕ заголовки
# → x-frame-options: DENY
# → x-content-type-options: nosniff
# → x-api-version: 1.0
```

---

## Диагностика и устранение неполадок

| Проявление проблемы | Первопричина | Метод диагностики | Способ устранения |
|---|---|---|---|
| **Утечка исходного кода или конфигураций (`.env`, `.git`)** | Отсутствует блокировка скрытых файлов, включен `autoindex on;`. | `curl -sI http://example.com/.env` возвращает код `200 OK`. | Добавить префиксный блок `location ~ /\.(?!well-known).* { deny all; return 404; }`. |
| **Заголовки безопасности пропадают на эндпоинтах API** | Сработала конфигурационная ловушка `add_header` в дочернем `location`. | Проверить ответ `curl -sI /api/`: глобальные заголовки HSTS/CSP отсутствуют. | Вынести заголовки в `/etc/nginx/snippets/security-headers.conf` и подключить через `include` внутри проблемного `location`. |
| **Клиенты обходят rate-limiting или IP-whitelist** | Сервер доверяет клиентскому `X-Forwarded-For` без директивы `set_real_ip_from`. | В логах `$remote_addr` равен IP-адресу балансировщика, а не клиента. | Настроить `set_real_ip_from <CIDR_балансировщика>; real_ip_header X-Forwarded-For; real_ip_recursive on;`. |
| **Зависание соединений и утечка сессий (Request Smuggling)** | Рассинхронизация парсеров CL.TE между прокси и upstream. | Алерты WAF на двойные заголовки `Transfer-Encoding`, ошибки `400 Bad Request` в логах бэкенда. | Включить `proxy_request_buffering on;`, принудительно использовать `proxy_http_version 1.1;` и удалять `Connection: close`. |
| **Сканеры уязвимостей находят внутренние пути по кодам 403** | Блокировка директивой `deny all;` выдает существование пути кодом `403 Forbidden`. | Сканер определяет наличие `/admin` по статусу `403` вместо `404`. | Заменять код ошибки: `deny all; return 404;` либо `error_page 403 =404 /404.html;`. |

---

## Лучшие практики

1. **Никогда не используйте `$uri` в `proxy_pass` и директивах `return`:** Использование раскодированного `$uri` открывает путь к Path Traversal (`%2e%2e%2f`) и CRLF-инъекциям. Для редиректов всегда применяйте `$request_uri`.
2. **Всегда задавайте виртуальный хост по умолчанию (`default_server`):** Сервер обязан немедленно сбрасывать немаршрутизируемый трафик (`return 444;`). Это снижает нагрузку на CPU от автоматизированных сканеров интернета и блокирует атаки на подмену Host.
3. **Строго проверяйте завершающие слеши в директиве `alias`:** Если путь в `location` оканчивается слешем (`/path/`), то и значение директивы `alias` обязано заканчиваться слешем (`/data/path/`). Предпочтительнее использовать директиву `root`.
4. **Используйте флаг `always` во всех директивах `add_header`:** Заголовки безопасности обязаны отправляться на всех статус-кодах, включая страницы ошибок (404, 500, 502), исключая возможность встраивания страниц ошибок в фишинговые `<iframe>`.
5. **Отключайте баннеры версий серверов:** Скрывайте детали операционной системы и точные версии демонов (`server_tokens off;` в Nginx/Angie, `ServerTokens Prod` в Apache), усложняя первичное профилирование инфраструктуры атакующими.

---

## Дополнительная информация

### См. также

- **[Безопасность веб-сервера Nginx и Angie](../Nginx/Security/nginx_security_guide.md)** — эшелонированная безопасность, интеграция WAF (ModSecurity / Coraza), защита от DoS.
- **[Заголовки безопасности в Angie](../Angie/angie-security-headers.md)** — детальный разбор директивы `add_header`, HSTS, CSP и спецификаций COOP/COEP/CORP.
- **[Сравнение веб-серверов и обратных прокси](./webserver_comparison.md)** — архитектурные различия моделей обработки запросов и безопасность.
- **[Защита веб-серверов от ботов](./bot_protection.md)** — фильтрация ботнетов, эвристический анализ User-Agent и интеграция с fail2ban.
- **[Rate Limiting для веб-серверов](./webserver_rate_limiting.md)** — алгоритмы ограничения частоты запросов и защита от перегрузок.
- **[Диагностика веб-серверов (Troubleshooting)](./webserver_troubleshooting.md)** — поиск и локализация сетевых и прикладных ошибок.
- **[Директива location: основы и приоритеты](../Nginx/Core/Location/basics.md)** — алгоритмы сопоставления префиксов и регулярных выражений.
- **[Proxy Protocol в сетевой архитектуре](../../Networking/Protocols/proxy_protocol.md)** — трансляция исходных IP-адресов через L4-балансировщики.
