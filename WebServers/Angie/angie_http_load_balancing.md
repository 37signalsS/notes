# Балансировка нагрузки HTTP в Angie

## Определения

**Балансировка нагрузки HTTP в Angie** — это процесс распределения входящего трафика уровня L7 (прикладной уровень модели OSI) между группой бэкенд-серверов. Angie значительно расширяет возможности стандартного Nginx, предоставляя в открытой версии (OSS) функции, которые ранее были доступны только в коммерческих редакциях.

**Upstream** — именованная группа бэкенд-серверов в конфигурации Angie, между которыми распределяется нагрузка. Для работы продвинутых функций (активные проверки, least_time, sticky) upstream должен содержать директиву `zone` — именованную область разделяемой памяти (shared memory), в которой хранится состояние группы в реальном времени.

**Пассивные проверки (Passive Health Checks)** — механизм, при котором Angie отслеживает ошибки при проксировании клиентских запросов (`max_fails` + `fail_timeout`). При достижении порога ошибок сервер временно исключается из ротации. Работают «из коробки», но реагируют только на уже поступивший трафик.

**Активные проверки (Active Health Checks)** — фоновый мониторинг бэкендов, при котором Angie самостоятельно отправляет проверочные запросы (модуль `check` в OSS) независимо от клиентского трафика. Позволяют обнаружить нерабочий сервер до того, как на него попадут реальные запросы.

**Зона разделяемой памяти (`zone`)** — именованный сегмент shared memory, где Angie хранит состояние upstream (активные соединения, веса, метрики времени ответа, таблицы sticky-сессий). Без `zone` не работают активные проверки, `least_time`, `sticky learn` и API-метрики.

**Keepalive-пул** — кэш открытых TCP/TLS-соединений между Angie и бэкендами. Директива `keepalive <N>` в блоке `upstream` задает максимальное число соединений на каждый воркер, которые возвращаются в пул после обработки запроса. Критична для производительности: исключает накладные расходы на TCP/TLS handshake для каждого запроса.

**Sticky-сессия (Session Affinity)** — механизм привязки клиента к конкретному бэкенду на протяжении всей сессии. В Angie реализован через методы `cookie` (вставка Cookie), `route` (привязка по Cookie) и `learn` (обучение по Cookie от бэкенда).

**Slow Start** — плавный ввод восстановленного бэкенда в ротацию. В течение заданного периода (`slow_start=<T>`) Angie увеличивает количество запросов, направляемых на сервер, линейно или экспоненциально, защищая «холодный» кэш и только что поднятое приложение от перегрузки.

**Drain** — режим плавного вывода сервера из эксплуатации. Сервер продолжает обрабатывать sticky-сессии, но не получает новые запросы. Активируется через API или директиву `down` с параметром `drain` (Angie PRO).

Общие принципы балансировки и базовые алгоритмы описаны в **[обзоре балансировки L7 в Nginx](../Nginx/Proxy/Load_Balancing/overview_concepts.md)**.

## Основные концепции

### Архитектура L7-балансировки в Angie

Angie обрабатывает HTTP-балансировку на уровне прикладного протокола, что позволяет анализировать заголовки, Cookie, URI и тело запроса перед принятием решения о выборе бэкенда.

**Жизненный цикл запроса:**
1. **Терминация клиентского соединения:** Angie принимает TCP/TLS-соединение от клиента, завершает TLS-рукопожатие (с аппаратным ускорением kTLS при наличии).
2. **Выбор бэкенда:** Применяется выбранный алгоритм (`round_robin`, `least_conn`, `least_time`, `hash`, `feedback`). Для `least_time` учитываются метрики времени ответа, хранящиеся в `zone`.
3. **Keepalive-соединение:** Если в пуле есть свободное соединение к целевому бэкенду — используется оно. Иначе открывается новое TCP/TLS-соединение.
4. **Проксирование:** Запрос передается на бэкенд с модифицированными заголовками (`X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`).
5. **Буферизация ответа:** Ответ бэкенда считывается в буферы (`proxy_buffer_size`, `proxy_buffers`), после чего передается клиенту.
6. **Возврат в пул:** Соединение с бэкендом либо возвращается в keepalive-пул, либо закрывается (при превышении `keepalive_requests` или таймаута `keepalive_timeout`).

### Алгоритмы распределения нагрузки

Angie поддерживает все стандартные алгоритмы (Round Robin, Least Connections, IP Hash) и добавляет продвинутые механизмы. Подробный теоретический разбор всех алгоритмов см. в **[Алгоритмы балансировки Nginx и Angie](../Nginx/Proxy/Load_Balancing/algorithms.md)**.

