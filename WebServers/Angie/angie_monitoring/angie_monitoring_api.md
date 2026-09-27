# Мониторинг Angie — Работа с конфигурацией и состоянием через API

## Определения

**HTTP API Angie** — встроенный REST-подобный интерфейс (модуль `ngx_http_api_module`), предоставляющий доступ к метрикам состояния, активной конфигурации и управлению апстримами в режиме реального времени. Данные передаются в формате JSON. Модуль включен в поставку по умолчанию и может быть отключен при сборке флагом `--without-http_api_module`.

**Stub Status** — простейший модуль мониторинга (`ngx_http_stub_status_module`), унаследованный от Nginx. Предоставляет базовую текстовую страницу с минимальными счетчиками (активные соединения, принятые/обработанные, чтение/запись/ожидание). Менее информативен, чем API, но не требует настройки зон и работает без разделяемой памяти. Требует флага `--with-http_stub_status_module` при сборке из исходников (в официальных пакетах включен по умолчанию).

**Keepalive Connection Pool** — пул соединений с апстримами, сохраняемых в открытом состоянии между запросами для повторного использования. Управляется директивой `keepalive` внутри блока `upstream`. Метрики пула доступны через API и отслеживают количество активных и промежуточных (idle) соединений.

**Конфигурационный API** — часть интерфейса, позволяющая получать содержимое файлов конфигурации, которые мастер-процесс Angie загрузил в память.

**Поколение конфигурации (Generation)** — целочисленный счетчик версий конфигурации. Инкрементируется при каждом успешном выполнении `reload`. Позволяет точно сопоставить работающие процессы с конкретной версией настроек.

## Базовые концепции

### Модуль `stub_status`

Простейший способ получить базовые метрики Angie — модуль `stub_status` (наследие Nginx). Он предоставляет текстовую страницу без JSON и разделяемой памяти.

**Директива `stub_status`:**

| Атрибут | Значение |
|:---|:---|
| Синтаксис | `stub_status;` |
| Контекст | `server`, `location` |

```nginx
location /basic_status {
    stub_status;
    allow 127.0.0.1;
    deny all;
}
```

**Формат вывода:**

```
Active connections: 291
server accepts handled requests
 16630948 16630948 31070465
Reading: 6 Writing: 179 Waiting: 106
```

| Поле | Описание |
|:---|:---|
| `Active connections` | Текущее количество активных соединений (включая ожидающие) |
| `accepts` | Общее число принятых соединений |
| `handled` | Общее число обработанных соединений (обычно равно `accepts`, если не достигнут `worker_connections`) |
| `requests` | Общее число запросов |
| `Reading` | Соединения, в которых Angie читает заголовок запроса |
| `Writing` | Соединения, в которых Angie отправляет ответ клиенту |
| `Waiting` | Простаивающие соединения, ожидающие запроса |

**Встроенные переменные:**

| Переменная | Описание |
|:---|:---|
| `$connections_active` | Количество активных соединений |
| `$connections_reading` | Соединения в фазе чтения |
| `$connections_writing` | Соединения в фазе записи |
| `$connections_waiting` | Простаивающие соединения |

> **Примечание:** Переменные регистрируются на этапе предварительной конфигурации HTTP и доступны в любом месте конфигурации (включая `add_header`), даже за пределами location со `stub_status`.

**Когда использовать `stub_status` вместо API:**
- Простые проверки доступности (health check) без необходимости в детальных метриках.
- Среды, где нежелательна зависимость от разделяемой памяти.
- Совместимость с существующими конфигурациями Nginx.

Для полноценного мониторинга (апстримы, зоны, кэш, SSL) используйте API — он значительно информативнее.

### Директива `api`

Активирует интерфейс API в конкретном `location`.

- **Синтаксис:** `api [/префикс/];`
- **Контекст:** `location`
- **Параметры:**
  - `/префикс/` — задает базовый путь для API (обязательный параметр). Заменяет путь, указанный в `location`, но в дереве API, а не файловой системы.

```nginx
# Полный доступ к API
location /status/ {
    api /status/;
}

# Частичный доступ — только HTTP server_zones
location /stats/ {
    api /status/http/server_zones/;
}

# С контролем доступа
location /status/ {
    api /status/;
    allow 127.0.0.1;
    deny all;
}

# С переменными и regex
location ~^/api/([^/]+)/(.*)$ {
    api /status/http/$1_zones/$2;
}
```

