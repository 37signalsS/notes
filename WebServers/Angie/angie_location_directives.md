# Директивы location в Angie

## Определения

**Директива `location`** — фундаментальный механизм конфигурации веб-сервера Angie, определяющий логику обработки входящего HTTP-запроса в зависимости от его URI (Uniform Resource Identifier). Она отвечает за маршрутизацию трафика, применение политик безопасности, кэширования и проксирования.

**Angie** расширяет классические возможности Nginx, добавляя поддержку нескольких путей в одном блоке, нативный мониторинг через зоны состояния и упрощенные внутренние перенаправления.

**URI (Uniform Resource Identifier)** — унифицированный идентификатор ресурса, строковое обозначение пути запроса. В контексте `location` URI нормализуется перед сопоставлением: декодируются `%XX`-последовательности, схлопываются множественные слэши, разрешаются `.` и `..` (контролируется директивой `merge_slashes`).

**Префиксное дерево (Radix Tree / Trie)** — структура данных, используемая Angie для сопоставления префиксных `location`. Обеспечивает время поиска O(k), где k — длина URI, что критично для производительности под высокой нагрузкой.

**PCRE (Perl Compatible Regular Expressions)** — библиотека регулярных выражений, используемая для обработки модификаторов `~` и `~*`. Angie поддерживает JIT-компиляцию PCRE (`pcre_jit on;`) для ускорения проверки regex-паттернов.

**Модификатор `=`** — точное совпадение URI. Имеет наивысший приоритет и немедленно останавливает поиск.

