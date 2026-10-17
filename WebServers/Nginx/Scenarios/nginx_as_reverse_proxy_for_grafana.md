# Nginx как обратный прокси для Grafana

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x (Mainline), Grafana 13.2.x / 12.4.x (LTS)

## Определения

**Nginx как обратный прокси для Grafana** — архитектурный сценарий развёртывания, при котором веб-сервер Nginx выступает единой точкой входа (Reverse Proxy), принимая клиентские запросы на стандартных портах 80 и 443 и перенаправляя их на внутренний порт Grafana (по умолчанию `3000/TCP`). Решение обеспечивает централизованную терминацию SSL/TLS, балансировку нагрузки между узлами кластера, разграничение доступа к API, скрытие сетевой топологии и передачу контекста аутентификации.

*   **[Nginx](../Core/nginx_overview.md)** — высокопроизводительный HTTP-сервер, обратный прокси и балансировщик нагрузки с событийно-ориентированной архитектурой (event-driven).
*   **[Grafana](../../../Grafana/grafana_overview.md)** — платформа визуализации метрик, логов, трассировок и оперативного мониторинга. По умолчанию запускает встроенный веб-сервер на порту `3000`.
*   **[Обратный прокси (Reverse Proxy)](../../../Networking/Concepts/proxy.md)** — промежуточный сервер, принимающий запросы внешних клиентов и транслирующий их бэкенд-серверам в изолированном контуре.
*   **Grafana Live (WebSocket)** — встроенная подсистема двусторонней потоковой передачи данных в реальном времени (endpoint `/api/live/`), используемая для live-обновления дашбордов и алертов. Требует обязательного проброса HTTP-заголовков `Upgrade` и `Connection`.
*   **[Auth proxy](../../../Grafana/grafana_user_management_and_authentication.md)** — режим делегированной аутентификации, при котором Nginx (или внешний шлюз) производит проверку подлинности пользователя и передаёт его имя и роли в HTTP-заголовках (`X-WEBAUTH-USER`, `X-WEBAUTH-ROLE`). Grafana принимает доверенные заголовки без повторного запроса пароля.
*   **Sub-path (подпуть)** — схема маршрутизации, при которой Grafana доступна не в корне домена, а по URL-префиксу (например, `https://monitoring.example.internal/grafana/`). Требует синхронного согласования директивы `proxy_pass` в Nginx и параметров `root_url` / `serve_from_sub_path` в Grafana.
*   **Upstream Connection Pooling (`keepalive`)** — механизм Nginx для сохранения и переиспользования открытых TCP-соединений с бэкендами Grafana, предотвращающий исчерпание эфемерных портов и накладные расходы на TCP-handshake.
*   **Пассивный Health Check и Failover** — встроенный механизм Nginx OSS (`max_fails`, `fail_timeout`, `proxy_next_upstream`), регистрирующий сбои реальных запросов и динамически исключающий неисправный узел Grafana из пула балансировки.
*   **[Отказоустойчивый кластер Grafana (HA)](../../../Grafana/high_availability.md)** — схема active-active с несколькими узлами Grafana, подключёнными к общей внешней СУБД (PostgreSQL/MySQL), где Nginx распределяет трафик без необходимости привязки клиентских сессий (sticky sessions).

---

## Базовые концепции и архитектура

### Архитектура решения

```
Клиенты (Браузеры / Grafana CLI / API / Webhook)
                    │
                    ▼ HTTPS (порт 443) [TLS 1.3, HTTP/2, HSTS, Rate Limiting]
┌───────────────────────────────────────────────────────────────┐
│                      Nginx Reverse Proxy                      │
│   (TLS Termination, Auth Proxy, WebSocket, Buffer Tuning)     │
└───────────────┬───────────────────────────────┬───────────────┘
                │                               │
     HTTP:3000 /│ Keepalive          HTTP:3000 /│ Keepalive
     (Node 1)   │                    (Node 2)   │
                ▼                               ▼
┌───────────────────────────────┐┌───────────────────────────────┐
│        Grafana Node 1         ││        Grafana Node 2         │
│      (Stateless Worker)       ││      (Stateless Worker)       │
│  Live / Alerting: Memberlist  ││  Live / Alerting: Memberlist  │
└───────────────┬───────────────┘└───────────────┬───────────────┘
                │                                │
                └───────────────┬────────────────┘
                                ▼
┌───────────────────────────────────────────────────────────────┐
│            Общая инфраструктура хранения состояния            │
│  - СУБД (PostgreSQL / MySQL): сессии, дашборды, права         │
│  - Redis (опционально): шина pub/sub для Grafana Live HA      │
└───────────────────────────────────────────────────────────────┘
```

Nginx размещается перед узлами Grafana и решает следующие инфраструктурные задачи:

1. **SSL/TLS-терминация:** Концентрация криптографической нагрузки на Nginx с централизованным обновлением сертификатов (включая автоматизацию Certbot/acme.sh или корпоративный внутренний PKI). На узлы Grafana трафик передаётся по быстрому локальному HTTP (или по внутреннему шифрованному каналу).
2. **Балансировка нагрузки и отказоустойчивость:** Распределение трафика по пулу узлов Grafana. При падении одного из экземпляров директива `proxy_next_upstream` обеспечивает незаметный для пользователя повтор запроса на соседний узел.
3. **Разграничение прав и защита периметра:**
   - Ограничение доступа к административным API (`/api/admin/`, `/api/org/`) по белым спискам IP-адресов.
   - Защита формы логина (`/login`) от перебора паролей через `limit_req_zone`.
   - Внедрение заголовков безопасности браузера (`Strict-Transport-Security`, `X-Content-Type-Options`, `Content-Security-Policy`).
