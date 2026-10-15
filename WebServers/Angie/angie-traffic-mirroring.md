# Mirror (дублирование трафика) в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Модуль `ngx_http_mirror_module`** — встроенный модуль ядра Angie, выполняющий асинхронное дублирование входящего клиентского HTTP-запроса путем создания внутренних подзапросов (subrequests) и отправки их на один или несколько заданных URI без ожидания и возврата их ответов клиенту.

**Зеркалирование трафика (Traffic Mirroring / Shadowing)** — процесс копирования реального входящего сетевого трафика с производственного окружения (production) на выделенный стенд тестирования, аудита или аналитики (shadow environment) без изменения логики обработки и задержки ответа для конечного пользователя.

**Зеркальный подзапрос (Mirrored Subrequest)** — специализированный внутренний фоновый HTTP-запрос, генерируемый воркером Angie на этапе обработки `PRECONTENT`. Подзапрос наследует заголовки, аргументы и (опционально) тело оригинального запроса, но его выходной поток данных и HTTP-статус перехватываются и отбрасываются ядром веб-сервера.

**Теневой бэкенд (Shadow Upstream)** — целевой сервис или тестовый сервер, принимающий копии запросов для проверки производительности, валидации новых релизов ПО или тестирования гипотез под реальной нагрузкой.

**Сэмплирование зеркалирования (Mirror Sampling)** — вероятностный или детерминированный отбор заданной доли трафика (например, 5% или 10%) для отправки в зеркало с целью защиты теневой инфраструктуры от перегрузки.

**Статус-зона локации (`status_zone`)** — сегмент разделяемой памяти Angie, аккумулирующий числовые показатели счетчиков запросов, байт и кодов ответов для конкретной директивы `location`, доступный через HTTP API и встроенный экспортер Prometheus.

---

## Архитектура и принцип работы

### 1. Механизм обработки в конвейере Angie

Модуль `ngx_http_mirror_module` интегрирован в фазу обработки HTTP-запросов `NGX_HTTP_PRECONTENT_PHASE`. Это означает, что зеркальный подзапрос инициируется до того, как основной обработчик контента (`proxy_pass`, `fastcgi_pass`, `static`) приступит к генерации или передаче ответа клиенту.

```
                  [ Клиентский запрос ]
                            │
                            ▼
               [ Фаза PRECONTENT (Angie) ]
              ngx_http_mirror_handler()
                            │
         ┌──────────────────┴──────────────────┐
         │                                     │
         ▼                                     ▼
[ Основной запрос ]                [ Зеркальный подзапрос ]
   proxy_pass                         proxy_pass
 (Production API)                   (Shadow Backend)
         │                                     │
         ▼                                     ▼
  [ Ответ сервиса ]                     [ Ответ стенда ]
         │                                     │
         ▼                                     ▼
 [ Передача клиенту ]                  [ Отбрасывание в Angie ]
                                       (discard response body)
```

1. **Инициализация:** При попадании запроса в локацию с включенной директивой `mirror` модуль создает внутренний подзапрос (`ngx_http_subrequest`) для каждого целевого URI.
2. **Формирование заголовков и тела:** Подзапрос копирует метод запроса, URI, аргументы строки запроса и заголовки клиента. Если директива `mirror_request_body` включена (`on`), тело запроса также дублируется.
3. **Исполнение подзапроса:** Подзапрос направляется во внутреннюю локацию (`internal`), где выполняется проксирование на теневой бэкенд через стандартные модули проксирования (`ngx_http_proxy_module`, `ngx_http_grpc_module` или `ngx_http_fastcgi_module`).
4. **Фильтрация ответа:** Ответ теневого бэкенда перехватывается внутренними фильтрами `ngx_http_mirror_header_filter` и `ngx_http_mirror_body_filter`. Тело ответа не буферизуется и сразу сбрасывается в `/dev/null`, а статус ответа теневого бэкенда никак не влияет на статус ответа, возвращаемый клиенту.

### 2. Жизненный цикл запроса и счетчик ссылок (`r->main->count`)

В архитектуре событийного цикла Angie основной запрос и его зеркальные подзапросы выполняются в контексте **одного и того же worker-процесса**.

