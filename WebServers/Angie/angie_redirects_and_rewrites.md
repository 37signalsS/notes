# Перенаправления и перезапись URI в Angie

## Определения

Механизмы перенаправлений и перезаписи URI в **[Angie](./angie_overview.md)** полностью совместимы с **[Nginx](../Nginx/Core/nginx_overview.md)** и базируются на движке регулярных выражений PCRE. Angie расширяет базовый набор директив для упрощения сложной маршрутизации и автоматизации.

- **Rewrite (перезапись)** — внутреннее изменение URI запроса сервером. Процесс происходит прозрачно для клиента: браузер продолжает отображать оригинальный URL, но сервер обрабатывает запрос по новому пути.
- **Redirect (редирект)** — внешнее перенаправление. Сервер возвращает ответ с кодом `3xx` (например, 301 или 302) и заголовком `Location`, заставляя браузер выполнить новый запрос по другому адресу.
- **Try_files (проверка)** — механизм последовательной проверки существования файлов или директорий на диске с последующим выполнением внутреннего перенаправления или возвратом кода ошибки.
- **Auto_redirect (Angie 1.10.0+)** — директива, автоматически перенаправляющая запрос с `/path` на `/path/` (301), если соответствует существующей директории.
- **Volatile** — параметр директивы `map`, отключающий кэширование значения переменной на запрос. Применяется, когда переменная должна пересчитываться после внутреннего перенаправления.
- **Map** — директива контекста `http`, создающая переменные на основе значений других переменных. В Angie поддерживает `volatile` и внешние файлы через `include`.
- **Internal redirect cycle** — ошибка `500`, возникающая при превышении лимита внутренних перенаправлений (10 в Nginx/Angie).

Базовая логика и синтаксис подробно описаны в справочнике **[Nginx: Rewrite, Redirect и try_files](../Nginx/Core/nginx_rewrite_rules_and_try_files.md)**.

## Основные концепции

### Порядок выполнения и флаги rewrite

Директивы `rewrite` выполняются в зависимости от контекста:

1. **Контекст `server`:** `rewrite` выполняется до поиска `location`. Если URI изменен, поиск локации производится по новому значению.
2. **Контекст `location`:** директивы выполняются последовательно сверху вниз.

**Флаги управления** определяют дальнейшую логику обработки:

| Флаг | Контекст | Поведение |
| :--- | :--- | :--- |
| **`last`** | `server`, `location` | Останавливает обработку правил. Angie инициирует новый цикл поиска `location` с измененным URI. |
| **`break`** | `location` | Останавливает обработку правил `rewrite` в текущем блоке. Angie продолжает обработку в этом же `location` без повторного поиска. |
| **`redirect`** | любой | Возвращает временный редирект (`302 Found`). |
| **`permanent`** | любой | Возвращает постоянный редирект (`301 Moved Permanently`). |

> **Предупреждение:** Angie ограничивает количество внутренних перенаправлений до **10**. Циклы, вызванные некорректными правилами `last`, приводят к ошибке `500 Internal Server Error`.

### Обработка строки запроса (query string)

Если строка `replacement` в `rewrite` содержит аргументы, они объединяются с исходными. Чтобы полностью заменить аргументы или избавиться от них, в конце строки замены ставится `?`:

```nginx
# Исходный: /users/123?src=web -> Результат: /profile/123 (без аргументов)
rewrite ^/users/(.*)$ /profile/$1? permanent;
```

Для анализа оригинального и измененного URI используются переменные `$request_uri` (оригинал, неизменяемый) и `$uri` (текущий нормализованный, изменяется при `rewrite`).

### Angie-специфичные расширения

Angie вводит возможности, упрощающие конфигурацию и снижающие дублирование:

| Функция | Описание | Версия |
| :--- | :--- | :--- |
| **Несколько шаблонов в location** | Возможность указывать список регулярных выражений в одной директиве. | 1.3.0+ |
| **Автоматические редиректы** | Директива `auto_redirect` для управления слешем в конце пути. | 1.10.0+ |
| **Volatile в map** | Отключение кэширования значения переменной при каждом обращении. | Все версии |
| **Директива `goto`** | Безусловный внутренний переход в именованный `location` без изменения `$uri` и без полного перезапуска алгоритма сопоставления. | 1.12.0+ |

Для детального изучения алгоритма выбора `location`, директив `goto`, `auto_redirect`, `internal` и `try_files` см.:
*   **[Директивы location в Angie](./angie_location_directives.md)** — приоритеты, расширения Angie, именованные локации.
*   **[Переменные в Angie](./angie_variables.md)** — `map`, `if`, `volatile`, `geo`, внешние файлы.

### Жизненный цикл rewrite/redirect

При обработке запроса, содержащего директивы `rewrite` или `return`, Angie проходит следующие этапы:

1. **Прием запроса:** сервер определяет блок `server` по `Host` и порту.
2. **Server-level rewrite:** если `rewrite` объявлен в контексте `server`, выполняется до выбора `location`.
3. **Выбор location:** по нормализованному URI выбирается наиболее специфичный блок.
4. **Location-level rewrite:** выполнение `rewrite`/`return`/`try_files` внутри `location`.
5. **Внутреннее перенаправление:** при флаге `last` или `try_files` инициируется новый цикл выбора `location` по измененному URI.
6. **Ответ клиенту:** при флагах `redirect`/`permanent` клиент получает `3xx` с заголовком `Location`. При `break` запрос продолжает обработку в текущем `location`.

### Производительность

- **`return` всегда предпочтительнее `rewrite`** для простых редиректов: не задействует PCRE и работает на уровне return-фазы.
- **PCRE JIT:** включите `pcre_jit on;` в контексте `main` для ускорения regex-проверок в `rewrite` и `location`.
- **`map` против `if`:** `map` вычисляется лениво и кэшируется на запрос, что дешевле чем `if` с `rewrite` внутри `location`.
- **Кэширование переменных:** параметр `volatile` отключает кэш и увеличивает нагрузку на CPU. Используйте только при необходимости.

## Практические сценарии

### 1. Безусловный редирект на HTTPS

Использование `return` — самый производительный метод, так как он не задействует механизм регулярных выражений.

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    # 301 Moved Permanently — постоянный редирект для сохранения SEO-веса
    return 301 https://$host$request_uri;
}
```

**Проверка:**
```bash
curl -I http://example.com/
# → HTTP/1.1 301 Moved Permanently
# → Location: https://example.com/
```

### 2. Мульти-шаблоны в location (Angie 1.3.0+)

Позволяет объединять правила для разных путей, сокращая дублирование конфигурации.

```nginx
# Одно правило для нескольких версий API
location ~ ^/api/v[12]/|^/v[12]/api/ {
    rewrite ^/v[12]/api/(.*)$ /api/v2/$1 break;
    proxy_pass http://backend_v2;
}
```

### 3. Автоматическое управление завершающим слешем (Angie 1.10.0+)

Директива `auto_redirect` позволяет серверу автоматически перенаправлять пользователя на URI со слешем, если запрос соответствует существующей директории.

```nginx
location /docs/ {
    auto_redirect on;
    alias /var/www/documentation/;
}
# Запрос GET /docs → 301 Location: /docs/
```

### 4. Поддержка ЧПУ через try_files

Стандартный метод для SPA и PHP-приложений, исключающий использование `if`.

```nginx
location / {
    # 1. Файл 2. Директория 3. Входная точка приложения
    try_files $uri $uri/ /index.php?$args;
}
```

### 5. Высокопроизводительная маршрутизация через map

Метод `map` идеален для реализации логики на основе условий (например, по User-Agent или GeoIP) без загромождения блоков `server`.

```nginx
map $http_user_agent $is_mobile {
    default       0;
    "~*iphone|android" 1;
}