**Модификатор `^~** — приоритетный префикс. Если является самым длинным совпавшим префиксом, пропускает проверку регулярных выражений.

**Модификатор `~` / `~*`** — регулярное выражение с учетом (`~`) и без учета (`~*`) регистра. Проверяются в порядке объявления в конфигурации.

**Именованный location (`@name`)** — блок, начинающийся с `@`, доступный только для внутренних перенаправлений (`try_files`, `error_page`, `goto`). Не участвует в прямом сопоставлении URI внешних запросов.

**Директива `internal`** — модификатор, ограничивающий доступ к `location` только внутренними запросами. Внешний запрос возвращает `404 Not Found`.

**Директива `limit_except`** — позволяет запретить или разрешить определенные HTTP-методы (`GET`, `POST`, `PUT`, `DELETE` и др.) внутри блока `location`.

**Директива `merge_slashes`** — контролирует схлопывание двух и более слэшей в один. По умолчанию `on`; отключение может использоваться для детекции атак по обходу ограничений, но требует аккуратного проектирования путей.

**Директива `status_zone`** — именованная зона разделяемой памяти для сбора атомарных метрик запросов к конкретному `location`. В Angie 1.12+ оптимизирована для снижения накладных расходов под высокой нагрузкой.

**Директива `goto`** — безусловный внутренний переход в именованный `location` без изменения `$uri` и без полного перезапуска алгоритма сопоставления. Введена в Angie 1.12.0.

**Multi-match** — возможность указания списка путей через пробел в одной директиве `location` (например, `location /api/v1/ /api/v2/`). Введена в Angie 1.12.0.

## Основные концепции

### Базовая логика и приоритеты

Алгоритм выбора `location` в Angie полностью наследуется от Nginx. Перед сопоставлением выполняется нормализация URI (декодирование, схлопывание слэшей, разрешение `.`/`..`). Поиск происходит по нормализованному значению:

1. **Точное совпадение (`=`):** Если URI в точности совпадает с паттерном — используется немедленно.
2. **Префиксные `location`:** Выбирается самый длинный совпавший префикс (с `^~` или без).
3. **Приоритетный префикс (`^~`):** Если самый длинный префикс имеет модификатор `^~`, поиск завершается, регулярные выражения не проверяются.
4. **Регулярные выражения (`~` / `~*`):** Проверяются в порядке объявления. Первое совпадение останавливает поиск.
5. **Префикс по умолчанию:** Если ни одно regex не совпало, используется самый длинный префиксный `location`.

Для детального изучения алгоритма и примеров используйте единый источник истины:
*   **[Директива location в Nginx: основы и приоритеты](../Nginx/Core/Location/basics.md)** — типы совпадений и пошаговый алгоритм выбора.
*   **[Лучшие практики и отладка location](../Nginx/Core/Location/best_practices.md)** — рекомендации по структурированию и предотвращению ошибок наследования.

### Специфические расширения Angie

Начиная с версии **1.12.0** (июль 2026), Angie вводит расширения, упрощающие конфигурацию и снижающие дублирование:

1. **Multi-match:** указание списка путей через пробел в одной директиве. Полезно для API-версионирования и группировки схожих ресурсов.
2. **Директива `goto`:** безусловный внутренний переход в именованный блок. В отличие от `rewrite ... last`, не инициирует повторный цикл сопоставления и не изменяет `$uri`, что снижает накладные расходы.
3. **Оптимизированные `status_zone`:** снижение contention на разделяемой памяти под высокой нагрузкой за счет атомарных операций без блокировок.

### Жизненный цикл запроса в контексте location

При обработке HTTP-запроса Angie проходит следующие этапы внутри `location`:

1. **Сопоставление:** Выбор наиболее специфичного блока по нормализованному URI.
2. **Наследование:** Применение директив из родительских контекстов (`http`, `server`), если они не переопределены в `location`.
3. **Обработка:** Выполнение логики блока (отдача статики, проксирование, редирект, аутентификация).
4. **Сбор метрик:** Если объявлена `status_zone`, инкрементация счетчиков (requests, bytes_sent, bytes_received) в разделяемой памяти.
5. **Завершение:** Возврат ответа клиенту или передача на следующий этап (error_page, try_files).

### Наследование и область видимости директив

Вложенные `location` (Nested locations) поддерживаются Angie, но являются антипаттерном. Они создают неочевидные цепочки наследования, особенно для директив `proxy_set_header`, `root` и `add_header`.

**Правило:** Используйте плоскую структуру с приоритетными префиксами (`^~`) или `include` для вынесения общих настроек.

## Практические сценарии

### 1. Объединение путей (Multi-match, v1.12+)

Позволяет избежать дублирования конфигурации для схожих ресурсов.

```nginx
# Определение одного блока для разных API-версий
location /api/v1/ /api/v2/ /internal/api/ {
    status_zone global_api_stats;
    proxy_pass http://backend_cluster;

    limit_req zone=api_limit burst=10;
}
```

### 2. Безусловные переходы через `goto` (v1.12+)

Заменяет сложные конструкции с `try_files` или `error_page` для внутренней логики. В отличие от `rewrite`, `goto` не инициирует полный цикл поиска локаций заново по измененному URI, а сразу переходит в именованный блок.

```nginx
location / {
    # Проверка наличия сессии (пример)
    if ($cookie_user_id = "") {
        goto @anonymous_landing;
    }

    proxy_pass http://app_server;
}

location @anonymous_landing {
    root /var/www/static/guest;
    try_files /index.html =404;
}
```

### 3. Нативный мониторинг и экспорт метрик

В Angie эндпоинты мониторинга настраиваются максимально просто и производительно.

```nginx
# Локация для сбора метрик Prometheus (стандарт 2026 года)
location /metrics {
    # Ограничение доступа
    allow 10.50.0.0/24; # Сеть мониторинга
    deny all;

    # Включение экспорта всех метрик (HTTP, Stream, Zones)
    prometheus all;

    # Отключаем логирование служебных запросов
    access_log off;
}

# Сбор статистики по конкретному пути
location /heavy-service/ {
    status_zone service_stats;
    proxy_pass http://heavy_backend;
}
```

### 4. Именованные локации (Named locations)

Используются для внутренних нужд сервера и недоступны напрямую извне. Начинаются с символа `@`.

```nginx
location / {
    try_files $uri $uri/ @fallback;
}