| Метод | Версия | Описание | Особенности |
| :--- | :--- | :--- | :--- |
| **Least Time** | OSS (1.12+) | Выбор сервера с наименьшим средним временем ответа. | Параметры `header` (первый байт заголовка) или `last_byte` (полный ответ), `inflight` (учитывает незавершенные запросы). |
| **Sticky** | OSS | Привязка клиента к серверу. | Поддерживает методы `cookie`, `route` и `learn`. |
| **Feedback** | OSS | Динамические веса на основе данных от бэкендов. | Учитывает загрузку CPU/RAM серверов приложения. |
| **Hash** | OSS | Хеширование по ключу (URI, заголовки). | Опция `consistent` для минимизации перераспределения. |

### Зоны разделяемой памяти и keepalive

Для работы продвинутых функций необходимо объявить зону разделяемой памяти (`zone`), где Angie хранит состояние группы серверов в реальном времени.

*   **Зона (zone):** Обязательна для активных проверок, `least_time`, `sticky learn` и API-метрик. Размер: 64–128 КБ на 50–200 серверов.
*   **Keepalive:** Пул открытых соединений к бэкендам. Исключает TCP/TLS handshake на каждый запрос.

```nginx
upstream app_servers {
    zone app_servers 128k;       # Хранение состояния группы
    status_zone app_status;      # Метрики для API
    
    server 10.0.0.1:8080 max_conns=100;
    server 10.0.0.2:8080 max_conns=100;
    
    keepalive 64;                # Пул соединений на каждый воркер
    
    # Резервирование очереди (PRO)
    # queue 500 timeout=30s;
}
```

**Важные нюансы keepalive:**
- Директива `keepalive` должна объявляться **после** всех серверов в блоке `upstream`.
- В `location` обязательно установите `proxy_set_header Connection "";` — иначе keepalive не активируется.
- `keepalive_requests` (по умолчанию 1000) ограничивает число запросов в одном соединении, предотвращая утечки.
- `keepalive_timeout` должен быть меньше, чем `keepalive_requests` × среднее время обработки, чтобы соединения успевали закрываться.

### Пассивные и активные проверки

Пассивные проверки (`max_fails`, `fail_timeout`) работают на уровне статистики проксирования:
```nginx
upstream backend {
    server 10.0.0.1:8080 max_fails=3 fail_timeout=30s;
    server 10.0.0.2:8080 max_fails=3 fail_timeout=30s;
}
```

Активные проверки в OSS используют модуль `upstream_check_module` (подключается через `load_module` или встроен в бинарный пакет Angie):
```nginx
upstream backend {
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
    
    check interval=5s fall=3 rise=2;
    check_http_send "GET /health HTTP/1.1\r\nHost: api.internal\r\nConnection: close\r\n\r\n";
    check_http_expect_rescode 200;
}
```

В Angie PRO используется нативная директива `upstream_probe` в контексте `location` — более гибкая, поддерживает проверку тела ответа, режимы `always`/`idle`/`onfail`, начальную верификацию `essential`. Подробнее: **[Мониторинг Angie — возможности Angie Pro](./angie_monitoring/angie_monitoring_pro.md)**.

### Sticky Sessions: методы Cookie, Route и Learn

**Cookie (вставка):** Angie самостоятельно устанавливает Cookie с именем сервера.
```nginx
upstream app {
    sticky cookie=server_id;
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}
```

**Route (привязка по существующей Cookie):** Используется, когда приложение уже устанавливает идентификатор сессии.
```nginx
upstream app {
    sticky route=$cookie_sessionid;
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}
```

**Learn (обучение):** Angie отслеживает Cookie от бэкенда (например, `JSESSIONID`) и создает локальную таблицу привязок в `zone`.
```nginx
upstream stateful_app {
    zone stateful_app 256k;
    
    sticky learn 
           create=$upstream_cookie_jsessionid
           lookup=$cookie_jsessionid
           zone=client_sessions:2m;
    
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}
```

### Параметры управления сервером

| Параметр | Описание | Доступность |
| :--- | :--- | :--- |
| `weight=N` | Относительный вес в балансировке. | Все версии |
| `max_fails=N` | Число ошибок до временного исключения. | Все версии |
| `fail_timeout=T` | Время «штрафа» после `max_fails`. | Все версии |
| `max_conns=N` | Лимит одновременных соединений. | Все версии |
| `slow_start=T` | Плавный ввод после восстановления. | Angie / Plus |
| `drain` | Плавный вывод из эксплуатации. | Angie PRO |
| `backup` | Резервный сервер (активен, если основные лежат). | Все версии |
| `down` | Ручное исключение из ротации. | Все версии |

