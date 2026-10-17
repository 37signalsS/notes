# Nginx: обратный прокси и балансировка gRPC (gRPC & HTTP/2 Microservices Gateway)

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x (Mainline), gRPC 1.62+ / 1.68+, HTTP/2 RFC 9113

---

## 0. Декларация перекрытия (Overlap Declaration)

Настоящий документ является единым источником правды (SSoT) по настройке Nginx в качестве пограничного шлюза и балансировщика трафика для микросервисов gRPC:
- [Performance/nginx_http_versions.md](../Performance/nginx_http_versions.md) — рассматривает общие спецификации протоколов HTTP/1.1, HTTP/2 и HTTP/3, но не затрагивает модуль `ngx_http_grpc_module`.
- [Proxy/nginx_buffering_and_streaming.md](../Proxy/nginx_buffering_and_streaming.md) — описывает потоковую передачу данных в HTTP-проксировании, не учитывая специфику HTTP/2 Trailers и двоичной сериализации Protobuf.
- [Proxy/Load_Balancing/overview_concepts.md](../Proxy/Load_Balancing/overview_concepts.md) — описывает общие принципы балансировки L7, на которые опирается данный сценарий.

---

## 1. Определения

- **gRPC (gRPC Remote Procedure Calls)** — высокопроизводительный RPC-фреймворк с открытым исходным кодом от Google, использующий протокол **HTTP/2** в качестве транспорта и **Protocol Buffers (Protobuf)** для строгой типизации и эффективной бинарной сериализации сообщений.
- **Модуль `ngx_http_grpc_module`** — специализированный встроенный модуль Nginx (начиная с версии 1.13.10), обеспечивающий прямое проксирование запросов к серверам gRPC через директивы `grpc_pass`, `grpc_set_header`, `grpc_connect_timeout`, `grpc_read_timeout` и управление трейлерами.
- **Директива `grpc_pass`** — основная директива проксирования gRPC. Поддерживает две схемы:
  * `grpc://` — открытый незашифрованный HTTP/2 (Cleartext / h2c), стандартный выбор для передачи данных внутри доверенного периметра дата-центра или пода Kubernetes.
  * `grpcs://` — защищенный HTTP/2 с TLS-шифрованием (HTTP/2 over TLS).
- **HTTP/2 Multiplexing (Мультиплексирование)** — базовая возможность HTTP/2, позволяющая передавать сотни параллельных независимых двунаправленных потоков (Streams) внутри одного физического TCP-соединения, исключая задержки Head-of-Line Blocking на уровне прикладного протокола.
- **HTTP/2 Trailers (Завершающие заголовки)** — служебные заголовки HTTP/2, отправляемые *после* передачи тела ответа (DATA-фреймов) в закрывающем HEADERS-фрейме с флагом `END_STREAM`. В gRPC трейлеры несут критическую информацию: статус завершения RPC (`grpc-status`) и текстовое описание ошибки (`grpc-message`).
- **`grpc-status`** — стандартизированный код состояния выполнения удаленного вызова (0 — `OK`, 1 — `CANCELLED`, 3 — `INVALID_ARGUMENT`, 4 — `DEADLINE_EXCEEDED`, 14 — `UNAVAILABLE` и др.). В отличие от стандартного REST, HTTP-код ответа в gRPC почти всегда равен `200 OK`, а реальный статус вызова передается именно в трейлере `grpc-status`.
- **gRPC Streaming (Потоковые вызовы)** — типы RPC-вызовов, при которых клиент, сервер или обе стороны передают последовательность сообщений в рамках одного длительного HTTP/2 стрима:
  * Unary (1 запрос → 1 ответ)
  * Server Streaming (1 запрос → N ответов)
  * Client Streaming (N запросов → 1 ответ)
  * Bidirectional Streaming (двунаправленный обмен сообщениями в реальном времени)

---

## 2. Архитектура и принципы работы

### 2.1 Схема пограничного gRPC Gateway

Nginx принимает внешние клиентские вызовы по защищенному протоколу HTTPS (HTTP/2 over TLS), терминирует SSL-сертификаты, валидирует заголовки, балансирует трафик и транслирует вызовы по протоколу `h2c` на пул бэкенд-микросервисов:

```text
               gRPC Клиенты (Мобильные приложения / Web / Внешние сервисы)
                                       │
                      HTTP/2 over TLS (ALPN: h2) :443
                                       ▼
                     ┌──────────────────────────────────┐
                     │     Nginx L7 gRPC Gateway        │
                     │  - TLS / mTLS Termination        │
                     │  - HTTP/2 Demuxing & Routing     │
                     │  - Rate Limiting & Auth Request  │
                     └─────────────────┬────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            │ grpc:// (h2c)                                       │ grpc:// (h2c)
            ▼                                                     ▼
┌──────────────────────────────┐              ┌───────────────────────────────────────┐
│ User Service (Go / gRPC)     │              │ Billing Service (Java / gRPC)         │
│ 10.0.1.10:50051              │              │ 10.0.1.20:50051                       │
│ - package users.v1.UserService│              │ - package billing.v1.PaymentService   │
└──────────────────────────────┘              └───────────────────────────────────────┘
```

### 2.2 Структура URI в gRPC и маршрутизация Nginx

В gRPC путь HTTP/2 запроса формируется по строгому стандарту Protobuf:
$$\text{URI} = \text{/}\langle\text{Package Name}\rangle\text{.}\langle\text{Service Name}\rangle\text{/}\langle\text{Method Name}\rangle$$

Пример: Запрос к методу `GetUser` сервиса `UserService` в пакете `company.users.v1` имеет URI:
`/company.users.v1.UserService/GetUser`

Это позволяет Nginx выполнять гранулярную маршрутизацию микросервисов на уровне блоков `location`:
* `location /company.users.v1.UserService/` — направляет вызовы всех методов сервиса пользователей.
* `location /company.billing.v1.PaymentService/` — направляет вызовы биллинга.
* `location /` — общий fallback или маршрутизация по умолчанию.

---

## 3. Практические сценарии

### Сценарий 1: TLS-терминация и балансировка нагрузки gRPC микросервисов (Cleartext h2c)

**Контекст:** Внутренний кластер микросервисов на Go слушает порт `50051`. Nginx принимает внешний трафик по HTTPS на 443 порту с обязательным ALPN-согласованием `h2`, распределяет вызовы между тремя экземплярами бэкенда и пробрасывает gRPC-статусы.

#### 1. Конфигурация Nginx (`/etc/nginx/conf.d/grpc_gateway.conf`)

```nginx
# Пул бэкендов gRPC микросервиса
upstream user_grpc_cluster {
    zone user_grpc_zone 64k;
    server 10.0.1.11:50051 max_fails=3 fail_timeout=10s;
    server 10.0.1.12:50051 max_fails=3 fail_timeout=10s;
    server 10.0.1.13:50051 max_fails=3 fail_timeout=10s;

    # Поддержание пула постоянных HTTP/2 соединений
    keepalive 32;
}

server {
    listen 80;
    server_name grpc.example.com;
    return 301 https://$host$request_uri;
}

server {
    # Включение HTTP/2 обязательно для gRPC
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name grpc.example.com;

    # SSL сертификаты с поддержкой ALPN (h2)
    ssl_certificate /etc/ssl/certs/grpc_example_com.crt;
    ssl_certificate_key /etc/ssl/private/grpc_example_com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Настройки HTTP/2 мультиплексирования
    http2_max_concurrent_streams 512;
    http2_recv_buffer_size 512k;

    # Формат логирования с поддержкой gRPC статусов
    log_format grpc_analytics escape=json '{'
        '"time_iso":"$time_iso8601",'
        '"remote_addr":"$remote_addr",'
        '"grpc_service":"$uri",'
        '"grpc_status":$sent_http_grpc_status,'
        '"status":$status,'
        '"request_time":$request_time,'
        '"upstream_response_time":"$upstream_response_time",'
        '"upstream_addr":"$upstream_addr"'
    '}';

    access_log /var/log/nginx/grpc_access.log grpc_analytics;
    error_log  /var/log/nginx/grpc_error.log warn;

    # Маршрутизация конкретного gRPC пакета
    location /company.users.v1.UserService/ {
        # Передача вызова по незашифрованному HTTP/2 (h2c)
        grpc_pass grpc://user_grpc_cluster;

        # Проброс заголовков авторизации и метаданных
        grpc_set_header Host $host;
        grpc_set_header X-Real-IP $remote_addr;
        grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        grpc_set_header X-Forwarded-Proto $scheme;
        grpc_set_header X-Request-ID $request_id;

        # Таймауты для Unary вызовов
        grpc_connect_timeout 5s;
        grpc_read_timeout 15s;
        grpc_send_timeout 15s;

        # Механизм повтора запроса при сбое бэкенда
        grpc_next_upstream error timeout invalid_header http_502 http_503;
        grpc_next_upstream_tries 3;
        grpc_next_upstream_timeout 10s;

        # Ограничение размера Protobuf сообщения (по умолчанию 4MB)
        client_max_body_size 8m;
    }

    # Специальный эндпоинт для Server/Bidirectional Streaming с большим таймаутом
    location /company.users.v1.UserService/StreamEvents {
        grpc_pass grpc://user_grpc_cluster;
        grpc_set_header Host $host;
        grpc_set_header X-Real-IP $remote_addr;

        # Увеличение таймаута для длительного стрима событий (1 час)
        grpc_read_timeout 3600s;
        grpc_send_timeout 3600s;

        # Отключение буферизации для мгновенной доставки сообщений стрима
        grpc_buffer_size 16k;
    }

    # Запрет любых обращений, не являющихся вызовами gRPC
    location / {
        return 404;
    }
}
```