4. **Полноценная поддержка Grafana Live (WebSockets):** Выделенная маршрутизация запросов к `/api/live/` с корректной обработкой протокола hop-by-hop и предотвращением разрыва долгоживущих TCP-сессий.
5. **Оптимизация сетевого ввода-вывода и буферизация:** Тюнинг буферов Nginx предотвращает сброс больших ответов (JSON-выгрузки дашбордов, тяжелые выборки Explore) во временные файлы на диске (`proxy_temp`).
6. **Централизованный аудит:** Регистрация клиентских запросов с фиксацией реального IP-адреса (`$remote_addr`), времени ответа апстрима (`$upstream_response_time`) и кодов возврата Grafana.

### Жизненный цикл запроса

1. **Приём соединения:** Клиент устанавливает TLS-сессию с Nginx на порту 443. Происходит согласование TLS 1.3 и ALPN (`h2` или `http/1.1`).
2. **Первичная фильтрация:** Nginx сверяет IP-адрес клиента с правилами `allow`/`deny` и проверяет лимит запросов в `limit_req`.
3. **Определение маршрута:**
   - Запросы к `/api/live/` классифицируются как WebSocket-трафик.
   - Запросы к статическим ассетам или стандартному HTTP API отправляются в общий пул бэкендов.
4. **Модификация заголовков:** Nginx добавляет служебные заголовки:
   - `Host $host` — сохранение оригинального имени хоста, необходимого Grafana для валидации источника и генерации ссылок.
   - `X-Real-IP $remote_addr` и `X-Forwarded-For $proxy_add_x_forwarded_for` — фиксация клиентского IP для логов и подсистем безопасности Grafana.
   - `X-Forwarded-Proto $scheme` — указание исходного протокола (HTTPS), без которого Grafana не устанавливает флаг `Secure` на сессионные cookie и пытается выполнить циклический редирект на HTTP.
5. **Проксирование и upstream keepalive:** Nginx выбирает узел из пула `upstream` (по алгоритму `least_conn` или `round-robin`) и передаёт запрос через переиспользуемый сокет пула `keepalive`.
6. **Обработка в Grafana:** Экземпляр Grafana извлекает сессию пользователя из общей БД (PostgreSQL/MySQL), исполняет запрос и формирует ответ.
7. **Возврат клиенту:** Nginx передаёт ответ клиенту, внедряя настроенные заголовки безопасности (`HSTS`, `nosniff`).

### Специфика долгоживущих соединений и WebSocket

Grafana использует два типа долгоживущих HTTP/TCP-взаимодействий:

*   **Grafana Live (WebSocket):** Клиент держит постоянное полнодуплексное соединение для приёма push-уведомлений и потоковых графиков. Соединение начинается со стандартного HTTP-запроса с заголовками `Upgrade: websocket` и `Connection: Upgrade`. Прокси обязан передать эти заголовки на бэкенд, иначе апгрейд протокола будет сброшен с кодом `400 Bad Request`.
*   **Тяжелые запросы Explore и построение панелей:** При выполнении аналитических запросов к медленным или нагруженным источникам данных (Loki, Elasticsearch, ClickHouse) соединение может ожидать ответа десятки секунд. Стандартный таймаут Nginx `proxy_read_timeout 60s` приводит к ошибкам `504 Gateway Time-out`. Значение должно быть увеличено минимум до `310s`.

> **Важно: взаимодействие Upstream Keepalive и WebSocket:**  
> Для работы пула `keepalive` с бэкендами Nginx требует директивы `proxy_http_version 1.1;` и очистки заголовка соединения: `proxy_set_header Connection "";`. Если же глобально в блоке `server` установить `proxy_set_header Connection $connection_upgrade;`, где маппинг возвращает `close` для обычных запросов, Nginx будет закрывать соединение с бэкендом после каждого HTTP-запроса, полностью отключая keepalive.  
> Рекомендуемый подход в production — разделять конфигурацию: для эндпоинта `/api/live/` задавать параметры WebSocket, а для общего location `/` сохранять активный `keepalive`.

### Конфигурация Grafana для работы за обратным прокси

Grafana генерирует ссылки, пути редиректов и параметры cookie на основе собственной конфигурации в `/etc/grafana/grafana.ini` (секция `[server]`):

*   `domain` — доменное имя, по которому пользователи обращаются к Nginx (например, `grafana.example.internal`).
*   `root_url` — полный публичный URL с указанием схемы и завершающего слэша (например, `https://grafana.example.internal/` или `https://example.internal/grafana/`).
*   `serve_from_sub_path` — флаг (`true`/`false`), указывающий Grafana, что внутренний маршрутизатор должен учитывать префикс подпути.
*   `enforce_domain` — принудительный редирект, если клиент обратился по IP-адресу или по несовпадающему доменному имени.

---

## Практические сценарии

### Предварительные требования

