# Балансировка и проксирование L4-трафика (TCP/UDP) в Angie

## Определения

**Модуль `stream` в Angie** — расширение функциональности, предоставляющее возможности балансировки нагрузки и проксирования трафика на транспортном уровне (L4). Он работает напрямую с TCP-сессиями и UDP-пакетами, что позволяет обслуживать протоколы, отличные от HTTP (базы данных, DNS, почтовые серверы, SSH, MQTT и др.).

### Сравнение L4 и L7 проксирования

| Характеристика | L4 (Transport Layer) | L7 (Application Layer) |
| :--- | :--- | :--- |
| **Уровень модели OSI** | Layer 4 (TCP, UDP) | Layer 7 (HTTP, HTTPS, gRPC) |
| **Единица обработки** | Сессия или пакет | Запрос и ответ |
| **Разбор содержимого** | Отсутствует (кроме TLS SNI/ALPN) | Полный (заголовки, куки, тело) |
| **Накладные расходы** | Минимальные (высокая производительность) | Более высокие (анализ прикладного уровня) |
| **Возможности** | Балансировка, ограничение соединений | Кэширование, модификация URI, WAF |

**Ключевые преимущества Angie для L4:**
*   **Status Zones:** сбор детальной статистики для каждой службы и группы серверов (доступно в OSS).
*   **Active Health Checks (PRO):** встроенные активные проверки состояния (TCP/UDP).
*   **Slow Start:** плавное наращивание нагрузки на восстановленные бэкенды.
*   **MQTT Preread:** извлечение ClientID и Username из MQTT-пакетов (с версии 1.4.0).
*   **Docker Discovery:** автоматическое обнаружение бэкендов через Docker API (с версии 1.10.0).
*   **Dynamic API (PRO):** изменение параметров `upstream` без перезагрузки.

## Основные концепции

### Взаимосвязь и совместимость с Nginx

Angie полностью сохраняет синтаксис и логику работы модуля `stream`, унаследованные от Nginx. Базовые директивы (`server`, `proxy_pass`, `ssl_preread`) работают идентично.

**Базовая логика и стандарты:**
*   **[Балансировка и проксирование L4 в Nginx](../Nginx/Proxy/nginx_l4_proxying.md)** — алгоритмы, таймауты и стандартные сценарии.

### Структура конфигурации

Блок `stream` располагается на верхнем уровне `angie.conf`, вне контекста `http`.

```nginx
# /etc/angie/angie.conf
stream {
    # Определение формата логов для сессий
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time "$upstream_addr"';

    access_log /var/log/angie/stream-access.log basic;

    # Инфраструктурные пути в Angie
    include /etc/angie/stream.d/*.conf;
}
```

**Инфраструктурные особенности Angie:**
*   **Конфиги:** `/etc/angie/stream.d/` (рекомендуемая директория для include).
*   **Логи:** `/var/log/angie/stream-access.log` и `stream-error.log`.

### Детальный мониторинг через `status_zone`

Директива `status_zone` активирует сбор метрик в разделяемой памяти. В отличие от Nginx OSS, в Angie этот функционал встроен.

1.  **В блоке `server`:** собирает статистику по входящему порту (количество соединений, принятые/отправленные байты).
2.  **В блоке `upstream`:** собирает статистику по каждому бэкенду (состояние, количество запросов, время ответа, ошибки).

```nginx
stream {
    upstream pg_cluster {
        zone pg_cluster_zone 64k;
        status_zone pg_upstreams; # Статистика группы бэкендов
        
        server 10.0.0.11:5432;
        server 10.0.0.12:5432;
    }

    server {
        listen 5432;
        status_zone pg_frontend; # Статистика слушающего порта
        proxy_pass pg_cluster;
    }
}
```

### Проверки состояния (Health Checks)

**Пассивные проверки (OSS/PRO):**
Реализуются через параметры `max_fails` и `fail_timeout` в директиве `server` внутри `upstream`.

**Активные проверки (Angie PRO):**
Сервер самостоятельно инициирует проверочные соединения. Используется директива `upstream_probe`.

*   `upstream_probe`: настраивает параметры активной проверки.
*   `interval`: интервал между проверками (по умолчанию 5с).
*   `passes` / `fails`: количество успешных/неудачных ответов для смены статуса.