### Директива `api_config_files`

Управляет доступом к файлам конфигурации через API.

- **Синтаксис:** `api_config_files on | off;`
- **Контекст:** `http`
- **Значение по умолчанию:** `off` (из соображений безопасности).

### HTTP-методы и параметры запроса

API поддерживает только методы **GET** и **HEAD**. Попытки использовать POST, PUT, DELETE или PATCH вернут ошибку:

```json
{
    "error": "MethodNotAllowed",
    "description": "The POST method is not allowed for the requested API element \"/\"."
}
```

**Параметры query string:**

| Параметр | Описание |
|:---|:---|
| `pretty=off` | Компактный JSON без отступов (по умолчанию — с отступами) |
| `date=epoch` | Unix-эпоха (целое число) вместо ISO 8601 строк |
| `defaults=on` (PRO) | Возвращает значения по умолчанию в конфигурационном API |

### Keepalive директивы для upstream

Пул keepalive-соединений с бэкендами критически важен для производительности проксирования. Каждое повторное использование соединения экономит время на TCP handshake и (для HTTPS) TLS handshake.

**Директива `keepalive`:**

| Атрибут | Значение |
|:---|:---|
| Синтаксис | `keepalive connections;` |
| Контекст | `upstream` |
| По умолчанию | (не активировано) |

Параметр `connections` задает максимальное количество **простаивающих (idle)** keepalive-соединений в кэше **каждого** рабочего процесса. При превышении — наименее используемые соединения закрываются.

> **Важно:** `keepalive` **не** ограничивает общее число соединений с апстримами. Параметр управляет только кэшем простаивающих соединений. Активные соединения не учитываются в этом лимите.

