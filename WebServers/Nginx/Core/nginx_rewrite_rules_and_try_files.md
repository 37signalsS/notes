# Перенаправления и перезапись URI в Nginx

## Определения

Манипуляция URI (Uniform Resource Identifier — унифицированный идентификатор ресурса) — ключевая задача при обработке входящих запросов. В [Nginx](./nginx_overview.md) для этого используются директивы `rewrite`, `return` и `try_files`.

- **Rewrite (перезапись):** внутреннее изменение URI запроса на стороне сервера. Браузер клиента не знает об этом изменении.
- **Redirect (редирект):** внешнее перенаправление. Сервер отправляет клиенту ответ (обычно с кодом `3xx`), указывающий на новый URL (Uniform Resource Locator — унифицированный определитель местонахождения ресурса), по которому браузер должен выполнить новый запрос.

Концепции и примеры, описанные в этом файле, в равной степени применимы к [Angie](../../Angie/angie_overview.md), являющемуся форком Nginx. Подробности — в разделе [Перенаправления и перезапись URI в Angie](../../Angie/angie_redirects_and_rewrites.md).

---

## Базовые концепции

### Директива `rewrite`

Используется для изменения URI запроса на основе регулярных выражений PCRE (Perl Compatible Regular Expressions — Perl-совместимые регулярные выражения).

**Синтаксис:** `rewrite regex replacement [flag];`

| Параметр | Описание |
| :--- | :--- |
| `regex` | Регулярное выражение для сопоставления с URI (без GET-параметров) |
| `replacement` | URI, на который будет перезаписан запрос; захваченные группы доступны как `$1`, `$2` |
| `flag` | Определяет дальнейшее поведение: `last`, `break`, `redirect`, `permanent` |

**Флаги `rewrite`:**

| Флаг | Тип | Поведение |
| :--- | :--- | :--- |
| `last` | internal | Прекращает обработку текущих rewrite-правил, начинает новый поиск `location` с изменённым URI |
| `break` | internal | Прекращает обработку rewrite, остаётся в текущем `location` с изменённым URI |
| `redirect` | external | Возвращает код `302 Found` (временный редирект) |
| `permanent` | external | Возвращает код `301 Moved Permanently` (постоянный редирект) |

### Директива `return`

Более простой и быстрый способ завершить обработку и отправить ответ, включая редиректы. Предпочтительнее `rewrite` для простых перенаправлений, так как не задействует движок регулярных выражений.

**Синтаксис:**

- `return code URL;`
- `return code [text];`

### Директива `try_files`

Проверяет существование файлов или директорий в указанном порядке и использует первый найденный ресурс. Если ничего не найдено, выполняется последнее действие. Идеально подходит для реализации «красивых» URL (ЧПУ — человекопонятный URL).