```nginx
# Только в Angie PRO
server {
    listen 12345;
    proxy_pass tcp_backend;
    
    # TCP проверка: простое установление соединения
    upstream_probe name=tcp_check interval=3s passes=2 fails=3 timeout=1s type=tcp;
}
```

### Постоянство сессий (Session Persistence)

На уровне L4 привязка клиента к конкретному серверу осуществляется на основе хэширования параметров соединения.

*   **`hash $remote_addr`**: привязка по IP клиента.
*   **`hash $remote_addr:$remote_port`**: сессионная привязка.
*   **`hash $mqtt_preread_clientid`**: привязка по ID клиента MQTT (требует версии 1.4.0+).

```nginx
upstream sticky_backend {
    zone sticky_zone 64k;
    hash $remote_addr consistent; # Консистентное хэширование
    
    server 10.0.0.31:9000;
    server 10.0.0.32:9000;
}
```

### Терминация SSL/TLS и SSL Pre-read

Модуль `stream` позволяет терминировать защищенные соединения или маршрутизировать их без расшифровки.

```nginx
stream {
    server {
        listen 5432 ssl; # Прием зашифрованных соединений (например, PostgreSQL)
        
        ssl_certificate     /etc/angie/ssl/server.crt;
        ssl_certificate_key /etc/angie/ssl/server.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        
        proxy_pass pg_cluster;
    }
}
```

### Ограничение скорости передачи данных

Angie позволяет ограничивать скорость чтения от сервера и клиента на уровне каждого соединения.

*   `proxy_download_rate`: лимит скорости от бэкенда к клиенту.
*   `proxy_upload_rate`: лимит скорости от клиента к бэкенду.

```nginx
server {
    listen 12345;
    proxy_pass backend_service;
    
    # Ограничение 1 Мбит/с на загрузку и 512 Кбит/с на отдачу
    proxy_download_rate 1m;
    proxy_upload_rate 512k;
}
```

### Архитектура модуля stream и жизненный цикл сессии

Модуль `stream` работает параллельно с `http`, используя отдельные слушатели (listeners) и воркеры. В отличие от L7, здесь нет фазы разбора HTTP-запроса — Angie перехватывает соединение на уровне TCP и перенаправляет его в выбранный `upstream`.

**Компоненты:**
*   **Listener:** Принимает входящие соединения на указанном `ip:port`. Может работать в режимах TCP и UDP.
*   **Upstream:** Именованная группа бэкенд-серверов с алгоритмом балансировки, зоной состояния и параметрами health checks.
*   **Shared Zone:** Область разделяемой памяти, где хранится состояние upstream (активные соединения, веса, метрики) и server_zones (метрики слушателей).
*   **Session Table:** Таблица активных сессий в памяти воркера; используется для таймаутов и ограничений.

**Жизненный цикл TCP-сессии:**
1.  **Accept:** Angie принимает новое TCP-соединение от клиента на слушатель `listen`.
2.  **Pre-read (опционально):** Если включен `ssl_preread` или `mqtt_preread`, Angie анализирует первые байты без расшифровки, чтобы определить протокол или извлечь MQTT ClientID.
3.  **Upstream selection:** Выбирается бэкенд из группы `upstream` согласно алгоритму (Round Robin, Hash, Least Time в stream-контексте).
4.  **Handshake (если TLS):** При `listen ... ssl` выполняется TLS-рукопожатие с клиентом. Для upstream без TLS трафик передается как есть (TCP).
5.  **Proxy:** Данные ретранслируются между клиентом и бэкендом. При `proxy_protocol on` в начало TCP-потока добавляется заголовок с IP/портом клиента.
6.  **Monitoring:** Метрики сессии (байты, длительность, статус) записываются в `server_zone` и `upstream_zone` (если объявлены).
7.  **Close:** При разрыве соединения (по таймауту или явном закрытии) сессия удаляется из таблицы, метрики фиксируются.

Для UDP жизненный цикл аналогичен, но сессия привязана к `proxy_responses` пакетам и `proxy_timeout`.

