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
    curl http://localhost:8080/api/v1/stream/upstreams/postgres_backend
    ```

2.  **Вывод сервера на обслуживание (Drain):**
    ```bash
    curl -X PATCH -d '{"drain": true}' \
      http://localhost:8080/api/v1/stream/upstreams/postgres_backend/servers/0
    ```

3.  **Динамическое добавление сервера:**
    ```bash
    curl -X POST -d '{"server": "192.168.1.55:5432", "weight": 2}' \
      http://localhost:8080/api/v1/stream/upstreams/postgres_backend/servers/
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
*   **[Руководство по Proxy Protocol](../../Networking/Protocols/proxy_protocol.md)** — детали работы протокола.
*   **[Логирование в Angie](./angie_logging.md)** — настройка форматов и файлов логов.