| Компонент | Требование | Назначение / Обоснование |
| :--- | :--- | :--- |
| **Операционная система** | Debian 12 / Ubuntu 22.04, 24.04 / RHEL 9, Rocky Linux 9 | Стандартные дистрибутивы Linux без привязки к облачным платформам |
| **Nginx** | Версия 1.26+ (Stable) или 1.28+ (Mainline) | Поддержка директивы `http2 on;`, пулов `keepalive` и расширенного логирования |
| **Grafana** | 13.2.x (актуальная линия) или 12.4.x (LTS) | OSS или Enterprise, локальная установка через deb/rpm пакеты или бинарный релиз |
| **Сетевой контур** | Порт 80/443 открыт на Nginx; порт 3000 доступен от Nginx к узлам Grafana | Firewall (nftables, iptables или firewalld) настроен на пропуск L7-трафика |
| **Права доступа** | Учётная запись с правами `sudo` | Управление системными службами через systemd и редактирование `/etc/nginx/` |
| **DNS-запись** | A/AAAA-запись `grafana.example.internal` → IP-адрес хоста Nginx | Локальный DNS-сервер (Bind9/Unbound) или `/etc/hosts` для тестовых стендов |

**Проверка исходного состояния системы:**

```bash
# Проверка версии и параметров сборки Nginx
nginx -v
# → nginx version: nginx/1.26.2

# Проверка сетевой доступности Grafana с хоста Nginx
curl -s -i http://127.0.0.1:3000/api/health
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → {"commit":"...","database":"ok","version":"13.2.0"}

# Проверка статуса службы Grafana
systemctl is-active grafana-server
# → active
```

---

### Сценарий 1: Базовый обратный прокси для одиночного узла

Классическая схема развёртывания: Nginx выполняет TLS-терминацию, перенаправляет HTTP на HTTPS, проксирует вызовы к локальному сервису Grafana и обрабатывает WebSocket-трафик Grafana Live.

#### Шаг 1: Конфигурация Nginx

Создайте файл виртуального хоста `/etc/nginx/conf.d/grafana.conf`:

```nginx
# Маппинг заголовков для безопасного переключения протокола WebSocket
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

# HTTP: Безусловный редирект на защищённый протокол HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name grafana.example.internal;

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS: Основной виртуальный хост
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name grafana.example.internal;

    # Пути к сертификатам TLS
    ssl_certificate     /etc/ssl/certs/grafana.example.internal.crt;
    ssl_certificate_key /etc/ssl/private/grafana.example.internal.key;

    # Параметры безопасности TLS (только современные надежные протоколы)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:GrafanaSSL:10m;
    ssl_session_tickets off;

    # Заголовки безопасности браузера
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Базовые параметры проксирования
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Port $server_port;
    proxy_redirect off;

    # Таймауты для тяжелых аналитических выборок и отчетов Explore
    proxy_connect_timeout 5s;
    proxy_send_timeout 310s;
    proxy_read_timeout 310s;

    # Тюнинг буферов для передачи объемных JSON-структур дашбордов
    proxy_buffering on;
    proxy_buffer_size 16k;
    proxy_buffers 8 32k;
    proxy_busy_buffers_size 64k;

    # Выделенный маршрут для WebSocket Grafana Live
    location /api/live/ {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Основной интерфейс и REST API
    location / {
        proxy_pass http://127.0.0.1:3000;
    }
}
```

> **Важно о синтаксисе HTTP/2:**  
> Начиная с Nginx 1.25.1+, параметр `http2` директивы `listen` объявлен устаревшим (`deprecated`) и порождает предупреждение в логах. Современным стандартом является раздельное объявление `listen 443 ssl;` и включение директивы `http2 on;` в контексте блока `server`.

#### Шаг 2: Настройка `grafana.ini`

Отредактируйте `/etc/grafana/grafana.ini` на хосте Grafana:

```ini
[server]
protocol = http
http_addr = 127.0.0.1
http_port = 3000
domain = grafana.example.internal
root_url = https://grafana.example.internal/
enforce_domain = true
enable_gzip = true
```

#### Шаг 3: Валидация и применение

```bash
# Валидация синтаксиса конфигурации Nginx
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Бесшовный reload Nginx
sudo systemctl reload nginx

# Перезапуск службы Grafana для применения параметров root_url
sudo systemctl restart grafana-server

# Проверка редиректа с HTTP на HTTPS
curl -sI http://grafana.example.internal/ | grep -iE "HTTP/|Location"
# → HTTP/1.1 301 Moved Permanently
# → Location: https://grafana.example.internal/

# Проверка ответа защищённого эндпоинта через HTTPS
curl -sI https://grafana.example.internal/api/health
# → HTTP/2 200
# → content-type: application/json
# → strict-transport-security: max-age=31536000; includeSubDomains
```

---

### Сценарий 2: Отказоустойчивый кластер (High Availability Upstream)

Сценарий для высоконагруженных окружений с несколькими активными узлами Grafana (Active-Active), общей базой данных (PostgreSQL) и пулом постоянных соединений `keepalive`.

#### Шаг 1: Конфигурация Nginx с балансировкой

`/etc/nginx/conf.d/grafana-ha.conf`:

