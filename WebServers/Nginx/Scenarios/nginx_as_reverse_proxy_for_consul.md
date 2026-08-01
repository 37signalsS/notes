# Настройка Nginx как обратного прокси для Consul

## 1. Определения

**Nginx в качестве обратного прокси для Consul** — сценарий развёртывания, при котором Nginx выступает единой точкой входа для доступа к веб-интерфейсу (UI) и API (Application Programming Interface) [Consul](../../../Consul/consul_overview.md), обеспечивая SSL/TLS-терминацию и ограничение прямого доступа к узлам кластера.

*   **Обратный прокси (Reverse Proxy)** — сервер, принимающий запросы извне и перенаправляющий их на внутренние ресурсы. Подробнее: **[Прокси-серверы](../../../Networking/Concepts/proxy.md)**.
*   **[Consul](../../../Consul/consul_overview.md)** — распределённая система для Service Discovery, конфигурации и Service Mesh.

## 2. Базовые концепции

Сценарий направлен на решение следующих архитектурных и эксплуатационных задач:

1.  **Централизованная безопасность**: использование единого доверенного SSL/TLS-сертификата на уровне Nginx, что упрощает управление сертификатами в кластере.
2.  **Скрытие инфраструктуры**: узлы Consul могут находиться в изолированной приватной подсети, исключая прямое воздействие из интернета.
3.  **Балансировка и отказоустойчивость**: Nginx распределяет запросы между серверами кластера Consul, обеспечивая доступ к UI/API даже при выходе из строя одного из узлов.
4.  **Управление доступом**: возможность фильтрации трафика на уровне HTTP-путей, например, блокировка критических методов API для внешних потребителей.

## 3. Практический сценарий

### 3.1. Предварительные требования

*   Сетевая связность между Nginx и серверами Consul по внутренним IP-адресам.
*   Открытый порт `8500` на узлах Consul для входящих запросов от Nginx.
*   Настроенная DNS-запись для домена управления (например, `consul.example.com`).

### 3.2. Конфигурация Nginx

Современная настройка (актуально для Nginx 1.27+) подразумевает использование раздельных директив для протоколов и поддержку IPv6.

#### Настройка группы серверов (Upstream)

Определите список узлов Consul для балансировки.

```nginx
# /etc/nginx/conf.d/upstream_consul.conf
upstream consul_backend {
    # Рекомендуется использовать keepalive для повышения производительности API
    keepalive 32;

    server 10.0.0.11:8500; # Сервер 1
    server 10.0.0.12:8500; # Сервер 2
    server 10.0.0.13:8500; # Сервер 3
}
```

> Подробнее о методах распределения нагрузки: **[Балансировка нагрузки в Nginx](../Proxy/Load_Balancing/overview_concepts.md)**.

#### Настройка виртуального хоста

```nginx
# /etc/nginx/sites-available/consul.example.com.conf
server {
    listen 80;
    listen [::]:80;
    server_name consul.example.com;

    # Принудительный редирект на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name consul.example.com;

    # Включение HTTP/2 (актуальный синтаксис 1.27+)
    http2 on;

    # Пути к сертификатам (например, Let's Encrypt)
    ssl_certificate     /etc/letsencrypt/live/consul.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/consul.example.com/privkey.pem;

    # Параметры безопасности TLS 1.3 и HSTS
    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    add_header Strict-Transport-Security "max-age=63072000" always;

    # Оптимизация заголовков прокси
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    location / {
        proxy_pass http://consul_backend;
    }

    # Безопасность: ограничение доступа к API управления агентом
    location /v1/agent {
        deny all;
        return 403;
    }
}
```

> Детальные настройки шифрования: **[Оптимальная настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**.

### 3.3. Валидация и применение

Перед применением изменений необходимо убедиться в отсутствии синтаксических ошибок:

```bash
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
```

## 4. Дополнительная информация

### Проактивные рекомендации

*   **Динамическая конфигурация**: Поскольку IP-адреса серверов Consul могут меняться, рассмотрите использование инструмента `consul-template` для автоматического обновления файла `upstream_consul.conf` и перезагрузки Nginx.
*   **Consul ACL**: Nginx обеспечивает сетевую защиту, но не заменяет систему авторизации Consul. Обязательно активируйте **ACL (Access Control List)** и требуйте токены доступа для всех запросов к API.
*   **Мониторинг**: Настройте экспорт метрик Nginx (например, через VTS-модуль) для отслеживания ошибок `5xx` при обращении к бэкендам Consul.

### См. также

*   **[Использование Let's Encrypt с Nginx](./nginx_with_letsencrypt.md)**
*   **[Оптимальная настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**
*   **[Обзор Consul](../../../Consul/consul_overview.md)**

---
**Достоверность:** 10 (Внутренняя верификация + Документация HashiCorp) | **Актуальность:** Июль 2026 (Nginx 1.27, Consul 1.16+)
