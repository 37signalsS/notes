# Мониторинг Angie — Работа с конфигурацией и состоянием через API

**Актуально для:** Angie 1.12.x

## Определения

**HTTP API Angie** — встроенный REST-подобный интерфейс (модуль `ngx_http_api_module`), предоставляющий доступ к метрикам состояния, активной конфигурации и диагностическим данным сервера в режиме реального времени. Данные передаются в формате JSON. В открытой версии Angie (Open Source) API работает в режиме только для чтения (`GET` и `HEAD`). Модуль включен в официальные пакеты по умолчанию и отключается при сборке из исходного кода флагом `--without-http_api_module`.

**Stub Status** — минималистичный модуль мониторинга (`ngx_http_stub_status_module`), унаследованный от Nginx. Предоставляет базовую текстовую страницу со счетчиками соединений и запросов (`Active connections`, `accepts`, `handled`, `requests`, `Reading`, `Writing`, `Waiting`). Не требует настройки зон и разделяемой памяти, но не дает детализации по апстримам, виртуальным хостам, кэшу и SSL.

**Зона разделяемой памяти (Shared Memory Zone)** — именованный сегмент памяти, разделяемый между всеми рабочими процессами (worker processes) Angie. Директивы `status_zone` (для виртуальных хостов и локаций) и `zone` (для групп серверов `upstream`) аллоцируют структуры в разделяемой памяти для атомарного инкрементирования метрик без межпроцессных блокировок.

**Конфигурационный API (Runtime Config Dump)** — механизм модуля `ngx_http_api_module`, позволяющий выгружать точные копии конфигурационных файлов, загруженных мастер-процессом Angie в оперативную память. Активируется директивой `api_config_files on;`.

**Поколение конфигурации (Generation)** — целочисленный монотонно возрастающий счетчик версий конфигурации master-процесса Angie. Инкрементируется на единицу при каждом успешном сигнале `reload` (SIGHUP). Позволяет сопоставлять активные worker-процессы с конкретной ревизией настроек и своевременно выявлять процессы, не завершившие обслуживание старых соединений.

**Keepalive Connection Pool** — пул постоянных TCP-соединений с серверами апстрима, сохраняемых открытыми между последовательными запросами клиентов. Метрики пула доступны через API на уровне каждого отдельного пира и всей группы балансировки.

**SRE Golden Signals в API** — базовые метрики надежности сервиса, извлекаемые напрямую из древовидного JSON API: задержка (Latency via `health.response_time`), трафик (Traffic via `requests.total`, `data.sent`), ошибки (Errors via `responses.5xx`, `health.fails`), насыщенность (Saturation via `connections.active`, `selected.current` vs `max_conns`).

## Базовые концепции

### Модуль stub_status

Модуль `stub_status` используется как легковесный агент для базовой проверки жизнеспособности (liveness probe) и интеграции с устаревшими коллекторами метрик.

**Синтаксис директивы:**

| Атрибут | Значение |
|:---|:---|
| Синтаксис | `stub_status;` |
| Контекст | `server`, `location` |
| Статус модуля | Включен в официальные пакеты (`--with-http_stub_status_module`) |

```nginx
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location = /basic_status {
        stub_status;
        allow 127.0.0.1;
        deny all;
    }
}
```

**Формат текстового вывода:**

```text
Active connections: 291 
server accepts handled requests
 16630948 16630948 31070465 
Reading: 6 Writing: 179 Waiting: 106 
```

| Поле | Описание |
|:---|:---|
| `Active connections` | Текущее суммарное количество активных клиентских соединений (включая `Waiting`) |
| `accepts` | Общее число клиентских соединений, принятых сервером с момента старта |
| `handled` | Число успешно обработанных соединений. Если `handled` < `accepts`, сервер сбрасывал соединения из-за исчерпания `worker_connections` |
| `requests` | Суммарное число клиентских запросов |
| `Reading` | Соединения, в которых Angie считывает заголовок клиентского запроса |
| `Writing` | Соединения, в которых Angie считывает тело запроса, обрабатывает запрос или передает ответ клиенту |
| `Waiting` | Простаивающие клиентские keepalive-соединения в ожидании следующего запроса |

**Встроенные переменные `stub_status`:**
- `$connections_active` — текущее количество активных соединений.
- `$connections_reading` — количество соединений в фазе чтения.
- `$connections_writing` — количество соединений в фазе записи/обработки.
- `$connections_waiting` — количество простаивающих keepalive-соединений.

### Сравнение HTTP API и stub_status

| Критерий | HTTP API (`ngx_http_api_module`) | `stub_status` |
|:---|:---|:---|
| **Формат данных** | Структурированный JSON (иерархическое дерево) | Неструктурированный плоский текст |
| **Разделяемая память** | Требуется (`status_zone`, `zone`) для сбора статистики | Не требуется |
| **Детализация HTTP (L7)** | Запросы, коды 1xx-5xx, SSL, кэш, лимиты по зонам | Только глобальные запросы и соединения |
| **Детализация апстримов** | Состояние серверов, RTT, тайминги, сбои, keepalive | Отсутствует |
| **Детализация Stream (L4)** | Сессии, байты, статусы TCP/UDP апстримов | Отсутствует |
| **Доступ к конфигурации** | Полный дамп активных файлов через API | Отсутствует |
| **Режимы доступа** | Тонкая грануляция по поддеревьям URI | Только полный вывод страницы |
| **Основное применение** | Эксплуатационный мониторинг SRE, дашборды, автоматизация | Простейший ping/liveness watchdog, legacy |

### Директива api

Активирует HTTP REST-интерфейс в контексте конкретного `location`.