- **Асинхронность ответа клиенту:** Клиент получает ответ от основного бэкенда сразу после того, как основной бэкенд завершит передачу заголовков и тела. Angie не ожидает завершения передачи данных в теневой бэкенд для закрытия клиентского HTTP-ответа.
- **Удержание ресурсов воркера:** Дескриптор соединения, буферы памяти пула запроса и сетевые сокеты удерживаются воркером до тех пор, пока счетчик активных ссылок главного запроса (`r->main->count`) не станет равным нулю.
- **Влияние медленного зеркала:** Если теневой бэкенд зависает, медленно принимает TCP-пакеты или не отвечает на запросы, зеркальный подзапрос продолжает удерживать ресурсы воркера вплоть до срабатывания тайм-аутов `proxy_connect_timeout`, `proxy_read_timeout` и `proxy_send_timeout`. При высокой плотности входящего трафика это приводит к исчерпанию пула файловых дескрипторов и лимита `worker_connections`, вызывая деградацию обслуживания основного продакшен-трафика.

### 3. Буферизация тела запроса (`mirror_request_body`)

Поведение модуля кардинально различается в зависимости от директивы `mirror_request_body`:

- **Режим `on` (по умолчанию):** Входящее тело клиентского запроса (POST, PUT, PATCH) полностью вычитывается в оперативную память (в пределах `client_body_buffer_size`) либо сохраняется во временный файл на диске (`client_body_temp_path`). После этого сформированный буфер передается как основному бэкенду, так и зеркальному подзапросу. При обработке тяжелых файлов (multipart upload) дублирование приводит к двойной нагрузке на шину памяти и дисковую подсистему ввода-вывода (I/O).
- **Режим `off`:** Тело клиентского запроса не передается в зеркальный подзапрос. При этом для корректной работы теневого бэкенда необходимо явно удалить заголовок `Content-Length` (`proxy_set_header Content-Length "";`) и отключить передачу тела на уровне прокси (`proxy_pass_request_body off;`), иначе теневой сервер зависнет в ожидании объявленного количества байт.

### 4. Ключевые риски и архитектурные ограничения

1. **Побочные эффекты (Side Effects):** Зеркалирование мутирующих запросов (POST, PUT, DELETE, PATCH) на тестовый стенд с подключенной базой данных или интеграциями может привести к повторной отправке почтовых уведомлений, повторным списаниям средств во внешних платежных шлюзах или нарушению целостности тестовых данных.
2. **Утечка конфиденциальных данных (PII / Secrets):** Продакшен-запросы содержат сессионные cookies, заголовки `Authorization: Bearer <token>`, персональные данные и токены доступа. Передача этих данных на менее защищенный тестовый стенд нарушает требования безопасности.
3. **Удвоение исходящей полосы пропускания (Network Egress):** При зеркалировании 100% трафика исходящий трафик с узла балансировки удваивается. Необходим контроль емкости сетевых интерфейсов и параметров сетевого стека Linux.

---

## Практические сценарии и конфигурация

### Требования к окружению

- Установленный пакет `angie` версии 1.12.x или `angie-pro` 1.12.x на ОС Linux (Debian 12 / Ubuntu 22.04 / 24.04 / RHEL 9 / Rocky Linux 9).
- Наличие основного пула бэкендов (`production_backend`) и изолированного теневого стенда (`staging_shadow_backend`).
- Настроенный резолвинг DNS или статические записи в `upstream`.

### Сценарий 1: Базовое изолированное зеркалирование на тестовый стенд (Production-Ready)

Конфигурация с жесткими защитными тайм-аутами, постоянными keepalive-соединениями и удалением авторизационных заголовков.

