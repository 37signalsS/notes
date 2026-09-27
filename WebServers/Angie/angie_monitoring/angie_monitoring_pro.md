# Мониторинг Angie — возможности Angie Pro

## Определения

**Angie Pro** — коммерческая редакция веб-сервера Angie, предназначенная для эксплуатации в критически важных инфраструктурах. Включает расширенный набор инструментов для динамического управления трафиком, глубокого мониторинга состояния и обеспечения высокой доступности. Бинарная и конфигурационная совместимость с Angie OSS позволяет переход на Pro без изменения существующей логики работы.

**Upstream Probe** — нативный механизм активных проверок состояния бэкенд-серверов в Angie Pro (директива `upstream_probe`). Отличается от модуля `check` в OSS гибкостью настройки: поддерживает именованные блоки `match`, HTTP-методы, проверку тела ответа, пороги `fails`/`passes`, режимы работы (`always`, `idle`, `onfail`) и начальную верификацию (`essential`). Располагается в `location` (не в `upstream`), что позволяет настраивать разные проверки для разных проксирующих локаций.

**Dynamic Feedback** — алгоритм балансировки, автоматически корректирующий нагрузку на серверы на основе данных от самих бэкендов. В отличие от статических весов и `least_time`, анализирует переменную (CPU load, latency, custom metric), передаваемую сервером приложения, и снижает приоритет деградирующих узлов.

**State File (Персистентность)** — файл на диске, в который Angie Pro сохраняет все динамические изменения конфигурации апстримов (веса серверов, `down`, `drain`). Обеспечивает сохранение состояния балансировщика после перезагрузки сервиса без ручной правки основного файла конфигурации.

**Key-Value Zone** — разделяемая память для хранения пар ключ-значение, доступная через REST API. Позволяет динамически управлять поведением Angie без перезагрузки: списки доступа, rate limiting по ключам, feature flags.

**Queue (Очередь запросов)** — PRO-механизм удержания запросов в очереди при достижении `max_conns` на всех серверах апстрима. Вместо мгновенного возврата 502 Bad Gateway запросы ожидают освобождения слота в течение заданного таймаута.

**Bind Conn** — директива Pro для условной привязки клиентского TCP-соединения к соединению с проксируемым сервером. Необходима для NTLM-аутентификации (Exchange, Active Directory), где одно соединение должно поддерживаться на всех этапах обработки запроса.

**Sticky Learn (External Store)** — расширенный метод привязки сессий, при котором данные о привязке хранятся во внешнем хранилище (shared memory zone). Позволяет объединять несколько балансировщиков в кластер с общей таблицей сессий.

**Console Pro** — расширенная версия графического интерфейса мониторинга (модуль `ngx_http_console_module`). Дополняет Console Lite управлением KV-зонами, визуализацией latency percentiles, детальной статистикой sticky sessions и фильтрацией активных соединений в реальном времени.

## Базовые концепции

### Ключевые отличия мониторинга и управления в версии Pro

| Функция | Angie OSS | Angie Pro |
|:---|:---|:---|
| **API управления** | Чтение / Ограниченная запись | Полнофункциональный REST API (`write=on`) |
| **Активные проверки** | Директива `check` (модуль `upstream_check_module`) | Директива `upstream_probe` в location (гибче, нативнее) |
| **Хранилище Key-Value** | Нет | Да (`keyval_zone`) |
| **Балансировка** | RR, Least Conn, Least Time, Hash | + Dynamic Feedback (по данным от бэкендов) |
| **Sticky Sessions** | Cookie, Route, Learn | + Sticky Learn с внешним хранилищем (кластеризация) |
| **Очередь запросов** | Нет (502 при `max_conns`) | Да (`queue` — удержание запросов) |
| **Привязка соединений** | Нет | `bind_conn` (NTLM, Exchange) |
| **Консоль управления** | Console Lite | Console Pro (Enterprise UI) |
| **Лицензия** | N/A | Эндпоинт `/status/angie/license` |

### Динамическое управление Upstream и персистентность

В версии Pro реализована поддержка директивы `state`, которая позволяет сохранять все изменения, внесенные через API (смена весов серверов, перевод в `down` или `drain`), в файл на диске. Это гарантирует сохранение актуального состояния балансировщика после перезагрузки сервиса без необходимости ручной правки основного файла конфигурации.