---

### Сценарий 2: Сквозное шифрование (End-to-End TLS / grpcs) и взаимная аутентификация (mTLS)

**Контекст:** Требования безопасности Zero-Trust предписывают шифровать трафик не только от клиента к шлюзу, но и между шлюзом Nginx и бэкендами gRPC. Клиенты обязаны предоставлять клиентский сертификат (mTLS).

```nginx
upstream secure_grpc_upstream {
    server 10.0.2.15:50052;
    keepalive 16;
}

server {
    listen 8443 ssl http2;
    server_name secure-grpc.company.internal;

    # Серверный TLS
    ssl_certificate /etc/ssl/certs/gateway.crt;
    ssl_certificate_key /etc/ssl/private/gateway.key;

    # Включение mTLS проверки клиентов
    ssl_client_certificate /etc/ssl/certs/internal_ca_chain.crt;
    ssl_verify_client on;
    ssl_verify_depth 2;

    location / {
        # Схема grpcs:// форсирует инициализацию TLS к бэкенду
        grpc_pass grpcs://secure_grpc_upstream;

        # Клиентский сертификат самого Nginx для авторизации перед бэкендом
        grpc_ssl_certificate /etc/ssl/certs/nginx_client.crt;
        grpc_ssl_certificate_key /etc/ssl/private/nginx_client.key;

        # Валидация сертификата бэкенда
        grpc_ssl_trusted_certificate /etc/ssl/certs/internal_ca_chain.crt;
        grpc_ssl_verify on;
        grpc_ssl_verify_depth 2;
        grpc_ssl_server_name on;
        grpc_ssl_name grpc-backend.company.internal;

        # Проброс отпечатка и CN сертификата внешнего клиента
        grpc_set_header X-Client-Cert-DN $ssl_client_s_dn;
        grpc_set_header X-Client-Cert-Serial $ssl_client_serial;

        grpc_read_timeout 30s;
    }
}
```

---

## 4. Операции и команды

### 4.1 Проверка конфигурации Nginx

```bash
# Валидация синтаксиса
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Перезагрузка конфигурации
sudo systemctl reload nginx
```

### 4.2 Тестирование gRPC сервиса через CLI-утилиту `grpcurl`

Утилита `grpcurl` является де-факто стандартом тестирования gRPC эндпоинтов (аналог `curl` для REST):

```bash
# 1. Запрос листинга доступных сервисов (gRPC Server Reflection)
grpcurl -proto users.proto grpc.example.com:443 list
# → company.users.v1.UserService
# → grpc.reflection.v1alpha.ServerReflection

# 2. Вызов Unary RPC метода с JSON-аргументом
grpcurl -d '{"user_id": "10042"}' \
        -proto users.proto \
        grpc.example.com:443 \
        company.users.v1.UserService/GetUser
# → {
# →   "user_id": "10042",
# →   "username": "ivan.petrov",
# →   "email": "ivan.petrov@company.com",
# →   "status": "ACTIVE"
# → }

# 3. Вызов с получением заголовков ответа и трейлеров (-v)
grpcurl -v -d '{"user_id": "non_existent"}' \
        -proto users.proto \
        grpc.example.com:443 \
        company.users.v1.UserService/GetUser
# → Resolved method to: company.users.v1.UserService/GetUser
# → Response headers received:
# → content-type: application/grpc
# → x-request-id: 7a8b9c0d1e2f3a4b
# →
# → Response trailers received:
# → grpc-status: 5 (NOT_FOUND)
# → grpc-message: user with specified id does not exist
# → ERROR:
# →   Code: NotFound
# →   Message: user with specified id does not exist
```

