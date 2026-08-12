# Настройка Nginx как обратного прокси для Grafana

## 1. Определения

**Nginx в качестве обратного прокси для Grafana** — сценарий развёртывания, при котором Nginx выступает посредником, принимая запросы на стандартных портах (80/443) и перенаправляя их на внутренний порт Grafana (по умолчанию 3000).

*   **[Nginx](../Core/nginx_overview.md)** — высокопроизводительный веб-сервер и обратный прокси.
*   **[Grafana](../../../Grafana/grafana_overview.md)** — аналитическая платформа для визуализации и мониторинга данных.
*   **[Обратный прокси (Reverse Proxy)](../../../Networking/Concepts/proxy.md)** — сервер, который принимает запросы от клиентов и распределяет их между внутренними серверами (бэкендами).

## 2. Базовые концепции

Использование Nginx перед Grafana решает следующие задачи:

1.  **Централизация доступа**: использование стандартных портов 80 (HTTP) и 443 (HTTPS) для доступа к интерфейсу без необходимости открытия порта 3000 во внешнюю сеть.
2.  **Безопасность**: терминация SSL/TLS-соединений на стороне Nginx, что позволяет скрыть Grafana за защищённым периметром и использовать современные протоколы шифрования (TLS 1.3).
3.  **Поддержка WebSockets**: Grafana использует протокол WebSocket для функций реального времени (Grafana Live). Nginx должен быть настроен для корректной передачи заголовков `Upgrade` и `Connection`.
4.  **Управление заголовками**: передача реального IP-адреса клиента (`X-Forwarded-For`) для корректного аудита сессий и работы систем ограничения частоты запросов (Rate Limiting) в Grafana.
5.  **Оптимизация**: использование кэширования статических ассетов и сжатия (Gzip/Brotli) на уровне Nginx для ускорения загрузки интерфейса.

## 3. Практический сценарий

### 3.1. Конфигурация виртуального хоста Nginx

Для Nginx версии 1.27+ используется актуальный синтаксис включения HTTP/2 через отдельную директиву.

**Пример конфигурации (`/etc/nginx/conf.d/grafana.conf`):**

```nginx
# Маппинг для поддержки WebSockets
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

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

    # Современные настройки TLS и заголовки безопасности
    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";

    location / {
        proxy_pass http://localhost:3000;
        
        # Передача заголовков для идентификации клиента
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Поддержка WebSockets (Grafana Live)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        # Оптимизация буферов для больших дашбордов
        proxy_buffers 8 32k;
        proxy_buffer_size 64k;
    }
}
```

### 3.2. Настройка Grafana (grafana.ini)

Конфигурация Grafana должна соответствовать настройкам прокси для правильной генерации ссылок и обработки куки.

**Файл `/etc/grafana/grafana.ini`:**

```ini
[server]
# Основной домен доступа
domain = grafana.example.com

# Полный URL (обязательно с протоколом)
root_url = https://grafana.example.com/

# Если Grafana работает в подпути (например, /grafana/)
# serve_from_sub_path = true

# Включение сжатия (если не настроено на Nginx)
enable_gzip = true
```

### 3.3. Сценарий работы в подпути (Sub-path)

Если Grafana должна быть доступна по адресу `example.com/grafana/`, необходимо внести изменения в оба конфига.

**Nginx:**
```nginx
location /grafana/ {
    proxy_pass http://localhost:3000/; # Обратите внимание на слэш в конце
    proxy_set_header Host $host;
    # ... остальные заголовки из 3.1 ...
}
```

**Grafana:**
```ini
root_url = https://example.com/grafana/
serve_from_sub_path = true
```

## 4. Дополнительная информация

### Критические ограничения

1.  **Запрет `try_files`**: В блоке `location /` при проксировании к Grafana нельзя использовать `try_files`. Nginx попытается найти файл на диске и вернёт 404, так как Grafana отдает контент динамически через свой бэкенд.
2.  **Заголовки безопасности**: Если вы используете `Content-Security-Policy` (CSP) на уровне Nginx, убедитесь, что разрешены скрипты и инлайновые стили, необходимые для работы Grafana, либо используйте встроенные механизмы CSP в `grafana.ini`.
3.  **Тайм-ауты**: Для работы тяжелых запросов в Explore или при использовании больших интервалов времени рекомендуется увеличить таймауты проксирования:
    ```nginx
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    ```

### Устранение неисправностей (White spots)

- **Ошибка "Origin not allowed"**: Возникает, если заголовок `Host` в Nginx не совпадает с `domain` в `grafana.ini`.
- **Проблемы с авторизацией**: Если после ввода логина/пароля происходит редирект на `http` вместо `https`, проверьте передачу заголовка `proxy_set_header X-Forwarded-Proto $scheme;`.
- **Пустой белый экран**: Часто связано с неверной настройкой `root_url` или блокировкой ресурсов браузером из-за смешанного контента (Mixed Content).

### См. также

*   **[Обзор Nginx](../Core/nginx_overview.md)**
*   **[Обзор Grafana](../../../Grafana/grafana_overview.md)**
*   **[Прокси-серверы: концепции](../../../Networking/Concepts/proxy.md)**
*   **[Оптимизация TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**