## Практические сценарии

### 1. Настройка алгоритма Least Time (OSS 1.12+)

Алгоритм выбирает сервер не только по количеству соединений, но и по скорости обработки запросов. Параметр `inflight` (Angie-specific) учитывает запросы, которые уже приняты, но еще не завершились — наиболее точный метод для предотвращения перегрузки медленных узлов.

```nginx
upstream fast_pool {
    zone fast_pool 64k;
    
    # Балансировка по времени получения полного ответа с учетом незавершенных запросов
    least_time last_byte inflight;
    
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}
```

**Валидация:**
```bash
curl -s http://127.0.0.1/status/http/upstreams/fast_pool/ | jq '.peers[] | {server, time, inflight}'
# → {"server":"10.0.0.1:8080","time":"120ms","inflight":3}
# → {"server":"10.0.0.2:8080","time":"85ms","inflight":1}
```

### 2. Активные проверки состояния (Active Health Checks)

В отличие от пассивных проверок (`max_fails`), активные проверки опрашивают бэкенды независимо от клиентского трафика.

```nginx
upstream backend_pool {
    zone backend_pool 64k;
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;

    # Интервал 5с, 3 ошибки = DOWN, 2 успеха = UP
    check interval=5s fall=3 rise=2;
    check_http_send "GET /health HTTP/1.1\r\nHost: api.internal\r\nConnection: close\r\n\r\n";
    check_http_expect_rescode 200;
}
```

**Валидация:**
```bash
curl -s http://127.0.0.1/status/http/upstreams/backend_pool/ | jq '.peers[] | {server, state, checks_failed}'
# → {"server":"10.0.0.1:8080","state":"up","checks_failed":0}
```

### 3. Продвинутые Sticky Sessions: метод Learn (OSS 1.12+)

Метод `learn` позволяет Angie отслеживать существующие сессии приложения (например, `JSESSIONID`), не вставляя собственные Cookie.

```nginx
upstream stateful_app {
    zone stateful_app 256k;
    
    sticky learn 
           create=$upstream_cookie_jsessionid
           lookup=$cookie_jsessionid
           zone=client_sessions:2m;
    
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}
```

**Валидация:**
```bash
curl -s http://127.0.0.1/status/http/upstreams/stateful_app/ | jq '.sticky.sessions | length'
# → 42  # количество активных sticky-сессий
```

### 4. Плавный вывод сервера (Drain) и Slow Start

**Slow Start** защищает восстановленный бэкенд от перегрузки «холодным» кэшем:
```nginx
upstream api_cluster {
    zone api_cluster 128k;
    server 10.0.0.1:8080 weight=3 slow_start=30s;
    server 10.0.0.2:8080 weight=1;
}
```

**Drain** (Angie PRO) через API:
```bash
# Плавный вывод сервера
curl -X PUT -d "drain" \
  'http://127.0.0.1/status/http/upstreams/api_cluster/servers/0/down'

# Проверка состояния
curl -s http://127.0.0.1/status/http/upstreams/api_cluster/ | jq '.peers[0] | {state, drain}'
# → {"state":"draining","drain":true}
```

### 5. Динамическое управление весами и статусами через API

Angie позволяет изменять параметры upstream без перезагрузки:
```bash
# Установка веса сервера
curl -X PATCH \
  -d '{"weight": 5}' \
  'http://127.0.0.1/status/http/upstreams/api_cluster/servers/0'

# Перевод сервера в резерв (down)
curl -X PUT \
  'http://127.0.0.1/status/http/upstreams/api_cluster/servers/1/down'
```

**Валидация:**
```bash
curl -s http://127.0.0.1/status/http/upstreams/api_cluster/ | jq '.peers[] | {server, weight, state}'
```

### 6. Динамическое управление и Docker Discovery

Angie 1.12+ поддерживает автоматическое обнаружение бэкендов в Docker-окружениях без перезагрузки конфигурации.

**Docker Upstream Discovery:**
```nginx
upstream docker_app {
    zone docker_app 64k;
    upstream_discovery docker label=app-type:backend;
}
```

### 7. Поддержка NTLM (Angie PRO)

Для приложений Microsoft (Exchange, AD) требуется поддержание связи клиента и бэкенда через одно TCP-соединение на всех этапах аутентификации.

