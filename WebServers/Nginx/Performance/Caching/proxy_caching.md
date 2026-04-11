# Серверное кэширование (Proxy Cache) в Nginx

## Определения

**Серверное кэширование (Proxy Cache)** — механизм, при котором Nginx сохраняет ответы от бэкенд-серверов на диске и в разделяемой памяти, чтобы отдавать их клиентам напрямую без повторного обращения к бэкенду.

**Кэш-зона (Cache Zone)** — именованная область в разделяемой памяти (`keys_zone`), хранящая ключи кэшированных объектов и их метаданные. Определяется директивой `proxy_cache_path` в контексте `http`.

**Ключ кэша (Cache Key)** — уникальная строка, формируемая из параметров запроса, по которой Nginx ищет сохранённый ответ в кэше.

**Статус кэша (Cache Status)** — индикатор результата обработки запроса:

| Статус | Значение |
|:-------|:---------|
| `MISS` | Запрос не найден в кэше, ответ получен от бэкенда |
| `HIT` | Ответ отдан из кэша |
| `EXPIRED` | Запись устарела, запрос ушёл на бэкенд для обновления |
| `STALE` | Отдан устаревший ответ из-за недоступности бэкенда |
| `UPDATING` | Отдан устаревший ответ, пока кэш обновляется в фоне |
| `BYPASS` | Кэш был обойден по условию `proxy_cache_bypass` |
| `REVALIDATED` | Nginx успешно валидировал кэш у бэкенда (получил `304 Not Modified`) |

Обзор всех типов кэширования — в [overview.md](./overview.md). Общие паттерны кэширования — в [caching_overview.md](../../../../Concepts/Caching/caching_overview.md).

## Основные концепции

### Архитектура кэша

Кэш в Nginx состоит из двух компонентов:

1. **Разделяемая память (shared memory)** — зона `keys_zone`, хранит ключи и метаданные. Размер указывается при определении `proxy_cache_path` (например, `keys_zone=my_cache:10m`).
2. **Дисковое хранилище** — файлы кэшированных ответов. Структура директорий задаётся параметром `levels`.

Двухуровневая структура (`levels=1:2`) предотвращает деградацию производительности файловой системы при большом количестве файлов.

### Жизненный цикл кэшированного ответа

1. Клиент отправляет запрос.
2. Nginx формирует ключ кэша и проверяет наличие объекта.
3. При `MISS` — запрос направляется на бэкенд, ответ сохраняется в кэш.
4. При `HIT` — ответ отдаётся клиенту без обращения к бэкенду.
5. По истечении TTL (`proxy_cache_valid`) — статус меняется на `EXPIRED`, следующий запрос обновит объект.

### Эффект «стада бизонов» (Cache Stampede)

При сбросе кэша или первом запуске тысячи одновременных запросов к одному ресурсу могут обрушить бэкенд. Защита — `proxy_cache_lock`: первый запрос уходит на бэкенд и ставит блокировку, остальные ожидают ответа из кэша.

### Отказоустойчивость

Директива `proxy_cache_use_stale` разрешает отдачу устаревшего кэша при недоступности бэкенда (ошибки, таймауты). В сочетании с `proxy_cache_background_update` (Nginx Plus / [Angie](../../../Angie/angie_overview.md)) кэш обновляется в фоне, а клиенты получают актуальную версию сразу после обновления.

## Практические сценарии

### Базовая конфигурация кэширования

Определение зоны кэширования в контексте `http` (файл `nginx.conf`):

```nginx
proxy_cache_path /var/cache/nginx/proxy_cache
                  levels=1:2
                  keys_zone=my_cache:10m
                  inactive=60m
                  max_size=1g;
```

Параметры:

| Параметр | Описание |
|:---------|:---------|
| `levels=1:2` | Двухуровневая структура директорий (1 символ / 2 символа) |
| `keys_zone=my_cache:10m` | Зона в памяти: имя `my_cache`, размер 10 МБ |
| `inactive=60m` | Удаление неиспользуемых объектов через 60 минут |
| `max_size=1g` | Максимальный размер на диске; при превышении `cache manager` удаляет старые объекты |

