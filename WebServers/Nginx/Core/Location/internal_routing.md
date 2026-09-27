# Nginx: внутренняя маршрутизация

## Определения

**Внутренняя маршрутизация (Internal routing)** — механизм Nginx, при котором запросы перенаправляются внутри сервера без участия клиента. Клиент не получает HTTP-редирект (301/302), и URL в браузере остается неизменным.

**Именованный `location` (`@name`)** — блок `location`, идентифицируемый именем после символа `@`, не участвующий в стандартном сопоставлении URI и вызываемый только явно через `try_files`, `error_page`, `rewrite ... last` или `X-Accel-Redirect`.

**Внутренний запрос** — запрос, генерируемый самим Nginx (через `rewrite`, `try_files`, `error_page`, `X-Accel-Redirect`, `auth_request`, `mirror`), без участия внешнего клиента.

**Подзапрос (Subrequest)** — внутренний запрос Nginx к другому `location`, выполняемый параллельно или последовательно основному запросу.

**Директива `internal`** — ограничивает доступ к `location` только внутренними запросами Nginx. Прямой запрос от клиента возвращает `404 Not Found` (начиная с версии 1.25.x; в более старых версиях мог возвращаться `403`).

**Директива `error_page`** — механизм обработки ошибок через внутренние редиректы.

**Заголовок `X-Accel-Redirect`** — позволяет бэкенду инициировать отдачу файла самим Nginx.

**`recursive_error_pages`** — директива, позволяющая продолжать внутренние перенаправления, если сама страница ошибки вызывает новую ошибку.

---

## Базовые концепции

### Жизненный цикл внутреннего запроса

При внутренней маршрутизации Nginx выполняет запрос к целевому `location` так, как будто это новый входящий запрос, но с сохранением части контекста исходного запроса. Ключевые этапы:

1. **Генерация внутреннего запроса:** Директивы `try_files`, `error_page`, `rewrite ... last` или заголовок `X-Accel-Redirect` от бэкенда создают новый внутренний запрос.
2. **Выбор location:** Nginx повторно выполняет алгоритм сопоставления `location` по новому URI. Подробности алгоритма — в **[Директива location: основы и приоритеты](./basics.md)**.
3. **Обработка:** Выбранный блок обрабатывает запрос. Если обработка завершается успешно, ответ возвращается клиенту.
4. **Ограничение глубины:** Nginx жестко ограничивает количество внутренних перенаправлений **10** на один запрос. При превышении возвращается ошибка `500 Internal Server Error`.

### Именованные location (`@name`)

Именованные `location` не участвуют в обычном сопоставлении URI. Они вызываются только явно через другие директивы.

```nginx
location / {
    try_files $uri $uri/ @backend;
}

location @backend {
    proxy_pass http://upstream_app;
}
```

**Особенности:**
- **Синтаксис:** `location @имя { ... }` — имя начинается с символа `@`.
- **Переменные:** Переменная `$uri` в именованном `location` сохраняет значение URI **исходного запроса**, а не путь именованного блока. Это важно при использовании `try_files`.
- **Ограничения:** В именованных `location` нельзя использовать директивы, создающие ответ напрямую (например, `return` в старых версиях), хотя в актуальных версиях Nginx это разрешено.

### Директива `internal`

Директива `internal` внутри блока `location` делает его доступным только для внутренних перенаправлений. Внешний запрос вернет `404 Not Found`.

```nginx
location /internal_files/ {
    internal;
    alias /data/secure/;
}
```

**Случаи использования:**
- Защита статики, отдаваемой через `X-Accel-Redirect`.
- Защита страниц ошибок, которые не должны вызываться напрямую.
- Внутренние API-эндпоинты для модуля `auth_request`.

### Наследование и переменные в подзапросах

При использовании внутренней маршрутизации важно понимать поведение переменных:

1. **Наследование заголовков:** По умолчанию подзапросы наследуют заголовки исходного запроса. Чтобы избежать передачи лишних данных, используйте `proxy_pass_request_body off;` и `proxy_set_header Content-Length "";`.
2. **Переменные контекста:** Некоторые переменные (например, `$request_uri`) остаются неизменными, в то время как другие (`$uri`) меняются на путь внутреннего запроса.

### Лимиты и предотвращение циклов