Помимо статичных путей, директива может работать с переменными, что позволяет реализовать сложную логику (см. [сценарий A/B-тестирования](#аб-тестирование-с-помощью-map) ниже).

**Синтаксис:**

- `try_files file ... uri;`
- `try_files file ... =code;`

### Условная логика: `map` vs `if`

#### Директива `map`

`map` — безопасная, производительная и рекомендуемая альтернатива `if` для создания условной логики. Позволяет создавать переменные на основе значений других переменных. Объявляется в блоке `http`.

**Синтаксис:**

```nginx
map $source_variable $new_variable {
    default value;
    "string" value1;
    ~regex   value2;
}
```

#### «If is Evil»: предостережение об использовании `if`

Использование `if` в Nginx **крайне не рекомендуется** (концепция «If is Evil»). Это может приводить к непредсказуемому поведению и проблемам с производительностью. Почти всегда существует лучшая альтернатива: `try_files`, `map` или [директива `location`](./Location/basics.md).

**Пример (не рекомендуется):**

```nginx
location / {
    if (!-f $request_filename) {
        rewrite ^(.*)$ /index.php?$1 last;
    }
}
```

Данный пример корректно заменяется на `try_files $uri $uri/ /index.php?$args;`.

> **Безопасное использование `if`:** директивы `return` и `rewrite ... last` — одни из немногих, которые надёжно работают внутри `if`.

---

## Практические сценарии

### Редирект на HTTPS / новый URL

**Задача:** перенаправить трафик с HTTP (HyperText Transfer Protocol) на HTTPS (HyperText Transfer Protocol Secure) или со старого URL на новый. Тесно связано с настройкой [SSL/TLS](../Security/TLS_SSL/nginx_tls_ssl_overview.md).
SSL (Secure Sockets Layer — уровень защищённых сокетов) / TLS (Transport Layer Security — протокол защиты транспортного уровня).

**Решение (`return`):**

```nginx
# 301 — HTTP → HTTPS
server {
    listen 80;
    server_name your_domain.com;
    return 301 https://$host$request_uri;
}

# 301 — старый URL → новый
location = /old-contacts {
    return 301 /contacts;
}
```

**Решение (`rewrite` с флагами):**

```nginx
# 302 — временный редирект
rewrite ^/tmp/(.*)$ /final/$1 redirect;

# 301 — постоянный редирект (браузеры агрессивно кэшируют — используйте redirect при отладке)
rewrite ^/username/(.*)$ /users/$1 permanent;
```

### Внутренняя перезапись URI

**Задача:** изменить URI «на лету» без уведомления браузера.

**Решение (`rewrite` с флагом `last`):**

```nginx
rewrite ^/old/(.*)$ /new/$1 last;
```

Nginx прекращает обработку текущих правил и начинает новый поиск `location` с изменённым URI.

### «Красивые» URL (ЧПУ) для фреймворков

**Задача:** все запросы, не соответствующие статическим файлам, направить на единую точку входа (например, `index.php`). Паттерн используется в связке с [балансировкой нагрузки](../Proxy/Load_Balancing/overview_concepts.md) и [кэшированием](../Performance/Caching/proxy_caching.md).

**Решение (`try_files`):**

```nginx
location / {
    try_files $uri $uri/ /index.php?$args;
}
```

**Разбор аргументов:**

| Аргумент | Описание |
| :--- | :--- |
| `$uri` | Поиск файла по URI запроса (`/about.html` → `/var/www/html/about.html`) |
| `$uri/` | Поиск каталога (`/blog/` → `/var/www/html/blog/`) |
| `/index.php?$args` | Fallback — передача запроса на `index.php` с оригинальными GET-параметрами |

Переменная `$args` содержит все параметры запроса после `?`. Пример: `/post/42?comments=1` → `/index.php?comments=1`.

### Выборочное логирование редиректов через `map`

**Задача:** логировать редиректы в отдельный файл, не засоряя основной лог доступа.

**Решение:**

```nginx
http {
    log_format redirect_log '$remote_addr [$time_local] "$request" -> "$sent_http_location"';

    map $status $is_redirect {
        ~^3   1;
        default 0;
    }

    server {
        access_log /var/log/nginx/redirects.log redirect_log if=$is_redirect;
        access_log /var/log/nginx/access.log main if=!$is_redirect;
    }
}
```

`map` создаёт переменную `$is_redirect`, равную `1` при статусе `3xx`. Условный `access_log` разделяет потоки записи.

### А/Б-тестирование с помощью `map`

**Задача:** показывать разным пользователям разные версии страницы на основе `cookie`, не изменяя URL.

**Решение:**

```nginx
http {
    map $cookie_version $ab_test_page {
        default /index-old.html;
        new     /index-new.html;
    }

    server {
        listen 80;
        server_name site1.local;
        root /var/www/html;

        location / {
            try_files $ab_test_page =404;
        }
    }
}
```

`map` (блок `http`) читает `$cookie_version` и вычисляет `$ab_test_page` один раз за запрос. `try_files` (блок `location`) отдаёт вычисленный файл. Логика определения переменной вынесена за пределы `location`, что обеспечивает высокую производительность.

---

## Дополнительная информация

### Отладка rewrite-правил

Для диагностики работы правил перезаписи:

1. Включите логирование rewrite в блоке `server` или `http`:

   ```nginx
   rewrite_log on;
   ```

2. Установите уровень логирования `notice` для `error_log` (по умолчанию — `error`, rewrite-логи не видны):

   ```nginx
   error_log /var/log/nginx/error.log notice;
   ```

После перезагрузки конфигурации в `error.log` появятся сообщения вида:

```
... rewriting: "/old/page" -> "/new/page"
... rewritten redirect: "/new/page"
```

### Рекомендации по выбору директивы

| Задача | Рекомендуемая директива |
| :--- | :--- |
| Простой редирект (HTTP → HTTPS, старый URL → новый) | `return` |
| Редирект с регулярными выражениями | `rewrite ... redirect/permanent` |
| Внутренняя перезапись с поиском нового `location` | `rewrite ... last` |
| Внутренняя перезапись без смены `location` | `rewrite ... break` |
| «Красивые» URL, fallback на фронт-контроллер | `try_files` |
| Условная логика (переменные, cookie, заголовки) | `map` + `try_files`/`return` |
| Проверка существования файла (устаревший подход) | **Не используйте** `if (!-f ...)` |

### См. также

- [Директива location](./Location/basics.md)
- [Внутренняя маршрутизация](./Location/internal_routing.md)
- [Установка и базовая настройка Nginx](./nginx_setup.md)
- [Кэширование прокси](../Performance/Caching/proxy_caching.md)
- [Перенаправления и перезапись URI в Angie](../../Angie/angie_redirects_and_rewrites.md)