- **Синтаксис:** `api [path];`
- **Контекст:** `location`
- **По умолчанию:** отключено

Параметр `path` задает базовый путь поддерева API, к которому привязывается данный `location`. По аналогии с директивой `alias`, префикс URI из `location` заменяется на путь внутри виртуального дерева API:

```nginx
# Полный доступ ко всем метрикам и узлам API
location /status/ {
    api /status/;
    allow 127.0.0.1;
    allow 192.168.1.0/24;
    deny all;
}

# Частичный доступ: выдача только статистики виртуальных серверов HTTP
location /vhost_stats/ {
    api /status/http/server_zones/;
}

# Динамическая привязка через регулярные выражения
location ~^/api/([^/]+)/(.*)$ {
    api /status/http/$1_zones/$2;
}
```

> **Примечание:** Если `location` объявлен со слэшем на конце (например, `location /status/`), а директива `auto_redirect` установлена в `default`, запросы без замыкающего слэша (`/status`) автоматически перенаправляются на `/status/` с HTTP-кодом 301.

### Директива api_config_files

Включает отображение содержимого файлов конфигурации, загруженных master-процессом Angie, в секции `/status/angie/config_files/`.

| Атрибут | Значение |
|:---|:---|
| Синтаксис | `api_config_files on \| off;` |
| По умолчанию | `off` |
| Контекст | `http`, `server`, `location` |

```nginx
location /status/ {
    api /status/;
    api_config_files on;
    
    # Строгий контроль доступа обязателен
    allow 127.0.0.1;
    deny all;
}
```

> **Безопасность:** По умолчанию директива отключена (`off`), так как выгрузка конфигурации раскрывает пути к файлам, пароли баз данных, директивы аутентификации и токены. Разрешайте `api_config_files on` только на изолированных внутренних сокетах или интерфейсах с авторизацией.

### HTTP-методы и аргументы запросов

Модуль `ngx_http_api_module` в открытой версии Angie поддерживает исключительно безопасные методы чтения:
- `GET` — получение содержимого запрашиваемой ветки или скалярного значения.
- `HEAD` — проверка доступности и метаданных ответа без передачи тела JSON.

При отправке методов `POST`, `PUT`, `DELETE` или `PATCH` сервер возвращает HTTP 405 Method Not Allowed:

```json
{
    "error": "MethodNotAllowed",
    "description": "The POST method is not allowed for the requested API element \"/\"."
}
```

> **Различие версий Angie Open Source и Angie PRO:** Динамическое изменение конфигурации в runtime через API (`POST`, `PUT`, `DELETE`, `PATCH`), модификация серверов в `upstream`, директива `api /config/;` и управление таблицами `keyval` поддерживаются только в коммерческой версии Angie PRO. Подробнее см. [Мониторинг Angie — возможности Angie Pro](./angie_monitoring_pro.md) и [Динамические upstreams в Angie](../dynamic_upstreams.md).

**Параметры строки запроса (Query Arguments):**

| Параметр | Возможные значения | Описание |
|:---|:---|:---|
| `pretty` | `on` (по умолчанию), `off` | Отключает форматирование JSON отступами и переводами строк. Аргумент `pretty=off` снижает объем сетевого трафика и затраты CPU при автоматическом сборе метрик скриптами |
| `date` | `iso` (по умолчанию), `epoch` | Переключает строковые даты ISO 8601 (UTC) на целочисленный формат Unix Epoch (секунды). Упрощает расчет задержек и разницы времени в bash-скриптах |
| `defaults` | `on`, `off` *(только Angie PRO)* | Отображает значения параметров по умолчанию при запросе конфигурационного эндпоинта `/config/` |

Примеры вызова:
```bash
# Получение компактного JSON без переносов
curl -s "http://127.0.0.1:8888/status/connections?pretty=off"
# → {"accepted":2257,"dropped":0,"active":3,"idle":1}

# Получение времени старта в формате epoch
curl -s "http://127.0.0.1:8888/status/angie/load_time?date=epoch"
# → 1711929599
```

### Организация пула Keepalive для Upstream

Повторное использование TCP-соединений с бэкендами снижает системный оверхед на операциях TCP Three-Way Handshake и TLS Handshake. Для отражения метрик пула в API блок `upstream` должен содержать разделяемую память `zone` и директиву `keepalive`.