Применение в `location`:

```nginx
location / {
    proxy_pass http://my_backend;

    # Включение кэша
    proxy_cache my_cache;

    # Ключ кэширования: схема + метод + хост + URI
    proxy_cache_key "$scheme$request_method$host$request_uri";

    # Время жизни для разных кодов ответа
    proxy_cache_valid 200 302 10m;
    proxy_cache_valid 404 1m;
    proxy_cache_valid any 5m;

    # Кэшировать объект после 3 запросов
    proxy_cache_min_uses 3;

    # Заголовок для отладки
    add_header X-Cache-Status $upstream_cache_status;
}
```

### Кэширование API

```nginx
location /api/v1/data {
    proxy_pass http://backend_upstream;

    proxy_cache api_cache;
    proxy_cache_valid 200 5m;
    proxy_cache_valid 404 1m;
    proxy_cache_key "$scheme$request_method$host$request_uri";

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;

    add_header X-Cache-Status $upstream_cache_status;
}
```

### Обход и запрет кэширования

**`proxy_cache_bypass`** — Nginx не берёт ответ из кэша, обращается к бэкенду напрямую:

```nginx
# Обход по куке или GET-параметру
proxy_cache_bypass $cookie_nocache $arg_nocache;

# Обход по заголовку
proxy_cache_bypass $http_x_no_cache;
```

**`proxy_no_cache`** — ответ не сохраняется в кэш:

```nginx
# Не сохранять, если есть кука сессии
proxy_no_cache $cookie_session;
```

### Защита от «стада бизонов»

```nginx
location / {
    proxy_cache_lock on;
    proxy_cache_lock_timeout 5s;
}
```

`proxy_cache_lock_timeout` — максимальное время ожидания блокировки. Если бэкенд не ответил за это время, следующий запрос также будет пропущен на бэкенд.

### Отказоустойчивость с отдачей устаревшего кэша

```nginx
location / {
    proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
    proxy_cache_background_update on;  # Nginx Plus / Angie
}
```

`proxy_cache_background_update` требует `proxy_cache_use_stale updating`.

### Управление заголовками бэкенда

`proxy_ignore_headers` позволяет игнорировать заголовки, запрещающие кэширование:

```nginx
proxy_ignore_headers Cache-Control Expires Set-Cookie;
```

### Точечная очистка кэша (Cache Purge)

Для выборочной очистки используется модуль `ngx_cache_purge` (входит в Angie, для Nginx требует отдельной установки).

Настройка `location` для очистки:

```nginx
location ~ /purge(/.*) {
    # Ограничение доступа — только доверенные IP
    allow 127.0.0.1;
    allow 192.168.77.0/24;
    deny all;

    proxy_cache_purge api_cache "$scheme$host$1";
}
```

Переменная `$1` содержит часть URI из захвата `(/.*)`. Например, запрос `GET /purge/api/v1/data` удалит из кэша `api_cache` объект с ключом, соответствующим `/api/v1/data`.

Пример очистки:

```bash
curl -X GET "http://example.com/purge/api/v1/data"
```

## Дополнительная информация

### Версионная совместимость

| Функция | Nginx OSS | Nginx Plus | Angie |
|:--------|:----------|:-----------|:------|
| `proxy_cache` | Да | Да | Да |
| `proxy_cache_lock` | Да | Да | Да |
| `proxy_cache_background_update` | Нет | Да | Да |
| `proxy_cache_purge` | Сторонний модуль | Да | Включён |

### Смотрите также

- Обзор кэширования в Nginx — [overview.md](./overview.md)
- Клиентское кэширование в Nginx — [client_caching.md](./client_caching.md)
- Мониторинг кэширования — [monitoring.md](./monitoring.md)
