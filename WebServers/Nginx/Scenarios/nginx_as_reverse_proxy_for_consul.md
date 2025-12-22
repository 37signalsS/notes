# Сценарий: Nginx в качестве обратного прокси для Consul с SSL

## 1. Цель и определения

**Цель:** Обеспечить безопасный доступ к UI Consul через стандартный порт 443, скрыть узлы кластера из публичного доступа и централизованно управлять TLS-терминацией с помощью Nginx.

**Обратный прокси (Reverse Proxy):** Сервер, который принимает запросы от клиентов, перенаправляет их на один или несколько бэкенд-серверов и возвращает ответ клиенту. Для клиента это выглядит так, будто он общается напрямую с Nginx.

---

## 2. Подготовка

Перед настройкой Nginx убедитесь, что:
1.  Есть сетевая связность между сервером Nginx и всеми узлами кластера Consul по их внутренним (серым) IP-адресам.
2.  Порт Consul (по умолчанию `8500`) доступен с сервера Nginx.
3.  На ваше доменное имя (например, `consul.your-domain.com`) настроена A-запись, указывающая на публичный IP-адрес сервера Nginx.

---

## 3. Конфигурация Nginx

### 3.1. Определение Upstream

Сначала определим группу `upstream`, в которую включим все серверы Consul.

```nginx
# /etc/nginx/conf.d/upstream-consul.conf
upstream consul_backend {
    server consul-1_private_ip:8500;
    server consul-2_private_ip:8500;
    server consul-3_private_ip:8500;
}
```

### 3.2. Основной блок Server (HTTPS)

Этот блок будет обрабатывать HTTPS-трафик.

```nginx
# /etc/nginx/sites-available/consul.your-domain.com.conf
server {
    listen 443 ssl http2;
    server_name consul.your-domain.com;

    # Пути к SSL-сертификатам
    ssl_certificate /etc/nginx/ssl/consul/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/consul/privkey.pem;

    # Подключение общих параметров TLS/SSL
    # Рекомендуется вынести общие настройки в отдельный файл.
    # > Подробное руководство: [[../Security/nginx_tls_ssl_configuration.md|Оптимальная настройка TLS/SSL в Nginx]]
    include /etc/nginx/snippets/ssl-params.conf;

    # Заголовок HSTS для безопасности
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://consul_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Опционально: можно закрыть доступ к определенным путям API
    location /v1/agent {
        deny all;
        return 403;
    }
}
```

### 3.3. Общие параметры TLS/SSL (пример `ssl-params.conf`)

```nginx
# /etc/nginx/snippets/ssl-params.conf

ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384';
ssl_prefer_server_ciphers off;

ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;
```

### 3.4. Редирект с HTTP на HTTPS

Добавьте блок `server` для перенаправления всего HTTP-трафика на HTTPS.

```nginx
server {
    listen 80;
    server_name consul.your-domain.com;
    return 301 https://$host$request_uri;
}
```

---

## 4. Получение SSL-сертификата и запуск

Для получения сертификата можно использовать `certbot`.

> ➡️ **Подробное руководство:** [[./nginx_with_letsencrypt.md|Использование Let's Encrypt с Nginx]]

1.  **Проверьте синтаксис конфигурации Nginx:** `sudo nginx -t`.
2.  **Запустите или перезагрузите Nginx:** `sudo systemctl reload nginx`.

После этого UI Consul должен быть доступен по адресу `https://consul.your-domain.com`.

---

## 5. Продвинутые детали и рекомендации

### Проверка сетевой связности
Перед настройкой убедитесь, что ваш Nginx-сервер "видит" узлы Consul.
```bash
# Проверяем доступность порта 8500
telnet consul-1_private_ip 8500
```

### Безопасность: Отключение публичных IP
После того как вы убедились, что доступ к Consul через Nginx работает, **отключите публичные IP-адреса** у виртуальных машин самого кластера Consul. Это значительно сокращает поверхность атаки, так как прямой доступ к узлам Consul извне становится невозможен.

---
## Смотри также
*   [[../Core/nginx_overview.md|Обзор Nginx]]
*   [[../Proxy/nginx_load_balancing.md|Балансировка нагрузки HTTP (L7)]]
*   [[../Security/nginx_tls_ssl_configuration.md|Настройка TLS/SSL в Nginx]]
*   [[./nginx_with_letsencrypt.md|Использование Let's Encrypt с Nginx]]