```nginx
upstream app_backend {
    zone app_backend 256k;
    server 10.0.1.10:8080 max_conns=50;
    server 10.0.1.11:8080 max_conns=50;

    keepalive 32;
    keepalive_requests 1000;
    keepalive_time 1h;
    keepalive_timeout 60s;
}

server {
    listen 127.0.0.1:80;

    location / {
        proxy_pass http://app_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

**Параметры тюнинга:**
- `keepalive connections` — максимальное количество простаивающих (idle) соединений к серверам апстрима, сохраняемых в кэше каждого worker-процесса. Не ограничивает общее число активных запросов.
- `proxy_http_version 1.1;` и `proxy_set_header Connection "";` — обязательные директивы в `location`. По умолчанию `proxy_pass` работает по HTTP/1.0 с заголовком `Connection: close`, что блокирует работу пула keepalive.
- `keepalive_requests` — лимит запросов, передаваемых через одно постоянное соединение (по умолчанию `1000`). По достижении соединение корректно закрывается воркером.
- `keepalive_timeout` — максимальное время простоя открытого соединения в пуле без входящих запросов (по умолчанию `60s`).

### Архитектура дерева JSON и метрики API

При запросе корневого эндпоинта `/status/` Angie отдает дерево доступных разделов мониторинга:

```text
/status/
├── angie                        Версия, сборка, адрес, поколение, uptime, файлы конфигурации
├── connections                  Принятые, сброшенные, активные и idle соединения клиентов
├── slabs/<zone>                 Статистика slab-аллокатора памяти (страницы, слоты, отказы аллокации)
├── resolvers/<zone>             Метрики DNS-клиента (запросы A/AAAA/SRV, коды ответов DNS-серверов)
├── http/
│   ├── server_zones/<zone>      SSL-хэндшейки, входящие запросы, HTTP-коды ответов, сетевой трафик
│   ├── location_zones/<zone>    Статистика запросов и ответов по отдельным location
│   ├── caches/<zone>            Эффективность кэша: hit, miss, stale, updating, expired, bypass
│   ├── limit_conns/<zone>       Счетчики passed, skipped, rejected, exhausted по соединениям
│   ├── limit_reqs/<zone>        Счетчики passed, delayed, rejected, exhausted по частоте запросов
│   ├── upstreams/<upstream>     Состояние пиров, веса, inflight-запросы, RTT бэкендов, fails, keepalive
│   ├── metric_zones/<zone>      Пользовательские метрики и гистограммы модуля ngx_http_metric_module
│   └── acme_clients/<client>    Статус выпуска и валидности сертификатов Let's Encrypt / ACME
└── stream/
    ├── server_zones/<zone>      Метрики TCP/UDP виртуальных серверов (сессии, соединения, байты)
    ├── upstreams/<upstream>     Состояние L4-пиров, сессии, сетевой трафик, проверки доступности
    └── metric_zones/<zone>      Пользовательские счетчики L4 Stream