**Особенности Angie gegenüber Nginx:**
*   Встроенная поддержка `status_zone` в OSS (в Nginx только в commercial subscriptions).
*   Нативный модуль `check` для активных проверок в stream (в Nginx OSS требуется сторонний модуль `upstream_check_module`).
*   Директива `upstream_probe` в PRO поддерживает TCP, UDP и HTTP-проверки для stream.

## Практические сценарии

### 1. Отказоустойчивая балансировка PostgreSQL с Proxy Protocol

Использование `proxy_protocol` позволяет передать реальный IP клиента, а `slow_start` защищает сервер от перегрузки при восстановлении.

```nginx
upstream postgres_backend {
    zone postgres_zone 64k;
    
    # Плавный старт в течение 1 минуты
    server 192.168.1.50:5432 slow_start=60s;
    server 192.168.1.51:5432;
}

server {
    listen 5432;
    proxy_pass postgres_backend;
    
    # Использование Proxy Protocol для передачи IP клиента
    proxy_protocol on;
    
    proxy_connect_timeout 1s;
    proxy_timeout 1h; # Таймаут неактивности сессии
    
    status_zone pg_lb_status;
}
```

### 2. Разделение HTTPS, SSH и MQTT на одном порту

Angie анализирует первые байты соединения для определения протокола без расшифровки трафика.

```nginx
map $ssl_preread_protocol $target_backend {
    "TLSv1.2"  https_cluster;
    "TLSv1.3"  https_cluster;
    default    other_protocols;
}

map $mqtt_preread_clientid $is_mqtt {
    ""      ssh_local;
    default mqtt_cluster;
}

upstream https_cluster { server 127.0.0.1:4430; }
upstream ssh_local     { server 127.0.0.1:22; }
upstream mqtt_cluster  { server 10.0.0.50:1883; }

server {
    listen 443;
    ssl_preread on;
    mqtt_preread on; # Активация разбора MQTT (версия 1.4.0+)
    
    proxy_pass $target_backend;
    
    # Если не TLS, проверяем на MQTT
    status_zone port_multiplexer;
}
```

### 3. Высокопроизводительный DNS-прокси (UDP)

При работе с UDP важно ограничить количество ожидаемых ответов.

```nginx
upstream dns_upstream {
    zone dns_upstream_zone 64k;
    server 8.8.8.8:53;
    server 1.1.1.1:53;
}

server {
    listen 53 udp;
    listen 53; # Поддержка TCP для больших ответов
    
    # Для UDP: ждать 1 ответ и закрыть сессию через 3 секунды
    proxy_responses 1;
    proxy_timeout 3s;
    
    proxy_pass dns_upstream;
    status_zone dns_proxy_status;
}
```

### 4. Проксирование Redis с балансировкой и терминацией TLS

Redis поддерживает как TCP, так и TLS. Angie может терминировать TLS и балансировать между экземплярами Redis Sentinel или Cluster.

```nginx
stream {
    upstream redis_cluster {
        zone redis_zone 64k;
        server 10.0.0.11:6379;
        server 10.0.0.12:6379;
        server 10.0.0.13:6379 backup; # Резервный Sentinel
    }

    server {
        listen 6379 ssl;
        status_zone redis_frontend;

        ssl_certificate     /etc/angie/ssl/redis.crt;
        ssl_certificate_key /etc/angie/ssl/redis.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;

        proxy_pass redis_cluster;
        proxy_timeout 60s;
        proxy_connect_timeout 2s;
    }
}
```

**Валидация:**
```bash
# Проверка TLS-рукопожатия
openssl s_client -connect localhost:6379 -servername redis.example.com
# → Verify return code: 0 (ok)

# Проверка балансировки
redis-cli -h localhost -p 6379 PING
# → PONG
# Повторите несколько раз, убедитесь что ротация работает
```

### 5. Маршрутизация TCP-трафика по SNI без расшифровки

`ssl_preread` анализирует поле SNI в ClientHello и направляет соединение на соответствующий бэкенд, не расшифровывая трафик. Полезно для мультитенантных сред.

