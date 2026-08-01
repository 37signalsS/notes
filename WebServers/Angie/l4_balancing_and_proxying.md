# Балансировка и проксирование L4-трафика (TCP/UDP) в Angie

## Определения

**Модуль `stream` в Angie** — расширение функциональности, предоставляющее возможности балансировки нагрузки и проксирования трафика на транспортном уровне (L4). Он работает напрямую с TCP-сессиями и UDP-пакетами, что позволяет обслуживать протоколы, отличные от HTTP (базы данных, DNS, почтовые серверы, SSH и др.).

### Сравнение L4 и L7 проксирования

| Характеристика | L4 (Transport Layer) | L7 (Application Layer) |
| :--- | :--- | :--- |
| **Уровень модели OSI** | Layer 4 (TCP, UDP) | Layer 7 (HTTP, HTTPS, gRPC) |
| **Единица обработки** | Сессия или пакет | Запрос и ответ |
| **Разбор содержимого** | Отсутствует (кроме TLS SNI/ALPN) | Полный (заголовки, куки, тело) |
| **Накладные расходы** | Минимальные (высокая производительность) | Более высокие (анализ прикладного уровня) |
| **Возможности** | Балансировка, ограничение соединений | Кэширование, модификация URI, WAF |

**Ключевые преимущества Angie для L4:**
*   **Active Health Checks:** встроенные активные проверки состояния для TCP/UDP бэкендов.
*   **Status Zones:** сбор детальной статистики для каждой службы и группы серверов.
*   **Slow Start:** плавное наращивание нагрузки на восстановленные бэкенды.
*   **Dynamic API:** изменение параметров `upstream` (веса, статус) без перезагрузки.

## Основные концепции

### Совместимость и SSoT

Angie полностью сохраняет синтаксис и логику работы модуля `stream`, унаследованные от Nginx. Базовые директивы (`server`, `proxy_pass`, `ssl_preread`) работают идентично.

**SSoT (Единый источник истины) для базовой логики:**
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

Директива `status_zone` активирует сбор метрик в разделяемой памяти. В модуле `stream` её можно использовать в двух местах:

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

## Практические сценарии

### 1. Отказоустойчивая балансировка PostgreSQL с Proxy Protocol

Использование `proxy_protocol` позволяет передать реальный IP-адрес клиента на бэкенд базы данных, а `slow_start` защищает сервер от перегрузки при включении.

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

### 2. Разделение HTTPS и SSH на одном порту (SSL Pre-read)

Angie анализирует первые байты соединения для определения протокола без расшифровки трафика.

```nginx
map $ssl_preread_protocol $target_backend {
    "TLSv1.2"  https_cluster;
    "TLSv1.3"  https_cluster;
    default    ssh_local;
}

upstream https_cluster { server 127.0.0.1:4430; }
upstream ssh_local     { server 127.0.0.1:22; }

server {
    listen 443;
    ssl_preread on; # Активация анализа начала сессии
    proxy_pass $target_backend;
    
    status_zone port_multiplexer;
}
```

### 3. Высокопроизводительный DNS-прокси (UDP)

При работе с UDP критически важно правильно настроить количество ожидаемых ответов и интервалы ожидания.

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

### Динамическое управление через API

Angie предоставляет HTTP API для управления L4-апстримами в реальном времени. Это позволяет:
*   Временно вывести сервер из балансировки (`drain: true`).
*   Изменить вес сервера (`weight`).
*   Посмотреть детальную статистику в JSON.

**Пример получения статистики через curl:**
```bash
curl http://localhost:8080/api/v1/stream/upstreams/postgres_backend
```

### Ограничение ресурсов

Для защиты от злоупотреблений используйте `limit_conn`. Важно помнить, что в L4 невозможно использовать `limit_req`, так как сервер не видит отдельных HTTP-запросов.

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
*   **[Руководство по Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md)** — детали работы протокола.