Nginx ограничивает глубину внутренней маршрутизации для предотвращения бесконечных циклов:
- **Максимум 10 внутренних перенаправлений** на один запрос.
- При превышении возвращается ошибка `500 Internal Server Error`.

```bash
# Пример ошибки в логе при зацикливании
# → rewrite or internal redirection cycle while internal redirection to "/index.html"
```

### Рекурсивные страницы ошибок

Если сама страница ошибки вызывает ошибку, Nginx возвращает стандартную заглушку. Директива `recursive_error_pages` позволяет продолжать внутренние перенаправления.

```nginx
server {
    recursive_error_pages on;
    error_page 404 /404.php;

    location = /404.php {
        internal;
        fastcgi_pass unix:/run/php/php-fpm.sock;
    }
}
```

### Директива `post_action`

Малоизвестная директива, позволяющая выполнить внутренний подзапрос **после** того, как основной ответ был отправлен клиенту.

```nginx
location /upload {
    proxy_pass http://storage;
    post_action @cleanup;
}

location @cleanup {
    internal;
    proxy_pass http://worker/clean-tmp;
}
```

> **Важно:** Директива `post_action` устарела и не рекомендуется к использованию в новых конфигурациях. Для асинхронных операций используйте модуль `mirror`.

---

## Практические сценарии

### Сценарий 1: Управление отдачей файлов бэкендом (`X-Accel-Redirect`)

Бэкенд-приложение проверяет права доступа и решает, какой файл отдать, отправляя заголовок `X-Accel-Redirect`. Nginx перехватывает его и отдает файл сам (Zero-Copy).

```nginx
# Конфигурация Nginx
location /internal_files/ {
    internal;
    root /var/www/protected;
    # Префикс /internal_files/ должен соответствовать заголовку от бэкенда
}

location /download {
    proxy_pass http://app_server;
}
```

**Логика:**
1. Клиент запрашивает `/download`.
2. Бэкенд возвращает заголовок `X-Accel-Redirect: /internal_files/report.pdf`.
3. Nginx отменяет текущую обработку и начинает поиск в `location /internal_files/`.
4. Файл отдается напрямую с диска.

### Сценарий 2: Рекурсивные страницы ошибок

```nginx
server {
    recursive_error_pages on;
    error_page 404 /404.php;

    location = /404.php {
        internal;
        fastcgi_pass unix:/run/php/php-fpm.sock;
    }
}
```

### Сценарий 3: Внутренняя проверка авторизации (`auth_request`)

Модуль `auth_request` выполняет внутренний подзапрос для проверки прав доступа.

```nginx
location /private/ {
    auth_request /auth-verify;
    root /var/www/private;
}

location = /auth-verify {
    internal;
    proxy_pass http://auth_service/validate;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
}
```

### Сценарий 4: Возврат JSON при ошибках API

Для API ошибки должны быть в формате JSON.

```nginx
server {
    error_page 404 = @json_404;

    location @json_404 {
        internal;
        default_type application/json;
        return 404 '{"status": 404, "message": "Not Found"}';
    }
}
```

### Сценарий 5: Maintenance-режим через `internal` и `error_page`

Полностью управляемый режим обслуживания, при котором все запросы получают страницу maintenance вместо прокси-ответа. Подробный разбор — в **[Maintenance-режим в Nginx](../../Scenarios/nginx_maintenance_mode.md)**.

### Сценарий 6: Дублирование трафика (`mirror`)

Модуль `mirror` выполняет параллельный подзапрос для сбора метрик или тестирования бэкенда без влияния на основной ответ.

```nginx
location / {
    proxy_pass http://backend;
    mirror /mirror;
    mirror_request_body off;
}

location = /mirror {
    internal;
    proxy_pass http://monitoring_backend;
    proxy_set_header X-Original-URI $request_uri;
}
```

---

## Операции и команды

### Валидация конфигурации

```bash
# Проверка синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Просмотр объединенного конфига
nginx -T | grep -n "location"
# → 45: location ^~ /assets/ {
# → 52: location ~ \.php$ {
# → 58: location / {

# Graceful reload — без потери соединений
nginx -s reload
# → signal processed
```

### Отладка внутренних редиректов