---

## 5. Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`HTTP/1.1 400 Bad Request` или `HTTP_1_1_REQUIRED`** | Клиент обратился по HTTP/1.1 либо Nginx не включил согласование `h2` на порту `listen`. | `grpcurl` возвращает: `"transport: received the unexpected content-type "text/html""`. | В блоке `listen` виртуального хоста обязательно указать: `listen 443 ssl http2;`. |
| **`grpc-status: 14 (UNAVAILABLE)`** | Бэкенд-микросервис недоступен, порт закрыт, упал процесс или сработал таймаут `grpc_connect_timeout`. | В `error.log`: `"connect() failed (111: Connection refused) while connecting to upstream"`. | 1. Проверить доступность бэкенда: `nc -zv 10.0.1.11 50051`.<br>2. Проверить сетевые доступы и состояние службы микросервиса. |
| **Разрыв соединения каждые 60 секунд при стриминге (Streaming RPC)** | Сработал дефолтный `grpc_read_timeout` (60 секунд). При отсутствии сообщений от бэкенда Nginx считает стрим зависшим и отправляет `RST_STREAM`. | Клиент ловит: `rpc error: code = Unavailable desc = transport is closing`. | В `location` стриминговых методов выставить: `grpc_read_timeout 3600s;` или настроить gRPC Keepalive ping в клиенте/сервере. |
| **Клиент получает ошибку `413 Request Entity Too Large`** | Размер передаваемого бинарного Protobuf-сообщения превышает лимит `client_max_body_size` (по умолчанию 1 МБ). | В `error.log`: `"client intended to send too large body: 5242880 bytes"`. | Увеличить директиву: `client_max_body_size 16m;` в контексте `server` или `location`. |
| **`grpc-status: 12 (UNIMPLEMENTED)`** | Ошибка в пути URI. Имя пакета, сервиса или метода в запросе не совпадает с Protobuf-декларацией бэкенда. | В `access.log`: запрос на `/MyService/Method` вместо `/package.v1.MyService/Method`. | Проверить сгенерированный код Protobuf и скорректировать клиентский вызов или префикс `location`. |

---

## 6. Рекомендации и лучшие практики

1. **Используйте keepalive для пулов upstream:**  
   Обязательно определяйте директиву `keepalive N;` в блоке `upstream`. Повторное использование открытых HTTP/2 TCP-сессий между Nginx и бэкендами снижает накладные расходы на хэндшейки на 80%.
2. **Разделяйте Unary и Streaming методы в конфигурации:**  
   Для обычных Unary-вызовов держите агрессивные короткие таймауты (`grpc_read_timeout 5-15s;`), чтобы быстро освобождать потоки при сбоях. Для двунаправленных или серверных стримов создавайте отдельные блоки `location` с таймаутом от 1800 до 3600 секунд.
3. **Логируйте `sent_http_grpc_status`:**  
   В gRPC HTTP-код ответа сервера почти всегда равен `200 OK`. Логирование только переменной `$status` не покажет ошибок бизнес-логики. Добавляйте в `log_format` переменную `$sent_http_grpc_status`, чтобы видеть реальные сбои (`grpc-status: 5`, `14`, `16`) в мониторинге и ELK/Loki.
4. **Не смешивайте `proxy_pass` и `grpc_pass`:**  
   Директива `grpc_pass` оперирует нативным бинарным фреймингом HTTP/2. Попытка проксировать gRPC через обычный `proxy_pass` разрушит заголовки трейлеров и приведет к падению клиентских SDK.
5. **Включайте повтор запросов только для идемпотентных методов:**  
   Директива `grpc_next_upstream` безопасна для методов чтения (например, `Get*`, `List*`). Для мутирующих методов (`Create*`, `Charge*`) повторы без проверки идемпотентности могут вызвать дублирование транзакций.

---

## 7. Дополнительная информация

- [Протоколы HTTP/1.1, HTTP/2 и HTTP/3 в Nginx](../Performance/nginx_http_versions.md) — механизмы мультиплексирования и фреймов HTTP/2.
- [Потоковая передача и буферизация в Nginx](../Proxy/nginx_buffering_and_streaming.md) — управление задержками и размерами буферов.
- [Балансировка нагрузки: основные концепции](../Proxy/Load_Balancing/overview_concepts.md) — алгоритмы балансировки и проверки доступности узлов.