```nginx
# /etc/angie/http.d/traffic_mirror.conf

upstream prod_cluster {
    zone prod_cluster_zone 1m;
    server 192.168.10.11:8080 max_fails=3 fail_timeout=10s;
    server 192.168.10.12:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

upstream shadow_cluster {
    zone shadow_cluster_zone 1m;
    server 192.168.20.50:8080 max_fails=5 fail_timeout=5s;
    keepalive 16;
}

server {
    listen 80;
    server_name api.example.internal;

    # Основная рабочая локация
    location /api/ {
        # Включение зеркалирования во внутренний location
        mirror /_shadow_mirror;
        mirror_request_body on;

        proxy_pass http://prod_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Стандартные тайм-ауты для продакшена
        proxy_connect_timeout 2s;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
    }

    # Внутренний обработчик зеркального трафика
    location = /_shadow_mirror {
        # Запрет доступа из внешней сети (возврат 404 при прямом обращении)
        internal;

        # Метрика зоны для независимого отслеживания зеркала
        status_zone shadow_mirror_zone;

        proxy_pass http://shadow_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Метка теневого трафика для приложения-кандидата
        proxy_set_header X-Shadow-Traffic "true";

        # Очистка чувствительных заголовков для безопасности
        proxy_set_header Authorization "";
        proxy_set_header Cookie "";

        # Агрессивные защитные тайм-ауты: медленный стенд сбрасывается мгновенно
        proxy_connect_timeout 500ms;
        proxy_read_timeout 1s;
        proxy_send_timeout 1s;

        # Отключение повторных попыток запроса при сбое теневого бэкенда
        proxy_next_upstream off;

        # Игнорирование обрыва клиентского соединения
        proxy_ignore_client_abort on;
    }
}
```

### Сценарий 2: Сэмплирование теневого трафика (процентное зеркалирование через `split_clients`)

Для высоконагруженных систем отправка 100% копий трафика на тестовый стенд экономически нецелесообразна или опасна перегрузкой стенда. Механизм `split_clients` позволяет зеркалировать строго заданный процент запросов на основе хеширования переменной `$request_id`.

```nginx
# Вычисление целевой локации для зеркалирования (10% запросов)
split_clients $request_id $mirror_target {
    10%              /_shadow_mirror;
    *                "";
}

server {
    listen 80;
    server_name service.example.internal;

    location / {
        # Если $mirror_target пустой (""), зеркалирование не выполняется
        mirror $mirror_target;
        mirror_request_body on;

        proxy_pass http://prod_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }

    location = /_shadow_mirror {
        internal;
        status_zone sampled_shadow_zone;

        proxy_pass http://shadow_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Shadow-Traffic "true";

        proxy_connect_timeout 500ms;
        proxy_read_timeout 800ms;
        proxy_send_timeout 800ms;
        proxy_next_upstream off;
    }
}
```

### Сценарий 3: Селективное безопасное зеркалирование (фильтрация мутирующих методов `GET`/`HEAD`)

Защита теневой базы данных и очередей сообщений от мутаций: на теневой стенд дублируются только безопасные идемпотентные HTTP-методы (`GET`, `HEAD`, `OPTIONS`).

```nginx
# Разрешаем зеркалирование только для безопасных методов чтения
map $request_method $safe_mirror_target {
    GET              /_shadow_mirror;
    HEAD             /_shadow_mirror;
    OPTIONS          /_shadow_mirror;
    default          "";
}

server {
    listen 80;
    server_name store.example.internal;

    location /api/v2/ {
        # Запросы POST, PUT, DELETE, PATCH получат пустую строку и не будут дублироваться
        mirror $safe_mirror_target;
        mirror_request_body off;

        proxy_pass http://prod_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }

    location = /_shadow_mirror {
        internal;
        status_zone readonly_shadow_zone;

        proxy_pass http://shadow_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Shadow-Traffic "readonly";

        proxy_connect_timeout 300ms;
        proxy_read_timeout 1s;
        proxy_next_upstream off;
    }
}
```

### Сценарий 4: Зеркалирование по требованию (On-Demand Debugging по заголовку или IP-сети)

Включение дублирования трафика только для запросов с определенным отладочным заголовком (например, от QA-инженеров) либо из доверенной корпоративной подсети.