location @fallback {
    # Логика обработки, если файл не найден
    proxy_pass http://static_fallback_server;
    status_zone fallback_stats;
}
```

### 5. Защита внутренних ресурсов (`internal` и `X-Accel-Redirect`)

Директива `internal` ограничивает доступ к локации только внутренними запросами. Это основа паттерна `X-Accel-Redirect`, когда бэкенд принимает решение об отдаче файла, а Angie выполняет доставку напрямую с диска.

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

    # Перехватываем ответы от бэкенда
    proxy_intercept_errors on;

    # Если бэкенд вернул X-Accel-Redirect: /protected_files/report.pdf
    # Angie отдаст файл напрямую из /data/secure_storage/report.pdf
}
```

### 6. Ограничение HTTP-методов (`limit_except`)

Позволяет дифференцировать доступ по методам внутри одной локации. Например, разрешить `GET`/`POST` всем, а `PUT`/`DELETE` — только внутренней сети.

```nginx
location /api/ {
    # Разрешаем чтение и создание всем
    # Запись и удаление — только из подсети админов
    limit_except GET POST {
        allow 10.0.0.0/8;
        deny all;
    }

    proxy_pass http://api_backend;
    status_zone api_stats;
}
```

### 7. Отладка сопоставления (Debug matching)

Для диагностики того, какой `location` обработал запрос в production, используйте кастомные заголовки. Angie поддерживает `add_header ... always`, чтобы заголовок отправлялся даже при ошибках.

```nginx
# Отладка: каждый location помечает себя
location ^~ /api/v2/ {
    add_header X-Debug-Location "API-V2" always;
    add_header X-Debug-Upstream "backend_v2" always;
    proxy_pass http://backend_v2;
}

location /api/ {
    add_header X-Debug-Location "API-DEFAULT" always;
    proxy_pass http://backend_default;
}
```

Проверка:
```bash
curl -sI https://example.com/api/v2/users | grep -i "X-Debug"
# → X-Debug-Location: API-V2
# → X-Debug-Upstream: backend_v2
```

### 8. Управление завершающим слэшем (`auto_redirect`, Angie 1.10.0+)

Директива `auto_redirect` автоматически перенаправляет запрос с `/path` на `/path/` (301), если соответствует существующей директории. Устраняет необходимость ручных правил `rewrite`.

```nginx
location /docs/ {
    auto_redirect on;
    alias /usr/share/doc/html/;
    try_files $uri $uri/ =404;
}
# Запрос GET /docs → 301 Location: /docs/
```

### 9. `root` vs `alias` в location

Несоответствие `root` и `alias` — частая причина ошибок 404. Разница в обработке конечного слэша:

- **`root /var/www/html;`** — URI добавляется к `root`. `location /images/` + запрос `/images/photo.jpg` → ищет `/var/www/html/images/photo.jpg`.
- **`alias /var/www/images/;`** — URI заменяется на `alias`. `location /images/` + запрос `/images/photo.jpg` → ищет `/var/www/images/photo.jpg`.

```nginx
# Правильно: alias с завершающим слэшем
location /static/ {
    alias /var/www/static/;
    expires 30d;
    add_header Cache-Control "public, immutable";
}

# Правильно: root без завершающего слэша в location
location /uploads/ {
    root /var/www/data;
    # Ищет /var/www/data/uploads/...
}
```

### Сценарий: Отдача статических файлов

Раздача статики (HTML, CSS/JS, картинки) — базовый сценарий, где `root`/`alias` и `try_files` формируют схему месторасположения файлов.

```nginx
server {
    listen 80;
    server_name example.com;

    root /var/www/example;         # base для всех location, которые не переопределяют root

    location / {
        index index.html;
        try_files $uri $uri/ /index.html;   # SPA-fallback на /index.html
    }

    location /assets/ {
        alias /var/www/example/build/assets/;  # физический путь не совпадает с URI
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location ^~ /downloads/ {
        internal;                    # только внутренние подзапросы (X-Accel-Redirect)
        root /srv/data;
    }
}
```

