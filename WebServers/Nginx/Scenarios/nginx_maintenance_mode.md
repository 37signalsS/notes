# Maintenance-режим в Nginx

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x (Mainline)

## Определения

**Maintenance-режим (режим обслуживания)** — управляемая временная остановка обработки штатного пользовательского трафика на уровне веб-сервера или обратного прокси, при которой клиентам возвращается статус `503 Service Unavailable` и специализированная страница либо JSON-ответ с описанием регламентных работ. В отличие от нештатных аварийных кодов (`502 Bad Gateway`, `504 Gateway Timeout`), maintenance-режим инициируется **планомерно и контролируемо**.

**Файл-флаг (Flag file)** — файл на локальной файловой системе сервера, наличие, отсутствие или текстовое содержимое которого служит триггером переключения логики обработки запросов без необходимости модификации основного тела конфигурации Nginx.

**Конфигурационный include** — директива Nginx (`include path/to/file.conf;`), позволяющая изолировать фрагмент конфигурации в отдельный файл и переключать его атомарной сменой символической ссылки (symlink) на файловой системе. Подробнее в **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)**.

**Map-директива** — директива контекста `http` модуля `ngx_http_map_module`, вычисляющая значение целевой переменной на основе одной или нескольких исходных переменных. Позволяет организовать декларативную логику включения заглушки и белых списков без ветвления через директиву `if`. Подробнее в **[Rewrite правила и try_files](../Core/nginx_rewrite_rules_and_try_files.md)**.

**Модуль Geo (`ngx_http_geo_module`)** — модуль ядра Nginx, строящий префиксное дерево (Radix tree) подсетей в оперативной памяти для проверки принадлежности IP-адреса клиента к доверенному диапазону с алгоритмической сложностью $O(1)$.

**Именованная локация (`@name`)** — специальный блок `location`, не участвующий в стандартном сопоставлении URI и вызываемый исключительно директивами внутренней переадресации (`error_page`, `try_files`). Подробнее в **[Внутренняя маршрутизация Nginx](../Core/Location/internal_routing.md)**.

**Грациозная перезагрузка (Graceful reload)** — перечитывание конфигурации Nginx мастер-процессом по сигналу `HUP` (`nginx -s reload` или `systemctl reload nginx`), при котором старые воркеры дорабатывают открытые TCP-соединения (`graceful shutdown`), а новые запросы принимаются воркерами с обновлённой конфигурацией без потери соединений.

**Health check (проверка здоровья)** — автоматизированный опрос контрольного эндпоинта приложения (`/healthz`, `/live`, `/ready`) для верификации доступности сервиса перед снятием режима обслуживания.

**Согласование контента (Content Negotiation / API Degradation)** — механизм выбора формата ответа (HTML vs JSON) в зависимости от заголовка запроса `Accept` или префикса URI, предотвращающий сбои парсинга в API-клиентах, мобильных приложениях и SPA во время регламентных работ.

**Заголовок `Retry-After`** — стандартный HTTP-заголовок ответа (RFC 9110), указывающий клиенту расчётное время ожидания (в секундах или HTTP-дате) перед повторной попыткой, предотвращающий лавинообразную нагрузку (thundering herd) при выходе из обслуживания.

**Байпас (Bypass / Whitelist)** — механизм исключения доверенных запросов (по IP-адресам через radix tree модуля `geo`, секретным cookie или HTTP-заголовкам) из-под действия заглушки для валидации продакшена дежурными инженерами.

**Дрейн соединений (Connection Draining)** — контролируемое дожидание завершения активных соединений и транзакций перед полной остановкой бэкендов на обслуживание.

---

## Архитектура и базовые концепции

### Зачем нужен maintenance-режим

В эксплуатации серверных инфраструктур выделяют два сценария активации режима обслуживания:

1. **Плановые регламентные работы (Maintenance Window):** миграции схемы баз данных, обновление мажорных версий backend-приложений, плановая замена upstream-хостов. Сервер гарантирует, что запросы пользователей не попадут на бэкенд в полуразобранном состоянии, а клиенты получат точную информацию о сроках завершения работ.
2. **Аварийная изоляция и инцидент-менеджмент (Circuit Breaking / Load Shedding):** при каскадной деградации инфраструктуры или отказе критических внешних сервисов maintenance-режим отсекает поток запросов на пограничном прокси, снимая нагрузку с базы данных и давая инженерам возможность стабилизировать сервисы.

### Почему необходимо возвращать HTTP 503, а не 200

Даже если сервер отдаёт клиенту полностью сформированную, стилизованную HTML-страницу или корректный JSON, статус ответа обязан быть строго **503 Service Unavailable**:

1. **SEO и индексация поисковыми системами:** роботы поисковых систем (Googlebot, YandexBot) при получении статуса 503 не обновляют кэш поискового индекса и повторяют сканирование позже. Если вернуть код `200 OK`, робот сочтёт текст заглушки реальным содержимым сайта, что приведёт к деиндексации оригинальных страниц и выпадению из поисковой выдачи. Подробнее о семантике кодов в **[HTTP-коды ответа](../../Networking/Protocols/HTTP/http_status_codes.md)**.
2. **Поведение балансировщиков и CDN:** внешние L4/L7-балансировщики (HAProxy, Keepalived, Envoy) и CDN-сети определяют доступность нод по кодам ответов. Статус 503 явно сигнализирует пограничным шлюзам о временной недоступности инстанса.
3. **Заголовок `Retry-After` и предотвращение Thundering Herd:** спецификация RFC 9110 обязывает использовать заголовок `Retry-After` совместно со статусом 503. Заголовок указывает клиентам интервал ожидания перед повторным запросом. Без него тысячи клиентов одновременно начнут отправлять повторные запросы сразу после кратковременного сбоя, вызывая лавинообразную перегрузку бэкенда в момент его старта.
4. **Защита от промежуточного кэширования:** браузеры и промежуточные прокси-серверы кэшируют ответы `200 OK` по умолчанию, если не заданы строгие ограничения. Ответ 503 с заголовком `Cache-Control: no-store, no-cache, must-revalidate` гарантирует, что заглушка не осядет в кэшах пользователей после завершения регламента.

### Фазы обработки запросов в Nginx и директива return

Nginx обрабатывает каждый HTTP-запрос последовательно через 11 фаз (`NGX_HTTP_*_PHASE`):

```text
[NGX_HTTP_SERVER_REWRITE_PHASE] (rewrite/return на уровне server)
           ↓
[NGX_HTTP_FIND_CONFIG_PHASE]    (сопоставление URI с location)
           ↓
[NGX_HTTP_REWRITE_PHASE]        (директивы return/set/rewrite в location)
           ↓
[NGX_HTTP_ACCESS_PHASE]         (проверка прав, auth_request, allow/deny)
           ↓
[NGX_HTTP_CONTENT_PHASE]        (генерация контента: proxy_pass, fastcgi, static)
```

**Ключевые архитектурные правила:**

- Директива `return 503` выполняется в фазе `REWRITE`. Фаза `REWRITE` всегда предшествует фазе `CONTENT`. Если в контексте сработал `return`, Nginx немедленно прерывает дальнейшую обработку и переходит к генерации ответа об ошибке. `proxy_pass` или отдача статических файлов не запускаются вовсе.
- **Опасность безусловного `return 503` на уровне `server`:** если разместить `return 503;` непосредственно в блоке `server` вне `location`, директива выполнится в `SERVER_REWRITE_PHASE`. При срабатывании `error_page 503 /maintenance.html;` Nginx выполняет внутренний редирект на `/maintenance.html`, который снова попадает в `SERVER_REWRITE_PHASE` того же сервера, вызывая ошибку зацикливания:
  `rewrite or internal redirection cycle while internally redirecting to "/maintenance.html"` (HTTP 500).
- **Изоляция блоков `location`:** директива `include`, размещённая исключительно в `location /`, не затрагивает более специфичные префиксные блоки (`location /api/`, `location /static/`). Для исключения сквозного пропуска трафика maintenance-правило должно охватывать все проксирующие локации либо управляться через общие переменные модуля `map`.

### Сравнение архитектурных подходов к переключению

| Критерий | `include` + Симлинк (`ln -sfn`) | Модуль `map` + Переменные | Проверка файла `if (-f ...)` |
| :--- | :--- | :--- | :--- |
| **Накладные расходы CPU/IO** | Нулевые (проверка в памяти) | Нулевые (хеш/дерево в памяти) | Высокие: системный вызов `stat()` на каждый запрос |
| **Требование к Reload** | Да (`systemctl reload nginx`) | Да (при правке файлов) / Нет (при динамическом cookie) | Нет (подхватывает появление файла на диске) |
| **Конфликт с `open_file_cache`** | Отсутствует | Отсутствует | Критический: кэширует наличие/отсутствие файла |
| **Гибкость белых списков** | Средняя (через отдельные conf) | Максимальная (IP, CIDR, Cookie, User-Agent) | Низкая (громоздкие конструкции `if`) |
| **Рекомендация для Production** | **Основной стандарт** | **Рекомендуется для сложных условий** | **Антипаттерн (не рекомендуется)** |

#### Почему подход с `if (-f ...)` признан антипаттерном

Исторический способ проверки наличия файла-флага через директиву `if`:

```nginx
# АНТИПАТТЕРН — НЕ ИСПОЛЬЗОВАТЬ В ПРОДАКШЕНЕ
location / {
    if (-f /var/run/maintenance.flag) {
        return 503;
    }
    proxy_pass http://backend_upstream;
}
```

Недостатки подхода:

1. **Деградация производительности ввода-вывода (IOPS):** проверка существования файла заставляет операционную систему выполнять системный вызов `stat()` или `access()` при обработке каждого входящего HTTP-запроса. На нагрузке от 5 000 до 50 000 rps это приводит к ненужному контекстному переключению ядра и блокировкам дисковой подсистемы.
2. **Конфликт с директивой `open_file_cache`:** если на сервере включён кэш дескрипторов файлов (`open_file_cache max=10000 inactive=60s; open_file_cache_errors on;`), Nginx кэширует как существование, так и отсутствие файла. При удалении файла-флага Nginx продолжит возвращать `503` до истечения параметра `open_file_cache_valid` (обычно 60 секунд), лишая инженера оперативного контроля.
3. **Недетерминированное поведение "If Is Evil":** в контексте блока `location` директива `if` модифицирует конфигурационные структуры Nginx, создавая неявную вложенную локацию. Это приводит к сегфолтам воркеров или игнорированию директив модулей `proxy`, `headers` и `rewrite`.

### Проблема зависимостей статических ресурсов (Self-contained assets)

Частая ошибка при разработке maintenance-страницы — использование внешних стилей, веб-шрифтов или изображений (`<link rel="stylesheet" href="/css/style.css">`, `<img src="/img/logo.png">`). Если сервер переведён в maintenance-режим глобально, запросы к `/css/style.css` также возвращают `503`, и клиент видит искажённую страницу без стилей и изображений.

Решения:
- **Полная автономность (Self-contained HTML):** все CSS-правила встраиваются в блок `<style>`, а графические логотипы интегрируются в виде векторного SVG или Base64 Data URI.
- **Явное исключение статических ассетов заглушки:** выделение отдельной директории (например, `/etc/nginx/maintenance/static/`) с безусловной отдачей файлов без применения maintenance-правил.

### Разделение веб-трафика и REST API

Современные инфраструктуры обслуживают одновременно веб-клиентов (браузеры) и программные API-клиенты (мобильные приложения, внешние интеграции, SPA). Если на запрос `GET /api/v1/orders` или запрос с заголовком `Accept: application/json` сервер вернёт HTML-разметку с кодом 503, JSON-парсер клиентского приложения завершит работу с критической ошибкой:

```text
SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON
```

Поэтому пограничный прокси должен поддерживать **согласование контента (Content Negotiation)**: отдавать структурированный JSON-документ `{"error": "maintenance", "retry_after": 3600}` для эндпоинтов API и HTML-страницу для браузерного трафика.

---

## Практические сценарии

### Сценарий 1: Базовая реализация через include и симлинк (Standard Web)

Классический, наиболее надёжный способ для типовых веб-приложений. Переключение происходит через смену симлинка конфигурационного файла.

#### Предварительные требования

- Nginx 1.26+ установлен и управляется через systemd.
- Права суперпользователя (`root` или `sudo`) на запись в директорию `/etc/nginx/`.
- Выделенная директория `/etc/nginx/maintenance/`.

#### Пошаговая настройка

**Шаг 1. Создание каталога и файлов состояния:**

```bash
mkdir -p /etc/nginx/maintenance
```

Создаём файл с активным состоянием блокировки:

```bash
cat << 'EOF' > /etc/nginx/maintenance/maintenance_on.conf
return 503;
EOF
```

Создаём пустой файл для штатного режима работы:

```bash
touch /etc/nginx/maintenance/maintenance_off.conf
```

Устанавливаем исходный симлинк в положение "выключено":

```bash
ln -sfn /etc/nginx/maintenance/maintenance_off.conf /etc/nginx/maintenance/maintenance_current.conf
```

**Шаг 2. Создание автономной страницы заглушки:**

Создаём файл `/etc/nginx/maintenance/maintenance.html` со встроенными стилями и векторным логотипом:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Технические работы | Сервис временно недоступен</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #38bdf8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            background-color: var(--card-bg);
            border: 1px solid #334155;
            border-radius: 12px;
            max-width: 520px;
            width: 100%;
            padding: 40px;
            text-align: center;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        }
        .icon {
            width: 64px;
            height: 64px;
            margin: 0 auto 24px;
            fill: var(--accent);
        }
        h1 { font-size: 24px; margin-bottom: 12px; }
        p { color: var(--text-muted); font-size: 15px; line-height: 1.6; margin-bottom: 20px; }
        .details {
            background: #0f172a;
            border-radius: 6px;
            padding: 12px;
            font-family: monospace;
            font-size: 13px;
            color: var(--accent);
        }
    </style>
</head>
<body>
    <div class="container">
        <svg class="icon" viewBox="0 0 24 24">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
        </svg>
        <h1>Сервис на техническом обслуживании</h1>
        <p>Мы проводим плановое обновление инфраструктуры. Доступ к сервису будет восстановлен в ближайшее время.</p>
        <div class="details">Код статуса: HTTP 503 Service Unavailable</div>
    </div>