```nginx
# Определение признака доверенного IP-адреса
geo $trusted_client {
    default          0;
    192.168.1.0/24   1;
    10.50.0.0/16     1;
}

# Включение зеркала только при совпадении отладочного заголовка и доверенной сети
map "$trusted_client:$http_x_debug_shadow" $debug_mirror_uri {
    "1:enable"       /_shadow_debug_mirror;
    default          "";
}

server {
    listen 80;
    server_name checkout.example.internal;

    location /checkout/ {
        mirror $debug_mirror_uri;
        proxy_pass http://prod_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }

    location = /_shadow_debug_mirror {
        internal;
        status_zone debug_mirror_zone;

        proxy_pass http://staging_debug_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Original-User-Agent $http_user_agent;
        proxy_set_header X-Debug-Session "true";

        proxy_connect_timeout 1s;
        proxy_read_timeout 2s;
    }
}
```

### Сценарий 5: Зеркалирование без передачи тела запроса (`mirror_request_body off;`)

Оптимизация сетевого трафика и дискового I/O при зеркалировании тяжелых маршрутов загрузки файлов (например, медиа-хранилищ или отчетов), где теневой сервис анализирует только URL и заголовки.

```nginx
server {
    listen 80;
    server_name files.example.internal;

    location /upload/ {
        mirror /_shadow_no_body;
        
        # Отключение передачи тела в подзапрос
        mirror_request_body off;

        # Разрешение больших тел для основного бэкенда
        client_max_body_size 50m;
        client_body_buffer_size 128k;

        proxy_pass http://prod_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }

    location = /_shadow_no_body {
        internal;
        status_zone no_body_shadow_zone;

        proxy_pass http://shadow_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;

        # Обязательное отключение передачи тела на апстрим
        proxy_pass_request_body off;

        # Обязательное удаление Content-Length, иначе бэкенд зависнет в ожидании данных
        proxy_set_header Content-Length "";

        proxy_connect_timeout 500ms;
        proxy_read_timeout 1s;
    }
}
```

### Сценарий 6: Мульти-зеркалирование и выборочное отключение в дочерних location (`mirror off;`)

Angie поддерживает отправку копии запроса сразу нескольким получателям (например, стенду новой версии сервиса и независимому коллектору аудита), а также полное отключение зеркалирования для изолированных эндпоинтов.

```nginx
server {
    listen 80;
    server_name portal.example.internal;

    # Глобальное зеркалирование на уровне сервера на два независимых приемника
    mirror /_mirror_shadow_v2;
    mirror /_mirror_security_audit;

    location / {
        proxy_pass http://prod_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }

    # Исключение: конфиденциальный раздел, где зеркалирование запрещено
    location /private-vault/ {
        # Отключение всех унаследованных директив mirror
        mirror off;

        proxy_pass http://prod_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }

    location = /_mirror_shadow_v2 {
        internal;
        status_zone mirror_v2_zone;
        proxy_pass http://shadow_v2_backend;
        proxy_connect_timeout 500ms;
        proxy_read_timeout 1s;
    }

    location = /_mirror_security_audit {
        internal;
        status_zone mirror_audit_zone;
        proxy_pass http://audit_collector_backend;
        proxy_connect_timeout 500ms;
        proxy_read_timeout 1s;
    }
}
```

### Сценарий 7: Защита прокси и теневого стенда от перегрузки (Rate Limiting и Upstream Keepalive)

Ограничение пропускной способности зеркального канала средствами `limit_req`: в случае аномального всплеска трафика излишки зеркальных подзапросов сбрасываются локально внутри Angie с кодом 503, не создавая нагрузку на теневой бэкенд и сеть.

```nginx
# Ограничение частоты зеркальных подзапросов: до 50 запросов в секунду
limit_req_zone $binary_remote_addr zone=mirror_rate_limit:10m rate=50r/s;

server {
    listen 80;
    server_name gateway.example.internal;

    location /api/ {
        mirror /_protected_mirror;
        proxy_pass http://prod_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }

    location = /_protected_mirror {
        internal;
        status_zone protected_mirror_zone;

        # Мгновенный сброс избыточных подзапросов без постановки в очередь
        limit_req zone=mirror_rate_limit burst=10 nodelay;
        limit_req_status 503;

        proxy_pass http://shadow_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Shadow-Traffic "true";

        proxy_connect_timeout 300ms;
        proxy_read_timeout 800ms;
        proxy_next_upstream off;
    }
}
```

### Сценарий 8: Сбор метрик и мониторинг теневого трафика (Status API и Prometheus)

