# Настройка Nginx как обратного прокси для Grafana

## 1. Определения

**Nginx в качестве обратного прокси для Grafana** — сценарий развёртывания, при котором Nginx выступает посредником, принимая запросы на стандартных портах (80/443) и перенаправляя их на внутренний порт Grafana (по умолчанию 3000).

*   **[Nginx](../Core/nginx_overview.md)** — высокопроизводительный веб-сервер и обратный прокси.
*   **[Grafana](../../../Grafana/grafana_overview.md)** — аналитическая платформа для визуализации и мониторинга данных.
*   **[Обратный прокси (Reverse Proxy)](../../../Networking/Concepts/proxy.md)** — сервер, который принимает запросы от клиентов и распределяет их между внутренними серверами (бэкендами).

## 2. Базовые концепции

Использование Nginx перед Grafana решает следующие задачи:

1.  **Централизация доступа**: использование стандартных портов 80 (HTTP) и 443 (HTTPS) для доступа к интерфейсу.
2.  **Безопасность**: терминация SSL/TLS-соединений на стороне Nginx, что позволяет скрыть Grafana за защищённым периметром.
3.  **Поддержка WebSockets**: Grafana использует протокол WebSocket для функций реального времени (Grafana Live). Nginx должен быть настроен для корректной передачи этих заголовков.
4.  **Управление заголовками**: передача реального IP-адреса клиента для корректного логирования и аудита в Grafana.

## 3. Практический сценарий

### 3.1. Конфигурация виртуального хоста Nginx

Для Nginx версии 1.27+ рекомендуется использовать директиву `http2 on;` вместо устаревшего параметра в `listen`.

**Пример конфигурации (`/etc/nginx/sites-available/grafana.conf`):**

```nginx
# Редирект с HTTP на HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name grafana.example.com;

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name grafana.example.com;

    # Включение HTTP/2 (актуальный синтаксис 1.27+)
    http2 on;

    # Параметры SSL (рекомендуется использовать Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/grafana.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/grafana.example.com/privkey.pem;

    # Современные настройки TLS
    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    add_header Strict-Transport-Security "max-age=63072000" always;

    location / {
        proxy_pass http://localhost:3000;
        
        # Передача заголовков для идентификации клиента
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Поддержка WebSockets (необходимо для Grafana Live)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 3.2. Настройка Grafana (grafana.ini)

Для корректной работы за прокси необходимо синхронизировать настройки домена в конфигурационном файле `/etc/grafana/grafana.ini`:

```ini
[server]
domain = grafana.example.com
root_url = https://grafana.example.com/
serve_from_sub_path = false
```

Это гарантирует, что Grafana будет генерировать правильные ссылки в интерфейсе и корректно обрабатывать редиректы после аутентификации.

### 3.3. Применение настроек

```bash
# Проверка синтаксиса конфигурации Nginx
sudo nginx -t

# Перезагрузка сервиса для применения изменений
sudo systemctl reload nginx
```

## 4. Дополнительная информация

### Особенности директивы `try_files`

При проксировании запросов к Grafana **запрещено** использовать директиву `try_files` в основном блоке `location /`.

```nginx
location / {
    # Эта строка НАРУШАЕТ работу Grafana
    # try_files $uri $uri/ =404; 
    
    proxy_pass http://localhost:3000;
}
```

Директива `try_files` заставляет Nginx искать файлы в локальной файловой системе (`root`). Так как все ресурсы Grafana генерируются динамически или обслуживаются встроенным сервером на порту 3000, Nginx вернёт ошибку 404, не доходя до `proxy_pass`.

### Устранение проблем с Cookies

Если Grafana выдаёт ошибку `Origin not allowed` или проблемы с CSRF (Cross-Site Request Forgery), убедитесь, что заголовок `Host` передаётся в Nginx корректно и совпадает с параметром `domain` в `grafana.ini`.

### См. также

*   **[Обзор Nginx](../Core/nginx_overview.md)**
*   **[Обзор Grafana](../../../Grafana/grafana_overview.md)**
*   **[Прокси-серверы: концепции](../../../Networking/Concepts/proxy.md)**

---
**Достоверность:** 10 (Внутренняя верификация + Официальная документация Grafana) | **Актуальность:** Июль 2026 (Nginx 1.27, Grafana 11+)