server {
    if ($is_mobile) {
        rewrite ^/$ /mobile/ last;
    }
}
```

### 6. Режим обслуживания (maintenance mode)

Используйте `map` с внешним файлом для быстрого включения/выключения режима обслуживания без редактирования основного конфига.

**Файл `/etc/angie/maps/maintenance.flag`:**
```text
# 1 — включить режим обслуживания, 0 — отключить
1
```

**Конфигурация:**
```nginx
http {
    map $uri $maintenance_mode {
        default 0;
        include /etc/angie/maps/maintenance.flag;
    }
}

server {
    listen 80;
    server_name example.com;

    location / {
        if ($maintenance_mode) {
            return 503 /maintenance.html;
        }
        proxy_pass http://backend;
    }

    location = /maintenance.html {
        internal;
        root /var/www/static;
    }
}
```

**Включение/отключение:**
```bash
# Включить
echo "1" > /etc/angie/maps/maintenance.flag
sudo systemctl reload angie

# Отключить
echo "0" > /etc/angie/maps/maintenance.flag
sudo systemctl reload angie
```

### 7. Безопасное использование `if` для redirect

Внутри `location` безопасно использовать `if` только с директивами модуля `rewrite` (`return`, `rewrite ... last/break`). Для сложной логики используйте `map`.

```nginx
http {
    # Безопасно: map в контексте http
    map $scheme $redirect_to_https {
        default 0;
        http    1;
    }
}

server {
    listen 80;
    server_name example.com;

    # Безопасно: if только с return
    if ($redirect_to_https) {
        return 301 https://$host$request_uri;
    }
}
```

### 8. Канонические редиректы по доменам

Используйте `map` для нормализации домена без дублирования блоков `server`.

```nginx
http {
    map $host $canonical_host {
        default        $host;
        "~^(www\.)?example\.com$" "example.com";
        "~^(www\.)?old-site\.com$" "example.com";
    }

    map $canonical_host $redirect_status {
        default        0;
        "~^example\.com$" 0;
    }
}

server {
    listen 80;
    server_name _;

    if ($redirect_status) {
        return 301 https://$canonical_host$request_uri;
    }

    # Обычная обработка...
}
```

### 9. Внутренний редирект с `X-Accel-Redirect`

Бэкенд принимает решение об отдаче файла, а Angie выполняет доставку напрямую с диска. Блок с `internal` недоступен извне.

```nginx
# Защищенная зона для внутренней отдачи файлов
location /protected_files/ {
    internal;
    alias /data/secure_storage/;
    add_header X-Content-Type-Options nosniff always;
}

# Бэкенд инициирует отдачу через заголовок
location /download/ {
    proxy_pass http://app_server;

    proxy_intercept_errors on;
    # Если бэкенд вернул X-Accel-Redirect: /protected_files/report.pdf
    # Angie отдаст файл напрямую из /data/secure_storage/report.pdf
}
```

### 10. Отладка правил перезаписи

Включите расширенное логирование для диагностики циклов и некорректных путей.

```nginx
server {
    rewrite_log on;
    error_log /var/log/angie/rewrite_debug.log notice;
}
```

**Пример вывода:**
```text
# /var/log/angie/rewrite_debug.log
2026/09/21 16:00:00 [notice] 12345#0: *1 rewrite: /old -> /new, server: example.com
2026/09/21 16:00:00 [notice] 12345#0: *1 rewrite: /new -> /old, server: example.com
2026/09/21 16:00:00 [error] 12345#0: *1 rewrite or internal redirection cycle while internal redirection to "/old"
```

## Операции и команды

### Валидация конфигурации

```bash
# Проверка всего конфига
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Поиск всех блоков location в активной конфигурации
angie -T | grep -n "location "
# → 45:location ^~ /static/ {
# → 62:location /api/ {
# → 78:location ~ \.php$ {
```

### Диагностика rewrite

```bash
# Тест редиректа с отслеживанием заголовков
curl -sI http://example.com/old-path
# → HTTP/1.1 301 Moved Permanently
# → Location: https://example.com/new-path