```nginx
upstream ntlm_backend {
    zone ntlm_backend 64k;
    server 10.0.0.1:8080;
    
    bind_conn;
}
```

### 8. Хэш-балансировка (hash / ip_hash)

Используется, когда каждый клиент (или URI) должен попадать на один и тот же бэкенд — например, для сессий в памяти, шардинга кэша или канонического разбора запросов по `X-Forwarded-For`.

```nginx
upstream cache_backends {
    zone cache_backends 64k;

    # Привязка клиента к серверу по IP (простейший случай)
    ip_hash;

    server 10.0.0.1:8080 weight=1;
    server 10.0.0.2:8080 weight=1;
    server 10.0.0.3:8080 weight=1;
}

upstream profile_backends {
    zone profile_backends 64k;

    # Привязка по URI с устойчивым consistent-хешированием
    hash $request_uri consistent;

    server 10.0.0.11:8080;
    server 10.0.0.12:8080;
    server 10.0.0.13:8080;
}
```

Ключевые замечания:

*   `ip_hash` хеширует первые три октета IPv4-адреса клиента — не работает одинаково за NAT и прокси без `set_real_ip_from`.
*   `consistent` (кольцевое хеширование) минимизирует перераспределение запросов при добавлении/удалении серверов — критично для кэш-шардов.
*   При `hash` допустимы переменные: `hash $binary_remote_addr$server_port` и т.п. Алгоритмическая теория методов — в [Алгоритмы балансировки Nginx](../Nginx/Proxy/Load_Balancing/algorithms.md).

### 9. Canary и Blue-Green: плавное переключение трафика

Переключение версий приложения через балансировщик без простоя и долгого A/B. Методика канареечного и shadow-деплоя описана в [Blue-Green (CI-CD)](../../CI-CD/Deployment_Strategies/blue_green_deployment.md) и [Shadow deployment (CI-CD)](../../CI-CD/Deployment_Strategies/shadow_deployment.md).

#### Канареечная раскатка (Canary) через веса

```nginx
upstream app_v2 {
    zone app_v2 64k;

    server 10.0.0.1:8080 weight=100;   # стабильная версия
    server 10.0.0.2:8080 weight=1;     # кандидат (1% трафика)
}
```

Постепенное переключение весов через REST API Angie без reload (динамические апстримы):

```bash
# Перевести кандидата с 1% на 10% трафика
curl -sX PATCH http://127.0.0.1/status/upstreams/app_v2 \
  -H 'Content-Type: application/json' \
  -d '{"servers": {"10.0.0.2:8080": {"weight": 2, "state": "up"}}}'
# → {"10.0.0.2:8080": {"state": "up", "weight": 2, ...}}
```

#### Blue-Green с гарантией «не обрезать» живые сессии

Совмещение `sticky`, `drain` и `slow_start`:

```nginx
upstream blue {
    zone blue 64k;
    sticky learn create=1h lookup=1h zone=blue_sticky:64k;

    server 10.0.0.1:8080 slow_start=30s;   # new green
    server 10.0.0.2:8080 drain;            # old blue — добивает сессии
}
```

1. Поднимаете новое окружение (green) в том же upstream рядом со старым.
2. Переводите старые ноды в `drain` — они завершают только начатые/sticky-сессии.
3. После полного вывода старых нод — переключаете DNS/веса на 100% на новые.
4. При проблемах возврат: увеличение веса старых нод (sticky перенаправит залогиненных).

#### Управление статусом серверов для переключения

```bash
# Вывести сервер в drain (плавно завершает обработку)
curl -sX PATCH http://127.0.0.1/status/upstreams/app_v2 \
  -d '{"server": "10.0.0.1:8080", "state": "draining"}'
# → {"server":"10.0.0.1:8080","state":"draining","drain":true}
```

