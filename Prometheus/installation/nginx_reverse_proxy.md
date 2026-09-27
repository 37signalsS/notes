# Nginx как Reverse Proxy перед Prometheus

## Определения

**Reverse Proxy (Обратный прокси)** — промежуточный сервер, принимающий входящие запросы от клиентов и пересылающий их на backend-серверы. В контексте Prometheus reverse proxy обеспечивает TLS termination, авторизацию, rate limiting и логирование без модификации конфигурации самого Prometheus.

**TLS Termination** — процесс завершения шифрованного SSL/TLS соединения на уровне reverse proxy. Клиент общается с Nginx по HTTPS, а Nginx — с Prometheus по HTTP (внутренняя сеть).

**Rate Limiting** — ограничение количества запросов от клиента за единицу времени. Защита от DoS-атак и чрезмерной нагрузки на Prometheus.

> **См. также:** [Безопасность Prometheus](../security.md) — TLS, Basic Auth, сетевая сегментация; [Установка Prometheus](./prometheus_server_installation.md) — `--web.listen-address=127.0.0.1:9090`.

## Основные концепции

### Зачем нужен reverse proxy

| Задача | Без reverse proxy | С reverse proxy |
|---|---|---|
| **Доступ по HTTPS** | Нужен `web-config.yml` + сертификаты в Prometheus | TLS termination на Nginx |
| **Балансировка (HA)** | Нужен внешний LB | Nginx upstream с балансировкой |
| **Rate Limiting** | Нет в Prometheus | `limit_req_zone` в Nginx |
| **Логирование доступа** | Только логи Prometheus | Полные HTTP-логи Nginx |
| **Базовая авторизация** | `web-config.yml` + bcrypt | `auth_basic` в Nginx |
| **Кэширование** | Нет | `proxy_cache` для статических запросов |

### Архитектура

```
Клиент (Grafana, CI/CD, оператор)
         │
         │ HTTPS (443)
         ▼
    ┌─────────────┐
    │    Nginx     │  TLS termination, Basic Auth, Rate Limiting
    │  (proxy)     │
    └──────┬──────┘
           │ HTTP (127.0.0.1:9090)
           ▼
    ┌─────────────┐
    │  Prometheus  │  --web.listen-address=127.0.0.1:9090
    │  (backend)   │
    └─────────────┘
```

## Практические сценарии

### Сценарий 1: Базовый reverse proxy с Basic Auth

#### 1. Ограничение Prometheus на localhost

Отредактируйте systemd unit Prometheus:

```bash
# Добавьте флаг в ExecStart
--web.listen-address=127.0.0.1:9090
```

Или через drop-in override:

```bash
sudo mkdir -p /etc/systemd/system/prometheus.service.d
sudo tee /etc/systemd/system/prometheus.service.d/proxy.conf <<EOF
[Service]
Environment="ARGS=--web.listen-address=127.0.0.1:9090"
EOF
sudo systemctl daemon-reload && sudo systemctl restart prometheus
```

#### 2. Генерация bcrypt-хеша пароля

```bash
sudo apt install -y apache2-utils
htpasswd -nB admin
# → New password: ********
# → admin:$2y$05$hash...
```

#### 3. Конфигурация Nginx

```nginx
# /etc/nginx/sites-available/prometheus
upstream prometheus_backend {
    server 127.0.0.1:9090;
    keepalive 16;
}

server {
    listen 80;
    server_name prometheus.corp.local;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name prometheus.corp.local;

    ssl_certificate     /etc/nginx/ssl/prometheus.crt;
    ssl_certificate_key /etc/nginx/ssl/prometheus.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Basic Auth
    auth_basic "Prometheus";
    auth_basic_user_file /etc/nginx/.htpasswd;

    # Rate Limiting
    limit_req_zone $binary_remote_addr zone=prometheus:10m rate=10r/s;

    location / {
        limit_req zone=prometheus burst=20 nodelay;

        proxy_pass http://prometheus_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Таймауты
        proxy_connect_timeout 10s;
        proxy_read_timeout 120s;    # PromQL-запросы могут быть долгими
        proxy_send_timeout 10s;

        # Буферизация
        proxy_buffering on;
        proxy_buffer_size 16k;
        proxy_buffers 4 32k;
    }

    # Доступ к /-/healthy без авторизации (для healthcheck)
    location = /-/healthy {
        auth_basic off;
        proxy_pass http://prometheus_backend;
    }

    # Доступ к /-/reload только с локального хоста
    location = /-/reload {
        allow 127.0.0.1;
        deny all;
        proxy_pass http://prometheus_backend;
    }
}
```

