# Microcaching в Nginx

## Определения

**Microcaching (микрокэширование)** — техника серверного кэширования ответов с крайне коротким сроком жизни (обычно 1–10 секунд). Используется как буфер между клиентом и динамическим бэкендом: даже короткое кэширование способно уменьшить нагрузку на приложение в десятки раз, защищая его от пиков трафика (flash crowd, «стадо бизонов»).

Термин был популяризирован в 2013 году Мартином Фьордвальдом в статье на официальном блоге Nginx; в сообществе этот паттерн так и называют — **microcaching**.

Ключевая идея: для большинства публичных страниц допустима задержка обновления в пару секунд. Жертвуя свежестью на долю секунды, мы радикально снижаем RPS на бэкенд и избавляемся от «простоя в нагрузке».

## Основные концепции

### Архитектура микрокэширования

В отличие от классического proxy cache (TTL минуты/часы), microcaching использует те же директивы `ngx_http_proxy_module`, но с малым `proxy_cache_valid`:

```nginx
http {
    proxy_cache_path /var/cache/nginx/micro levels=1:2
                     keys_zone=micro:10m max_size=1g
                     inactive=60s;

    proxy_cache_key "$scheme://$host$request_uri";

    server {
        location / {
            proxy_cache micro;
            proxy_cache_valid 200 1s;   # <-- микро-TTL
            proxy_pass http://app_backend;
        }
    }
}
```

### Почему это работает

- Nginx с event-driven моделью выдерживает тысячи запросов в секунду даже для статики из кэша.
- Большинство бэкендов (WordPress, Django, Rails, Go/Node-API) тратят на 1 RPS десятки миллисекунд и ресурсы БД/CPU. Кэширование на 1–5 секунд срезает пиковую нагрузку до уровня среднего трафика.
- Кэшировать ответ даже «на мгновение» выгоднее, чем не кэшировать вообще: эффект достигается при высокой доле повторных запросов к одним и тем же URL (типично для публичных страниц).

### Точная настройка ключа и условное кэширование

По умолчанию `proxy_cache_key` учитывает полный URI. Для микрокэша типична комбинация схемы, хоста и пути без чувствительных параметров:

```nginx
proxy_cache_key "$scheme://$host$uri";
```

При этом для персонализированного контента необходимо «отключить» кэширование по признакам сессии (cookies, авторизация). Частые приёмы:

```nginx
# Запрет кэширования запросов с авторизацией/сессией
proxy_no_cache $cookie_sessionid $http_authorization $http_cookie;
proxy_cache_bypass $cookie_sessionid $http_authorization $http_cookie;
```

`proxy_cache_bypass` пропускает обращение к кэшу (запрос уходит на бэкенд и **обновляет** кэш), `proxy_no_cache` не сохраняет ответ в кэш. Обе директивы принимают непустое значение как «истину», поэтому их удобно задавать через `map`:

```nginx
map $http_cookie $cache_control {
    default     "";
    "~*session" 1;
    "~*auth"    1;
}

server {
    location / {
        proxy_no_cache  $cache_control;
        proxy_cache_bypass $cache_control;
    }
}
```

### Обход кэша через X-Accel-Redirect (сессионный прорыв)

Классический паттерн из статьи о microcaching: страница кэшируется целиком, но бэкенд помечает пользовательские блоки через `X-Accel-Redirect` на отдельный не кэшируемый `location`, который собирает персональные данные подзапросом.

```nginx
# Не кэшируемая зона для персональных фрагментов
location /private/ {
    internal;
    proxy_cache off;
    proxy_pass http://app_backend;
}
```

Бэкенд при рендеринге страницы отдаёт заголовок `X-Accel-Redirect: /private/avatar?id=<user>`, Nginx выполняет внутренний подзапрос и подставляет результат. Страница при этом остаётся кэшируемой для всех, а персональные фрагменты собираются для каждого пользователя отдельно.

### Защита от «стада бизонов» (Cache Stampede)

При истечении TTL множество запросов одновременно устремляются к бэкенду. Решается директивами:

```nginx
location / {
    proxy_cache micro;
    proxy_cache_lock on;                 # только один запрос идёт на бэкенд
    proxy_cache_lock_timeout 5s;         # остальные ждут ответа
    proxy_cache_lock_age 10s;            # защита от зависшего апстрима
    proxy_cache_valid 200 1s;
    proxy_pass http://app_backend;
}
```

Альтернатива — `proxy_cache_use_stale updating;`, которая отдаёт устаревшую копию, пока фоновый запрос обновляет кэш (stale-while-revalidate). Для overly динамичных страниц лучше Lock.

### Ограничения

- **1s — нижняя граница TTL в Nginx**: `proxy_cache_valid` принимает только целые секунды. Для суб-секундного кэширования требуются сторонние решения (Varnish, OpenResty/lua, CDN).
- Microcaching **не спасает от перегрева одной тяжёлой операции** внутри одного URL, если каждый запрос разный (например, `?query=` у поиска). Ключ с исключением параметров или канонизация URL обязательна.
- Не кэшируйте ответы с `Set-Cookie`, POST-запросы (кэшируются только GET/HEAD), ошибки (по умолчанию `proxy_cache_valid 200 1s` кэширует только код 200).
- Для очень персонализированного контента (личные кабинеты) microcaching почти бесполезен без сегментации по пользователям.

## Практические сценарии

### Предварительные требования

- Nginx OSS (документация всех директив актуальна для 1.19+ / mainline 1.27+).
- Бэкенд должен отдавать корректные заголовки `Cache-Control`/`Expires`, если вы используете валидацию через них (опционально).
- Достаточно места на диске: зона кэша `max_size` + `levels=1:2` в `proxy_cache_path`.

### Сценарий 1: Базовый microcaching для высоконагруженного сайта

```nginx
http {
    proxy_cache_path /var/cache/nginx/micro levels=1:2 keys_zone=micro:10m max_size=1g inactive=1m;

    server {
        listen 80;
        server_name example.com;

        location / {
            proxy_cache micro;
            proxy_cache_key "$scheme://$host$uri";
            proxy_cache_valid 200 1s;
            proxy_cache_lock on;
            proxy_pass http://127.0.0.1:3000;
        }
    }
}
```

### Сценарий 2: Микрокэш с обходом для авторизованных пользователей

```nginx
map $http_cookie $is_session {
    default      "";
    "~*session"  "1";
    "~*PHPSESSID" "1";
}

server {
    location / {
        proxy_cache_bypass $is_session;
        proxy_no_cache    $is_session;
        proxy_cache_valid 200 2s;
        proxy_pass http://php_fpm_upstream;
    }
}
```

### Сценарий 3: Microcaching API с кэшированием только успешных ответов и быстрым сбросом

```nginx
location /api/ {
    proxy_cache api_micro;
    proxy_cache_valid 200 302 5s;      # кэшируем успехи на 5 секунд
    proxy_cache_valid 404 1s;          # ошибки держим коротко (быстрое исправление)
    proxy_cache_bypass $http_authorization;
    proxy_pass http://api_backend;
}
```

Обратите внимание: короткий TTL для 404 позволяет быстро «убирать» ошибки из кэша после фикса бэкенда, не дожидаясь полного срока жизни ошибки.

### Сценарий 4: Диагностика попаданий (hit ratio)

```nginx
log_format cache_micro '$remote_addr - $status $request '
                       'cache=$upstream_cache_status '
                       'ct=$upstream_connect_time rt=$upstream_response_time';
access_log /var/log/nginx/micro_access.log cache_micro;
```

Проверка:

```bash
tail -f /var/log/nginx/micro_access.log
# → 10.0.0.5 - 200 GET / HTTP/1.1 cache=HIT ct=0.000 rt=0.000
# → 10.0.0.6 - 200 GET / HTTP/1.1 cache=HIT ct=0.000 rt=0.000
# → 10.0.0.7 - 200 GET / HTTP/1.1 cache=EXPIRED ct=0.012 rt=0.045
```

Нормальным считается HIT-более 90% при TTL 1–5 секунд, если трафик повторяется по одним URL.

## Операции и команды