```nginx
# Определение пула бэкендов Grafana
upstream grafana_ha_backend {
    # Метод распределения: наименьшее число активных соединений
    least_conn;

    # Узлы кластера с пассивным мониторингом сбоев
    server 10.0.2.11:3000 max_fails=3 fail_timeout=10s;
    server 10.0.2.12:3000 max_fails=3 fail_timeout=10s;
    server 10.0.2.13:3000 max_fails=3 fail_timeout=10s;

    # Пул активных открытых соединений к бэкендам
    keepalive 32;
}

# Маппинг для WebSockets
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name grafana-cluster.example.internal;

    ssl_certificate     /etc/ssl/certs/grafana-cluster.example.internal.crt;
    ssl_certificate_key /etc/ssl/private/grafana-cluster.example.internal.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Общие заголовки проксирования
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Port $server_port;
    proxy_redirect off;

    # Политика автоматического переключения при сбое (Failover)
    proxy_next_upstream error timeout invalid_header http_500 http_502 http_503 http_504;
    proxy_next_upstream_tries 3;
    proxy_next_upstream_timeout 10s;

    # WebSocket-маршрут к кластеру Grafana Live
    location /api/live/ {
        proxy_pass http://grafana_ha_backend;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
    }

    # Основной трафик с активным upstream keepalive
    location / {
        proxy_pass http://grafana_ha_backend;

        # Очистка заголовка Connection обязательна для работы keepalive к upstream
        proxy_set_header Connection "";

        proxy_read_timeout 310s;
        proxy_connect_timeout 5s;

        proxy_buffers 8 32k;
        proxy_buffer_size 64k;
    }
}
```

#### Шаг 2: Требования к конфигурации узлов Grafana в кластере

На **каждом** узле кластера (`10.0.2.11`, `10.0.2.12`, `10.0.2.13`) в файле `grafana.ini`:

1. Подключение к общей СУБД (PostgreSQL/MySQL):
   ```ini
   [database]
   type = postgres
   host = postgres-lb.example.internal:5432
   name = grafana
   user = grafana_user
   password = SecretDbPassword123
   ```
2. Синхронизированный ключ шифрования секретов источников (обязан быть идентичным!):
   ```ini
   [security]
   secret_key = SuperSecretClusterEncryptionKeySynchronizedAcrossAllNodes
   ```
3. Единый внешний адрес и шина для Grafana Live:
   ```ini
   [server]
   domain = grafana-cluster.example.internal
   root_url = https://grafana-cluster.example.internal/

   [live]
   ha_engine = redis
   ha_engine_address = redis-ha.example.internal:6379
   ```

#### Шаг 3: Проверка балансировки и отказоустойчивости

```bash
# Тест балансировки запросов (должны отвечать разные узлы кластера)
for i in {1..6}; do
    curl -s -i https://grafana-cluster.example.internal/api/health | grep -i "date"
done

# Проверка активных соединений пула keepalive с хоста Nginx
ss -tnp '( dport = :3000 )'
# → ESTAB 0 0 10.0.2.1:54320 10.0.2.11:3000 users:(("nginx",pid=1234,fd=12))
# → ESTAB 0 0 10.0.2.1:54322 10.0.2.12:3000 users:(("nginx",pid=1234,fd=13))
# → ESTAB 0 0 10.0.2.1:54324 10.0.2.13:3000 users:(("nginx",pid=1234,fd=14))
```

---

### Сценарий 3: Размещение Grafana в подпути (Sub-path)

Используется, когда домен разделяется между несколькими приложениями, и Grafana должна открываться по адресу `https://portal.example.internal/grafana/`.

#### Шаг 1: Конфигурация Nginx

Фрагмент конфигурации виртуального хоста `/etc/nginx/conf.d/portal.conf`:

```nginx
# Обязательный редирект с адреса без слэша на адрес со слэшем
location = /grafana {
    return 301 https://$host/grafana/;
}

# Обработка WebSocket внутри подпути
location /grafana/api/live/ {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
}

# Основная локация подпути Grafana
location /grafana/ {
    # Внимание: URI в proxy_pass НЕ указывается!
    # Nginx передает запрос '/grafana/...' как есть, поскольку Grafana сама знает свой подпуть.
    proxy_pass http://127.0.0.1:3000;

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Port $server_port;

    # Запрет переписывания заголовков Location от Grafana
    proxy_redirect off;

    proxy_read_timeout 310s;
    proxy_buffers 8 32k;
    proxy_buffer_size 64k;
}
```

> **Архитектурный принцип согласования путей:**  
> Когда в `grafana.ini` включён параметр `serve_from_sub_path = true`, встроенный маршрутизатор Grafana ожидает запросы, начинающиеся с `/grafana/...`.  
> Если в Nginx ошибочно указать завершающий слэш в `proxy_pass` (`proxy_pass http://127.0.0.1:3000/;`), Nginx удалит префикс `/grafana/` и передаст в Grafana корень `/`. В результате Grafana вернёт циклический редирект или ошибку `404 Not Found`.

#### Шаг 2: Настройка `grafana.ini` для подпути

```ini
[server]
domain = portal.example.internal
root_url = https://portal.example.internal/grafana/
serve_from_sub_path = true
```

#### Шаг 3: Валидация

```bash
# Проверка редиректа с /grafana на /grafana/
curl -sI https://portal.example.internal/grafana | grep -iE "HTTP/|Location"
# → HTTP/2 301
# → location: https://portal.example.internal/grafana/

# Проверка доступности API через подпуть
curl -sI https://portal.example.internal/grafana/api/health
# → HTTP/2 200
# → content-type: application/json
```

---

### Сценарий 4: Аутентификация через Auth Proxy (SSO на уровне прокси)

Сценарий делегирования аутентификации: Nginx проверяет права пользователя (например, через mTLS-сертификат, внешний сервис через `auth_request` или Basic Auth) и передаёт логин и роль в HTTP-заголовках на бэкенд Grafana.