```nginx
stream {
    map $ssl_preread_server_name $backend {
        default         tcp_default;
        pg.example.com  pg_cluster;
        redis.example.com redis_cluster;
    }

    upstream pg_cluster     { server 10.0.0.21:5432; server 10.0.0.22:5432; }
    upstream redis_cluster  { server 10.0.0.31:6379; server 10.0.0.32:6379; }
    upstream tcp_default    { server 10.0.0.99:9999; }

    server {
        listen 443;
        status_zone sni_router;
        ssl_preread on;
        proxy_pass $backend;
    }
}
```

**Валидация:**
```bash
# Симуляция клиента с SNI
openssl s_client -connect localhost:443 -servername pg.example.com -brief
# → Проверьте логи: $upstream_addr должен указывать на 10.0.0.21 или 10.0.0.22
```

### 6. Балансировка AMQP/RabbitMQ с ограничением соединений

Для протоколов с длинными соединениями важно ограничивать количество одновременных подключений с одного IP, чтобы предотвратить монополизацию бэкендов.

```nginx
stream {
    limit_conn_zone $binary_remote_addr zone=amqp_conns:10m;

    upstream rabbitmq_cluster {
        zone rabbit_zone 64k;
        server 10.0.0.41:5672 max_conns=200;
        server 10.0.0.42:5672 max_conns=200;
    }

    server {
        listen 5672;
        status_zone amqp_frontend;
        proxy_pass rabbitmq_cluster;
        proxy_timeout 3600s;
        proxy_connect_timeout 5s;

        limit_conn amqp_conns 10;
    }
}
```

**Валидация:**
```bash
# Проверка статуса через API
curl -s http://127.0.0.1/status/stream/upstreams/rabbitmq_cluster/ | jq '.peers[] | {server, active, max_conns}'
# → {"server":"10.0.0.41:5672","active":15,"max_conns":200}
```

## Дополнительная информация

### Динамическое управление апстримами

**В Angie OSS:**
1.  **Docker Discovery:** Angie подключается к Docker API и автоматически наполняет `upstream` серверами на основе меток контейнеров.
    ```nginx
    docker_endpoint unix:/var/run/docker.sock;
    upstream dynamic_app {
        zone dynamic_zone 64k;
    }
    ```
2.  **DNS Resolve:** динамическое разрешение имен через SRV-записи.
    ```nginx
    upstream consul_service {
        zone consul_zone 64k;
        server backend.service.consul service=_api._tcp resolve;
    }
    ```

**В Angie PRO (API):**
Полноценный REST API для управления конфигурацией на лету.

1.  **Получение статистики:**
    ```bash
    curl http://127.0.0.1/status/stream/upstreams/postgres_backend/
    ```

2.  **Вывод сервера на обслуживание (Drain):**
    ```bash
    curl -X PUT -d "drain" \
      http://127.0.0.1/config/stream/upstreams/postgres_backend/servers/0/down
    ```

3.  **Динамическое добавление сервера:**
    ```bash
    curl -X PUT -d '{"server": "192.168.1.55:5432", "weight": 2}' \
      http://127.0.0.1/config/stream/upstreams/postgres_backend/servers/192.168.1.55:5432
    ```

*Примечание:* Для работы API и сохранения состояния после перезагрузки в PRO используется директива `state`.

### Особенности UDP-проверок (PRO)

Для UDP-сервисов активные проверки требуют специфических данных.

```nginx
upstream dns_cluster {
    zone dns_zone 64k;
    server 10.0.0.53:53;
}

server {
    proxy_pass dns_cluster;
    # UDP проверка с ожиданием конкретных данных
    upstream_probe name=dns_check type=udp interval=5s
                   data="\x00\x01\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x03www\x06google\x03com\x00\x00\x01\x00\x01";
}
```

### Ограничение ресурсов

Для защиты от злоупотреблений используйте `limit_conn`.

```nginx
stream {
    limit_conn_zone $binary_remote_addr zone=addr:10m;

    server {
        listen 12345;
        limit_conn addr 5; # Не более 5 соединений с одного IP
        proxy_pass backend_service;
    }
}
```

### См. также

*   **[Обзор архитектуры Angie](./angie_overview.md)** — общие возможности.
*   **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — сравнение с L7.
*   **[Мониторинг Angie: концепции](./angie_monitoring/angie_monitoring_concepts.md)** — подробнее о зонах статуса.

## Операции и команды

