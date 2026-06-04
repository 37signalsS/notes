# Настройка Nginx как обратного прокси для Consul

## 1. Определения

**Nginx в качестве обратного прокси для Consul** — сценарий развёртывания, при котором Nginx выступает единой точкой входа для доступа к веб-интерфейсу (UI) и API (Application Programming Interface) [Consul](../../../Consul/consul_overview.md), обеспечивая SSL/TLS-терминацию и ограничение прямого доступа к узлам кластера.

* **Обратный прокси (Reverse Proxy)** — сервер, принимающий запросы извне и перенаправляющий их на внутренние ресурсы. Подробнее: **[Прокси-серверы](../../../Networking/Concepts/proxy.md)**.
* **[Consul](../../../Consul/consul_overview.md)** — инструмент для Service Discovery и Service Mesh.

## 2. Базовые концепции

Сценарий направлен на решение следующих задач:

1. **Централизованная безопасность**: использование единого SSL/TLS-сертификата на уровне Nginx.
2. **Скрытие инфраструктуры**: узлы Consul могут находиться в приватной подсети без публичных IP-адресов.
3. **Балансировка нагрузки**: распределение запросов между несколькими серверами Consul для обеспечения отказоустойчивости.
4. **Фильтрация трафика**: возможность блокировки доступа к административным путям API (например, `/v1/agent`).

## 3. Практический сценарий

### 3.1. Подготовка

* Наличие сетевой связности между Nginx и узлами Consul по внутренним IP-адресам.
* Доступность порта `8500` на узлах Consul со стороны сервера Nginx.
* Настроенная A-запись DNS (Domain Name System) для домена (например, `consul.example.com`).

### 3.2. Конфигурация Nginx

#### Настройка Upstream

Определение группы серверов для балансировки нагрузки.

```nginx
# /etc/nginx/conf.d/upstream_consul.conf
upstream consul_backend {
    server 10.0.0.11:8500; # IP первого узла
    server 10.0.0.12:8500; # IP второго узла
    server 10.0.0.13:8500; # IP третьего узла
}
```

> См. также: **[Балансировка нагрузки в Nginx](../Proxy/Load_Balancing/overview_concepts.md)**.

#### Настройка виртуального хоста (HTTPS)

```nginx
# /etc/nginx/sites-available/consul.example.com.conf
server {
    listen 443 ssl http2;
    server_name consul.example.com;

    # SSL-сертификаты
    ssl_certificate     /etc/letsencrypt/live/consul.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/consul.example.com/privkey.pem;

    # Оптимальные параметры TLS
    # Подробнее: [Настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)
    include /etc/nginx/snippets/ssl-params.conf;

    location / {
        proxy_pass http://consul_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Ограничение доступа к API агента
    location /v1/agent {
        deny all;
        return 403;
    }
}

# Редирект HTTP -> HTTPS
server {
    listen 80;
    server_name consul.example.com;
    return 301 https://$host$request_uri;
}
```

### 3.3. Применение настроек

1. **Проверка конфигурации**:

    ```bash
    nginx -t
    # → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
    # → nginx: configuration file /etc/nginx/nginx.conf test is successful
    ```

2. **Перезагрузка сервиса**:

    ```bash
    systemctl reload nginx
    ```

## 4. Дополнительная информация

### Рекомендации по безопасности

* **Отключение публичных IP**: После настройки прокси рекомендуется убрать публичные IP-адреса с узлов Consul, оставив их доступными только через Nginx или VPN (Virtual Private Network).
* **HSTS (HTTP Strict Transport Security)**: Рекомендуется добавить заголовок `Strict-Transport-Security "max-age=31536000; includeSubDomains" always;` для принудительного использования HTTPS.
* **Аутентификация в Consul**: Проксирование через Nginx не заменяет встроенную систему **Consul ACL (Access Control List)**. Всегда используйте токены доступа для защиты API.

### См. также

* **[Использование Let's Encrypt с Nginx](./nginx_with_letsencrypt.md)**
* **[Оптимальная настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**
* **[Обзор Consul](../../../Consul/consul_overview.md)**