#### Шаг 1: Конфигурация Nginx

```nginx
server {
    listen 443 ssl;
    server_name grafana-sso.example.internal;

    ssl_certificate     /etc/ssl/certs/grafana-sso.crt;
    ssl_certificate_key /etc/ssl/private/grafana-sso.key;

    # Пример проверки через внутренний auth-эндпоинт компании
    location = /internal_auth {
        internal;
        proxy_pass http://10.0.1.50:8080/verify_session;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
    }

    location / {
        # Делегирование проверки внешнему модулю
        auth_request /internal_auth;

        # Извлечение данных пользователя из ответа auth-сервиса
        auth_request_set $auth_user $upstream_http_x_user_login;
        auth_request_set $auth_role $upstream_http_x_user_role;
        auth_request_set $auth_email $upstream_http_x_user_email;

        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Передача доверенных заголовков аутентификации в Grafana
        proxy_set_header X-WEBAUTH-USER $auth_user;
        proxy_set_header X-WEBAUTH-ROLE $auth_role;
        proxy_set_header X-WEBAUTH-EMAIL $auth_email;

        # Безопасность: очистка клиентских заголовков при неавторизованном запросе
        proxy_set_header Authorization "";
    }
}
```

#### Шаг 2: Настройка Grafana Auth Proxy (`grafana.ini`)

```ini
[server]
domain = grafana-sso.example.internal
root_url = https://grafana-sso.example.internal/

[auth.proxy]
enabled = true
header_name = X-WEBAUTH-USER
header_property = username
auto_sign_up = true
sync_ttl = 60

# Маппинг дополнительных атрибутов пользователя
headers = Role:X-WEBAUTH-ROLE Email:X-WEBAUTH-EMAIL

# КРИТИЧЕСКИ ВАЖНО: список доверенных IP-адресов, от которых принимаются заголовки!
# Запросы с заголовком X-WEBAUTH-USER от любых других IP будут отвергнуты.
whitelist = 127.0.0.1, 10.0.2.1
```

#### Шаг 3: Валидация

```bash
# Тестовый запрос через прокси с эмуляцией заголовков auth-сервиса
curl -s -H "X-WEBAUTH-USER: alexey" \
     -H "X-WEBAUTH-ROLE: Editor" \
     -H "X-WEBAUTH-EMAIL: alexey@example.internal" \
     http://127.0.0.1:3000/api/user
# → {"id":2,"email":"alexey@example.internal","name":"","login":"alexey","theme":"","orgId":1,"isGrafanaAdmin":false,"isDisabled":false,"isExternal":true,"updatedAt":"..."}
```

---

### Сценарий 5: Защита периметра (IP-Allowlist и Rate Limiting)

Защита панели управления и служебных интерфейсов от подбора паролей, сканирования и несанкционированного доступа из внешней сети.

#### Конфигурация Nginx

`/etc/nginx/conf.d/grafana-security.conf`:

```nginx
# Ограничение частоты запросов к форме аутентификации (10 запросов в минуту с одного IP)
limit_req_zone $binary_remote_addr zone=grafana_login_limit:10m rate=10r/m;

# Ограничение параллельных соединений с одного адреса
limit_conn_zone $binary_remote_addr zone=grafana_conn_limit:10m;

server {
    listen 443 ssl;
    http2 on;
    server_name grafana-secure.example.internal;

    ssl_certificate     /etc/ssl/certs/grafana.crt;
    ssl_certificate_key /etc/ssl/private/grafana.key;

    # Защита от перебора паролей на странице логина
    location = /login {
        limit_req zone=grafana_login_limit burst=5 nodelay;
        limit_conn grafana_conn_limit 10;

        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Ограничение доступа к системному API метрик и администрирования
    location ^~ /api/admin/ {
        # Доступ разрешен только инженерам из доверенной management-подсети
        allow 10.0.100.0/24;
        allow 127.0.0.1;
        deny all;

        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Основная локация
    location / {
        limit_conn grafana_conn_limit 25;

        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Валидация правил фильтрации

```bash
# Проверка доступа к /api/admin/ из запрещенного IP-адреса
curl -sI https://grafana-secure.example.internal/api/admin/settings
# → HTTP/2 403
# → content-type: text/html

# Проверка срабатывания rate limiting при частых запросах к /login
for i in {1..8}; do
    curl -s -o /dev/null -w "%{http_code}\n" https://grafana-secure.example.internal/login
done
# → 200
# → 200
# → 200
# → 200
# → 200
# → 200
# → 503
# → 503
```

---

### Сценарий 6: Развёртывание на Bare-Metal и системная интеграция systemd

На production-серверах Nginx и Grafana управляются через systemd с настройкой повышенных лимитов файловых дескрипторов для поддержки тысяч одновременных WebSocket-соединений.

#### Шаг 1: Системные лимиты дескрипторов (systemd override)

Создайте оверрайд конфигурации службы Nginx `/etc/systemd/system/nginx.service.d/limits.conf`:

```ini
[Service]
LimitNOFILE=65536
```

Примените изменения:

```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx

# Проверка примененных лимитов у запущенного процесса Nginx
cat /proc/$(pgrep -o nginx)/limits | grep "Max open files"
# → Max open files            65536                65536                files
```

#### Шаг 2: Настройка параметров воркеров в `nginx.conf`

В секциях `main` и `events` `/etc/nginx/nginx.conf`:

```nginx
worker_processes auto;
worker_rlimit_nofile 65536;