```

#### 1. Системная информация (`/status/angie/`)

```json
{
    "version": "1.12.3",
    "build": "angie-1.12.3-1.el9",
    "build_time": "2026-10-13T12:00:00Z",
    "address": "192.168.1.15",
    "generation": 4,
    "load_time": "2026-10-14T08:30:00Z",
    "config_files": {
        "/etc/angie/angie.conf": "...",
        "/etc/angie/http.d/backend.conf": "..."
    }
}
```

- `version` — установленная версия Angie.
- `generation` — текущее поколение master-процесса (число успешных `reload` + 1).
- `load_time` — временная метка последней загрузки конфигурации.
- `config_files` — объект с полным текстом конфигурационных файлов (при `api_config_files on`).

#### 2. Соединения клиентов (`/status/connections/`)

```json
{
    "accepted": 15420310,
    "dropped": 0,
    "active": 412,
    "idle": 89
}
```

- `accepted` — общее число принятых клиентских сокетов.
- `dropped` — число клиентских соединений, сброшенных из-за нехватки системных дескрипторов или превышения `worker_connections`. В штатном режиме равно `0`.
- `active` — количество соединений, находящихся в обработке в данный момент.
- `idle` — простаивающие клиентские keepalive-соединения.

#### 3. Виртуальные серверы (`/status/http/server_zones/<zone>`)

Для сбора метрик виртуальный хост должен содержать директиву `status_zone <имя>;`.

```json
{
    "ssl": {
        "handshaked": 128450,
        "reuses": 95120,
        "timedout": 12,
        "failed": 3
    },
    "requests": {
        "total": 458920,
        "processing": 18,
        "discarded": 14
    },
    "responses": {
        "200": 441000,
        "301": 8200,
        "404": 120,
        "500": 4,
        "502": 2
    },
    "data": {
        "received": 89451204,
        "sent": 1458965412
    }
}
```

- `ssl.handshaked` — число успешных инициализаций TLS-сессий.
- `ssl.reuses` — число сессий, возобновленных через TLS Session Resumption (Session IDs / Session Tickets). Отношение `reuses / handshaked` показывает эффективность TLS-кэша.
- `ssl.timedout` — сбои хэндшейка по таймауту.
- `ssl.failed` — фатальные ошибки TLS (несовпадение cipher suites, ошибки клиентских сертификатов).
- `requests.discarded` — запросы, разорванные без отправки заголовков клиенту (клиентский обрыв TCP RST, превышение `client_header_timeout`). Сюда же входят внутренние коды 499.

#### 4. Группы серверов (`/status/http/upstreams/<upstream>`)

Для активации сбора метрик в блоке `upstream` обязательна директива `zone <имя> <размер>;`.

```json
{
    "peers": {
        "10.0.1.10:8080": {
            "server": "10.0.1.10:8080",
            "service": "",
            "backup": false,
            "weight": 1,
            "state": "up",
            "selected": {
                "current": 4,
                "total": 245100
            },
            "max_conns": 50,
            "responses": {
                "200": 244980,
                "502": 20
            },
            "data": {
                "sent": 15420312,
                "received": 89654120
            },
            "health": {
                "fails": 2,
                "unavailable": 0,
                "downtime": 0,
                "downstart": "",
                "header_time": 18,
                "response_time": 34
            },
            "keepalive": 8,
            "sid": "0a00010a1f90"
        }
    },
    "keepalive": 16
}
```

**Возможные статусы узлов (`state`):**
- `up` — сервер функционирует и принимает клиентский трафик.
- `down` — сервер административно выключен.
- `unhealthy` — сервер помечен неработоспособным пассивными проверками (`max_fails`) или активным зондированием.
- `draining` — сервер находится в режиме вывода из эксплуатации: новые клиенты не направляются, существующие соединения дорабатывают до завершения.
- `busy` — число одновременных запросов достигло предела `max_conns`.
- `recovering` — сервер плавно наращивает долю трафика после восстановления в рамках директивы `slow_start`.

**Диагностика задержек и здоровья (health):**
- `health.header_time` — скользящее среднее времени ожидания первого байта ответа бэкенда (Time to First Byte, TTFB) в миллисекундах.
- `health.response_time` — скользящее среднее полного времени чтения ответа бэкенда в миллисекундах.
- `health.fails` — число зафиксированных коммуникационных сбоев (connect timeout, connection refused, read timeout).
- `health.unavailable` — количество переходов сервера в статус `unhealthy` по превышению порога `max_fails`.

#### 5. Состояние Slab-памяти (`/status/slabs/<zone>`)

Секция отражает утилизацию внутренних страниц и слотов в разделяемой памяти:

```json
{
    "pages": {
        "used": 4,
        "free": 60
    },
    "slots": {
        "64": {
            "used": 12,
            "free": 52,
            "reqs": 480,
            "fails": 0
        },
        "128": {
            "used": 8,
            "free": 24,
            "reqs": 150,
            "fails": 0
        }
    }
}
```

- `pages.free` — количество свободных страниц памяти размером 4 КБ.
- `slots.<size>.fails` — количество отказов в аллокации слота заданного размера. Если счетчик `fails` растет — разделяемая память фрагментирована или исчерпана, требуется увеличение размера зоны в конфигурации.

#### 6. Зоны лимитов (`limit_conn` и `limit_req`)

```json
{
    "passed": 1250400,
    "skipped": 0,
    "delayed": 1420,
    "rejected": 85,
    "exhausted": 0
}
```

- `delayed` (только `limit_req`) — число запросов, задержанных директивой `burst` без отклонения.
- `rejected` — число отклоненных запросов или соединений при превышении лимита (HTTP 429 или 503).
- `exhausted` — критический счетчик SRE: число запросов, отброшенных из-за полной нехватки памяти в `limit_req_zone` / `limit_conn_zone`. Если `exhausted > 0`, размер зоны памяти недостаточен для хранения IP-адресов уникальных клиентов.

#### 7. DNS-резолвер (`/status/resolvers/<zone>`)

Активируется параметром `status_zone` директивы `resolver`:
```nginx
resolver 127.0.0.53 status_zone=dns_resolver valid=10s;
```

API возвращает распределение запросов по типам (`queries.name`, `queries.srv`, `queries.addr`) и исходы ответов (`responses.success`, `responses.timedout`, `responses.server_failure`, `responses.not_found`, `responses.refused`).

## Практические сценарии

### Сценарий 1: Аудит актуальности конфигурации (Runtime vs Disk)

В практике системного администрирования часто возникает ситуация, когда конфигурационные файлы на диске были изменены или обновлены через систему управления конфигурациями (Ansible, Git), но веб-сервер не был перезагружен, либо наоборот — ручные правки на диске не соответствуют работающему процессу.

**Конфигурация Angie:**
```nginx
http {
    server {
        listen 127.0.0.1:8888;
        server_name localhost;

        location /status/ {
            api /status/;
            api_config_files on;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Bash-скрипт верификации дрейфа конфигурации:**
```bash
#!/usr/bin/env bash
set -euo pipefail

API_URL="http://127.0.0.1:8888/status/angie/config_files"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[*] Получение списка загруженных файлов из Angie API..."
FILES=$(curl -sSf "$API_URL" | jq -r 'keys[]')

DRIFT_DETECTED=0

for FILE in $FILES; do
    if [[ ! -f "$FILE" ]]; then
        echo "[!] КРИТИЧЕСКАЯ ОШИБКА: Файл $FILE присутствует в памяти Angie, но удален с диска!"
        DRIFT_DETECTED=1
        continue
    fi

    # Извлечение содержимого файла из API во временный файл
    curl -sSf "$API_URL$FILE" > "$TMP_DIR/runtime.conf"

    # Сравнение хэш-сумм
    RUNTIME_MD5=$(md5sum "$TMP_DIR/runtime.conf" | awk '{print $1}')
    DISK_MD5=$(md5sum "$FILE" | awk '{print $1}')

    if [[ "$RUNTIME_MD5" != "$DISK_MD5" ]]; then
        echo "[!] ОБНАРУЖЕН ДРЕЙФ: $FILE отличается на диске от запущенного в памяти!"
        diff -u "$TMP_DIR/runtime.conf" "$FILE" || true
        DRIFT_DETECTED=1
    else
        echo "[OK] $FILE идентичен."
    fi
done

if [[ "$DRIFT_DETECTED" -eq 1 ]]; then
    echo "ВНИМАНИЕ: Требуется синхронизация конфигурации (reload или откат изменений на диске)."
    exit 1
fi

echo "Все файлы конфигурации синхронизированы."
```

**Проверка выполнения:**
```bash
./verify_config_drift.sh
# → [*] Получение списка загруженных файлов из Angie API...
# → [OK] /etc/angie/angie.conf идентичен.
# → [OK] /etc/angie/http.d/app.conf идентичен.
# → Все файлы конфигурации синхронизированы.
```

### Сценарий 2: Мониторинг жизненного цикла воркеров при Reload и детектирование зомби-процессов

При выполнении `angie -s reload` master-процесс считывает новую конфигурацию, инкрементирует `generation` и запускает новый пул воркеров. Старые воркеры переходят в режим graceful shutdown: они перестают принимать новые соединения и ждут закрытия существующих (например, долгих WebSocket, gRPC или скачивания файлов). Если клиент удерживает соединение, старый воркер превращается в «зомби-процесс», занимая память сервера.

**Bash-скрипт контроля процессов после reload:**
```bash
#!/usr/bin/env bash
set -euo pipefail

API_URL="http://127.0.0.1:8888/status/angie"

# Получение целевого поколения мастера
EXPECTED_GEN=$(curl -sSf "$API_URL" | jq '.generation')
echo "[*] Текущее активное поколение master-процесса: $EXPECTED_GEN"

# Поиск всех процессов worker
WORKER_PIDS=$(pgrep -f "angie: worker process" || true)

if [[ -z "$WORKER_PIDS" ]]; then
    echo "ОШИБКА: Процессы worker не найдены в операционной системе!"
    exit 2
fi

STALE_COUNT=0

for PID in $WORKER_PIDS; do
    # Проверка командной строки процесса
    CMD=$(tr '\0' ' ' < "/proc/$PID/cmdline")
    
    # В Angie процессы воркеров нового поколения несут актуальный статус
    # Проверяем открытые файловые дескрипторы или сокеты процесса
    SOCKETS_COUNT=$(lsof -p "$PID" -a -i 4 -i 6 2>/dev/null | wc -l || echo "0")
    
    echo "Воркер PID $PID: открытых сетевых сокетов: $SOCKETS_COUNT"
done

# Проверка через системные счетчики Angie API
ACTIVE_CONNECTIONS=$(curl -sSf http://127.0.0.1:8888/status/connections | jq '.active')
echo "[*] Активных соединений на сервере: $ACTIVE_CONNECTIONS"
```

**Проверка вывода:**
```bash
./check_workers_generation.sh
# → [*] Текущее активное поколение master-процесса: 4
# → Воркер PID 14210: открытых сетевых сокетов: 85
# → Воркер PID 14211: открытых сетевых сокетов: 92
# → [*] Активных соединений на сервере: 177
```

### Сценарий 3: SRE Golden Signals Healthcheck для локального балансировщика

Скрипт проверки жизнеспособности узла для интеграции с Keepalived, HAProxy или локальными мониторинговыми скриптами. Проверяет не просто факт ответа порта 80/443, а ключевые показатели надежности: процент ошибок 5xx, доступность апстримов и среднее время ответа (RTT).

```bash
#!/usr/bin/env bash
set -euo pipefail

API_BASE="http://127.0.0.1:8888/status"
MAX_RESPONSE_TIME_MS=250
MAX_5XX_PERCENT=5

# 1. Проверка доступности самого сервера
ANGIE_STATUS=$(curl -sSf -m 2 "$API_BASE/angie" 2>/dev/null || echo "DOWN")
if [[ "$ANGIE_STATUS" == "DOWN" ]]; then
    echo "CRITICAL: Angie master не отвечает на локальный API запрос"
    exit 1
fi

# 2. Проверка апстрима 'prod_cluster'
UPSTREAM_DATA=$(curl -sSf -m 2 "$API_BASE/http/upstreams/prod_cluster")

# Проверка, есть ли хотя бы один живой пир в статусе 'up'
ALIVE_PEERS=$(echo "$UPSTREAM_DATA" | jq '[.peers[] | select(.state == "up")] | length')
TOTAL_PEERS=$(echo "$UPSTREAM_DATA" | jq '.peers | length')

if [[ "$ALIVE_PEERS" -eq 0 ]]; then
    echo "CRITICAL: Все бэкенды в группе prod_cluster недоступны (0/$TOTAL_PEERS up)"
    exit 1
fi

# 3. Проверка среднего времени ответа бэкендов
AVG_RT=$(echo "$UPSTREAM_DATA" | jq '[.peers[].health.response_time] | add / length')
if (( $(echo "$AVG_RT > $MAX_RESPONSE_TIME_MS" | bc -l) )); then
    echo "WARNING: Среднее время ответа апстрима деградировало: ${AVG_RT}ms > ${MAX_RESPONSE_TIME_MS}ms"
    exit 1
fi

# 4. Проверка ошибок 5xx на виртуальном хосте 'main_vhost'
SERVER_DATA=$(curl -sSf -m 2 "$API_BASE/http/server_zones/main_vhost")
TOTAL_REQS=$(echo "$SERVER_DATA" | jq '.requests.total')
ERR_5XX=$(echo "$SERVER_DATA" | jq '[(.responses["500"] // 0), (.responses["502"] // 0), (.responses["503"] // 0), (.responses["504"] // 0)] | add')

if [[ "$TOTAL_REQS" -gt 100 ]]; then
    ERR_RATE=$(echo "scale=2; ($ERR_5XX * 100) / $TOTAL_REQS" | bc)
    if (( $(echo "$ERR_RATE > $MAX_5XX_PERCENT" | bc -l) )); then
        echo "CRITICAL: Доля 5xx ошибок превысила порог: ${ERR_RATE}% > ${MAX_5XX_PERCENT}%"
        exit 1
    fi
fi

echo "OK: Узел полностью работоспособен (Upstreams: $ALIVE_PEERS/$TOTAL_PEERS, RT: ${AVG_RT}ms)"
exit 0
```

**Проверка выполнения:**
```bash
./sre_healthcheck.sh
# → OK: Узел полностью работоспособен (Upstreams: 2/2, RT: 14.50ms)
# → # echo $? -> 0
```

### Сценарий 4: Детектирование исчерпания разделяемой памяти и слэбов (Slab Exhaustion Prevention)

Одной из самых опасных скрытых проблем в высоконагруженных инсталляциях является исчерпание памяти в зонах `limit_req_zone`, `limit_conn_zone` или `zone`. При исчерпании памяти сервер начинает отбрасывать запросы клиентов с ошибками (`exhausted`), а в `error.log` появляются сообщения `could not allocate new entry`.

**Скрипт превентивного аудита Slab-памяти:**
```bash
#!/usr/bin/env bash
set -euo pipefail

API_BASE="http://127.0.0.1:8888/status"

echo "=== Аудит отказов аллокации памяти (Slab Fails) ==="
SLABS=$(curl -sSf "$API_BASE/slabs" | jq -r 'to_entries[] | .key as $zone | .value.slots | to_entries[] | select(.value.fails > 0) | "\($zone) slot:\(.key) fails:\(.value.fails)"')

if [[ -n "$SLABS" ]]; then
    echo "[!] КРИТИЧЕСКАЯ ОШИБКА: Зафиксированы отказы в аллокации слотов:"
    echo "$SLABS"
    echo "Действие: Увеличьте размер соответствующих зон памяти в angie.conf"
    exit 1
else
    echo "[OK] Отказов аллокации в slabs не зафиксировано."
fi

echo "=== Проверка зон ограничения частоты запросов (limit_req) ==="
EXHAUSTED_REQS=$(curl -sSf "$API_BASE/http/limit_reqs" | jq 'to_entries[] | select(.value.exhausted > 0) | {zone: .key, exhausted: .value.exhausted}')

if [[ -n "$EXHAUSTED_REQS" ]]; then
    echo "[!] ВНИМАНИЕ: Зоны limit_req переполнены:"
    echo "$EXHAUSTED_REQS"
    exit 1
else
    echo "[OK] Все зоны limit_req имеют достаточный объем памяти."
fi
```

### Сценарий 5: Мониторинг эффективности пула Keepalive и локализация сброса соединений

Если keepalive настроен некорректно, нагрузка на стек TCP ядра и latency клиентов резко возрастают.

**Диагностика через API:**
```bash
# Получение данных пула для апстрима backend_cluster
curl -s "http://127.0.0.1:8888/status/http/upstreams/backend_cluster?pretty=off" | jq '{
    configured_pool_total: .keepalive,
    peers: [.peers[] | {
        ip: .server,
        state: .state,
        idle_in_pool: .keepalive,
        active_inflight: .selected.current,
        total_requests: .selected.total
    }]
}'
```

**Ожидаемый результат в исправной системе:**
```json
{
  "configured_pool_total": 16,
  "peers": [
    {
      "ip": "10.0.1.10:8080",
      "state": "up",
      "idle_in_pool": 8,
      "active_inflight": 2,
      "total_requests": 142500
    },
    {
      "ip": "10.0.1.11:8080",
      "state": "up",
      "idle_in_pool": 8,
      "active_inflight": 3,
      "total_requests": 142100
    }
  ]
}
```

**Правила интерпретации SRE:**
1. Если `idle_in_pool` постоянно равен `0` при наличии клиентского трафика:
   - Проверьте конфигурацию: отсутствует `proxy_http_version 1.1;` или заголовок `Connection: ""` в `location`.
   - Проверьте бэкенд: бэкенд возвращает заголовок `Connection: close` (например, стандартное поведение некоторых фреймворков или Gunicorn с низким `keepalive`).
2. Если `active_inflight` постоянно упирается в `max_conns`, сервер переходит в статус `busy` и запросы накапливаются в очереди.

### Сценарий 6: Мониторинг L4 TCP/UDP проксирования (Stream)

Модуль Stream используется для проксирования баз данных (PostgreSQL, ClickHouse, Redis) и очередей сообщений.

**Конфигурация Angie Stream:**
```nginx
stream {
    upstream pg_pool {
        zone pg_pool 128k;
        server 10.0.2.10:5432 max_conns=100;
        server 10.0.2.11:5432 max_conns=100;
    }

    server {
        listen 5432;
        status_zone pg_frontend;
        proxy_pass pg_pool;
        proxy_timeout 10m;
        proxy_connect_timeout 2s;
    }
}
```

**Снятие L4-метрик через API:**
```bash
# Метрики слушающего сокета TCP фронтенда
curl -s http://127.0.0.1:8888/status/stream/server_zones/pg_frontend/
# → {
# →   "connections": 540,
# →   "sessions": {
# →     "2xx": 538,
# →     "5xx": 2
# →   },
# →   "data": {
# →     "received": 1420580,
# →     "sent": 89541200
# →   }
# → }

# Состояние L4 апстримов базы данных
curl -s http://127.0.0.1:8888/status/stream/upstreams/pg_pool/ | jq '.peers[] | {server, state, active: .selected.current}'
# → {"server": "10.0.2.10:5432", "state": "up", "active": 24}
# → {"server": "10.0.2.11:5432", "state": "up", "active": 21}
```

## Операции и команды

Сводка типовых команд системного администратора и SRE для инспекции состояния сервера через CLI с использованием `curl` и `jq`:

```bash
# 1. Проверка версии сервера, поколения конфигурации и времени аптайма
curl -s http://127.0.0.1:8888/status/angie/ | jq '{version, generation, load_time}'
# → {
# →   "version": "1.12.3",
# →   "generation": 4,
# →   "load_time": "2026-10-14T08:30:00Z"
# → }

# 2. Выявление серверов апстрима, находящихся не в статусе 'up'
curl -s http://127.0.0.1:8888/status/http/upstreams/app_backend/ | jq '.peers[] | select(.state != "up") | {server, state, fails: .health.fails, downtime: .health.downtime}'
# → {
# →   "server": "10.0.1.12:8080",
# →   "state": "unhealthy",
# →   "fails": 3,
# →   "downtime": 45000
# → }

# 3. Расчет коэффициента попадания в кэш (Cache Hit Ratio) в процентах
curl -s http://127.0.0.1:8888/status/http/caches/my_cache/ | jq '
  (.hit.responses) as $hit |
  (.miss.responses + .expired.responses + .stale.responses + .bypass.responses) as $miss |
  ($hit + $miss) as $total |
  if $total > 0 then {
    total_requests: $total,
    hit_ratio_percent: (($hit / $total) * 100 | round)
  } else { status: "Cache cold / no requests" } end'
# → {
# →   "total_requests": 154200,
# →   "hit_ratio_percent": 87
# → }

# 4. Проверка исчерпания памяти во всех зонах limit_req
curl -s http://127.0.0.1:8888/status/http/limit_reqs/ | jq 'to_entries[] | {zone: .key, exhausted: .value.exhausted, rejected: .value.rejected}'
# → {
# →   "zone": "api_rate_limit",
# →   "exhausted": 0,
# →   "rejected": 14
# → }

# 5. Проверка ошибок в работе DNS-резолвера
curl -s http://127.0.0.1:8888/status/resolvers/dns_resolver/responses/
# → {
# →   "success": 18450,
# →   "timedout": 0,
# →   "format_error": 0,
# →   "server_failure": 0,
# →   "not_found": 2,
# →   "unimplemented": 0,
# →   "refused": 0,
# →   "other": 0
# → }

# 6. Быстрое извлечение конфигурации бэкенда из оперативной памяти в файл
curl -s http://127.0.0.1:8888/status/angie/config_files/etc/angie/http.d/backend.conf > /tmp/recovered_backend.conf
# → Файл сохранен на диск из памяти master-процесса
```

## Устранение неисправностей

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
|:---|:---|:---|:---|
| **HTTP 405 Method Not Allowed** при обращении к API | Использование недопустимого HTTP-метода (`POST`, `PUT`, `DELETE`, `PATCH`). В Angie Open Source API работает строго в режиме read-only | Проверьте метод запроса в `curl -X` или конфигурации клиента сбора метрик | Используйте исключительно методы `GET` и `HEAD`. Для динамического управления конфигурацией требуется версия Angie PRO |
| **API возвращает пустой объект `{}` в `upstreams` или `server_zones`** | В конфигурации не объявлена зона разделяемой памяти (`zone` или `status_zone`) | `curl -s http://127.0.0.1:8888/status/http/upstreams/` возвращает `{}`. Проверьте `angie -T \| grep zone` | Добавьте директиву `zone <имя> <размер>;` в блок `upstream` и `status_zone <имя>;` в блок `server` / `location`, затем выполните `angie -s reload` |
| **Раздел `/config_files/` возвращает пустой объект `{}` или ошибку 404** | Директива `api_config_files` установлена в `off` или отсутствует в контексте | Проверьте вывод `curl -s http://127.0.0.1:8888/status/angie/` на наличие ключа `config_files` | Добавьте `api_config_files on;` в блок `location`, где включен `api`, или на уровне `http`, и выполните `reload` |
| **Счетчик `exhausted > 0` в `limit_reqs` или `limit_conns`** | Недостаточный размер разделяемой памяти для отслеживания уникальных ключей (клиентских IP-адресов) | `curl -s http://127.0.0.1:8888/status/http/limit_reqs/` показывает `exhausted > 0`. В `error.log` фиксируются записи `could not allocate new entry` | Увеличьте размер зоны в директиве `limit_req_zone` (например, с `10m` до `32m` или `64m`) |
| **Счетчик `fails > 0` в `/status/slabs/<zone>/slots/`** | Фрагментация разделяемой памяти либо нехватка свободного пространства для новых структур данных | Проверьте `curl -s http://127.0.0.1:8888/status/slabs/<zone>/` на наличие `fails > 0` в слотах | Увеличьте размер зоны памяти `zone <name> <size>` в соответствующем модуле (`upstream`, `proxy_cache_path`, `limit_conn_zone`) |
| **Keepalive-соединения не удерживаются (`idle = 0`)** | Запросы к бэкенду проксируются по протоколу HTTP/1.0, либо отправляется заголовок `Connection: close` | Запустите `tcpdump -nn -A -i any port 8080` и проверьте заголовок `Connection` в запросах к апстриму | Укажите `proxy_http_version 1.1;` и `proxy_set_header Connection "";` в блоке `location` |
| **Поколения воркеров не сходятся после `reload`** | Старые воркеры не завершаются из-за зависших соединений (клиент не закрывает соединение, WebSocket, медленные клиенты) | Сравните вывод `ps -eo pid,cmd \| grep angie` и значение `generation` в `/status/angie/` | Настройте директиву `worker_shutdown_timeout 30s;` в глобальном контексте `angie.conf` для принудительного завершения старых процессов |
| **API медленно отдает ответ под высокой нагрузкой** | Форматирование громоздкого JSON дерева создает накладные расходы на CPU | Замерьте время ответа: `curl -w "%{time_total}\n" -o /dev/null -s http://127.0.0.1:8888/status/` | Добавьте параметр `?pretty=off` в запросы мониторинга и опрашивайте только целевые эндпоинты (например, `/status/http/upstreams/` вместо корневого `/status/`) |

## Лучшие практики

1. **Изоляция интерфейса мониторинга:**
   Никогда не публикуйте эндпоинт `/status/` на внешних сетевых интерфейсах без шифрования и авторизации. Привязывайте служебный виртуальный хост к loopback-интерфейсу `127.0.0.1`, изолированному менеджмент-VLAN или Unix-сокету:
   ```nginx
   server {
       listen 127.0.0.1:8888;
       listen unix:/var/run/angie_status.sock;
       server_name localhost;

       location /status/ {
           api /status/;
           allow 127.0.0.1;
           deny all;
       }
   }
   ```

2. **Защита конфиденциальных данных в `api_config_files`:**
   Включайте `api_config_files on;` только при реальной производственной необходимости (аудит, централизованная сверка конфигураций). Если файлы содержат пароли, SSL-ключи или директивы `auth_basic_user_file`, ограничьте доступ директивами `auth_basic` или `auth_jwt`.

3. **Оптимизация опроса мониторинговыми системами:**
   При сборе метрик внешними коллекторами (Prometheus node-exporter, Zabbix-агенты, Telegraf) всегда используйте параметр `?pretty=off`. Это экономит до 40% объема генерируемого трафика и снижает нагрузку на CPU воркера при сериализации JSON.

4. **Расчет размеров разделяемой памяти зон:**
   - Для зон `upstream`: 64 КБ достаточно для 20–30 серверов; для кластеров из 100–200 серверов выделяйте от `256k` до `512k`.
   - Для зон `limit_req_zone` и `limit_conn_zone`: 1 МБ памяти вмещает состояние примерно 16 000 IP-адресов IPv4 (или 8 000 адресов IPv6). Для интернет-проектов с высокой посещаемостью задавайте зоны от `10m` до `32m` во избежание роста счетчика `exhausted`.

5. **Обязательная настройка `worker_shutdown_timeout`:**
   Чтобы старые воркеры гарантированно завершали работу после `reload` и не накапливались в системе, задавайте жесткий таймаут завершения в глобальной конфигурации:
   ```nginx
   worker_shutdown_timeout 30s;
   ```

6. **Алертинг на аномальные скачки `generation`:**
   Настройте оповещение в системе мониторинга на внезапный рост счетчика `generation` за короткий интервал времени. Это сигнализирует о нестабильности процесса, частых неконтролируемых релоадах от CI/CD или аварийных перезапусках master-процесса.

## Дополнительная информация

### Сводная таблица эндпоинтов API

**Общесистемные эндпоинты:**

| Эндпоинт | Метод | Описание |
|:---|:---|:---|
| `/status/` | GET, HEAD | Корневой объект со ссылками на все доступные ветки дерева API |
| `/status/angie/` | GET, HEAD | Версия, сборка, адрес хоста, поколение мастера и время последней загрузки |
| `/status/angie/config_files/` | GET, HEAD | Содержимое файлов конфигурации сервера (требует `api_config_files on`) |
| `/status/connections/` | GET, HEAD | Метрики соединений клиентов (accepted, dropped, active, idle) |
| `/status/slabs/<zone>/` | GET, HEAD | Состояние slab-аллокатора памяти зоны (pages, slots, отказы аллокации) |
| `/status/resolvers/<zone>/` | GET, HEAD | Статистика запросов и ответов встроенного DNS-резолвера |

**Эндпоинты протокола HTTP:**

| Эндпоинт | Метод | Описание |
|:---|:---|:---|
| `/status/http/server_zones/<zone>/` | GET, HEAD | Статистика виртуального хоста (SSL handshake/reuse, запросы, коды ответов, байты) |
| `/status/http/location_zones/<zone>/` | GET, HEAD | Статистика запросов и ответов по конкретному `location` |
| `/status/http/upstreams/<upstream>/` | GET, HEAD | Детальное состояние бэкендов (статусы, веса, active, RTT, fails, keepalive) |
| `/status/http/caches/<zone>/` | GET, HEAD | Эффективность кэширования ответов (размер кэша, hit, miss, stale, expired) |
| `/status/http/limit_conns/<zone>/` | GET, HEAD | Лимиты одновременных соединений (passed, skipped, rejected, exhausted) |
| `/status/http/limit_reqs/<zone>/` | GET, HEAD | Лимиты частоты запросов (passed, delayed, rejected, exhausted) |
| `/status/http/metric_zones/<zone>/` | GET, HEAD | Пользовательские счетчики и гистограммы модуля `ngx_http_metric_module` |
| `/status/http/acme_clients/<client>/` | GET, HEAD | Статусы выпуска и сроки действия TLS-сертификатов Let's Encrypt / ACME |

**Эндпоинты транспортного уровня Stream (L4):**

| Эндпоинт | Метод | Описание |
|:---|:---|:---|
| `/status/stream/server_zones/<zone>/` | GET, HEAD | Метрики TCP/UDP виртуальных серверов (сессии, соединения, трафик) |
| `/status/stream/upstreams/<upstream>/` | GET, HEAD | Состояние серверов в L4-группах балансировки (PostgreSQL, Redis и др.) |
| `/status/stream/limit_conns/<zone>/` | GET, HEAD | Лимиты одновременных соединений в Stream-контексте |
| `/status/stream/metric_zones/<zone>/` | GET, HEAD | Пользовательские L4-метрики модуля `ngx_stream_metric_module` |

---

**См. также:**

- [Основные концепции мониторинга Angie](./angie_monitoring_concepts.md) — расчет разделяемой памяти, принципы сбора метрик и иерархия L4/L7
- [Настройка Console Light и API](./angie_monitoring_console.md) — развертывание встроенной веб-панели визуализации состояния Angie
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md) — экспорт метрик в Prometheus и VictoriaMetrics через модуль `ngx_http_prometheus_module`
- [Пользовательские метрики и их экспорт](./angie_monitoring_custom_metrics.md) — настройка `metric_zone`, APDEX и кастомных счетчиков
- [Мониторинг Angie — возможности Angie Pro](./angie_monitoring_pro.md) — динамическое конфигурирование апстримов через API (`write=on`), модуль `upstream_probe`
- [Динамические группы проксируемых серверов в Angie](../dynamic_upstreams.md) — управление серверами в runtime, DNS resolve, файлы состояния `state`
- [Балансировка и проксирование L4 в Angie](../l4_balancing_and_proxying.md) — конфигурация модуля Stream, TCP/UDP балансировка и `status_zone`