Конфигурация раздельного учета телеметрии для основного и зеркального трафика с экспортом в Prometheus.

```nginx
# /etc/angie/http.d/monitoring.conf

server {
    listen 127.0.0.1:8080;
    server_name localhost;

    # Интерфейс Angie HTTP API (JSON)
    location /status/ {
        api /status/;
        allow 127.0.0.1;
        deny all;
    }

    # Встроенный экспорт метрик в формате Prometheus
    location /metrics {
        prometheus all;
        allow 127.0.0.1;
        deny all;
    }
}
```

---

## Операции и команды

### Валидация конфигурации и безопасная перезагрузка

```bash
# Проверка корректности синтаксиса конфигурационных файлов
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Применение изменений без разрыва активных соединений (graceful reload)
angie -s reload
# → (сигнал SIGHUP успешно отправлен master-процессу)
```

### Проверка изоляции зеркальной локации

Попытка прямого вызова внутренней локации извне должна возвращать HTTP-код 404 Not Found:

```bash
# Тестирование прямого доступа к internal location
curl -s -i http://api.example.internal/_shadow_mirror
# → HTTP/1.1 404 Not Found
# → Server: angie
# → Content-Type: text/html
```

### Тестирование генерации зеркального запроса

Отправка боевого запроса в основной API с проверкой ответа:

```bash
# Вызов основного API
curl -s -i -X POST http://api.example.internal/api/v1/orders \
  -H "Content-Type: application/json" \
  -d '{"order_id": 10042, "item": "server-rack"}'
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → {"status":"created","order_id":10042}
```

### Анализ логов основного и теневого потоков

```bash
# Просмотр логов основного приложения
tail -n 1 /var/log/angie/access.log
# → 192.168.1.50 [14/Oct/2026:21:10:05 +0300] "POST /api/v1/orders HTTP/1.1" 200 42 "-" "curl/8.5.0"

# Проверка, что запрос поступил на теневой бэкенд с установленным заголовком X-Shadow-Traffic
tail -n 1 /var/log/angie/shadow_backend_access.log
# → 192.168.20.50 [14/Oct/2026:21:10:05 +0300] "POST /api/v1/orders HTTP/1.1" 200 42 "X-Shadow: true"
```

### Запрос метрик через HTTP API Angie

Проверка счетчиков запросов и кодов ответа зеркальной зоны локации:

```bash
# Запрос состояния статус-зоны зеркала
curl -s http://127.0.0.1:8080/status/http/location_zones/shadow_mirror_zone/ | jq .
# → {
# →   "requests": {
# →     "total": 45120,
# →     "discarded": 0
# →   },
# →   "responses": {
# →     "200": 44800,
# →     "502": 310,
# →     "504": 10
# →   },
# →   "data": {
# →     "received": 12845600,
# →     "sent": 84521000
# →   }
# → }

# Проверка состояния пула апстрима shadow_cluster
curl -s http://127.0.0.1:8080/status/http/upstreams/shadow_cluster_zone/ | jq '.peers[] | {server, state, active, requests}'
# → {
# →   "server": "192.168.20.50:8080",
# →   "state": "up",
# →   "active": 2,
# →   "requests": 45120
# → }
```

### Проверка метрик Prometheus

```bash
# Получение метрик зоны зеркалирования в формате OpenMetrics
curl -s http://127.0.0.1:8080/metrics | grep -E "angie_http_location_zone.*shadow_mirror_zone"
# → angie_http_location_zone_requests_total{status_zone="shadow_mirror_zone"} 45120
# → angie_http_location_zone_responses_total{status_zone="shadow_mirror_zone",code="200"} 44800
# → angie_http_location_zone_responses_total{status_zone="shadow_mirror_zone",code="502"} 310
```

---

## Диагностика и устранение неисправностей