**Верификация:**
```bash
# Проверка, что статика отдаётся и кэшируется
curl -sI http://example.com/assets/app.js | grep -E "^(HTTP|Cache-Control)"
# → HTTP/1.1 200 OK
# → Cache-Control: public, immutable

# alias без завершающего слэша — частая ошибка: root при location /assets/
ls /var/www/example/assets/                # пусто, а файлы в /var/www/example/build/assets/

# Проверка try_files: запрос глубокого пути без файла → fallback index.html
curl -s -o /dev/null -w "%{http_code} %{url_effective}\n" -L http://example.com/some/route
# → 200
```

Полный разбор `root`/`alias`/`try_files`/`autoindex` с troubleshoot-section — во **[`serving_files.md`](../Nginx/Core/Location/serving_files.md)** (SSoT, общий для Nginx и Angie).

## Операции и команды

### Валидация конфигурации

Перед применением изменений проверяйте синтаксис и ищем опечатки в директивах `location`:

```bash
# Проверка всего конфига
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка только конкретного include (если конфиг большой)
sudo angie -c /etc/angie/angie.conf -t

# Поиск всех блоков location в активной конфигурации
angie -T | grep -n "location "
# → 45:location ^~ /static/ {
# → 62:location /api/ {
# → 78:location ~ \.php$ {
```

### Диагностика сопоставления

Определите, какой `location` обрабатывает конкретный URI, без изменения production-конфигурации:

```bash
# Метод 1: curl с подменой Host (если multiple server_name)
curl -sI https://example.com/api/v2/users -H "Host: example.com" | grep -i "X-Debug-Location"

# Метод 2: запрос к внутреннему stub_location
# (добавьте временно в конфиг:
#  location = /_debug_match { internal; return 200 "$uri"; } )
curl -s https://example.com/_debug_match?url=/api/v2/users

# Метод 3: grep по конфигу для поиска конфликтов regex
angie -T | awk '/location /{print NR": "$0}' | sort -t/ -k2
```

### Управление сервисом

```bash
# Graceful reload (не рвет соединения)
sudo systemctl reload angie

# Проверка что новый конфиг загружен
curl -s http://127.0.0.1:8888/status/angie/ | jq '.generation'
# → 42  (увеличился после reload)

# Просмотр ошибок конфигурации в реальном времени
sudo journalctl -u angie -f --since "2 minutes ago" | grep -E "location|syntax"
```

### Запрос метрик `status_zone` через API

```bash
# Список всех активных зон
curl -s http://127.0.0.1:8888/status/http/status_zones/ | jq '.[] | .name'

# Метрики конкретной зоны
curl -s http://127.0.0.1:8888/status/http/status_zones/api_stats/ | jq '{
    requests: .requests,
    bytes_in: .bytes_in,
    bytes_out: .bytes_out
}'
# → {
#     "requests": 15234,
#     "bytes_in": 5242880,
#     "bytes_out": 104857600
#   }

# Проверка что status_zone собирает данные (сравнение до/after)
ab -n 1000 -c 10 https://example.com/api/users
curl -s http://127.0.0.1:8888/status/http/status_zones/api_stats/ | jq '.requests'
# → должно быть >= 1000
```

## Устранение неисправностей

### Location не срабатывает (ожидался один блок, сработал другой)

**Причина:** Неправильный приоритет модификаторов, опечатка в URI, конфликт regex и префикса.

**Диагностика:**
```bash
# 1. Проверка активного конфига
angie -T | grep -A2 "location /expected-path"

# 2. Поиск конфликтующих regex
angie -T | grep -E "location ~|location ~\*"

# 3. Тест с curl
curl -sI https://example.com/expected-path | grep -i "X-Debug-Location"
```

**Решения:**
- Убедитесь что модификатор `=` или `^~` применяется для критических путей.
- Проверьте порядок regex: первый совпавший паттерн побеждает.
- Используйте `merge_slashes on;` если запросы содержат двойные слэши.