# Проверка что query string сохраняется
curl -sI "http://example.com/search?q=test&page=1"
# → Location: https://example.com/search?q=test&page=1

# Поиск циклических перенаправлений в логе
grep -E "rewrite or internal redirection cycle" /var/log/angie/error.log
# → 2026/09/21 16:00:00 [error] 12345#0: *1 rewrite or internal redirection cycle...
```

### Метрики и API

```bash
# Проверка generation после reload
curl -s http://127.0.0.1:8888/status/angie/ | jq '.generation'
# → 42  (увеличился после reload)

# Проверка статуса зон (если используются status_zone)
curl -s http://127.0.0.1:8888/status/http/status_zones/ | jq '.[] | .name'
```

### Управление сервисом

```bash
# Graceful reload (не рвет соединения)
sudo systemctl reload angie

# Просмотр ошибок конфигурации в реальном времени
sudo journalctl -u angie -f --since "2 minutes ago" | grep -E "rewrite|location|syntax"
```

## Устранение неисправностей

### Цикл внутренних перенаправлений (500)

**Симптом:** `500 Internal Server Error`, в логе `rewrite or internal redirection cycle`.

**Причина:** `rewrite ... last` создает бесконечный цикл, или `try_files`/`error_page` ссылаются друг на друга.

**Диагностика:**
```bash
grep -E "rewrite or internal redirection cycle" /var/log/angie/error.log
# → 2026/09/21 16:00:00 [error] 12345#0: *1 rewrite or internal redirection cycle...
```

**Решение:**
- Добавьте `break` вместо `last`, если не требуется повторный поиск `location`.
- Проверьте что `try_files` не ссылается на URI, который снова попадает в тот же `location` с `try_files`.
- Используйте именованные локации (`@name`) для разрыва цикла.

### Потеря query string при rewrite

**Симптом:** после `rewrite` или `return` теряются параметры запроса.

**Диагностика:**
```bash
curl -sI "http://example.com/old?utm_source=google&page=2"
# → Location: https://example.com/new  (параметры исчезли)
```

**Решение:**
- Добавьте `$args` в строку замены: `rewrite ^/old$ /new? permanent;` → `rewrite ^/old$ /new?$args permanent;`
- Или используйте `return` с переменной: `return 301 https://$host/new?$args;`

### Неожиданный 301/302

**Симптом:** клиент получает редирект, который не был настроен явно.

**Причина:** `auto_redirect on` срабатывает для существующей директории; кэширование редиректа в браузере; конфликт regex и префиксного `location`.

**Диагностика:**
```bash
# Сбросьте кэш браузера и проверьте снова
curl -sI http://example.com/api/v1/users
# → HTTP/1.1 301 Moved Permanently
# → Location: /api/v1/users/
```

**Решение:**
- Проверьте `auto_redirect` в блоке `location`.
- Используйте `map` для тонкого контроля редиректов вместо `if` в `server`.
- Добавьте модификатор `^~` для префиксного `location`, чтобы предотвратить перехват regex.

### Проблемы с `if` в `location`

**Симптом:** `if` работает непредсказуемо, блокирует `proxy_pass`, ломает `alias`.

**Причина:** Директива `if` в Nginx/Angie имеет ограниченную семантику и создает отдельный контекст выполнения.

**Решение:**
- Используйте `map` для всех условных логик, которые не являются простыми `return` или `rewrite`.
- Внутри `if` допускаются только директива модуля `rewrite` (`return`, `rewrite ... last/break`).
- Для сложной логики используйте `map` + `rewrite ... last` или `auth_request`.

### Конфликт `alias` и `try_files`

**Симптом:** `404` при использовании `alias` с `try_files`.