```bash
# Включение debug-лога в конфигурации:
# error_log /var/log/nginx/error.log debug;

# После reload в логе появляются записи:
# → *12345 using location "/api/v1/" for "/api/v1/users"
# → *12345 http script var: "$uri" = "/api/v1/users"

# Включение логирования rewrite (только для контекста server)
# server { rewrite_log on; }
```

### Проверка через curl

```bash
# Проверить заголовки ответа
curl -sI http://nginx-host/download
# → HTTP/1.1 200 OK
# → X-Accel-Redirect: /internal_files/report.pdf

# Проверить код ответа при прямом запросе к internal location
curl -s -o /dev/null -w "%{http_code}" http://nginx-host/internal_files/report.pdf
# → 404

# Проверить работу auth_request
curl -s -o /dev/null -w "%{http_code}" http://nginx-host/private/ -H "Host: example.com"
# → 200 (если auth_service вернул 2xx)
# → 403 (если auth_service вернул 4xx)
```

### Мониторинг

```bash
# Проверка stub_status
curl -s http://localhost/nginx_status
# → Active connections: 1
#   server accepts handled requests
#   10 10 20
#   Reading: 0 Writing: 1 Waiting: 0

# Поиск URL с наибольшим количеством ошибок
awk '$9 ~ /^[45]/ {print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10
```

### Управление правами (sysadmin)

```bash
# Установка владельца для корневого каталога сайта
chown -R www-data:www-data /var/www/html

# Установка прав: директории 755, файлы 644
find /var/www/html -type d -exec chmod 755 {} \;
find /var/www/html -type f -exec chmod 644 {} \;

# Удаление прав на запись для группы и остальных
chmod -R go-w /var/www/html

# Проверка контекста SELinux
ls -Z /var/www/html/

# Установка контекста для веб-контента (SELinux)
chcon -R -t httpd_sys_content_t /var/www/html/

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
| `404` при прямом запросе к защищенному пути | Отсутствует директива `internal` или запрос идет не через внутренний механизм | Добавить `internal;` в блок `location` |
| `500` с сообщением о цикле | Превышен лимит внутренних перенаправлений (10) или `try_files` вызывает тот же `location` | Использовать именованный `location @fallback` вместо URI |
| `403` вместо `404` для `internal` location | Версия Nginx older than 1.25.x (в новых версиях возвращается 404) | Обновить Nginx или принимать поведение как особенность версии |
| Файл не отдается через `X-Accel-Redirect` | Путь в заголовке не совпадает с префиксом `location` или неверный `root`/`alias` | Проверить согласованность путей и завершающие слэши |
| `auth_request` не работает | Модуль не скомпилирован или отсутствует `internal` у проверочного location | Проверить `nginx -V` на наличие `--with-http_auth_request_module` |
| Подзапросы теряют query string | В `try_files` используется URI без `$is_args$args` | Добавить `$is_args$args` в fallback URI |
| Maintenance-страница кэшируется | Отсутствует `Cache-Control: no-store` в `location = /maintenance.html` | Добавить заголовок с модификатором `always` |

### Диагностические команды

```bash
# Определить фактический порядок location после include
nginx -T | grep -n "location"

# Включить debug-лог для отслеживания выбора location
# error_log /var/log/nginx/error.log debug;

# После reload в логе:
# → *12345 using location "/api/v1/" for "/api/v1/users"

# Проверить переменную document_root для отладки
# location /test/ {
#     default_type text/plain;
#     return 200 "document_root: $document_root\nuri: $uri\n";
# }

# Просмотр логов доступа
tail -f /var/log/nginx/access.log | grep "\.\(css\|js\|png\|jpg\)"

# Анализ ошибок доступа
grep "denied" /var/log/nginx/error.log