```nginx
upstream backend_cluster {
    zone backend_cluster 128k;
    state /var/lib/angie/backend_cluster.state;   # Персистентность

    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}
```

**Как работает state file:**
- Angie записывает изменения при каждом успешном API-запросе `PATCH`/`POST`/`DELETE` к апстриму.
- При старте Angie читает state file и применяет сохраненные веса/состояния.
- Формат файла — внутренний, не предназначен для ручного редактирования.
- При конфликте между конфигурацией и state file побеждает state file (последнее сохраненное состояние через API).

> **Важно:** При `reload` state file **не** перечитывается — изменения через API сохраняются без перезагрузки. Перечитывание происходит только при полном `stop`/`start`.

### Нативные активные проверки (`upstream_probe`)

Директива `upstream_probe` в Angie Pro — замена модулю `check` из OSS. Располагается в `location` (а не в `upstream`), что позволяет настраивать разные проверки для разных проксирующих путей.

**Синтаксис:**

| Атрибут | Значение |
|:---|:---|
| Синтаксис | `upstream_probe name [uri=address] [port=number] [interval=time] [method=method] [test=condition] [essential [persistent]] [fails=number] [passes=number] [max_body=size] [mode=always\|idle\|onfail];` |
| Контекст | `location` |

**Параметры:**

| Параметр | По умолчанию | Описание |
|:---|:---|:---|
| `name` | (обязательный) | Имя проверки (уникальное в пределах location) |
| `uri` | `/` | URI для запроса проверки (аппендится к `proxy_pass`) |
| `port` | (порт `proxy_pass`) | Альтернативный порт для проверки |
| `interval` | `5s` | Интервал между проверками |
| `method` | `GET` | HTTP-метод запроса |
| `test` | — | Условие проверки (строка с переменными); `""` или `"0"` = fail |
| `essential` | (отсутствует) | Сервер не получает клиентские запросы до прохождения проверки |
| `persistent` | (отсутствует) | Серверы, работавшие до `reload`, не требуют прохождения проверки |
| `fails` | `1` | Число последовательных неудач для перевода в unhealthy |
| `passes` | `1` | Число последовательных успехов для перевода в healthy |
| `max_body` | `256k` | Максимальный размер тела ответа для проверки |
| `mode` | `always` | Режим проверки: `always` / `idle` / `onfail` |

**Режимы работы:**
- `always` — проверяются все серверы независимо от состояния.
- `idle` — проверяются unhealthy-серверы и серверы, по которым не было клиентских запросов в течение `interval`.
- `onfail` — проверяются только unhealthy-серверы.

**Логика перевода состояний:**
- Сервер считается **нездоровым**, если **любая** из настроенных для него проверок достигает порога `fails` **или** сервер достигает порога `max_fails`.
- Для восстановления **все** проверки должны достичь своих порогов `passes`.
- Если `essential` указан, клиентские запросы не направляются на сервер до прохождения **всех** essential-проверок.
- Если `persistent` указан, серверы, работавшие до `reload`, запускаются без проверки.

**Пример конфигурации:**

```nginx
upstream backend {
    zone backend 1m;
    server backend1.example.com;
    server backend2.example.com;
}

map $upstream_status $good {
    200     "1";
}

server {
    listen 443 ssl;

    location /backend {
        proxy_pass http://backend;

        upstream_probe backend_probe
            uri=/probe
            port=8080
            interval=5s
            method=GET
            test=$good
            essential
            persistent
            fails=3
            passes=2
            max_body=10m
            mode=idle;
    }
}
```

> **Сравнение с OSS `check`:** Модуль `check` в OSS работает в контексте `upstream` и использует собственный синтаксис (`check interval=5s fall=3 rise=2`). `upstream_probe` в Pro гибче: поддерживает пороги `fails`/`passes`, режимы `idle`/`onfail`, проверку тела ответа, несколько проверок на один upstream и начальную верификацию `essential`.

### Хранилище Key-Value (KV Store)

Angie Pro предоставляет механизм разделяемой памяти для хранения пар ключ-значение. Это позволяет динамически управлять поведением сервера без перезагрузки:
- Управление списками доступа (IP blacklist/whitelist).
- Динамическое ограничение скорости (Rate limiting) по ключам.
- Переключение флагов функциональности (Feature flags) на уровне L7.

**Директивы KV-хранилища:**