### Валидация и управление конфигурацией

```bash
# Проверка синтаксиса stream-блока
angie -t -g "daemon off;"
# → [emerg] ... или silent success

# Проверка только stream-конфигов
angie -t -c /etc/angie/stream.d/*.conf

# Поиск дублирующихся listen
ss -tlnp | grep ':5432'
# → Вывод: angie    LISTEN  0  4096  *:5432
```

### Диагностика соединений

```bash
# Активные TCP-сессии на слушающем порту
ss -tnp | grep ':5432' | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn
# → 45 10.0.0.5
# → 12 10.0.0.6

# Состояние TCP (retransmits, window scale)
ss -ti | grep -E 'angie|bcke' | head -20

# Захват трафика для отладки SNI или Proxy Protocol
tcpdump -i any -nn port 443 -A | head -100
# → Ищите ClientHello с полем server_name (SNI)
```

### Просмотр метрик через API

```bash
# Список всех stream upstream и их состояние
curl -s http://127.0.0.1/status/stream/upstreams/ | jq '.'

# Детали конкретного upstream
curl -s http://127.0.0.1/status/stream/upstreams/postgres_backend/ | jq '.peers[] | {server, state, active, requests, time}'

# Метрики слушающего порта (server_zone)
curl -s http://127.0.0.1/status/stream/server_zones/pg_frontend/ | jq '.'

# Проверка здоровья бэкендов
curl -s http://127.0.0.1/status/stream/upstreams/rabbitmq_cluster/ | jq '.peers[] | {server, state, fails, selected}'
```

### Управление сервисом

| Команда | Назначение |
| :--- | :--- |
| `angie -s reload` | Graceful reload конфигурации без потери соединений |
| `angie -s stop` | Graceful shutdown с ожиданием завершения сессий |
| `systemctl status angie` | Проверка статуса systemd-сервиса |
| `journalctl -u angie -f` | Потоковый просмотр логов |

## Устранение неисправностей

### Клиент не может подключиться к слушающему порту

**Причины:** Слушатель неактивен, firewall блокирует порт, порт занят другим процессом.

**Диагностика:**
```bash
# Проверка что Angie слушает порт
ss -tlnp | grep ':5432'
# → Если пусто — listen не объявлен или порт конфликтует

# Проверка firewall
iptables -L -n | grep 5432
# или
firewall-cmd --list-ports | grep 5432
```

**Решение:** Добавьте `listen` в stream-блок, откройте порт в firewall, убедитесь что порт не занят.

### 502 Bad Gateway при достижении max_conns

**Причина:** Все серверы в upstream достигли лимита одновременных соединений (`max_conns`), очередь отсутствует или переполнена.

**Диагностика:**
```bash
curl -s http://127.0.0.1/status/stream/upstreams/postgres_backend/ | jq '.peers[] | {server, active, max_conns}'
# → {"server":"10.0.0.50:5432","active":100,"max_conns":100}
```

**Решение:** Увеличьте `max_conns`, добавьте резервные серверы (`backup`), настройте очередь в PRO (`queue`).

### Не передается реальный IP клиента через Proxy Protocol

**Причина:** Бэкенд не поддерживает Proxy Protocol или `proxy_protocol` не включен.

**Диагностика:**
```bash
# Проверка что заголовок Proxy Protocol отправляется
tcpdump -i any -nn port 5432 -X | grep -E 'PROXY|10\.0\.0'
```

**Решение:** Включите `proxy_protocol on` на слушателе и настройте бэкенд на прием Proxy Protocol (HAProxy: `accept-proxy`, Envoy: `allow_original_src`).

### Sticky-сессии не работают в модуле stream

**Причина:** В stream нет директивы `sticky`, используется только `hash` с переменной.

**Диагностика:**
```bash
curl -s http://127.0.0.1/status/stream/upstreams/sticky_backend/ | jq '.peers[] | {server, active}'
# → Проверьте распределение active соединений
```

**Решение:** Используйте `hash $remote_addr consistent;` в блоке `upstream`. Для MQTT используйте `hash $mqtt_preread_clientid;`. Проверьте что `zone` объявлена.

### UDP-ответы теряются или таймаутят