events {
    worker_connections 8192;
    use epoll;
    multi_accept on;
}
```

---

### Сценарий 7: Мониторинг прокси и экспорт метрик в Prometheus

Сбор оперативных метрик производительности и сетевых подключений Nginx для последующей визуализации в самой Grafana.

#### Конфигурация локального эндпоинта stub_status

`/etc/nginx/conf.d/status.conf`:

```nginx
server {
    listen 127.0.0.1:8080;
    server_name 127.0.0.1;

    location = /nginx_status {
        stub_status;
        allow 127.0.0.1;
        deny all;
        access_log off;
    }
}
```

Проверка вывода метрик:

```bash
curl -s http://127.0.0.1:8080/nginx_status
# → Active connections: 5
# → server accepts handled requests
# →  1420 1420 3890
# → Reading: 0 Writing: 2 Waiting: 3
```

#### Скрипт сборщика метрик для Prometheus Node Exporter

Создайте скрипт `/usr/local/bin/nginx-status-collector.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

STATUS_URL="http://127.0.0.1:8080/nginx_status"
OUTPUT_FILE="/var/lib/node_exporter/textfile_collector/nginx_proxy.prom"
TMP_FILE="${OUTPUT_FILE}.$$"

RAW_DATA=$(curl -fsS "$STATUS_URL")

ACTIVE=$(echo "$RAW_DATA" | awk '/Active connections:/ {print $3}')
READING=$(echo "$RAW_DATA" | awk '/Reading:/ {print $2}')
WRITING=$(echo "$RAW_DATA" | awk '/Writing:/ {print $4}')
WAITING=$(echo "$RAW_DATA" | awk '/Waiting:/ {print $6}')

cat <<EOF > "$TMP_FILE"
# HELP nginx_active_connections Current number of active client connections
# TYPE nginx_active_connections gauge
nginx_active_connections $ACTIVE
# HELP nginx_reading_connections Connections where Nginx is reading request header
# TYPE nginx_reading_connections gauge
nginx_reading_connections $READING
# HELP nginx_writing_connections Connections where Nginx is writing response back to client
# TYPE nginx_writing_connections gauge
nginx_writing_connections $WRITING
# HELP nginx_waiting_connections Idle client connections waiting for request
# TYPE nginx_waiting_connections gauge
nginx_waiting_connections $WAITING
EOF

mv "$TMP_FILE" "$OUTPUT_FILE"
```

Сделайте скрипт исполняемым и добавьте таймер systemd:

```bash
sudo chmod +x /usr/local/bin/nginx-status-collector.sh
```

`/etc/systemd/system/nginx-metrics.service`:

```ini
[Unit]
Description=Collect Nginx stub_status metrics for Prometheus
After=network.target nginx.service

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/bin/nginx-status-collector.sh
```

`/etc/systemd/system/nginx-metrics.timer`:

```ini
[Unit]
Description=Run Nginx metrics collector every 15 seconds

[Timer]
OnBootSec=1min
OnUnitActiveSec=15s
AccuracySec=1s

[Install]
WantedBy=timers.target
```

Активация таймера:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nginx-metrics.timer

# Проверка наличия собранных метрик
cat /var/lib/node_exporter/textfile_collector/nginx_proxy.prom
# → nginx_active_connections 5
# → nginx_reading_connections 0
# → nginx_writing_connections 2
# → nginx_waiting_connections 3
```

---

### Сценарий 8: Эксплуатационные процедуры (Graceful Reload, Ротация и Откат)

#### 1. Бесшовное применение изменений конфигурации (Graceful Reload)

При изменении настроек upstream или правил маршрутизации нельзя перезапускать сервис командой `systemctl restart nginx`, так как это приведет к обрыву активных сессий Grafana Live:

```bash
# 1. Обязательная предварительная проверка синтаксиса
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Плавная перезагрузка воркеров (старые воркеры дообслуживают WebSocket, новые принимают трафик)
sudo systemctl reload nginx

# 3. Проверка статуса службы
systemctl is-active nginx
# → active
```

#### 2. Настройка ротации журналов доступа (`logrotate`)

`/etc/logrotate.d/nginx`:

```ini
/var/log/nginx/*log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    prerotate
        if [ -d /etc/logrotate.d/httpd-prerotate ]; then \
            run-parts /etc/logrotate.d/httpd-prerotate; \
        fi \
    endscript
    postrotate
        invoke-rc.d nginx rotate >/dev/null 2>&1
    endscript
}
```

#### 3. Процедура отката конфигурации (Rollback)

В случае обнаружения деградации после reload:

```bash
# 1. Восстановление резервной копии конфигурации
sudo cp /etc/nginx/conf.d/grafana.conf.bak /etc/nginx/conf.d/grafana.conf

# 2. Проверка валидности
sudo nginx -t

# 3. Применение рабочей конфигурации
sudo systemctl reload nginx
```

---

## Операции и команды

### Управление Nginx