| Неисправность / Симптом | Вероятная причина | Метод диагностики | Способ решения |
|:---|:---|:---|:---|
| Рост задержки (latency) и потребления памяти на основном сайте при включении mirror | Теневой бэкенд не справляется с нагрузкой или медленно отвечает; воркер удерживает контекст запроса | `curl .../status/connections/` (`active` растет); проверка времени ответа `$upstream_response_time` | Снизить `proxy_connect_timeout` (300–500ms) и `proxy_read_timeout` (1s); ограничить трафик через `split_clients` или `limit_req` |
| Ошибки `1024 worker_connections are not enough` в error.log | Зависшие зеркальные подзапросы исчерпали доступные сокеты в worker-процессе | `grep "worker_connections are not enough" /var/log/angie/error.log` | Увеличить `worker_connections` в `events {}`; настроить `keepalive` в блоке `upstream`; ужесточить тайм-ауты зеркала |
| Теневой бэкенд зависает по тайм-ауту (HTTP 408 / 504) при `mirror_request_body off` | Клиент отправил `Content-Length`, но тело не передано; бэкенд ждет заявленный payload | Анализ логов теневого сервиса; проверка заголовков подзапроса через `tcpdump` | Добавить `proxy_set_header Content-Length "";` и `proxy_pass_request_body off;` в зеркальном location |
| Всплеск нагрузки на диск (I/O wait) и переполнение `/var/lib/angie/body` | Включен `mirror_request_body on` при передаче больших файлов; тело сбрасывается на диск дважды | `iostat -xz 1`; `lsof +D /var/lib/angie/client_body_temp` | Отключить передачу тела: `mirror_request_body off;` для путей загрузки файлов либо выключить зеркало: `mirror off;` |
| Нежелательные изменения данных или отправка уведомлений из тестовой среды | На теневой стенд зеркалируются мутирующие запросы (POST/PUT/DELETE) с доступом к реальным базам | Проверка access.log тестового стенда на наличие методов, отличных от GET/HEAD | Внедрить `map $request_method $mirror_target` (только GET); передавать `X-Shadow-Traffic "true"` и изолировать БД стенда |
| Ошибки 502/504 от зеркала засоряют основной лог ошибок `error.log` | Стандартный уровень логирования фиксирует сбои подзапросов в общий лог | `grep "[error]" /var/log/angie/error.log` | Вынести логирование зеркальной локации в отдельный файл: `access_log /var/log/angie/mirror_access.log;` |

### Диагностический сценарий 1: Устранение деградации latency из-за зависшего зеркального стенда

1. **Идентификация задержки:** В системах мониторинга фиксируется рост P99 Latency на основном трафике:
   ```bash
   # Проверка времени ответа через curl
   curl -s -w "TCP handshake: %{time_connect}s, TTFB: %{time_starttransfer}s, Total: %{time_total}s\n" \
     -o /dev/null http://api.example.internal/api/v1/ping
   # → TCP handshake: 0.002s, TTFB: 1.050s, Total: 1.052s
   ```
2. **Локализация источника задержки:** Изучение значений времени ответа бэкендов в `access.log`:
   ```bash
   # Формат лога с раздельным выводом upstream_response_time
   tail -f /var/log/angie/access.log | awk '{print "URI: "$7, "Status: "$9, "UpstreamTime: "$NF}'
   ```
3. **Оперативное решение:** Уменьшение тайм-аутов и отключение зеркала для предотвращения отказа сервиса:
   ```nginx
   # Временное отключение в конфигурации без перезапуска через map:
   # $mirror_target устанавливается в пустую строку ""
   ```

### Диагностический сценарий 2: Зависание теневого бэкенда при `mirror_request_body off;`

1. **Симптом:** При отправке POST-запросов теневой бэкенд фиксирует таймаут чтения HTTP-запроса (например, `408 Request Timeout` в логах бэкенда).
2. **Анализ пакетов:** Проверка фактических заголовков, отправляемых Angie на теневой сервер:
   ```bash
   tcpdump -i any -A -s 0 'tcp port 8080 and host 192.168.20.50' | grep -E "POST|Content-Length"
   # → POST /upload/file HTTP/1.1
   # → Content-Length: 1048576   <-- ОШИБКА: тело не передано, но заголовок присутствует!
   ```
3. **Исправление:**
   ```nginx
   location = /_shadow_no_body {
       internal;
       proxy_pass http://shadow_cluster;
       # Устранение несоответствия:
       proxy_pass_request_body off;
       proxy_set_header Content-Length "";
   }
   ```