</body>
</html>
```

Устанавливаем права доступа:

```bash
chown -R root:root /etc/nginx/maintenance
chmod 644 /etc/nginx/maintenance/maintenance.html
chmod 644 /etc/nginx/maintenance/maintenance_on.conf
chmod 644 /etc/nginx/maintenance/maintenance_off.conf
```

**Шаг 3. Конфигурация виртуального хоста Nginx:**

Файл `/etc/nginx/conf.d/example.conf`:

```nginx
server {
    listen 80;
    server_name example.com;

    # Маршрутизация ошибки 503 на страницу заглушки
    error_page 503 /maintenance.html;

    # Локация отдачи заглушки (только для внутренних переходов)
    location = /maintenance.html {
        internal;
        root /etc/nginx/maintenance;

        # Запрет кэширования всеми типами клиентов и прокси
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;

        # Рекомендованный интервал повторного обращения (1 час)
        add_header Retry-After "3600" always;
    }

    location / {
        # Подключение переключателя
        include /etc/nginx/maintenance/maintenance_current.conf;

        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Включение и отключение режима

Включение:

```bash
ln -sfn /etc/nginx/maintenance/maintenance_on.conf /etc/nginx/maintenance/maintenance_current.conf
nginx -t && systemctl reload nginx
```

Валидация включения:

```bash
curl -I -s http://example.com
# → HTTP/1.1 503 Service Unavailable
# → Retry-After: 3600
# → Cache-Control: no-store, no-cache, must-revalidate, proxy-revalidate
```

Отключение:

```bash
ln -sfn /etc/nginx/maintenance/maintenance_off.conf /etc/nginx/maintenance/maintenance_current.conf
nginx -t && systemctl reload nginx
```

Валидация отключения:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://example.com
# → 200
```

---

### Сценарий 2: Раздельный ответ HTML и JSON API (Content Negotiation)

Сценарий для проектов с микросервисной архитектурой или разделением веб-портала и REST API.

```nginx
server {
    listen 80;
    server_name api.example.com example.com;

    # Именованная локация для отдачи структурированного JSON
    location @maintenance_json {
        internal;
        default_type application/json;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header Retry-After "1800" always;
        return 503 '{"error":{"code":503,"status":"Service Unavailable","message":"Scheduled maintenance in progress. Please retry later.","retry_after_seconds":1800}}\n';
    }

    # Локация для веб-страницы
    location = /maintenance.html {
        internal;
        root /etc/nginx/maintenance;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header Retry-After "1800" always;
    }

    # API endpoints: перехват 503 в JSON-обработчик
    location /api/ {
        error_page 503 @maintenance_json;
        include /etc/nginx/maintenance/maintenance_current.conf;

        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
    }

    # Пользовательский веб-трафик
    location / {
        error_page 503 /maintenance.html;
        include /etc/nginx/maintenance/maintenance_current.conf;

        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

Проверка API-ответа:

```bash
curl -i http://example.com/api/v1/status
# → HTTP/1.1 503 Service Unavailable
# → Content-Type: application/json
# → Retry-After: 1800
# → {"error":{"code":503,"status":"Service Unavailable","message":"Scheduled maintenance in progress. Please retry later.","retry_after_seconds":1800}}
```

---

### Сценарий 3: Комплексный байпас (Whitelist по IP через geo + Cookie/Header)

Инженерам и тестировщикам необходим доступ к реальному приложению во время регламентных работ. IP-адреса инженеров могут быть динамическими (удалённая работа), поэтому белый список должен поддерживать как корпоративные подсети, так и секретный токен обхода (в Cookie или HTTP-заголовке).

#### Конфигурация уровней `http` и `server`

В файле `/etc/nginx/nginx.conf` (контекст `http`):

```nginx
http {
    # Корректное определение реального IP клиента за прокси/балансировщиками
    # Подробнее в [Практическая конфигурация балансировки](../Proxy/Load_Balancing/practical_configuration.md)
    set_real_ip_from  10.0.0.0/8;
    set_real_ip_from  172.16.0.0/12;
    set_real_ip_from  192.168.0.0/16;
    real_ip_header    X-Forwarded-For;
    real_ip_recursive on;

    # 1. Белый список IP-адресов на базе Radix tree (модуль geo)
    geo $maintenance_ip_bypass {
        default        0;
        127.0.0.1/32   1; # Локальный хост
        10.50.0.0/16   1; # Офисная подсеть инженеров
        198.51.100.25  1; # Статический внешний IP администратора
    }

    # 2. Проверка секретного Cookie для инженеров с динамическими IP
    map $http_cookie $maintenance_cookie_bypass {
        default 0;
        "~*maint_secret=Adm1nSuperPass2026" 1;
    }

    # 3. Проверка секретного HTTP-заголовка для CI/CD и скриптов автоматизации
    map $http_x_maintenance_bypass $maintenance_header_bypass {
        default 0;
        "Adm1nSuperPass2026" 1;
    }

    # 4. Агрегация флагов исключения: если хотя бы один источник валиден — доступ открыт
    map "$maintenance_ip_bypass:$maintenance_cookie_bypass:$maintenance_header_bypass" $is_maintenance_bypassed {
        default 0;
        "~1"    1;
    }
}
```

Файл переключателя `/etc/nginx/maintenance/maintenance_on.conf`:

```nginx
# Если запрос не находится в белом списке — возвращаем 503
if ($is_maintenance_bypassed = 0) {
    return 503;
}
```

#### Проверка работы байпаса

1. Запрос от обычного пользователя (без токена и не из белой сети):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://example.com
# → 503
```

2. Запрос инженера с передачей секретного Cookie:

```bash
curl -s -o /dev/null -w "%{http_code}\n" --cookie "maint_secret=Adm1nSuperPass2026" http://example.com
# → 200
```

3. Запрос от скрипта проверки с секретным заголовком:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Maintenance-Bypass: Adm1nSuperPass2026" http://example.com
# → 200
```

---

### Сценарий 4: Maintenance через директиву map (без симлинков)

Для окружений, где изменение файловой структуры нежелательно или где управление производится изменением одной переменной в файле.

Создаём файл значения флага `/etc/nginx/maintenance/flag_value.conf`:

```nginx
# 1 — включить maintenance, 0 — штатный режим
1;
```

Конфигурация Nginx:

```nginx
http {
    map $uri $maintenance_active {
        default 0;
        # Исключаем отдачу самой заглушки из проверки флага
        /maintenance.html 0;
    }

    # Подключаем вычисленный статус через include
    # Значение переменной читается при инициализации
}

server {
    listen 80;
    server_name example.com;

    error_page 503 /maintenance.html;

    location = /maintenance.html {
        internal;
        root /etc/nginx/maintenance;
        add_header Cache-Control "no-store" always;
        add_header Retry-After "3600" always;
    }

    location / {
        # Проверяем значение флага
        if ($maintenance_active = 1) {
            return 503;
        }

        proxy_pass http://127.0.0.1:8080;
    }
}
```

Управление состоянием:

```bash
# Включение
sed -i 's/default .*/default 1;/' /etc/nginx/conf.d/maintenance_map.conf
nginx -t && systemctl reload nginx

# Отключение
sed -i 's/default .*/default 0;/' /etc/nginx/conf.d/maintenance_map.conf
nginx -t && systemctl reload nginx
```

---

### Сценарий 5: Автоматизация управления через Bash-утилиту и Systemd Timer

Для исключения ошибок оператора при ручном создании симлинков создаётся стандартизированный CLI-инструмент.

#### Управляющий скрипт `/usr/local/bin/nginx-maintenance`

```bash
#!/usr/bin/env bash
set -euo pipefail

MAINT_DIR="/etc/nginx/maintenance"
CURRENT_SYM="${MAINT_DIR}/maintenance_current.conf"
ON_FILE="${MAINT_DIR}/maintenance_on.conf"
OFF_FILE="${MAINT_DIR}/maintenance_off.conf"

check_prerequisites() {
    if [[ $EUID -ne 0 ]]; then
        echo "ERROR: Этот скрипт должен выполняться с правами root (sudo)." >&2
        exit 1
    fi
    if [[ ! -f "$ON_FILE" ]] || [[ ! -f "$OFF_FILE" ]]; then
        echo "ERROR: Файлы конфигурации maintenance не найдены в $MAINT_DIR" >&2
        exit 1
    fi
}

apply_reload() {
    echo "Проверка синтаксиса Nginx..."
    if nginx -t; then
        echo "Применение конфигурации (graceful reload)..."
        systemctl reload nginx
        echo "Успешно выполнено."
    else
        echo "CRITICAL: Ошибка валидации Nginx. Изменения не применены." >&2
        exit 1
    fi
}

get_status() {
    if [[ ! -L "$CURRENT_SYM" ]]; then
        echo "Status: UNKNOWN (симлинк $CURRENT_SYM отсутствует)"
        exit 2
    fi
    local target
    target="$(readlink -f "$CURRENT_SYM")"
    if [[ "$target" == "$ON_FILE" ]]; then
        echo "Maintenance Mode: ACTIVE (ON)"
    elif [[ "$target" == "$OFF_FILE" ]]; then
        echo "Maintenance Mode: INACTIVE (OFF)"
    else
        echo "Maintenance Mode: CUSTOM TARGET -> $target"
    fi
}

check_prerequisites

case "${1:-}" in
    on)
        echo "Включение maintenance-режима..."
        ln -sfn "$ON_FILE" "$CURRENT_SYM"
        apply_reload
        ;;
    off)
        echo "Отключение maintenance-режима..."
        ln -sfn "$OFF_FILE" "$CURRENT_SYM"
        apply_reload
        ;;
    status)
        get_status
        ;;
    *)
        echo "Использование: $0 {on|off|status}"
        exit 1
        ;;
esac
```

Установка прав:

```bash
chmod 750 /usr/local/bin/nginx-maintenance
```

Тестирование выполнения:

```bash
/usr/local/bin/nginx-maintenance status
# → Maintenance Mode: INACTIVE (OFF)

/usr/local/bin/nginx-maintenance on
# → Проверка синтаксиса Nginx...
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
# → Применение конфигурации (graceful reload)...
# → Успешно выполнено.

/usr/local/bin/nginx-maintenance status
# → Maintenance Mode: ACTIVE (ON)
```

#### Расписание через Systemd Timer (Плановое ночное окно)

Для выполнения регламентных работ в строго заданное время настраивается таймер systemd.

Создаём сервис включения `/etc/systemd/system/maintenance-start.service`:

```ini
[Unit]
Description=Enable Nginx Maintenance Mode
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/nginx-maintenance on
```

Создаём таймер включения `/etc/systemd/system/maintenance-start.timer` (каждое воскресенье в 02:00):

```ini
[Unit]
Description=Trigger Nginx Maintenance Mode Start

[Timer]
OnCalendar=Sun *-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Создаём сервис отключения `/etc/systemd/system/maintenance-stop.service`:

```ini
[Unit]
Description=Disable Nginx Maintenance Mode
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/nginx-maintenance off
```

Создаём таймер отключения `/etc/systemd/system/maintenance-stop.timer` (каждое воскресенье в 04:00):

```ini
[Unit]
Description=Trigger Nginx Maintenance Mode Stop

[Timer]
OnCalendar=Sun *-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Активация таймеров:

```bash
systemctl daemon-reload
systemctl enable --now maintenance-start.timer maintenance-stop.timer
systemctl list-timers maintenance-*
# → NEXT                        LEFT     LAST PASSED UNIT                   ACTIVATES
# → Sun 2026-10-18 02:00:00 MSK 12h left n/a  n/a    maintenance-start.timer maintenance-start.service
```

---

### Сценарий 6: Проверка здоровья (Health Check) и Graceful Draining

Отключение заглушки до момента, пока бэкенд не готов обрабатывать запросы (например, приложение инициализирует соединения с БД или компилирует кэш), приводит к массовым ошибкам `502 Bad Gateway`.

Скрипт `/usr/local/bin/nginx-safe-exit-maintenance.sh` выполняет валидацию эндпоинта готовности перед снятием заглушки:

```bash
#!/usr/bin/env bash
set -euo pipefail

HEALTH_URL="http://127.0.0.1:8080/healthz"
MAX_ATTEMPTS=30
SLEEP_INTERVAL=2
SUCCESS_REQUIRED=3

echo "Запуск верификации готовности бэкенда: $HEALTH_URL"

consecutive_success=0

for ((i=1; i<=MAX_ATTEMPTS; i++)); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$HEALTH_URL" || echo "000")

    if [[ "$HTTP_CODE" == "200" ]]; then
        ((consecutive_success++))
        echo "Попытка $i/$MAX_ATTEMPTS: OK ($consecutive_success/$SUCCESS_REQUIRED)"
        if [[ $consecutive_success -ge $SUCCESS_REQUIRED ]]; then
            echo "Бэкенд полностью прогрет и стабилен."
            break
        fi
    else
        consecutive_success=0
        echo "Попытка $i/$MAX_ATTEMPTS: бэкенд вернул HTTP $HTTP_CODE, ожидание ${SLEEP_INTERVAL}c..."
    fi

    if [[ $i -eq $MAX_ATTEMPTS ]]; then
        echo "CRITICAL: Бэкенд не перешёл в статус готовности за $((MAX_ATTEMPTS * SLEEP_INTERVAL)) секунд." >&2
        echo "Maintenance-режим ОСТАЁТСЯ ВКЛЮЧЁННЫМ во избежание всплеска 502 ошибок." >&2
        exit 1
    fi

    sleep "$SLEEP_INTERVAL"
done

echo "Отключение maintenance-режима..."
/usr/local/bin/nginx-maintenance off
echo "Сервис успешно переведён в штатный режим."
```

---

### Сценарий 7: Автоматизация в CI/CD пайплайнах (Ansible Playbook)

Идемпотентный плейбук Ansible для управления состоянием maintenance на пуле серверов Nginx во время процедур развёртывания.

Файл `playbooks/nginx_maintenance.yml`:

```yaml
---
- name: Управление режимом обслуживания Nginx
  hosts: loadbalancers
  become: true
  vars:
    # Передаётся через --extra-vars "maintenance_state=on" или "off"
    maintenance_state: "on"
    nginx_maintenance_dir: "/etc/nginx/maintenance"

  tasks:
    - name: Валидация входных параметров
      ansible.builtin.assert:
        that:
          - maintenance_state in ['on', 'off']
        fail_msg: "Переменная maintenance_state должна принимать значение 'on' или 'off'."

    - name: Управление символической ссылкой maintenance_current.conf
      ansible.builtin.file:
        src: "{{ nginx_maintenance_dir }}/maintenance_{{ maintenance_state }}.conf"
        dest: "{{ nginx_maintenance_dir }}/maintenance_current.conf"
        state: link
        force: true
      notify: Перечитать конфигурацию Nginx

    - name: Проверка синтаксической корректности конфигурации Nginx
      ansible.builtin.command:
        cmd: nginx -t
      changed_when: false

  handlers:
    - name: Перечитать конфигурацию Nginx
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
```

Запуск в CI/CD пайплайне:

```bash
# Включение заглушки перед началом деплоя
ansible-playbook -i inventory/prod playbooks/nginx_maintenance.yml -e "maintenance_state=on"

# Отключение заглушки после успешного смоук-тестирования
ansible-playbook -i inventory/prod playbooks/nginx_maintenance.yml -e "maintenance_state=off"
```

---

## Операции и команды

### Сводная таблица эксплуатационных команд

| Задача | Команда | Ожидаемый результат / Пояснение |
| :--- | :--- | :--- |
| **Синтаксический тест** | `nginx -t` | `# → nginx: configuration file ... test is successful` |
| **Грациозная перезагрузка** | `systemctl reload nginx` или `nginx -s reload` | Применение симлинка без разрыва соединений |
| **Статус процесса** | `systemctl status nginx` | `# → Active: active (running)` |
| **Проверка статуса ответа** | `curl -s -o /dev/null -w "%{http_code}\n" http://example.com` | `# → 503` (при active) или `# → 200` |
| **Проверка заголовков ответа** | `curl -I -s http://example.com` | Наличие `HTTP/1.1 503`, `Retry-After: 3600`, `Cache-Control` |
| **Проверка JSON API** | `curl -s http://example.com/api/v1/ping` | `# → {"error":{"code":503,...}}` |
| **Проверка байпаса по Cookie**| `curl -I -s --cookie "maint_secret=Token" http://example.com` | `# → HTTP/1.1 200 OK` |
| **Текущий статус симлинка** | `readlink -f /etc/nginx/maintenance/maintenance_current.conf` | Вывод целевого файла (`..._on.conf` или `..._off.conf`) |

### Анализ логов во время обслуживания

Подробный анализ логов описан в **[Логирование и анализ логов в Nginx](../Operations/nginx_log_analysis.md)**.

Фильтрация запросов, получивших статус 503:

```bash
grep ' 503 ' /var/log/nginx/access.log | tail -n 20
```

Подсчёт распределения обращений к URI во время технических работ:

```bash
awk '$9 == 503 {print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -n 10
```

Проверка отсутствия критических ошибок воркеров в error.log:

```bash
tail -n 50 /var/log/nginx/error.log | grep -E '\[emerg\]|\[alert\]|\[crit\]'
# → вывод должен быть пустым
```

### Очистка локального прокси-кэша Nginx

Если перед бэкендом используется модуль `proxy_cache`, страницы заглушки могут быть ошибочно помещены в кэш при неверно настроенных заголовках:

```bash
# Удаление объектов кэша, связанных с maintenance
find /var/cache/nginx -type f -delete
systemctl reload nginx
```

---

## Устранение неисправностей

| Симптом / Ошибка | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| **HTTP 500 Internal Server Error** вместо страницы 503 | Зацикливание редиректов (`redirection cycle`) из-за директивы `return 503` на уровне `server` | Проверьте `/var/log/nginx/error.log` на наличие `rewrite or internal redirection cycle`. Убедитесь, что `return 503;` размещён внутри проксирующих `location`, либо исключите `/maintenance.html` из обработки через `map` |
| **Заглушка отображается, но код ответа 200 OK** | Ошибка перенаправления `error_page` (например, `error_page 503 =200`) или статический файл отдаётся напрямую без вызова ошибки | Проверьте директиву `error_page`. Символ `=` меняет код ответа. Используйте строго `error_page 503 /maintenance.html;` без указания `=200` |
| **Заголовок `Retry-After` отсутствует в ответе** | Директива `add_header` объявлена без флага `always` | В Nginx директива `add_header` без параметра `always` применяется только к ответам `200, 201, 204, 206, 301, 302, 303, 304, 307, 308`. Для 503 обязательно: `add_header Retry-After "3600" always;` |
| **Стили и изображения на странице заглушки не загружаются (404/503)** | Внешние CSS/изображения попадают под общий блок `location /`, возвращающий 503 | Переведите стили и графику в автономный формат (inlined CSS, встроенный SVG Data URI) внутри `maintenance.html` |
| **Клиенты продолжают видеть заглушку после её отключения** | Браузерный или промежуточный кэш сохранил ответ | Проверьте наличие заголовков `Cache-Control: no-store, no-cache, must-revalidate` в блоке `location = /maintenance.html`. Сбросьте кэш браузера комбинацией `Ctrl+F5` |
| **API-клиенты выдают ошибку парсинга JSON при работах** | Для эндпоинтов API возвращается HTML-документ | Настройте именованную локацию `@maintenance_json` и переопределите `error_page 503 @maintenance_json;` внутри `location /api/` |
| **Байпас по IP не работает за балансировщиком** | Модуль `geo` анализирует `$remote_addr` пограничного L4/L7 прокси, а не реального клиента | Настройте модуль `real_ip`: укажите `set_real_ip_from <CIDR_балансировщика>;` и `real_ip_header X-Forwarded-For;`. Проверьте, что в логах пишется реальный IP |
| **Всплеск ошибок 502/504 сразу после выключения заглушки** | Бэкенд ещё не завершил инициализацию соединений при старте | Внедрите обязательную проверку `/healthz` перед отключением maintenance (Сценарий 6). Не выключайте заглушку вручную до прогрева приложения |
| **Системы мониторинга (Prometheus/Zabbix) генерируют алерты** | Мониторинг воспринимает 503 как деградацию SLO/SLI | Активируйте Silence в Alertmanager либо Maintenance Period в Zabbix на период окна регламентных работ |
| **`nginx -s reload` зависает при высокой нагрузке** | Долгоживущие соединения (WebSockets, SSE, медленные скачивания) держат старые воркеры | Проверьте директиву `worker_shutdown_timeout 15s;` в основном контексте `nginx.conf` для принудительного закрытия старых соединений |

---

## Лучшие практики

- **Защита Error Budget и мониторинг (SRE-подход):** перед включением maintenance-режима создавайте окно подавления алертов (Alertmanager Silence или Zabbix Maintenance Window). В противном случае массовые ответы 503 исчерпают бюджет ошибок (Error Budget) сервиса и вызовут ложное оповещение дежурной смены. Подробнее в **[Zabbix: управление оповещениями и эскалациями](../../Zabbix/zabbix_alerting_and_escalation.md)**.
- **Ограничение времени жизни старых соединений (`worker_shutdown_timeout`):** при частом выполнении `reload` воркеры с долгоживущими TCP-соединениями (WebSockets, HTTP Long-polling) могут накапливаться в системе. Задавайте лимит в `nginx.conf`:
  ```nginx
  worker_shutdown_timeout 30s;
  ```
- **Предотвращение Thundering Herd:** используйте заголовок `Retry-After` с запасом времени относительно фактического завершения работ. При возможности используйте рандомизацию (jitter) для клиентов API, чтобы распределить входящую волну запросов во времени.
- **Автономность заглушки:** оформляйте `maintenance.html` без внешних сетевых зависимостей. Все стили, шрифты и графика должны быть внедрены в тело документа.
- **Обязательное использование модификатора `always`:** для всех заголовков, передаваемых вместе с ошибкой 503 (`Cache-Control`, `Retry-After`, `Pragma`), модификатор `always` обязателен.
- **Соблюдение регламента проверки синтаксиса:** ни один скрипт автоматизации или playbook не должен выполнять `reload` без предшествующего `nginx -t`.
- **Сепарация ответов Web и API:** гарантируйте, что ни один программный интерфейс не получит HTML-разметку в ответ на API-вызов.

---

## Связанные темы

- **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)** — структура конфигурационных файлов и работа директивы `include`.
- **[Rewrite правила и try_files](../Core/nginx_rewrite_rules_and_try_files.md)** — вычисление переменных через `map` и правила внутренних перенаправлений.
- **[Внутренняя маршрутизация Nginx](../Core/Location/internal_routing.md)** — директива `internal`, именованные локации (`@name`) и обработка `error_page`.
- **[Практическая конфигурация балансировки](../Proxy/Load_Balancing/practical_configuration.md)** — настройка модуля `real_ip` за балансировщиками нагрузки и CDN.
- **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)** — анализ сигналов управления процессами и graceful reload.
- **[Логирование и анализ логов в Nginx](../Operations/nginx_log_analysis.md)** — форматирование access_log и фильтрация ответов 5xx.
- **[HTTP-коды ответа](../../Networking/Protocols/HTTP/http_status_codes.md)** — стандарт RFC 9110, спецификация кода 503 и заголовка `Retry-After`.
- **[Load Shedding](../../CI-CD/Core_Concepts/load_shedding.md)** — управление перегрузкой и защитное отсечение трафика.
- **[Rate Limiting и circuit breakers](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — ограничение частоты запросов и сценарии временной изоляции сервисов.
- **[Zabbix: управление оповещениями и эскалациями](../../Zabbix/zabbix_alerting_and_escalation.md)** — подавление алертов через Maintenance Windows во время плановых работ.
- **[Руководство по безопасности Nginx](../Security/nginx_security_guide.md)** — фильтрация доступа на базе списков сетей и заголовков.