| Директива | Контекст | Описание |
|:---|:---|:---|
| `keyval_zone zone=name:size [state=file] [type=ip\|string] [sync=time]` | `http` | Объявление KV-зоны |
| `keyval $key $variable zone=name` | `http` | Привязка переменной к ключу KV-зоны |

**Параметры `keyval_zone`:**

| Параметр | Описание |
|:---|:---|
| `zone=name:size` | Имя и размер разделяемой памяти |
| `state=file` | Путь к файлу для персистентности (аналог `state` для upstream) |
| `type=ip\|string` | Тип ключа: `ip` (по умолчанию, для CIDR) или `string` |
| `sync=time` | Интервал синхронизации с state file (по умолчанию — при изменении) |

**API-эндпоинты KV:**

| Метод | Путь | Описание |
|:---|:---|:---|
| `GET` | `/status/http/keyvals/<zone>` | Чтение всех пар |
| `POST` | `/status/http/keyvals/<zone>` | Добавление/обновление пар (JSON body) |
| `DELETE` | `/status/http/keyvals/<zone>/<key>` | Удаление ключа |

### Алгоритм Dynamic Feedback

Интеллектуальный алгоритм балансировки, который автоматически корректирует нагрузку на серверы на основе их текущей производительности. В отличие от статических весов, `feedback` анализирует переменную (CPU load, latency, custom metric), передаваемую сервером приложения, и снижает приоритет деградирующих узлов.

**Синтаксис:**

| Атрибут | Значение |
|:---|:---|
| Синтаксис | `feedback variable=$var [interval=time] [weight=number];` |
| Контекст | `upstream` |

```nginx
upstream highload_app {
    zone highload_app 128k;
    server srv1.example.com;
    server srv2.example.com;

    # Переменная с данными от бэкенда (например, через заголовок)
    set $backend_load "";
    proxy_set_header X-Backend-Load $backend_load;

    feedback variable=$backend_load interval=5s;
}
```

**Принцип работы:**
- Бэкенд передает значение переменной (например, через заголовок ответа или special endpoint).
- Angie обновляет веса серверов пропорционально значению переменной.
- Интервал обновления настраивается через `interval`.
- Переменная должна быть строковым числом (дробное или целое).

> **Примечание:** Подробнее об алгоритмах балансировки, включая `least_time` и `hash`, см. в [Балансировка нагрузки HTTP в Angie](../angie_http_load_balancing.md).

### Очередь запросов (Queue)

PRO-механизм удержания запросов в очереди при достижении лимита одновременных соединений на всех серверах апстрима.

**Синтаксис:**

| Атрибут | Значение |
|:---|:---|
| Синтаксис | `queue number [timeout=time] [jitter=number];` |
| Контекст | `upstream` |

| Параметр | Описание |
|:---|:---|
| `number` | Максимальный размер очереди |
| `timeout` | Максимальное время ожидания в очереди (по умолчанию `60s`) |
| `jitter` | Доля случайного отклонения таймаута (0.0–1.0) для предотвращения thundering herd |

```nginx
upstream app_servers {
    zone app_servers 128k;
    server 10.0.0.1:8080 max_conns=100;
    server 10.0.0.2:8080 max_conns=100;

    # Очередь на 500 запросов, таймаут 30с
    queue 500 timeout=30s;
}
```

**Поведение:**
- Когда все серверы достигают `max_conns`, новые запросы попадают в очередь.
- Если очередь заполнена или таймаут истек — клиент получает 502 Bad Gateway.
- При освобождении слота запрос из очереди направляется на освободившийся сервер.
- `jitter` добавляет случайность к таймауту, предотвращая массовый одновременный возврат ошибок.

### Sticky Sessions с внешним хранилищем

Расширенный метод `learn` в Pro поддерживает хранение данных о привязке сессий во внешнем хранилище (shared memory zone). Это позволяет объединять несколько балансировщиков Angie в кластер — все инстансы используют общую таблицу сессий.

```nginx
upstream stateful_app {
    zone stateful_app 256k;

    sticky learn
           create=$upstream_cookie_jsessionid
           lookup=$cookie_jsessionid
           zone=client_sessions:2m    # Общая зона для кластера
           expire=1h;                 # Время жизни записи

    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}
```

**Параметры `sticky learn`:**

| Параметр | Описание |
|:---|:---|
| `create=$variable` | Переменная для создания записи привязки |
| `lookup=$variable` | Переменная для поиска существующей привязки |
| `zone=name:size` | Shared memory zone для хранения данных |
| `expire=time` | Время жизни записи (TTL) |