# Проверка, что модуль auth_request включен
nginx -V 2>&1 | grep -o "http_auth_request_module"
# → http_auth_request_module
```

### Распространённые проблемы с `try_files`

1. **Бесконечный редирект:** `try_files $uri $uri/ /index.html` внутри `location /` вызывает `/index.html`, который снова попадает в тот же `location` и снова вызывает `try_files`.
   - **Решение:** Добавьте `index index.html;` или используйте именованный `location @fallback`.

2. **Потеря параметров запроса:** `try_files` передаёт только URI, query string отбрасывается.
   - **Решение:** Используйте `$is_args$args` в fallback: `try_files $uri $uri/ @backend;` и в `location @backend { proxy_pass http://backend$request_uri; }`.

3. **Неверный `alias`:** В `location /static/ { alias /data/files; }` запрос `/static/file.txt` ищет файл по пути `/data/filesfile.txt` (отсутствует слэш).
   - **Решение:** Убедитесь, что `alias` заканчивается слэшем: `alias /data/files/;`.

---

## Лучшие практики

### Безопасность

1. **Используйте `internal`** для защищенных путей, доступных только через `X-Accel-Redirect`, `error_page` или `auth_request`. Прямой запрос всегда возвращает `404`.
2. **Всегда добавляйте `internal`** к location для страниц ошибок (`error_page`), чтобы предотвратить прямой доступ.
3. **Используйте `proxy_pass_request_body off;`** и **`proxy_set_header Content-Length "";`** для auth_request, чтобы не передавать тело запроса на проверку.
4. **Устанавливайте `merge_slashes on;`** (по умолчанию) для предотвращения атак обхода ограничений через двойные слэши.
5. **Используйте `limit_except`** для запрета нежелательных HTTP-методов на API-эндпоинтах.
6. **Применяйте `server_tokens off;`** для сокрытия версии Nginx.

### Производительность

1. **Используйте именованные locations** для fallback-механизмов (`try_files`) вместо дублирования конфигурации.
2. **Включайте `pcre_jit on;`** в контексте `main` для ускорения обработки регулярных выражений.
3. **Для статики через `X-Accel-Redirect`** используйте `sendfile on;` и `tcp_nopush on;` для Zero-Copy отдачи.
4. **Настраивайте `limit_req` и `limit_conn`** на уровне `location` для защиты чувствительных эндпоинтов.
5. **Используйте `access_log off;`** для локаций с высокой частотой запросов к несуществующим ресурсам.

### Эксплуатация (SRE/sysadmin)

1. **Валидация перед reload:** Всегда выполняйте `nginx -t` перед `nginx -s reload`. Ошибка в синтаксисе не затрагивает уже работающий Nginx.
2. **Ведение логов:** Настройте раздельные логи для статики и динамики, чтобы быстро диагностировать проблемы:
   ```nginx
   log_format static '$remote_addr - $remote_user [$time_local] '
                     '"$request" $status $body_bytes_sent '
                     '"$http_referer" "$http_user_agent"';

   location ~* \.(css|js|png|jpg|gif|ico|svg|woff2?)$ {
       access_log /var/log/nginx/static.access.log static;
   }
   ```
3. **Мониторинг:** Используйте `stub_status` для отслеживания активных соединений. Подробнее — в **[Диагностика Nginx](../../Operations/nginx_troubleshooting.md)**.
4. **Ротация логов:** Настройте `logrotate` для предотвращения заполнения диска логами внутренних редиректов.
5. **Права доступа:** Nginx работает от пользователя `www-data` (Debian/Ubuntu) или `nginx` (RHEL/CentOS). Убедитесь, что у этого пользователя есть права на чтение файлов, отдаваемых через `X-Accel-Redirect`, и права на выполнение для каталогов в пути.
6. **Версионирование конфигурации:** Храните конфиги в `git`, применяйте через CI/CD с автоматическим `nginx -t` и rollback.
7. **Разделение ответственности:** Отдачу статики с TLS-терминацией лучше оставить на Nginx, а загрузку пользовательских файлов — вынести в отдельный виртуальный хост для изоляции политик безопасности.

### Наблюдаемость

1. **Кастомные заголовки для отладки:** Используйте `add_header X-Matched-Location "..." always;` для быстрой идентификации обрабатывающего блока в production.
2. **Раздельные логи по типам:** Отдельные `log_format` для статики, API и ошибок.
3. **Метрики:** Подключите `stub_status` или `vts` для сбора метрик по location-блокам.

---

## Дополнительная информация

### См. также

- **[Директива location: основы и приоритеты](./basics.md)** — алгоритмы выбора и приоритеты.
- **[Rewrite правила и try_files](../nginx_rewrite_rules_and_try_files.md)** — манипуляции с URI.
- **[Maintenance-режим в Nginx](../../Scenarios/nginx_maintenance_mode.md)** — управление обслуживанием через `internal` и `error_page`.