| Действие | Команда | Назначение |
| :--- | :--- | :--- |
| **Проверка синтаксиса** | `sudo nginx -t` | Валидация всех подключенных конфигурационных файлов |
| **Плавный перезапуск (Reload)** | `sudo systemctl reload nginx` | Применение новых конфигов без сброса TCP/WebSocket-соединений |
| **Статус процесса** | `sudo systemctl status nginx` | Проверка времени аптайма и PID master/worker |
| **Проверка открытых портов** | `ss -tlnp \| grep nginx` | Проверка привязки портов 80, 443 к процессам Nginx |
| **Просмотр загруженных модулей** | `nginx -V 2>&1 \| tr ' ' '\n' \| grep _module` | Список модулей, собранных в текущий бинарный файл |

### Диагностика сетевых соединений и Upstream

```bash
# Подсчет активных WebSocket-соединений к Grafana (порт 3000)
ss -tnp '( dport = :3000 )' | grep ESTAB | wc -l
# → 42

# Мониторинг времени ответа апстрима в реальном времени (лог должен содержать $upstream_response_time)
tail -f /var/log/nginx/access.log | awk '{print $7, "HTTP-"$9, "RespTime="$NF}'
# → /api/datasources/proxy/1/api/v1/query_range HTTP-200 RespTime=0.342
# → /api/live/ws HTTP-101 RespTime=3600.120

# Проверка регистрации ошибок обрыва соединения со стороны бэкенда
grep -iE "upstream timed out|connection refused" /var/log/nginx/error.log | tail -n 5
# → 2026/09/22 14:10:05 [error] 1234#1234: *567 upstream timed out (110: Connection timed out) while reading response header from upstream, client: 10.0.1.5, server: grafana.example.internal, request: "GET /api/datasources/proxy/1/query HTTP/2.0", upstream: "http://10.0.2.11:3000/api/datasources/proxy/1/query"
```

---

## Диагностика и устранение неисправностей

| Симптом / Ошибка в логах | Первопричина | Метод локализации и устранение |
| :--- | :--- | :--- |
| `502 Bad Gateway` в браузере; в error.log: `connect() failed (111: Connection refused)` | Служба `grafana-server` не запущена, либо локальный firewall блокирует порт 3000. | 1. Проверить статус службы: `systemctl status grafana-server`.<br>2. Проверить прослушивание порта: `ss -tlnp \| grep 3000`.<br>3. Убедиться, что `http_addr` в `grafana.ini` разрешает входящие соединения от Nginx. |
| `504 Gateway Time-out` на тяжелых запросах Explore или дашбордах с сотнями графиков | Запрос к источнику данных выполняется дольше, чем `proxy_read_timeout` в Nginx (по умолчанию 60s). | Увеличить `proxy_read_timeout` до `310s` (или `600s`) в блоке `location /`. Проверить производительность бэкенд-хранилища метрик (Loki, Prometheus). |
| `WebSocket connection failed: Error during WebSocket handshake: Unexpected response code: 400` | Nginx не передает заголовки `Upgrade` и `Connection` на эндпоинт `/api/live/`. | 1. Убедиться в наличии блока `map $http_upgrade $connection_upgrade`.<br>2. Добавить явный блок `location /api/live/` с директивами `proxy_set_header Upgrade $http_upgrade;` и `proxy_set_header Connection $connection_upgrade;`. |
| `Origin not allowed` в консоли браузера при попытке подключения Grafana Live | Заголовок `Host`, переданный Nginx, не совпадает со значением параметра `domain` в `grafana.ini`. | Проверить соответствие: `server_name` в Nginx, заголовок `proxy_set_header Host $host;` и параметр `domain` в `grafana.ini` должны содержать одинаковый FQDN. |
| Белый экран и цикличный редирект (301/302 loop) при размещении в подпути (`/grafana/`) | Несовпадение завершающих слэшей в `proxy_pass` при активном параметре `serve_from_sub_path = true`. | При `serve_from_sub_path = true` Nginx **не должен** удалять префикс. Замените `proxy_pass http://127.0.0.1:3000/;` на `proxy_pass http://127.0.0.1:3000;`. |
| Редирект на HTTP вместо HTTPS при переходе по ссылкам внутри Grafana | Отсутствует заголовок `X-Forwarded-Proto $scheme;`, из-за чего Grafana считает внешний протокол незащищенным. | Добавить `proxy_set_header X-Forwarded-Proto $scheme;` и `proxy_redirect off;` в контекст `server` или `location /`. |
| `an upstream response is buffered to a temporary file` в `error.log` | Объем JSON-ответа от Grafana превышает размер оперативных буферов Nginx `proxy_buffers`. | Увеличить буферы в Nginx: `proxy_buffer_size 16k; proxy_buffers 8 32k; proxy_busy_buffers_size 64k;`. |
| Предупреждение Nginx: `the "http2" parameter of the "listen" directive is deprecated` | Использование устаревшего синтаксиса Nginx до версии 1.25.1. | Заменить строку `listen 443 ssl http2;` на раздельные директивы `listen 443 ssl;` и `http2 on;`. |
| `Auth proxy: User not found` / доступ запрещен при включенном `[auth.proxy]` | IP-адрес хоста Nginx отсутствует в белом списке `whitelist` в `grafana.ini`. | В секции `[auth.proxy]` файла `grafana.ini` прописать `whitelist = 127.0.0.1, <IP_NGINX>`. |
| `worker_connections are not enough while connecting to upstream` | Превышен лимит одновременных сокетов из-за большого числа открытых вкладок с WebSocket. | В `/etc/nginx/nginx.conf` поднять `worker_connections 8192;` и системный лимит `worker_rlimit_nofile 65536;`. |

---

