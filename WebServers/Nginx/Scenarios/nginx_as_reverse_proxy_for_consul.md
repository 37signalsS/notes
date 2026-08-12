# Настройка Nginx как обратного прокси для Consul

## 1. Определения

**Nginx в качестве обратного прокси для Consul** — сценарий развёртывания, при котором Nginx выступает единой точкой входа для доступа к веб-интерфейсу (UI) и HTTP API (Application Programming Interface) [Consul](../../../Consul/consul_overview.md). Это обеспечивает SSL/TLS-терминацию, централизованную аутентификацию и сокрытие внутренней инфраструктуры кластера.

*   **[Обратный прокси (Reverse Proxy)](../../../Networking/Concepts/proxy.md)** — сервер-посредник, принимающий запросы от клиентов и распределяющий их между серверами бэкенда.
*   **Consul UI** — графический интерфейс для управления сервисами, узлами, KV-хранилищем и политиками безопасности.
*   **Consul API** — основной интерфейс взаимодействия для Service Discovery и автоматизации (порт `8500` по умолчанию).

## 2. Базовые концепции

Использование Nginx перед Consul решает следующие задачи:

1.  **Терминация SSL/TLS**: Перенос вычислительной нагрузки по шифрованию на Nginx. Это позволяет использовать один сертификат (например, Wildcard или Let's Encrypt) для доступа к консоли управления без необходимости настройки HTTPS на каждом узле Consul.
2.  **Отказоустойчивость**: Nginx может выполнять балансировку между всеми серверами кластера (обычно 3 или 5 узлов), автоматически переключаясь на доступные инстансы при сбоях.
3.  **Усиление безопасности**:
    *   Ограничение доступа к административному API (`/v1/agent/`, `/v1/operator/`) по IP-адресам или через Basic Auth.
    *   Внедрение заголовков безопасности (HSTS, CSP, X-Frame-Options).
    *   Передача токенов доступа ([Consul ACL](../../../Consul/consul_overview.md#безопасность-acl)) через кастомные заголовки.
4.  **Поддержка Long Polling**: Consul активно использует блокирующие запросы (Blocking Queries) для мгновенного получения обновлений. Nginx требует специальной настройки тайм-аутов для поддержки таких соединений.

## 3. Практический сценарий

### 3.1. Предварительные требования

- Наличие работающего кластера Consul (Servers или Clients).
- Сетевой доступ от Nginx к портам `8500` узлов Consul.
- Установленный Nginx версии 1.27+.

### 3.2. Конфигурация Upstream

Для обеспечения высокой доступности и производительности API рекомендуется использовать `keepalive`.

**Пример (`/etc/nginx/conf.d/consul_upstream.conf`):**

```nginx
upstream consul_servers {
    # Поддержание постоянных соединений для снижения задержек API
    keepalive 32;

    # Список узлов кластера Consul
    server 10.0.1.10:8500 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8500 max_fails=3 fail_timeout=10s;
    server 10.0.1.12:8500 max_fails=3 fail_timeout=10s;
}
```

### 3.3. Виртуальный хост с поддержкой Long Polling

Основная сложность при проксировании Consul — необходимость длительного ожидания ответа (до 5-10 минут) при блокирующих запросах API.

**Пример (`/etc/nginx/conf.d/consul.example.com.conf`):**

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name consul.example.com;

    # Редирект на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name consul.example.com;

    # Актуальный синтаксис 1.27+ для HTTP/2
    http2 on;

    ssl_certificate     /etc/letsencrypt/live/consul.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/consul.example.com/privkey.pem;

    # Настройки безопасности TLS
    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    add_header Strict-Transport-Security "max-age=63072000" always;

    # Общие настройки проксирования
    proxy_http_version 1.1;
    proxy_set_header Connection ""; # Необходимо для keepalive
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Оптимизация для Long Polling (Consul Blocking Queries)
    # Consul по умолчанию ждет до 5 минут (300s). Nginx должен ждать чуть дольше.
    proxy_read_timeout 310s;
    proxy_connect_timeout 5s;

    # Обработка UI и API
    location / {
        proxy_pass http://consul_servers;

        # Обработка путей UI: Consul ожидает /ui/
        # Если пользователь зашел на /, перенаправляем в интерфейс
        if ($request_uri = "/") {
            return 301 /ui/;
        }
    }

    # Ограничение доступа к критическому API агента
    location /v1/agent {
        # Разрешить доступ только из внутренней сети управления
        allow 10.0.0.0/24;
        deny all;
        proxy_pass http://consul_servers;
    }

    # Ограничение доступа к API оператора
    location /v1/operator {
        allow 10.0.0.0/24;
        deny all;
        proxy_pass http://consul_servers;
    }
}
```

### 3.4. Проверка и применение

1.  Проверьте синтаксис: `nginx -t`.
2.  Перезагрузите конфигурацию: `systemctl reload nginx`.
3.  Проверьте доступность интерфейса: `https://consul.example.com/ui/`.

## 4. Дополнительная информация

### Проактивная эксплуатация (White spots)

- **Проблема слэша в UI**: Consul UI требует завершающего слэша в пути `/ui/`. Без него статические ассеты (JS/CSS) могут загружаться некорректно. Рекомендуется добавлять принудительный редирект с `/ui` на `/ui/`.
- **ACL и токены**: Если в Consul включены ACL, Nginx может автоматически добавлять заголовок `X-Consul-Token` для определенных запросов, если это необходимо для интеграции с внешними системами.
- **Динамические Upstreams**: В больших средах IP-адреса серверов Consul могут меняться.
    - **Nginx OSS**: Требует использования `consul-template` для генерации конфига и вызова `nginx -s reload`.
    - **Angie / Nginx Plus**: Поддерживают динамическое разрешение имен в `upstream` через DNS (директива `resolve`).
- **Мониторинг**: Обязательно отслеживайте метрику `upstream_addr` в логах Nginx, чтобы понимать, на какой конкретно узел Consul ушел запрос и были ли ошибки связи.

### См. также

*   **[Использование Let's Encrypt с Nginx](./nginx_with_letsencrypt.md)** — автоматизация SSL.
*   **[Оптимальная настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)** — усиление защиты.
*   **[Обзор Consul](../../../Consul/consul_overview.md)** — архитектура и возможности.
*   **[Service Discovery в Prometheus](../../../Prometheus/service_discovery_and_relabeling.md)** — использование Consul как источника целей.