```nginx
upstream http_backend {
    zone http_backend 1m;
    server 127.0.0.1:8080;
    keepalive 16;
}

server {
    location /http/ {
        proxy_pass http://http_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

> **Важно:** Для работы keepalive необходимо явно указать HTTP/1.1 и очистить заголовок `Connection` (значение по умолчанию — HTTP/1.0 с `Connection: close`).

**Дополнительные директивы:**

| Директива | Синтаксис | По умолчанию | Описание |
|:---|:---|:---|:---|
| `keepalive_requests` | `keepalive_requests number;` | `1000` | Максимальное число запросов через одно keepalive-соединение |
| `keepalive_time` | `keepalive_time time;` | `1h` | Максимальное время жизни keepalive-соединения |
| `keepalive_timeout` | `keepalive_timeout timeout;` | `60s` | Время ожидания idle-соединения перед закрытием |

**Ограничения keepalive:**
- Директива `keepalive` должна располагаться **после** всех директив, задающих метод балансировки.
- Кэшированные соединения матчатся с серверами **по адресу**. При удалении адреса через `resolve` или API `DELETE` кэшированные соединения **не закрываются** — они занимают слоты до закрытия сервером, истечения `keepalive_timeout` или вытеснения.
- При наличии idle keepalive-соединений, нескольких воркерах и разделяемой памяти общее число активных и idle соединений может превышать `max_conns`.

### Структура JSON-ответа

Корневой эндпоинт (обычно `/status/`) возвращает объект со ссылками на основные разделы:

```
/                           -> корневой объект
/angie                      -> версия, адрес, поколение, время загрузки
/connections                -> принятые, отброшенные, активные, простаивающие
/slabs/<zone>               -> страницы, слоты (статистика распределения памяти)
/resolvers/<zone>           -> запросы, ответы, отправлено (DNS-статистика)
/http/server_zones/<zone>   -> ssl, запросы, ответы, данные
/http/location_zones/<zone> -> запросы, ответы, данные
/http/caches/<zone>         -> размер, cold, hit, stale, updating и др.
/http/limit_conns/<zone>    -> passed, skipped, rejected, exhausted
/http/limit_reqs/<zone>     -> passed, skipped, delayed, rejected, exhausted
/http/upstreams/<upstream>  -> peers, keepalive
/http/metric_zones/<zone>   -> discarded, metrics
/http/acme_clients/<client> -> информация о сертификатах
/stream/server_zones/<zone> -> ssl, соединения, сессии, данные
/stream/upstreams/<upstream>-> peers
/stream/metric_zones/<zone> -> discarded, metrics
```

#### Серверный статус (`/status/angie`)

```json
{
    "version": "1.12.2",
    "build": "some-build-name",
    "build_time": "2026-09-17T16:05:43.805Z",
    "address": "192.168.16.5",
    "generation": 1,
    "load_time": "2026-09-17T16:15:43.805Z",
    "config_files": {
        "/etc/angie/angie.conf": "..."
    }
}
```

| Поле | Тип | Описание |
|:---|:---|:---|
| `version` | String | Версия Angie |
| `build` | String | Имя сборки (если указано) |
| `build_time` | String | Время сборки бинарного файла |
| `address` | String | Адрес сервера, принявшего запрос API |
| `generation` | Number | Счетчик перезагрузок конфигурации с момента старта |
| `load_time` | String | Время последней загрузки конфигурации |
| `config_files` | Object | Содержимое загруженных файлов (требует `api_config_files on`) |

#### Соединения (`/status/connections`)

```json
{
    "accepted": 2257,
    "dropped": 0,
    "active": 3,
    "idle": 1
}
```

| Поле | Описание |
|:---|:---|
| `accepted` | Общее число принятых соединений |
| `dropped` | Общее число отброшенных соединений (достигнут `worker_connections`) |
| `active` | Текущее число активных соединений |
| `idle` | Текущее число простаивающих keepalive-соединений |

#### HTTP server_zones (`/status/http/server_zones/<zone>`)

```json
{
    "ssl": {
        "handshaked": 4174,
        "reuses": 0,
        "timedout": 0,
        "failed": 0
    },
    "requests": {
        "total": 4327,
        "processing": 0,
        "discarded": 8
    },
    "responses": {
        "200": 4305,
        "302": 12,
        "404": 4
    },
    "data": {
        "received": 733955,
        "sent": 59207757
    }
}
```

| Поле | Описание |
|:---|:---|
| `ssl.handshaked` | Успешные SSL-хэндшейки |
| `ssl.reuses` | Повторное использование SSL-сессий |
| `ssl.timedout` | SSL-хэндшейки, завершившиеся по таймауту |
| `ssl.failed` | Неудачные SSL-хэндшейки |
| `requests.total` | Общее число запросов |
| `requests.processing` | Запросы, обрабатываемые в данный момент |
| `requests.discarded` | Завершенные запросы без отправки ответа |
| `responses.<code>` | Число ответов с указанным HTTP-кодом (100–599) |
| `data.received` | Получено байт от клиентов |
| `data.sent` | Отправлено байт клиентам |

> **Примечание:** Счетчик `responses` учитывает только **реально отправленные** ответы. Запросы, завершенные без ответа, попадают в `discarded`. Код `499` — внутренний код Angie (не реальный ответ), записывается только в access log; такие запросы учитываются в `discarded`, никогда в `responses`.

#### HTTP location_zones (`/status/http/location_zones/<zone>`)

| Поле | Описание |
|:---|:---|
| `requests.total` | Общее число запросов |
| `requests.discarded` | Завершенные запросы без отправки ответа |
| `responses.<code>` | Число ответов с указанным HTTP-кодом |
| `data.received` | Получено байт от клиентов |
| `data.sent` | Отправлено байт клиентам |

#### HTTP upstreams (`/status/http/upstreams/<upstream>`)

```json
{
    "peers": {
        "192.168.16.4:80": {
            "server": "backend.example.com",
            "service": "_example._tcp",
            "backup": false,
            "weight": 5,
            "state": "up",
            "selected": {
                "current": 2,
                "total": 232
            },
            "last": "2026-09-17T12:00:00Z",
            "max_conns": 5,
            "responses": {
                "200": 222,
                "302": 12
            },
            "data": {
                "sent": 543866,
                "received": 27349934
            },
            "health": {
                "fails": 0,
                "unavailable": 0,
                "downtime": 0,
                "downstart": "2026-09-17T11:30:00Z",
                "header_time": 21,
                "response_time": 42
            },
            "keepalive": 2
        }
    },
    "keepalive": 2
}
```

**Поля пира (peer):**

| Поле | Описание |
|:---|:---|
| `server` | Параметр директивы `server` |
| `service` | DNS SRV-сервис (если настроен) |
| `backup` | `true` для backup-серверов |
| `weight` | Настроенный вес |
| `state` | Текущее состояние (см. таблицу ниже) |
| `selected.current` | Текущее число соединений с пиром |
| `selected.total` | Общее число запросов, отправленных пиру |
| `last` | Время последнего выбора пира |
| `max_conns` | Максимум одновременных активных соединений (если задан) |
| `responses.<code>` | Число ответов с указанным кодом |
| `data.sent/received` | Отправлено/получено байт |
| `health.fails` | Общее число неудачных попыток связи |
| `health.unavailable` | Число срабатываний `max_fails` |
| `health.downtime` | Общее время недоступности (мс) |
| `health.downstart` | Время недоступности (только пока недоступен) |
| `health.header_time` | Среднее время получения заголовков (мс) |
| `health.response_time` | Среднее время получения полного ответа (мс) |
| `keepalive` | Текущее число кэшированных (idle) соединений с пиром |

**Состояния пиров (`state`):**

| Состояние | Описание |
|:---|:---|
| `up` | Сервер доступен и работает |
| `down` | Сервер выведен из эксплуатации вручную |
| `unhealthy` | Сервер не прошел проверки состояния (health checks) |
| `draining` | Сервер завершает обработку текущих соединений перед выключением |
| `busy` | Достигнут лимит `max_conns`, новые запросы не отправляются |
| `recovering` | Восстановление после сбоя через `slow_start` |

> **Примечание:** Поля `health.downstart` и `health.downtime` заполняются только при недоступности сервера. После восстановления `downstart` сбрасывается.

#### Stream/L4 upstreams (`/status/stream/upstreams/<upstream>`)

Аналогично HTTP, но с меньшим набором полей. Требуется директива `zone` в блоке `upstream` модуля Stream.

#### Зоны лимитов

**HTTP connections (`/status/http/limit_conns/<zone>`):**

| Поле | Описание |
|:---|:---|
| `passed` | Число соединений, прошедших через лимит |
| `skipped` | Соединения, пропущенные из-за `dry_run` |
| `rejected` | Отклоненные соединения (превышен лимит) |
| `exhausted` | Соединения, отклоненные из-за нехватки памяти в зоне |

**HTTP requests (`/status/http/limit_reqs/<zone>`):**

| Поле | Описание |
|:---|:---|
| `passed` | Число запросов, прошедших через лимит |
| `skipped` | Запросы, пропущенные из-за `dry_run` |
| `delayed` | Задержанные запросы (в очереди) |
| `rejected` | Отклоненные запросы (превышен лимит) |
| `exhausted` | Запросы, отклоненные из-за нехватки памяти в зоне |

**DNS resolvers (`/status/resolvers/<zone>`):**

| Поле | Описание |
|:---|:---|
| `queries` | Общее число DNS-запросов |
| `responses` | Полученные DNS-ответы |
| `sent` | Отправленные DNS-запросы |

## Практические сценарии

### Сценарий 1: Проверка актуальности конфигурации (Runtime vs Disk)

Команда `angie -T` показывает, что *будет* загружено при следующем старте. API показывает, что *уже* работает.

```nginx
http {
    api_config_files on;

    server {
        listen 127.0.0.1:8888;
        
        location /api/ {
            api /status/;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Получение списка файлов и их содержимого:**
```bash
# Список всех инклюдов
curl -s http://localhost:8888/api/status/angie/config_files/ | jq keys

# Чтение конкретного файла
curl -s http://localhost:8888/api/status/angie/config_files/etc/angie/http.d/backend.conf
```

### Сценарий 2: Мониторинг жизненного цикла процессов при Reload

Используется для выявления "зомби-воркеров", которые не завершаются из-за открытых соединений.

```bash
# Проверка текущего поколения мастера
GEN=$(curl -s http://localhost:8888/api/status/angie/ | jq .generation)

# Проверка поколений воркеров в системе
ps -eo pid,cmd | grep "angie: worker process"
# Ожидаемый результат: все процессы должны иметь gen=$GEN
```

### Сценарий 3: Детальный мониторинг апстримов

API позволяет получить состояние каждого сервера в группе балансировки.

```bash
# Получение статуса всех серверов в апстриме 'backend_cluster'
curl -s http://localhost:8888/api/status/http/upstreams/backend_cluster/ | jq '.peers[] | {server, state, active}'
```
**Ключевые состояния (`state`):**
- `up` — сервер доступен.
- `down` — сервер выведен из эксплуатации вручную.
- `unhealthy` — сервер не прошел проверки состояния (health checks).
- `draining` — сервер завершает обработку текущих соединений перед выключением.

### Сценарий 4: Нативный экспорт в формате Prometheus

Хотя Angie имеет отдельный модуль для Prometheus, API также может отдавать данные в этом формате при добавлении заголовка или использовании специального пути.

```bash
# Получение метрик в формате OpenMetrics/Prometheus через основной API
curl -s http://localhost:8888/api/status/prometheus
```

### Сценарий 5: Быстрый health check через stub_status

Для простых проверок доступности (load balancer health check) `stub_status` подходит лучше API — он легче и не требует настройки разделяемой памяти.

```nginx
server {
    listen 8080;

    location /health {
        stub_status;
        allow 10.0.0.0/8;
        deny all;
    }
}
```

**Проверка через curl:**
```bash
curl -s http://localhost:8080/health
# → Active connections: 1
# → server accepts handled requests
# →  123456 123456 234567
# → Reading: 0 Writing: 1 Waiting: 0
```

**Парсинг активных соединений для алертинга:**
```bash
ACTIVE=$(curl -s http://localhost:8080/health | awk '/Active connections/{print $3}')
if [ "$ACTIVE" -gt 1000 ]; then
    echo "ALERT: Active connections above threshold: $ACTIVE"
fi
```

### Сценарий 6: Мониторинг эффективности keepalive пула

Мониторинг использования keepalive-пула позволяет выявить проблемы с конфигурацией соединений с бэкендами.

```bash
# Проверка keepalive соединений для конкретного upstream
curl -s http://localhost:8888/api/status/http/upstreams/backend_cluster/ | jq '{
    upstream_peers: [.peers[] | {server, keepalive, selected: .selected.current}],
    total_keepalive: .keepalive
}'
# → {
# →   "upstream_peers": [
# →     {"server": "10.0.0.1:8080", "keepalive": 8, "selected": 3},
# →     {"server": "10.0.0.2:8080", "keepalive": 6, "selected": 2}
# →   ],
# →   "total_keepalive": 14
# → }
```

**Индикаторы проблем:**
- `keepalive = 0` на всех пирах при наличии `keepalive N` в конфигурации — соединения не кэшируются (проверьте `proxy_http_version 1.1` и `proxy_set_header Connection ""`).
- `keepalive` растет до значения `keepalive` в конфигурации — пул работает эффективно.
- `health.fails > 0` — проблемы с доступностью бэкенда.

### Сценарий 7: Мониторинг TCP/UDP сервисов (L4)

Для мониторинга проксированных TCP/UDP-соединений (PostgreSQL, DNS, Redis) используется модуль Stream.

```nginx
stream {
    upstream pg_cluster {
        zone pg_cluster 64k;
        server 10.0.0.1:5432;
        server 10.0.0.2:5432;
    }

    server {
        listen 5432;
        status_zone postgres_proxy;
        proxy_pass pg_cluster;
    }
}
```

**Получение L4-метрик:**
```bash
# Сессии Stream upstream
curl -s http://localhost:8888/api/status/stream/upstreams/pg_cluster/ | jq '.peers[] | {server, state, sessions}'

# Server zones Stream
curl -s http://localhost:8888/api/status/stream/server_zones/postgres_proxy/
```

## Операции и команды

Краткая сводка повседневных проверок через Status API:

```bash
# Версия и поколение конфигурации
curl -s http://localhost:8888/api/status/angie/ | jq '{version, generation}'

# Активные/ожидающие соединения
curl -s http://localhost:8888/api/status/connections/ | jq '.accepted, .active'

# Состояние конкретного upstream
curl -s http://localhost:8888/api/status/http/upstreams/api_backend/ | jq '.peers[] | {server, state, requests}'

# Показатели кэша
curl -s http://localhost:8888/api/status/http/caches/api_cache/ | jq '{miss, hit, stale}'
```

## Устранение неисправностей (Troubleshooting)

**API возвращает пустой JSON для upstream:**
- Убедитесь, что в блоке `upstream` указана директива `zone <имя> <размер>;`. Без нее метрики upstream не собираются.

**`config_files` не отображается:**
- Проверьте, что `api_config_files on;` задано в контексте `http` (не в `location`).

**Метрики сбрасываются при `stop`/`start`:**
- Это ожидаемое поведение. Метрики хранятся в разделяемой памяти, которая освобождается при остановке процесса. При `reload` метрики сохраняются.

**Keepalive-соединения не кэшируются:**
- Проверьте `proxy_http_version 1.1;` и `proxy_set_header Connection "";` в location.
- Убедитесь, что бэкенд поддерживает HTTP/1.1 и keepalive.

**Высокое потребление памяти зонами:**
- Проверьте размеры зон через `/status/slabs/`. Для крупных установок увеличьте размер зон (например, `zone app_cluster 2m;`).

**API отвечает медленно:**
- Используйте `pretty=off` для компактного JSON.
- Запрашивайте только нужные подпути (например, `/status/http/upstreams/my_upstream/` вместо `/status/`).

## Лучшие практики

1.  **Выделенный порт для API**: выносите `location /api/` на `listen 127.0.0.1:8888;` — API не должен видеть интернет.
2.  **`api_config_files` включайте только при необходимости**: файлы конфигурации могут содержать пароли и ключи; по умолчанию — `off`.
3.  **`write=on` только где нужно**: включайте динамическое управление апстримами только на инстансах с Service Discovery; на остальных — `off`/не указывать.
4.  **Аутентификация**: для API на внешнем интерфейсе используйте `auth_basic`/`auth_jwt` + `allow`/`deny`.
5.  **Мониторинг поколения**: снимайте `generation` из `/status/angie/` в алерты — резкий скачок указывает на неожиданный `reload`.
6.  **Не заводите тяжёлые `pretty`-ответы в сценариях сбора**: ставьте `?pretty=off` при pull-опросах Prometheus/Grafana.

## Дополнительная информация

### Полная таблица эндпоинтов API

**Общая информация:**

| Путь | Описание |
|:---|:---|
| `/status/` | Корневой объект со ссылками на все разделы |
| `/status/angie/` | Версия, билд, поколение и время загрузки мастера |
| `/status/angie/config_files/` | Содержимое файлов конфигурации (требует `api_config_files on`) |
| `/status/connections/` | Принятые, отброшенные, активные и простаивающие соединения |
| `/status/slabs/<zone>/` | Статистика распределения памяти (слэбы) |

**HTTP:**

| Путь | Описание |
|:---|:---|
| `/status/http/server_zones/<zone>/` | Метрики виртуального хоста (SSL, запросы, ответы, трафик) |
| `/status/http/location_zones/<zone>/` | Метрики по конкретной локации |
| `/status/http/upstreams/<upstream>/` | Состояние серверов в группе балансировки |
| `/status/http/caches/<zone>/` | Статистика кэша (размер, hit/miss/stale) |
| `/status/http/limit_conns/<zone>/` | Лимиты числа соединений |
| `/status/http/limit_reqs/<zone>/` | Лимиты частоты запросов |
| `/status/http/metric_zones/<zone>/` | Пользовательские метрики (модуль `metric`) |
| `/status/http/acme_clients/<client>/` | Информация о SSL-сертификатах ACME |

**Stream (L4):**

| Путь | Описание |
|:---|:---|
| `/status/stream/server_zones/<zone>/` | Метрики Stream-серверов (SSL, соединения, сессии, трафик) |
| `/status/stream/upstreams/<upstream>/` | Состояние серверов в Stream upstream |
| `/status/stream/metric_zones/<zone>/` | Пользовательские метрики Stream |

**DNS:**

| Путь | Описание |
|:---|:---|
| `/status/resolvers/<zone>/` | Статистика DNS-резолвера (запросы, ответы) |

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md) — определения `status_zone`, иерархия L4/L7, расчет памяти
- [Настройка Console Light и API](./angie_monitoring_console.md) — веб-интерфейс для визуализации метрик API
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md) — экспорт метрик в Prometheus/Grafana