### Regex конфликтуют с префиксными location

**Причина:** Регулярное выражение с более длинным паттерном перехватывает запрос, который должен попасть в префиксный `location`.

**Диагностика:**
```bash
# Список всех regex в порядке объявления
angie -T | grep -n "location ~"
```

**Решения:**
- Добавьте модификатор `^~` к префиксному `location`.
- Переместите regex ниже в конфигурации (или в отдельный файл с меньшим приоритетом).
- Упростите regex: замените `~* \.(jpg|png|gif)$` на префикс `location ^~ /images/`.

### `internal` блок недоступен извне (ошибка 404)

**Причина:** Ожидалось, что внешний клиент сможет обратиться напрямую к защищенному ресурсу.

**Диагностика:**
```bash
curl -I https://example.com/protected_files/secret.pdf
# → HTTP/1.1 404 Not Found
```

**Решения:**
- Это корректное поведение. `internal` блоки предназначены только для `X-Accel-Redirect` от бэкенда, `error_page` или `rewrite`.
- Убедитесь что бэкенд отправляет заголовок `X-Accel-Redirect: /protected_files/secret.pdf`.
- Для отладки временно добавьте в конфиг `allow all;` или уберите `internal`, но не оставляйте в production.

### `status_zone` не собирает метрики

**Причина:** Директива указана в неправильном контексте, зона переполнена или API не настроен.

**Диагностика:**
```bash
# 1. Проверка что status_zone объявлена внутри location
angie -T | grep -B1 -A1 "status_zone"

# 2. Проверка размера зоны (по умолчанию может быть недостаточно)
angie -T | grep "status_zone api_stats"

# 3. Проверка API
curl -s http://127.0.0.1:8888/status/http/status_zones/api_stats/
# → {"name":"api_stats",...} или пустой объект
```

**Решения:**
- Увеличьте размер зоны: `status_zone api_stats 10m;` (для высоконагруженных путей до 64M).
- В Angie 1.12.1+ убедитесь что в имени зоны нет переменных (используйте статическое имя).
- Проверьте что модуль `ngx_http_api_module` включен и слушает на порту 8888.

### `goto` вызывает цикл или неожиданное поведение

**Причина:** Именованный `location` содержит `goto` обратно в исходный блок, или `$uri` изменяется косвенно.

**Диагностика:**
```bash
# Логи Angie: ищем циклические перенаправления
grep -E "rewrite or internal redirection cycle" /var/log/angie/error.log
```

**Решения:**
- Не используйте `goto` внутри именованного `location`, который может быть вызван из того же блока.
- Помните: `goto` не изменяет `$uri`, поэтому условия в целевом блоке будут работать с исходным URI.
- Для сложной логики используйте комбинацию `map` + `rewrite ... last` вместо `goto`.

### Ошибка 404/403 при использовании `alias` и `try_files`

**Причина:** Неправильное сочетание `alias` с `try_files` из-за разной обработки пути.

**Диагностика:**
```bash
# Проверка фактического пути к файлу
angie -T | grep -A3 "location /static/"
# → alias /var/www/static/;
# → try_files $uri =404;
# Запрос /static/photo.jpg → ищет /var/www/static/static/photo.jpg (двойной префикс!)
```

**Решения:**
- При использовании `alias` в `try_files` используйте переменную `$request_filename` или явно укажите путь без дублирования префикса.
- Альтернатива: используйте `root` вместо `alias`, если логика путей позволяет.

## Лучшие практики

### Структура и модульность

- **Плоская структура:** Избегайте вложенных `location`. Используйте плоскую структуру с приоритетными префиксами (`^~`) или выносите общие директивы в файлы через `include`.
- **Один `location` — одна ответственность:** Не смешивайте статику, проксирование и аутентификацию в одном блоке без необходимости.
- **Именование `status_zone` по домену ответственности:** `location /api/v2/users/ { status_zone api_v2_users; }` — облегчает фильтрацию метрик.
- **Группировка через `include`:** Для повторяющихся настроек (заголовки безопасности, CORS) выносите конфиг в отдельный файл.