> **Примечание:** В OSS доступны методы `cookie` и `route`. Метод `learn` с внешним хранилищем — эксклюзив Pro.

### Bind Conn для NTLM

Директива `bind_conn` обеспечивает привязку клиентского TCP-соединения к соединению с проксируемым сервером на протяжении всего цикла обработки. Критична для NTLM-аутентификации (Microsoft Exchange, Active Directory), где протокол требует сохранения одного соединения на всех этапах handshake.

```nginx
upstream ntlm_backend {
    zone ntlm_backend 64k;
    server 10.0.0.1:8080;
}

server {
    location /exchange/ {
        proxy_pass http://ntlm_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        bind_conn;   # Привязка соединения (PRO)
    }
}
```

### Разделение API: конфигурация vs статус

Angie Pro позволяет разделить API динамической конфигурации (`write=on`) и API статуса (read-only) на разные эндпоинты. Это улучшает безопасность: статус доступен шире, а управление — только доверенным клиентам.

```nginx
# Динамическая конфигурация (write=on) — только изнутри
location /config/ {
    api /config/;
    allow 10.0.0.0/8;
    deny all;
}

# Read-only статус — доступен мониторингу
location /status/ {
    api /status/;
    allow 10.0.0.0/8;
    deny all;
}
```

### Эндпоинт лицензии

Pro предоставляет эндпоинт для проверки статуса лицензии:

```
GET /status/angie/license
```

```json
{
    "path": "/etc/angie/license.pem",
    "status": "valid",
    "owner": "Example Corp",
    "days_left": 30,
    "since": "2026-01-01",
    "until": "2027-01-01",
    "limits": {
        "worker_processes": 16,
        "worker_connections": 65535
    }
}
```

| Поле | Описание |
|:---|:---|
| `status` | Статус лицензии: `missing`, `invalid`, `valid`, `grace`, `expired`, `pending` |
| `days_left` | Дней до изменения статуса (отрицательное — уже истекла) |
| `limits` | Лимиты лицензии: максимальные `worker_processes` и `worker_connections` |

## Практические сценарии

### Сценарий 1: Динамическое управление через API с сохранением состояния

Настройка upstream с персистентностью и API для управления серверами в runtime.

```nginx
http {
    upstream backend_cluster {
        zone backend_cluster 128k;
        # Сохранение динамических изменений состояния на диск
        state /var/lib/angie/backend_cluster.state;

        server 10.0.0.1:8080;
        server 10.0.0.2:8080;
    }

    server {
        listen 8888;
        location /api/ {
            api write=on; # Разрешение модификации через API
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Проверка работоспособности:**
```bash
# Просмотр текущего состояния апстрима
curl -s http://localhost:8888/api/status/http/upstreams/backend_cluster/ | jq '.peers[] | {server, state, weight}'

# Динамическое изменение веса сервера
  curl -X PATCH -d '5' \
  http://127.0.0.1/config/http/upstreams/backend_cluster/servers/0/weight

# Проверка сохранения в state file
cat /var/lib/angie/backend_cluster.state
```

### Сценарий 2: Активная проверка состояния через upstream_probe

Настройка глубокой проверки доступности API-сервера с валидацией по HTTP-коду, Content-Type и телу ответа.

```nginx
http {
    upstream api_service {
        zone api_service 64k;
        server app1.internal:8443;
        server app2.internal:8443;
    }

    map $upstream_status $api_healthy {
        200     "1";
    }

    server {
        listen 443 ssl;

        location /api/ {
            proxy_pass https://api_service;
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            # Pro: upstream_probe вместо OSS check
            upstream_probe api_health
                uri=/v1/status
                interval=10s
                method=GET
                test=$api_healthy
                essential
                persistent
                fails=3
                passes=2
                mode=idle;
        }
    }
}
```

**Проверка работоспособности:**
```bash
# Просмотр состояния серверов (после прохождения проверок)
curl -s http://localhost:8888/api/status/http/upstreams/api_service/ | jq '.peers[] | {server, state, health}'