Подробнее о динамическом управлении через API — [Динамическое управление весами и статусами](#5-динамическое-управление-весами-и-статусами-через-api) и [Динамические апстримы в Angie](./dynamic_upstreams.md).

## Операции и команды

### Валидация конфигурации

| Команда | Ожидаемый результат |
| :--- | :--- |
| `angie -t` | `angie: configuration file /etc/angie/angie.conf test is successful` |
| `angie -T` | Вывод конфигурации с развернутыми include (для отладки). |

### Управление сервисом

| Команда | Ожидаемый результат |
| :--- | :--- |
| `systemctl reload angie` | Graceful reload без потерь соединений. |
| `systemctl status angie` | `active (running)` с указанием PID и memory usage. |
| `angie -s stop` | Graceful shutdown с ожиданием завершения сессий. |

### Проверка upstream через API

```bash
# Список всех upstream и состояние серверов
curl -s http://127.0.0.1/status/http/upstreams/ | jq '.'

# Детали конкретного upstream
curl -s http://127.0.0.1/status/http/upstreams/app_servers/ | jq '.peers[] | {server, state, active, requests, time}'

# Keepalive-метрики
curl -s http://127.0.0.1/status/http/upstreams/app_servers/ | jq '.peers[] | {server, keepalive}'
```

### Проверка sticky-сессий

```bash
# Количество активных sticky-сессий
curl -s http://127.0.0.1/status/http/upstreams/stateful_app/ | jq '.sticky.sessions | length'
```

### Диагностика соединений

```bash
# Активные соединения к бэкендам
ss -tnp | grep angie | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn

# Таймауты и retransmit
ss -ti | grep -E 'angie|bcke' | head -20

# Проверка DNS-разрешения (если используется dynamic upstream)
dig backend.internal +short
```

### Работа с зонами разделяемой памяти

```bash
# Размер зоны в /dev/shm
ls -la /dev/shm/ | grep angie

# Мониторинг shared memory в реальном времени
watch -n1 'df -h /dev/shm && echo "---" && ls -la /dev/shm/ | grep angie'
```

### Логирование

```bash
# Tail access log с upstream-метриками
tail -f /var/log/angie/access.log | awk '{print $7, $9, $12, $13}'

# Ошибки upstream
grep -E 'upstream|502|503|504' /var/log/angie/error.log

# Активные проверки (если модуль check загружен)
grep -E 'check|health' /var/log/angie/error.log
```

## Устранение неисправностей

### 502 Bad Gateway при достижении max_conns

**Причина:** Все серверы в upstream достигли лимита одновременных соединений, очередь (queue) отсутствует или переполнена.

**Диагностика:**
```bash
curl -s http://127.0.0.1/status/http/upstreams/app_servers/ | jq '.peers[] | {server, active, max_conns}'
```

**Решение:**
- Angie OSS: добавьте `backup`-сервер или увеличьте `max_conns`.
- Angie PRO: настройте `queue` с достаточным размером и таймаутом.
- Оптимизируйте `keepalive_timeout` и `keepalive_requests` для ускорения возврата соединений в пул.

### Sticky-сессии не работают

**Причина:** Зона `zone` слишком мала, или `sticky learn` объявлен до `zone`, или Cookie не передаются через прокси.

**Диагностика:**
```bash
curl -s http://127.0.0.1/status/http/upstreams/stateful_app/ | jq '.sticky'
# → {"sessions": 0}  # если 0 — sticky не работает
```

**Решение:**
- Убедитесь, что `zone` объявлена **до** `sticky learn`.
- Увеличьте размер зоны (`zone=client_sessions:2m` → `4m`).
- Проверьте, что `proxy_pass` не модифицирует Cookie: `proxy_pass_header Set-Cookie;`.

### Least Time не снижает latency

**Причина:** Зона `zone` недостаточна для хранения метрик, или `least_time` указан без `inflight`.

**Диагностика:**
```bash
curl -s http://127.0.0.1/status/http/upstreams/fast_pool/ | jq '.peers[] | {server, time, inflight}'
```

**Решение:**
- Добавьте `inflight` к `least_time` для учета незавершенных запросов.
- Убедитесь, что размер `zone` позволяет хранить метрики для всех серверов.
- Проверьте, что бэкенды не кэшируют ответы (может искажать время ответа).

### Активные проверки не обнаруживают сбой

**Причина:** Неправильный URI проверки, строгий `check_http_expect_rescode`, или фаервол блокирует доступ к health endpoint.

**Диагностика:**
```bash
# Ручная проверка с той же стороны, где работает Angie
curl -v http://10.0.0.1:8080/health -H "Host: api.internal"

# Проверка, что модуль check загружен
angie -V 2>&1 | grep check
```

**Решение:**
- Убедитесь, что health endpoint доступен из сети Angie.
- Используйте `check_http_expect_rescode` только если статус-код стабилен (например, 200).
- Для сложных проверок перейдите на Angie PRO с `upstream_probe`.

### Высокий p99 latency при нормальном RPS

**Причина:** Деградация конкретного бэкенда, TCP retransmit, или исчерпание keepalive-пула.

**Диагностика:**
```bash
ss -ti | grep -E 'angie|bcke' | head -20
curl -s http://127.0.0.1/status/http/upstreams/app_servers/ | jq '.peers[] | {server, keepalive}'
```

**Решение:**
- Проверьте сетевые задержки (`mtr`, `tcpdump`).
- Увеличьте `keepalive` в upstream.
- Добавьте `proxy_next_upstream error timeout http_502 http_503 http_504;` для автоматического переключения при проблемах.

### Исчерпание пула keepalive-соединений

**Причина:** Слишком маленькое значение `keepalive` в upstream при высокой нагрузке, или отсутствие `proxy_http_version 1.1`.

**Диагностика:**
```bash
curl -s http://127.0.0.1/status/http/upstreams/app_servers/ | jq '.peers[] | {server, keepalive}'
```

**Решение:**
- Увеличьте значение `keepalive` в блоке `upstream`.
- Обязательно добавьте в `location`:
  ```nginx
  proxy_http_version 1.1;
  proxy_set_header Connection "";
  ```
- Увеличьте `keepalive_requests` и `keepalive_timeout`.

## Лучшие практики

### Безопасность
- Размещайте бэкенды в закрытой сети; единственный доступ — через Angie.
- Используйте `proxy_set_header X-Real-IP $remote_addr;` и `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` для передачи реального IP.
- Ограничьте `client_max_body_size` на уровне `location` для предотвращения exhaustion диска и памяти.
- Используйте TLS 1.3 с аппаратным ускорением (`ssl_conf_command Options +KTLS;`).

### Производительность
- Всегда включайте `keepalive` в upstream и `proxy_http_version 1.1`.
- Размер `zone`: 64 КБ на 50 серверов, 128 КБ на 100–200. Для тысяч контейнеров используйте `1m`.
- `keepalive_timeout` должен быть больше, чем `keepalive_requests` × среднее время ответа.
- Для тяжелых API используйте `least_time last_byte inflight` вместо `least_conn`.
- `slow_start=30s` защищает восстановленные бэкенды от перегрузки.
- `worker_processes auto;` + `worker_cpu_affinity` для привязки воркеров к ядрам CPU.

### Эксплуатация
- Настройте `limit_req_zone` и `limit_conn_zone` для защиты от DDoS и thundering herd.
- Используйте `proxy_cache` для читаемых данных — снижает нагрузку на бэкенды на 60–90%.
- Мониторьте метрики через `/status/http/upstreams/` и `/metrics` (Prometheus).
- Настройте алерты на `upstream_connect_time`, `upstream_response_time`, `peers[].state`.

### Откат и восстановление
- При проблемах с sticky-сессиями временно переключитесь на `round_robin` или `least_conn`.
- При проблемах с keepalive отключите его (`keepalive off;`) и вернитесь к HTTP/1.0 для диагностики.
- Используйте `angie -t` перед каждым `reload`.

## Дополнительная информация

### Версии Angie

**Актуальность (2025–2026):** Angie активно развивается как open-source форк Nginx. Версия **1.12.x** (2026) включает стабильную поддержку `least_time inflight`, `sticky learn`, Docker discovery, динамические веса через API и расширенный мониторинг Prometheus.

### Ограничения

- `least_time` доступен только в Angie OSS (не в Nginx OSS). В Nginx Plus аналогичная функция называется `least_time`.
- `feedback` алгоритм требует поддержки на стороне приложения (агент или endpoint с метриками).
- `queue` доступен только в Angie PRO.
- `bind_conn` доступен только в Angie PRO.
- `sticky learn` требует `zone` размером не менее 256 КБ для 100+ concurrent сессий.
- VIP (в контексте HA с Keepalived) не связан с upstream — см. **[Angie с Keepalived для HA](./angie_ha_with_keepalived.md)**.

### См. также

- **[Обзор возможностей Angie](./angie_overview.md)** — архитектурные отличия.
- **[Мониторинг бэкендов в Angie](./angie_monitoring/angie_monitoring_concepts.md)** — использование API и консоли.
- **[Динамические апстримы и Service Discovery](./dynamic_upstreams.md)** — глубокая настройка DNS и Docker.
- **[Алгоритмы балансировки Nginx](../Nginx/Proxy/Load_Balancing/algorithms.md)** — подробный разбор Round Robin и Least Conn.
- **[Проверки состояния и мониторинг (Health Checks)](../Nginx/Proxy/Load_Balancing/health_checks_and_monitoring.md)** — активные и пассивные проверки, upstream_check_module.