**Причина:** `alias` заменяет префикс URI, а `try_files` ищет файлы относительно `root`. При `location /static/` + `alias /var/www/static/` запрос `/static/photo.jpg` приводит к поиску `/var/www/static/static/photo.jpg`.

**Решение:**
- При использовании `alias` в `try_files` используйте `$request_filename` или явно укажите путь без дублирования префикса.
- Альтернатива: используйте `root` вместо `alias`.

### Переменная не обновляется после `rewrite`

**Симптом:** после внутреннего перенаправления переменная содержит устаревшее значение.

**Диагностика:**
```bash
curl -s http://localhost/test -I
# → X-Test: 1 (устаревшее значение)
```

**Решение:**
- Добавьте параметр `volatile` в `map` для переменной, которая должна пересчитываться.
- Убедитесь, что `rewrite` завершается флагом `break` или `last`.

### `rewrite_log` не работает

**Симптом:** в `error_log` нет сообщений о перезаписях.

**Причина:** уровень логирования ниже `notice`; `rewrite_log` включен в неправильном контексте.

**Решение:**
```nginx
server {
    rewrite_log on;
    error_log /var/log/angie/rewrite_debug.log notice;
}
```

## Лучшие практики

### Выбор инструмента

| Задача | Рекомендуемая директива | Преимущество |
| :--- | :--- | :--- |
| Глобальный редирект | `return 301` | Скорость (без Regex) |
| Смена префикса URI | `rewrite ... permanent` | Гибкость захвата переменных |
| Внутренняя подмена | `rewrite ... last` | Прозрачность для клиента |
| Сложные условия | `map` | Чистота конфига, масштабируемость |
| Статика и SPA | `try_files` | Исключение ошибок "If is Evil" |

### Query string

- Всегда добавляйте `$args` в `rewrite`/`return`, если требуется сохранить параметры запроса.
- Для полной очистки аргументов используйте `?` в конце строки замены.
- Проверяйте редиректы через `curl -I` с параметрами.

### Избегание циклов

- Используйте `break` вместо `last`, когда не требуется повторный поиск `location`.
- Для внутренней логики используйте именованные локации (`@name`) или `try_files`, а не цепочки `rewrite ... last`.
- Лимит внутренних перенаправлений — 10. При превышении — `500 Internal Server Error`.

### Производительность

- Включите `pcre_jit on;` в контексте `main` для ускорения regex.
- Для часто опрашиваемых путей используйте `location = /health` (точное совпадение).
- Избегайте `volatile` в `map` без необходимости — он отключает кэширование переменной.
- Используйте `return` вместо `rewrite` для всех статических редиректов.

### Безопасность

- Используйте `map` вместо множества `if` для сложной логики.
- Внутри `if` в `location` безопасно использовать только `return` или `rewrite ... last/break`.
- Для защищенных ресурсов, отдаваемых через внутренние перенаправления, используйте `internal`.
- Включайте `server_tokens off;` в контексте `http` для скрытия версии.

### Эксплуатация

- Всегда выполняйте `angie -t` перед `systemctl reload angie`.
- Включите `rewrite_log on` и `error_log ... notice` только на время отладки; в production используйте `warn` или `error`.
- Для долгоживущих редиректов (301) сохраняйте копии старых правил для аудита и отката.
- Используйте `map` с `include` для больших списков редиректов — это позволяет управлять ими без редактирования основного конфига.

## Дополнительная информация

### См. также

*   **[Nginx: Rewrite, Redirect и try_files](../Nginx/Core/nginx_rewrite_rules_and_try_files.md)** — теоретическая база, флаги `rewrite`, `try_files`, `if is evil`.
*   **[Переменные в Angie](./angie_variables.md)** — `map`, `if`, `volatile`, `geo`, внешние файлы.
*   **[Директивы location в Angie](./angie_location_directives.md)** — `auto_redirect`, `goto`, `internal`, `try_files`, приоритеты сопоставления.