# Проверка логов Angie на ошибки проверки
grep "upstream_probe" /var/log/angie/error.log | tail -5
```

### Сценарий 3: Использование Key-Value для динамической блокировки IP

Динамическое управление списком заблокированных IP через REST API без перезагрузки конфигурации.

```nginx
http {
    # Объявление KV-зоны на 10 МБ с сохранением на диск
    keyval_zone zone=blocked_ips:10m state=/var/lib/angie/blocked.keyval;
    keyval $remote_addr $target zone=blocked_ips;

    server {
        listen 80;
        if ($target) {
            return 403;
        }
        location / {
            proxy_pass http://backend;
        }
    }

    # API для управления KV-зоной
    server {
        listen 8888;
        location /kv/ {
            api /status/http/keyvals/blocked_ips;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Управление через API:**
```bash
# Добавление IP в список блокировки
curl -X POST -H "Content-Type: application/json" \
     -d '{"192.168.1.100": "blocked"}' \
     http://localhost:8888/kv/

# Просмотр текущего списка
curl -s http://localhost:8888/kv/ | jq .
# → {"192.168.1.100": "blocked"}

# Удаление IP из списка
curl -X DELETE http://localhost:8888/kv/192.168.1.100

# Блокировка CIDR-подсети (type=ip в keyval_zone)
curl -X POST -H "Content-Type: application/json" \
     -d '{"10.0.0.0/8": "blocked"}' \
     http://localhost:8888/kv/
```

### Сценарий 4: Балансировка по методу Feedback

Настройка адаптивной балансировки, которая учитывает текущую загрузку серверов приложения.

```nginx
http {
    upstream highload_app {
        zone highload_app 128k;

        # Бэкенд передает загрузку через заголовок ответа
        # (на стороне приложения: X-Backend-Load: 0.75)
        set $backend_load "";

        server srv1.example.com;
        server srv2.example.com;

        feedback variable=$backend_load interval=5s;
    }

    server {
        listen 80;
        location / {
            proxy_pass http://highload_app;
            proxy_set_header X-Backend-Load "";
            # Заголовок заполняется ответом бэкенда
            proxy_hide_header X-Backend-Load;
            set $backend_load $upstream_http_x_backend_load;
        }
    }
}
```

**Проверка:**
```bash
# Просмотр весов серверов (влияние feedback)
curl -s http://localhost:8888/api/status/http/upstreams/highload_app/ | jq '.peers[] | {server, weight, selected}'

# Мониторинг распределения запросов
watch -n 2 'curl -s http://localhost:8888/api/status/http/upstreams/highload_app/ | jq ".peers[] | {server, selected: .selected.total}"'
```

### Сценарий 5: Очередь запросов при высокой нагрузке

Настройка очереди для удержания запросов при временной нехватке Capacity бэкендов.

```nginx
http {
    upstream critical_service {
        zone critical_service 128k;
        server 10.0.0.1:8080 max_conns=50;
        server 10.0.0.2:8080 max_conns=50;

        # Очередь на 200 запросов, таймаут 15с, jitter 0.1
        queue 200 timeout=15s jitter=0.1;
    }

    server {
        listen 443 ssl;

        location /api/ {
            proxy_pass http://critical_service;
            proxy_next_upstream timeout;
        }
    }
}
```

**Проверка:**
```bash
# Проверка размера очереди через API
curl -s http://localhost:8888/api/status/http/upstreams/critical_service/ | jq '.peers[] | {server, selected}'

# Имитация нагрузки для проверки очереди
ab -n 1000 -c 100 https://localhost/api/
```

### Сценарий 6: Мониторинг статуса лицензии

Проверка лицензии через API для алертинга при приближении к истечению.

```bash
# Просмотр статуса лицензии
curl -s http://localhost:8888/api/status/angie/license | jq .
# → {
# →     "path": "/etc/angie/license.pem",
# →     "status": "valid",
# →     "owner": "Example Corp",
# →     "days_left": 30,
# →     "since": "2026-01-01",
# →     "until": "2027-01-01",
# →     "limits": {"worker_processes": 16, "worker_connections": 65535}
# → }

# Алертинг при приближении к истечению
DAYS=$(curl -s http://localhost:8888/api/status/angie/license | jq .days_left)
if [ "$DAYS" -lt 14 ]; then
    echo "ALERT: License expires in $DAYS days"
fi
```

## Операции и команды

Краткая сводка повседневных операций с Pro-функциями:

```bash
# Проверка состояния лицензии
curl -s http://localhost:8888/api/status/angie/license | jq .status

# Динамическое изменение весов/сервера в upstream (write=on)
curl -s -X PATCH http://localhost:8888/api/6/http/upstreams/api_backend/servers/1 \
  -d '{"weight": 5}' | jq

# KV-зона: чтение/запись ключа
curl -s http://localhost:8888/api/status/http/keyvals/blacklist/ | jq
curl -s -X POST http://localhost:8888/api/6/http/keyvals/blacklist \
  -d '{"1.2.3.4": "blocked"}' | jq

# Проверка, что upstream_probe активен
curl -s http://localhost:8888/api/status/http/upstreams/api_backend/ \
  | jq '.peers[] | {server, state, "probe.status": .probe.status}'
```

## Решение проблем (Troubleshooting)

**`upstream_probe` не проверяет серверы:**
- Убедитесь, что директива `upstream_probe` расположена в `location` с `proxy_pass` (а не в `upstream`).
- Проверьте, что в upstream объявлена `zone` — без нее проверки не работают.
- Убедитесь, что URI проверки доступен на бэкенде (`curl http://backend:port/probe`).

**KV-зона не сохраняется после перезапуска:**
- Убедитесь, что указана директива `state=/path/to/file` в `keyval_zone`.
- Проверьте, что процесс Angie имеет права на запись в указанную директорию.
- Файл создается при первом изменении KV-зоны, а не при старте.

**State file не перечитывается после `reload`:**
- Это ожидаемое поведение. State file перечитывается только при `stop`/`start`.
- При `reload` изменения через API сохраняются в разделяемой памяти и записываются в state file автоматически.

**Очередь (`queue`) не удерживает запросы:**
- Убедитесь, что `max_conns` установлен на серверах upstream — без него очередь не активируется.
- Проверьте, что `proxy_next_upstream` включает обработку таймаутов.

**`feedback` не корректирует веса:**
- Убедитесь, что переменная `$backend_load` содержит числовое значение (строка с числом).
- Проверьте, что интервал обновления (`interval`) не слишком велик для вашей нагрузки.
- Переменная должна обновляться на стороне приложения — Angie не генерирует ее автоматически.

**Консоль Pro не отображает KV-зоны:**
- Убедитесь, что используется Console Pro (а не Console Lite).
- Проверьте доступ к API-эндпоинту KV-зон: `curl http://localhost:8888/api/status/http/keyvals/`.

**Лицензия не распознается:**
- Проверьте путь к файлу лицензии: `curl http://localhost:8888/api/status/angie/license`.
- Статус `missing` — файл не найден; `invalid` — поврежден или не подписан; `grace` — грейс-период после истечения.

## Рекомендации по безопасности

1. **Изоляция API управления:** Выносите API с `write=on` на отдельный порт или внутренний интерфейс. Используйте `allow`/`deny` для ограничения по IP.
2. **Разделение API:** Используйте Pro-возможность разделения `/config/` (write) и `/status/` (read) на разные location.
3. **KV-зоны и IP:** При использовании KV для IP-blacklist не храните sensitive данные — KV-зона доступна через API.
4. **State file:** Обеспечьте restricted permissions на директорию и файл state (`chmod 600`, владелец — процесс Angie).
5. **`upstream_probe` и `essential`:** При использовании `essential` убедитесь, что проверки не создают ложных срабатываний (например, из-за таймаутов).
6. **Лицензия:** Эндпоинт `/status/angie/license` раскрывает информацию о лицензии — ограничьте доступ.

## Дополнительная информация

*   Angie PRO добавляет поверх OSS: `keyval` с `state=`, динамическое управление через API (`write=on`), `upstream_probe`, `feedback`, очередь с `max_conns`, метрики `metric_zone`, расширенную Console Pro и синхронизацию shared memory в кластере.
*   Ценообразование/лицензирование меняется; проверяйте актуальные лимиты (`worker_processes`, `worker_connections`) через `/status/angie/license`.
*   Все перечисленные Pro-эндпоинты работают на том же Status API, что и OSS — для полной схемы обращайтесь к эндпоинт-таблице в [angie_monitoring_api.md](./angie_monitoring_api.md).

---

**См. также:**

- [Работа с конфигурацией через API](./angie_monitoring_api.md) — полная таблица эндпоинтов, keepalive, JSON-схемы
- [Балансировка нагрузки HTTP в Angie](../angie_http_load_balancing.md) — алгоритмы Least Time, Hash, Sticky в OSS
- [Настройка Console Lite и API](./angie_monitoring_console.md) — веб-интерфейс для визуализации метрик