**Причина:** Неверный `proxy_responses`, слишком маленький `proxy_timeout`, или бэкенд отправляет несколько ответов.

**Диагностика:**
```bash
# Проверка счетчиков UDP
curl -s http://127.0.0.1/status/stream/upstreams/dns_upstream/ | jq '.peers[] | {server, requests, responses, fails}'
# → requests: 100, responses: 0, fails: 50
```

**Решение:** Установите `proxy_responses 1` для DNS. Увеличьте `proxy_timeout`. Убедитесь что бэкенд не отправляет fragmented ответы.

### Высокий p99 latency при нормальном RPS

**Причина:** TCP retransmits, блокировка `max_conns`, отсутствие keepalive, slow start.

**Диагностика:**
```bash
ss -ti | grep -E 'angie|bcke' | head -20
# → Ищите high retransmit count или zero window

curl -s http://127.0.0.1/status/stream/upstreams/pg_cluster/ | jq '.peers[] | {server, time, inflight}'
# → time выше 500ms при нормальном RTS
```

**Решение:** Проверьте сетевые задержки (`mtr`). Увеличьте `max_conns`. Добавьте `slow_start` для восстановленных бэкендов. Настройте `proxy_connect_timeout`.

## Лучшие практики

### Производительность

*   **Zone sizing:** 64 КБ на 50 серверов, 128 КБ на 100–200. Для тысяч контейнеров используйте `1m`. Без `zone` не работают `status_zone`, `upstream_probe`, `hash` в stream.
*   **Таймауты:** `proxy_connect_timeout` должен быть минимально достаточным (1–5с). `proxy_timeout` для долгоживущих протоколов (Redis, MQTT) — до 1ч.
*   **Slow start:** Всегда используйте `slow_start=30s`–`60s` для восстановленных бэкендов, чтобы защитить «холодный» кэш.
*   **Keepalive в stream:** Не применим напрямую (нет HTTP keepalive), но параметр `proxy_timeout` контролирует длительность TCP-сессии. Для коротких сессий (DNS) — 1–5с, для долгих (базы данных) — до 1ч.
*   **UDP optimization:** Всегда указывайте `proxy_responses 1` для запрос-ответ протоколов (DNS). Для потоковых UDP увеличивайте `proxy_timeout`.

### Безопасность

*   **Ограничение ресурсов:** Используйте `limit_conn_zone` + `limit_conn` для защиты от DDoS и монополизации соединений. Размер зоны: 10м на 10.000 IP.
*   **Proxy Protocol:** Передавайте реальный IP только доверенным хостам. Включите `set_real_ip_from` на слушателе, чтобы предотвратить spoofing.
*   **TLS в stream:** Используйте `ssl_preread on` вместо полной терминации TLS, если бэкенд сам управляет сертификатами. Это снижает накладные расходы.
*   **Доступ к API:** Ограничьте `/status/stream/` и `/config/` только внутренней сетью или management-интерфейсом.

### Эксплуатация

*   **Логирование:** Всегда объявляйте `log_format` в блоке `stream` с `$upstream_addr`, `$session_time`, `$status`. Включайте `access_log` для всех слушателей.
*   **Мониторинг:** Объявляйте `status_zone` на каждом `server` и `upstream`. Настройте алерты на `peers[].state != "up"` и `fails > 0`.
*   **Валидация:** Перед `reload` всегда выполняйте `angie -t`. Используйте `ss`/`tcpdump` для проверки слушателей после реконфигурации.
*   **Резервное копирование:** Сохраняйте `/etc/angie/stream.d/*.conf` и `/var/lib/angie/state/` (PRO) в системе контроля версий или резервной копии.

### Ограничения

*   **Вложенные location:** В модуле `stream` нет блока `location`. Вся логика маршрутизации определяется на уровне `server` и `upstream`.
*   **Переменные в status_zone:** Директива `status_zone` принимает только статическое имя строки, нельзя использовать переменные.
*   **Активные проверки в OSS:** Требуют подгрузки `upstream_check_module`. В PRO используется `upstream_probe`, который проще в настройке.
*   **L7-функции в stream:** Нет доступа к HTTP-заголовкам, Cookie, URI. Для маршрутизации по HTTP-параметрам используйте модуль `http`.