---

## Рекомендации и лучшие практики

### Изоляция ресурсов и сетевая безопасность

- **Обязательная директива `internal`:** Любая локация, выступающая целью для `mirror`, обязана содержать директиву `internal;`. Без нее конечный пользователь может напрямую обратиться к зеркальному обработчику, обходя логику маршрутизации и аутентификации.
- **Агрессивные тайм-ауты:** Всегда настраивайте предельно жесткие тайм-ауты на зеркальном location:
  ```nginx
  proxy_connect_timeout 300ms;
  proxy_read_timeout 1s;
  proxy_send_timeout 1s;
  ```
- **Отключение `proxy_next_upstream`:** Теневой стенд не должен генерировать каскадные повторные запросы. При сбое ноды запрос должен быть немедленно завершен:
  ```nginx
  proxy_next_upstream off;
  ```

### Сетевая оптимизация и пулы соединений

- **Использование `keepalive` в блоках `upstream`:** Зеркалирование удваивает число TCP-рукопожатий. Чтобы предотвратить исчерпание локальных эфемерных портов и накопление сокетов в состоянии `TIME_WAIT`, настраивайте пул постоянных TCP-соединений к теневому стенду:
  ```nginx
  upstream shadow_cluster {
      zone shadow_cluster_zone 1m;
      server 192.168.20.50:8080;
      keepalive 32;
  }
  ```
  В блоке `location` обязательно укажите:
  ```nginx
  proxy_http_version 1.1;
  proxy_set_header Connection "";
  ```

### Защита данных (PII / Secrets) и предотвращение побочных эффектов

- **Очистка заголовков авторизации:** Запрещайте передачу пользовательских токенов и cookies на тестовые стенды:
  ```nginx
  proxy_set_header Authorization "";
  proxy_set_header Cookie "";
  ```
- **Маркировка теневого трафика:** Передавайте заголовок `proxy_set_header X-Shadow-Traffic "true";`. Целевое приложение-кандидат должно проверять данный заголовок и программно блокировать:
  - Обращения к внешним платежным шлюзам и фискальным сервисам.
  - Отправку SMS, Push-уведомлений и Email-сообщений реальным пользователям.
  - Запись мутирующих транзакций в боевые или общие базы данных.

### Управление нагрузкой и Graceful Fallback

- **Управление через переменные без reload:** Используйте директиву `mirror` с переменной (`mirror $mirror_target;`). Это позволяет менять процент сэмплирования или мгновенно отключать зеркало через изменение `map` или динамические таблицы без остановки рабочих процессов.
- **Лимитирование частоты подзапросов:** Всегда используйте `limit_req` с директивой `nodelay` внутри зеркальной локации для сброса пиков входящего трафика.

---

## Дополнительная информация

- [Модуль `mirror` (основы) — Nginx, внутренняя маршрутизация](../Nginx/Core/Location/internal_routing.md) — базовые принципы внутренних подзапросов в Nginx.
- [Shadow Deployment (CI-CD)](../../CI-CD/Deployment_Strategies/shadow_deployment.md) — концепция и архитектурные стратегии теневого развертывания.
- [Директивы location в Angie](./angie_location_directives.md) — правила сопоставления URI, директива `internal` и приоритеты обработки.
- [Настройка Angie в роли обратного HTTP-прокси](./angie_reverse_proxy.md) — конфигурация директив проксирования и передача HTTP-заголовков.
- [Мониторинг Angie — Работа с конфигурацией и состоянием через API](./angie_monitoring/angie_monitoring_api.md) — работа со статус-зонами и REST API.
- [Сбор и экспорт метрик Angie в Prometheus](./angie_monitoring/angie_monitoring_prometheus.md) — мониторинг производительности и экспортер OpenMetrics.

---

## См. также

- [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md) — балансировка трафика и параметры upstream.
- [Динамические апстримы в Angie](./dynamic_upstreams.md) — управление серверами бэкенда в runtime.
- [Ограничение запросов и соединений в Angie High Load](./High_Load/dos_protection.md) — механизмы `limit_req` и `limit_conn`.