### Производительность

- **Префиксы перед regex:** Для часто запрашиваемых путей (статика, API) используйте `location ^~ /path/`. Это исключает проверку regex и ускоряет сопоставление за счет префиксного дерева.
- **Точное совпадение для hot paths:** Используйте `location = /health` или `location = /favicon.ico` для часто опрашиваемых эндпоинтов.
- **PCRE JIT:** Включите `pcre_jit on;` в контексте `main` для ускорения regex.
- **`merge_slashes on`:** Оставьте включенным по умолчанию для предотвращения неожиданных промахов сопоставления.

### Безопасность

- **`internal` для защищенных ресурсов:** Все эндпоинты, отдаваемые через `X-Accel-Redirect` или `error_page`, должны иметь `internal`.
- **`deny all` для технических путей:** Локации `/metrics`, `/status`, `/console` защищайте строгими ACL.
- **`limit_except` вместо глобальных `if`:** Ограничивайте методы на уровне `location`, а не через условные блоки.
- **Сокрытие версии:** Используйте `server_tokens off;` в контексте `http` для скрытия точной версии Angie.

### Эксплуатация и отладка

- **Debug-заголовки в non-production:** Используйте `add_header X-Debug-Location ... always` для отладки, но отключайте в production или ограничьте `allow` внутренней подсетью.
- **Валидация перед reload:** Всегда выполняйте `angie -t` перед `systemctl reload angie`.
- **Логирование до деплоя:** Включите `access_log` с `$request_id` для корреляции запросов в распределенной среде.
- **Резервное копирование конфига:** Перед массовыми изменениями создавайте бэкап: `cp /etc/angie/angie.conf /etc/angie/angie.conf.bak.$(date +%Y%m%d%H%M%S)`.

### Ограничения и известные нюансы

- **Вложенные `location`:** Поддерживаются, но наследование директив неочевидно. Избегайте без крайней необходимости.
- **Переменные в `location`:** Запрещены. Путь должен быть статической строкой или статическим regex.
- **Глубина внутренней маршрутизации:** Angie/Nginx ограничивает 10 внутренних перенаправлений на запрос. При превышении возвращается `500 Internal Server Error`.
- **`status_zone` с переменными:** В версиях до 1.12.1 использование переменных в `status_zone` вызывало деградацию производительности. Используйте статические имена.

## Дополнительная информация

### Версии Angie и совместимость

Актуальная версия Angie (сентябрь 2026): **1.12.2** (базируется на Nginx 1.27.x). Полная обратная совместимость конфигурации с Nginx позволяет выполнять миграцию без изменения логики `location`.

Ключевые отличия в директивном наборе:
- **OSS:** `multi-match`, `goto`, `prometheus`, `least_time`, `sticky learn`.
- **PRO:** `upstream_probe`, `queue`, `bind_conn`, расширенный API Console Light.

### Связанные директивы и модули

- **[Обратный прокси-сервер в Angie](./angie_reverse_proxy.md)** — `proxy_pass`, заголовки, буферизация, жизненный цикл запроса.
- **[Контроль доступа в Angie](./angie_access_control.md)** — `allow`/`deny`, `auth_basic`, `auth_request`, `satisfy`, `limit_except`.
- **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — `upstream`, `zone`, `keepalive`, sticky-сессии.
- **[Мониторинг Angie через API](./angie_monitoring/angie_monitoring_concepts.md)** — `status_zone`, `metric_zone`, REST API.

### См. также

*   **[Директива location в Nginx: основы и приоритеты](../Nginx/Core/Location/basics.md)** — алгоритмы выбора и модификаторы.
*   **[Лучшие практики и отладка location](../Nginx/Core/Location/best_practices.md)** — рекомендации по безопасности и производительности.
*   **[Обратный прокси-сервер в Angie](./angie_reverse_proxy.md)** — настройка `proxy_pass`, таймауты и отказоустойчивость.