#### 4. Активация и проверка

```bash
# Символическая ссылка
sudo ln -s /etc/nginx/sites-available/prometheus /etc/nginx/sites-enabled/
sudo nginx -t
# → syntax is ok
# → test is successful

# Перезапуск
sudo systemctl reload nginx

# Проверка (без авторизации — должен вернуть 401)
curl -kI https://prometheus.corp.local/graph
# → HTTP/2 401

# Проверка (с авторизацией)
curl -k -u admin:password https://prometheus.corp.local/api/v1/status/flags
# → {"status":"success",...}
```

### Сценарий 2: Reverse proxy для Alertmanager

```nginx
# /etc/nginx/sites-available/alertmanager
upstream alertmanager_backend {
    server 127.0.0.1:9093;
    keepalive 4;
}

server {
    listen 443 ssl http2;
    server_name alertmanager.corp.local;

    ssl_certificate     /etc/nginx/ssl/alertmanager.crt;
    ssl_certificate_key /etc/nginx/ssl/alertmanager.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    auth_basic "Alertmanager";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://alertmanager_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Важно: long polling для等候 алертов
        proxy_read_timeout 300s;
    }

    # Здоровье без авторизации
    location = /-/healthy {
        auth_basic off;
        proxy_pass http://alertmanager_backend;
    }
}
```

### Сценарий 3: Балансировка HA Prometheus

При HA-конфигурации (два Prometheus) Nginx может балансировать запросы:

```nginx
upstream prometheus_ha {
    least_conn;
    server 10.0.0.1:9090;
    server 10.0.0.2:9090;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name prometheus.corp.local;

    ssl_certificate     /etc/nginx/ssl/prometheus.crt;
    ssl_certificate_key /etc/nginx/ssl/prometheus.key;

    auth_basic "Prometheus";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://prometheus_ha;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }
}
```

### Сценарий 4: Reverse proxy для Pushgateway

```nginx
upstream pushgateway_backend {
    server 127.0.0.1:9091;
}

server {
    listen 443 ssl http2;
    server_name pushgateway.corp.local;

    ssl_certificate     /etc/nginx/ssl/pushgateway.crt;
    ssl_certificate_key /etc/nginx/ssl/pushgateway.key;

    # Pushgateway требует авторизации для записи
    location /metrics/job/ {
        auth_basic "Pushgateway";
        auth_basic_user_file /etc/nginx/.htpasswd_pushgateway;
        proxy_pass http://pushgateway_backend;
    }

    # Чтение метрик — только для Prometheus
    location /metrics {
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://pushgateway_backend;
    }

    location /-/healthy {
        auth_basic off;
        proxy_pass http://pushgateway_backend;
    }
}
```

## Дополнительная информация

### Диагностика

| Проблема | Причина | Решение |
|---|---|---|
| `502 Bad Gateway` | Prometheus не запущен или порт неверный | `curl http://127.0.0.1:9090/-/healthy`, проверить `ss -tlnp \| grep 9090` |
| `401 Unauthorized` | Неверный пароль или отсутствует `.htpasswd` | Проверить `htpasswd -v /etc/nginx/.htpasswd admin` |
| `504 Gateway Timeout` | PromQL-запрос слишком долгий | Увеличить `proxy_read_timeout`, проверить `--query.timeout` в Prometheus |
| `413 Request Entity Too Large` | Большой POST-запрос (alerts) | Увеличить `client_max_body_size` в Nginx |
| `SSL handshake failed` | Проблема с сертификатом | Проверить `nginx -t`, срок действия сертификата |

### Рекомендации SRE

1. **Всегда используйте reverse proxy** — никогда не открывайте порт 9090/9093 напрямую в production.
2. **Отключайте Basic Auth на `/-/healthy`** — это необходимо для внешних healthcheck'ов.
3. **Ограничивайте `/-/reload`** — только с localhost или jump-hosts.
4. **Настройте rate limiting** — минимум 10 req/s с burst 20 для предотвращения DoS.
5. **Логируйте доступ** — настройте access log с IP клиента для аудита.

## См. также

*   **[Безопасность Prometheus](../security.md)** — TLS, Basic Auth, сетевая сегментация.
*   **[Установка Prometheus](./prometheus_server_installation.md)** — `--web.listen-address`.
*   **[HA Setup](./ha_setup.md)** — высокая доступность Prometheus.