## Рекомендации и лучшие практики

### Безопасность

1. **Изоляция сетевого порта Grafana:** В production Grafana не должна быть доступна извне напрямую в обход Nginx. Задавайте `http_addr = 127.0.0.1` в `grafana.ini` (при размещении на одном хосте) или настраивайте firewall на пропуск порта 3000 только с IP-адресов прокси-серверов.
2. **Только современные протоколы TLS:** Отключайте устаревшие протоколы SSLv3, TLS 1.0 и TLS 1.1. Используйте директиву `ssl_protocols TLSv1.2 TLSv1.3;`.
3. **Защита cookie:** Всегда передавайте `proxy_set_header X-Forwarded-Proto $scheme;`. В сочетании с `cookie_secure = true` в `grafana.ini` это предотвращает перехват сессионных cookie через незащищенный канал.
4. **Защита от внедрения через Auth Proxy:** При использовании режима `[auth.proxy]` строго настраивайте параметр `whitelist = ...` в `grafana.ini` и удаляйте потенциально поддельные клиентские заголовки авторизации в Nginx.
5. **Маскировка версии веб-сервера:** Отключайте вывод версии Nginx в заголовках ответов и на страницах ошибок: `server_tokens off;` в контексте `http`.

### Производительность и оптимизация

6. **Использование Upstream Keepalive:** В кластерных развёртываниях обязательно настраивайте блок `upstream` с директивой `keepalive 32;` и передавайте `proxy_set_header Connection "";` для стандартного HTTP-трафика. Это снижает время отклика интерфейса на 15–25% за счет ликвидации лишних фаз TCP handshake.
7. **Раздельная маршрутизация WebSocket:** Направляйте запросы к `/api/live/` в отдельный `location` с таймаутом `3600s`, не увеличивая избыточно глобальный таймаут `proxy_read_timeout` для всех остальных HTTP-эндпоинтов.
8. **Тюнинг буферизации для больших панелей:** Дашборды со множеством панелей могут генерировать единовременные ответы объемом в несколько мегабайт. Значения `proxy_buffers 8 32k;` и `proxy_buffer_size 16k;` избавляют диск от лишних операций ввода-вывода.
9. **Сжатие трафика (Gzip/Brotli):** Рекомендуется оставлять сжатие включенным на стороне Grafana (`enable_gzip = true` в `[server]`), чтобы Nginx проксировал уже сжатый контент без дополнительных затрат процессорного времени фронтенда.

### Эксплуатационная надежность

10. **Хранение конфигураций в системе контроля версий:** Файлы `/etc/nginx/conf.d/grafana.conf` и `/etc/grafana/grafana.ini` должны быть версионированы в Git (через Ansible, SaltStack или Puppet).
11. **Тестирование перед reload:** Автоматизируйте пайплайны деплоя так, чтобы команда `systemctl reload nginx` вызывалась только после успешного завершения `nginx -t`.
12. **Разделение прав на сертификаты:** Файлы закрытых ключей TLS (`privkey.pem`) должны принадлежать суперпользователю `root:root` с правами доступа `0600` или специализированной системной группе прокси-сервера.

---

## Дополнительная информация

### Критические архитектурные ограничения

1. **Запрет директивы `try_files` в корневом location:**  
   В блоке `location /` при проксировании запросов к Grafana **запрещено** использовать директиву `try_files $uri $uri/ =404;`. Поскольку Grafana генерирует весь пользовательский интерфейс динамически через собственный Go-бэкенд, Nginx попытается найти файл на локальной файловой системе прокси и вернет ошибку `404 Not Found`.
2. **Ограничения CSP (Content Security Policy):**  
   Если в Nginx внедряется строгий заголовок `Content-Security-Policy`, он может заблокировать выполнение внешних плагинов и рендеринг панелей Grafana. Безопаснее настраивать CSP штатными средствами Grafana в секции `[security]` (`custom_response_headers`).
3. **Отказоустойчивость Grafana Live в HA:**  
   Если за Nginx работает несколько узлов Grafana, стандартный gossip-механизм Memberlist синхронизирует состояние алертов, но **не синхронизирует** потоки WebSocket Grafana Live. Для работы Grafana Live в кластере обязательно требуется внешний Redis (`[live] ha_engine = redis`).

### См. также

*   **[Обзор Nginx](../Core/nginx_overview.md)** — архитектура, жизненный цикл воркеров, обработка запросов.
*   **[Обзор Grafana](../../../Grafana/grafana_overview.md)** — архитектурные уровни, компоненты, базовая конфигурация.
*   **[Высокая доступность Grafana (HA)](../../../Grafana/high_availability.md)** — построение active-active кластера, SNE, gossip-протокол Memberlist, требования к СУБД.
*   **[Управление пользователями и аутентификация в Grafana](../../../Grafana/grafana_user_management_and_authentication.md)** — детальная настройка Auth Proxy, LDAP, SAML, роли.
*   **[Безопасность и жесткая настройка Grafana](../../../Grafana/grafana_security_hardening.md)** — изоляция сетевого периметра, CSP, HTTPS.
*   **[Настройка виртуальных хостов TLS в Nginx](../Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — генерация параметров Диффи-Хеллмана, современные cipher suites, OCSP Stapling.
*   **[Балансировка нагрузки: практическая конфигурация](../Proxy/Load_Balancing/practical_configuration.md)** — детальный разбор директив `upstream`, алгоритмов и failover.