| Команда/Директива | Назначение | Примечание |
| :--- | :--- | :--- |
| `proxy_cache_path` | Определяет зону и каталог кэша | Параметры `levels`, `keys_zone`, `max_size`, `inactive` |
| `proxy_cache micro;` | Включает использование зоны | Обязательно после `proxy_cache_path` |
| `proxy_cache_valid 200 1s;` | TTL по кодам ответа | Целые секунды; перечисляемые коды |
| `proxy_cache_lock on;` | Защита от stampede | Один запрос на бэкенд за раз |
| `proxy_cache_bypass` / `proxy_no_cache` | Условное пропускание кэша | Любое непустое значение = истина |
| `X-Accel-Redirect` | Персональные фрагменты вне кэша | Внутренний подзапрос к `internal` location |
| `$upstream_cache_status` | Статус кэширования в логе | HIT / MISS / EXPIRED / BYPASS / UPDATING / STALE |
| `proxy_cache_use_stale updating;` | Отдача устаревшего при обновлении | Аналог stale-while-revalidate |

Очистка и мониторинг зоны:

```bash
# Размер зоны кэша
du -sh /var/cache/nginx/micro

# Принудительная очистка (полная)
find /var/cache/nginx/micro -type f -delete   # не рекомендуется в проде без подготовки
```

## Устранение неполадок

### HIT равно 0, всё «EXPIRED»

**Причина:** TTL истёк к моменту повторного запроса, либо каждый запрос уникален (разные параметры).

**Решение:** проверьте `$request_uri` в ключе — при динамических параметрах вроде `?utm_source=...` ключ ломается. Используйте `$uri` или канонизируйте ключ через `map`. Увеличьте TTL до 5–10 секунд.

### Пользователь видит чужие данные

**Причина:** кэширование ответа с сессией/авторизацией. `$http_cookie` не проанализирован.

**Решение:** добавьте `proxy_cache_bypass`/`proxy_no_cache` по cookie-признакам (см. Сценарий 2) или исключите персонализированные URL из кэша вообще.

### Cache Stampede после TTL (пик на бэкенде каждые N секунд)

**Причина:** одновременно истекает много ключей; `proxy_cache_lock` выключен.

**Решение:** включите `proxy_cache_lock on`; рандомизируйте TTL (не весь контент обновлять синхронно) частичной настройкой `proxy_cache_valid` для разных location; при высоком RPS добавьте `proxy_cache_use_stale updating`.

### Микрокэш не помогает: бэкенд всё ещё в Max Load

**Причина:** либо hit ratio низкий (уникальные URL), либо бэкенд отвечает медленно и TTL меньше времени ответа.

**Решение:** посчитайте HIT в логах; проверьте middleware на стороне Nginx (`X-Accel`, header-аура), уберите из ключа всё, что размножает записи; увеличьте TTL осознанно (Acceptable: 2–5s для новостного/лендингового трафика).

## Лучшие практики

- Начинайте с TTL **1–2 секунды** в пик и растите до 30с только если бизнес допускает задержку обновления.
- Всегда добавляйте `proxy_cache_lock on` для защиты от stampede.
- Отключайте кэширование по `Set-Cookie`, POST, авторизации.
- Ведите метрику `$upstream_cache_status` и алерт на «drop of hit ratio» — она сигнализирует об изменении паттерна трафика или об ошибке в ключе.
- Для персонализированных фрагментов используйте `X-Accel-Redirect` на `internal`-location, а не полное отключение кэша страницы.
- Протестируйте на нагрузочном тесте (`wrk`, `hey`) до/после включения: цель — снижение RPS на бэкенд и TTFB.

## Дополнительная информация

### Связь с другими техниками

- **[Кэширование в Nginx: обзор](./overview.md)** — архитектура client/server кэша, жизненный цикл объекта.
- **[Серверное кэширование (Proxy Cache)](./proxy_caching.md)** — полный набор директив, SWR, отравление кэша.
- **[Мониторинг кэширования в Nginx](./monitoring.md)** — JSON-логи, OpenTelemetry, Prometheus экспорт, eBPF.

### См. также

- [Обзор Nginx](../../Core/nginx_overview.md) — архитектура и роли Nginx.
- [Кэширование в Nginx: Обзор и концепции](./overview.md) — выбор стратегии кэширования.